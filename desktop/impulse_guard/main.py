"""쇼핑 화면 감지 프로그램 진입점

원본 shopping_detector.py와 같은 판정 + 가격 분석(B-1) + 서버 연동(B-2) + 차단 팝업(B-3) + 자동 감지(B-4)
- 시작할 때 local_config.json의 토큰으로 회원을 확인한다. 실패하면 오프라인 모드로 감지만 한다.
- 자동 감지(auto_detect.py): 화면이 바뀌고 멈추면 분석해서 단계별로 처리한다 (App.handle_auto)
    쇼핑 아님   로그만
    상품 화면   로그와 내부 상태(쇼핑몰별 마지막 상품)만. 서버 호출 없음
    결제 화면   서버 check(is_checkout) + 기록 + 항상 충동구매 팝업. 같은 주문은 한 번만 (dedup.py)
    차단 시간   상품/결제 화면 모두 차단 안내 창 + blocked 기록. 닫은 뒤 blocked_repeat_sec 동안은 다시 띄우지 않음
- F4: 디버그·백업용. 예전처럼 쇼핑 화면이면 바로 서버 check와 팝업 (중복 검사 없음)
- 오프라인이면 알림 창 없이 콘솔 안내만 한다.

스레드 (popup.py 맨 위 설명도 참고)
    main 스레드       tkinter mainloop (창은 이 스레드만 다룬다)
    keyboard 스레드   F4 콜백. 작업 스레드를 띄우기만 하고 바로 끝난다
    작업 스레드       F4: 캡처 → OCR → 서버 check → 띄울 창을 main 스레드에 넘김
    자동 감지 스레드  주기 캡처 → (화면이 바뀌고 멈췄을 때만) OCR → handle_auto
    분석과 창은 잠금 하나(App._busy)로 한 번에 하나씩. 창이 떠 있는 동안 자동 감지는 쉰다

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe -m impulse_guard.main
"""
import signal
import threading
import time
from dataclasses import dataclass

from . import capture, config, frame, ocr, popup_model, timing
from .dedup import NoticeGate, RecentOrders, title_key
from .detect_log import DetectLog, NullLog
from .detector import page as page_info, price, shopping, stage as stage_mod
from .popup_model import hms as _hms
from .server_client import Client, auto_settings, load_config


@dataclass
class Analysis:
    shop: shopping.ShoppingResult
    prices: price.PriceResult = None
    page: page_info.PageInfo = None
    boxes: list = None
    stage: stage_mod.StageResult = None
    frame_hash: int = None       # 분석한 화면의 해시 (F4 캡처, 같은 주문 판단에 쓴다)
    title_key: object = None     # 캡처할 때 맨 앞 창 제목의 해시 (dedup.title_key). 제목 원문은 두지 않는다

    @property
    def is_shopping(self):
        """상품 화면이나 결제 화면 (stage가 없으면 원본 판정)"""
        return self.stage.stage != stage_mod.NONE if self.stage else self.shop.is_mall

    @property
    def is_checkout(self):
        return bool(self.stage and self.stage.stage == stage_mod.CHECKOUT)

    @property
    def amount(self):
        """서버에 보낼 금액: 결제 화면이면 결제 금액 라벨 옆 금액, 상품 화면이면 할인가. 모르면 0

        결제 화면에서 라벨 옆 금액을 못 찾으면 할인가로 대신하지 않는다. 상품 화면용 가격 분석은 결제 화면의
        혜택/적립 금액을 할인가로 고를 수 있다 (실제 버그: 지그재그 '최대 1,630원' 혜택을 630원/15,006원으로 기록).
        금액을 모르면 같은 주문은 화면 해시 거리로 판단한다 (dedup.py).
        """
        if self.is_checkout:
            return int(self.page.checkout_total or 0) if self.page else 0
        return int((self.prices.sale_price if self.prices else 0) or 0)


def analyze_boxes(boxes, img=None, reread=None, site_hints=None):
    """OCR 상자로 쇼핑 판정, 화면 단계, 가격 분석, 페이지 정보를 만든다 (테스트는 OCR 캐시로 부른다)"""
    text = ocr.full_text(boxes)
    shop = shopping.judge(text)
    st = stage_mod.classify(text, shop.is_mall)
    if st.stage == stage_mod.NONE:
        return Analysis(shop, boxes=boxes, stage=st)
    prices = price.analyze(boxes, img, reread=reread)
    info = page_info.analyze(boxes, text, prices, site_hints, st)
    return Analysis(shop, prices, info, boxes, st)


@dataclass
class AmountWait:
    """금액을 몰라 팝업을 미룬 결제 화면 (같은 쇼핑몰의 최근 주문과 같은 주문인지 금액을 읽을 때까지)"""
    order: object                # dedup.SeenOrder (금액 모름)
    since: float                 # 미루기 시작한 시각 (App.clock)
    analysis: object             # 시간이 지나면 이 분석 결과로 '확인 중' 팝업을 띄운다


@dataclass
class PendingAmount:
    """결제 금액 확인 중인 팝업과 그 주문"""
    order: object                # dedup.SeenOrder
    window: object               # popup.ImpulsePopup
    site: str = ''


def covered_box(rect, origin, shape):
    """화면 좌표 rect가 캡처 이미지(왼쪽 위 origin, 크기 shape)에서 차지하는 영역 (x0, y0, x1, y1). 안 겹치면 None"""
    if not rect:
        return None
    ox, oy = origin
    h, w = shape[:2]
    x0, y0 = max(0, int(rect[0] - ox)), max(0, int(rect[1] - oy))
    x1, y1 = min(w, int(rect[2] - ox)), min(h, int(rect[3] - oy))
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def mask_rect(img, rect, origin=(0, 0)):
    """화면 좌표 rect(x0, y0, x1, y1) 영역을 흰색으로 지운다 (팝업 자기 글자를 읽지 않게). img를 바로 고친다"""
    box = covered_box(rect, origin, img.shape)
    if box:
        x0, y0, x1, y1 = box
        img[y0:y1, x0:x1] = 255
    return img


@dataclass
class OcrEngine:
    name: str                 # 로그와 콘솔용 ('Windows OCR', 'EasyOCR')
    read: object              # 이미지 → OcrBox 목록
    reread: object            # 취소선 구간 다시 읽기
    note: str = ''            # 원하는 엔진을 못 쓴 이유 (EasyOCR로 바꿨을 때)


_engine = None


def ocr_engine():
    """쓸 OCR 엔진 (처음 한 번 정한다). config.OCR_ENGINE이 'win'이고 한국어 Windows OCR이 있으면 Windows OCR,
    아니면 EasyOCR (원본과 같은 설정)"""
    global _engine
    if _engine is None:
        note = ''
        if config.OCR_ENGINE == 'win':
            from . import winocr
            if winocr.available():
                _engine = OcrEngine('Windows OCR', winocr.read, winocr.read_struck)
            else:
                note = 'Windows OCR(한국어)을 쓸 수 없어 EasyOCR을 씁니다'
        if _engine is None:
            _engine = OcrEngine('EasyOCR', ocr.read, ocr.read_struck, note)
    return _engine


def analyze_image(img, site_hints=None):
    """이미지 한 장을 OCR부터 분석한다"""
    eng = ocr_engine()
    t = timing.current()
    if t is not None:
        t.info['엔진'] = eng.name
    return analyze_boxes(eng.read(img), img, reread=eng.reread, site_hints=site_hints)


def timed_analysis(fn, *args):
    """분석 함수를 부르고 걸린 시간을 돌려준다. 측정 중이면 OCR/다시 읽기를 뺀 나머지를 '판정'으로 더한다"""
    t = timing.current()
    before = (t.sec.get('ocr', 0.0) + t.sec.get('reread', 0.0)) if t else 0.0
    started = timing.now()
    a = fn(*args)
    sec = timing.now() - started
    if t:
        t.add('judge', sec - (t.sec.get('ocr', 0.0) + t.sec.get('reread', 0.0) - before))
    return a, sec


def _won(v):
    return f'{v:,}원' if v else '찾지 못함'


def print_result(a):
    """원본과 같은 판정 출력 + 가격 분석"""
    print("-" * 40)
    if a.is_shopping:
        print("⭕ [판정 결과] 쇼핑몰 사이트입니다!")
        if a.stage is not None:
            print(f"  - 화면 단계: {a.stage.label} ({a.stage.evidence()})")
        print(f"  - 감지된 키워드: {a.shop.found_keywords}")
        print(f"  - 감지된 가격 정보: {a.shop.price_patterns[:3]}")
        p = a.prices
        if p is not None:
            check = '검산 통과' if p.verified else '검산 못 함'
            rate = f'{p.discount_rate}%' if p.discount_rate is not None else '찾지 못함'
            if p.discount_rate is not None and not p.rate_shown:
                rate += ' (원가와 할인가로 계산)'
            print(f"  - 할인가: {_won(p.sale_price)} (확신도 {p.sale_conf:.2f})")
            print(f"  - 원가:   {_won(p.original_price)} (확신도 {p.original_conf:.2f})")
            print(f"  - 할인율: {rate} (확신도 {p.rate_conf:.2f}, {check})")
            dropped = [c for c in p.candidates if c.role == 'excluded']
            if dropped:
                print(f"  - 제외한 값: {[f'{c.text} ({c.reason})' for c in dropped]}")
        if a.page is not None:
            print(f"  - 사이트: {a.page.site or '모름'} / 상품명: {a.page.item_name or '찾지 못함'}"
                  f" / 결제 화면: {'예 ' + str(list(a.page.checkout_words)) if a.page.is_checkout else '아니오'}")
            if a.page.is_checkout:
                label = f" ('{a.page.total_label}' 옆)" if a.page.total_label else ' (결제 금액 라벨을 못 찾음)'
                print(f"  - 결제 금액: {_won(a.amount)}{label}")
    else:
        print("❌ [판정 결과] 쇼핑몰이 아닙니다.")
        print("  - 쇼핑몰 특유의 구매 버튼이나 가격 정보가 충분히 발견되지 않았습니다.")


def check_params(a, item_name=None):
    """서버 check에 보낼 값. 결제 화면이면 결제 금액을 보내고 원가/할인율은 보내지 않는다 (상품 하나의 값이 아님)"""
    p, info = a.prices, a.page
    product = not a.is_checkout
    return dict(site=info.site, item_name=info.item_name if item_name is None else item_name, price=a.amount,
                orig_price=(p.original_price or 0) if product else 0,
                discount_rate=(p.discount_rate or 0) if product else 0,
                is_checkout=a.is_checkout, page='product' if product else '', log=True)


def send_and_print(client, a):
    """쇼핑 화면이면 서버에 위험도를 묻고 기록을 남긴 뒤 결과를 출력한다. 서버 결과(ApiResult 또는 None)를 돌려준다"""
    if not a.is_shopping:
        print("-" * 40)
        return None
    r = client.check(**check_params(a))
    if r.ok:
        d = r.data
        print("  [서버] 위험도 판단")
        if d.get('is_blocking'):
            client.get_setting()
            if not client.block_remain():          # 캐시가 차단 시작 전 것이면 다시 받는다
                client.get_setting(force=True)
            remain = client.block_remain()
            print(f"    - 차단 시간입니다{f' (남은 시간 {_hms(remain)})' if remain else ''}")
        else:
            print("    - 차단 시간: 아님")
        print(f"    - 충동구매 감지: {'예' if d.get('is_impulse') else '아니오'}")
        for text in popup_model.reason_texts(d):
            print(f"      · {text}")
        if a.amount:
            print(f"    - 지금 포기하면 {d.get('point', 0)}P, 24시간 참으면 {d.get('point2', 0)}P")
        event = '차단' if d.get('event') == 'blocked' else '감지'
        print(f"    - {event} 기록 저장 (번호 {d.get('bl_id')})")
    elif r.offline:
        print(f"  [서버] 연결 안 됨 ({r.msg}) - 감지만 했습니다")
        remain = client.block_remain()
        if remain:
            print(f"    - (마지막으로 받은 설정 기준) 차단 시간입니다. 남은 시간 {_hms(remain)}")
    else:
        print(f"  [서버] 요청 실패 (HTTP {r.status}): {r.msg}")
    print("-" * 40)
    return r


def print_connection(client):
    if client.online:
        m = client.member
        print(f"[서버] 연결됨: {client.server} / {m.get('nick')}({m.get('mb_id')}) / 포인트 {m.get('point', 0):,}P")
    elif client.auth_failed:
        print(f"[서버] 토큰이 올바르지 않습니다. 웹 설정 화면에서 토큰을 다시 발급해 {config.LOCAL_CONFIG}에 넣으세요.")
        print("       오프라인 모드로 감지만 합니다.")
    else:
        print(f"[서버] 연결 안 됨 ({client.last_error}). 오프라인 모드로 감지만 합니다.")
        if client.token:
            print(f"       F4를 누를 때 {config.RECONNECT_SEC}초 간격으로 다시 연결해 봅니다.")


class App:
    """F4와 자동 감지 → 분석 → 창 띄우기. ui는 popup.UiHost (main 스레드에서 만든 것)

    analyze: F4용 (캡처 + 분석) 함수, analyze_frame: 자동 감지용 (이미지 → 분석) 함수. 테스트에서 바꿔 끼운다
    """

    def __init__(self, client, ui, analyze=None, analyze_frame=None, settings=None, log=None, clock=time.monotonic):
        self.client = client
        self.ui = ui
        self.analyze = analyze or self._capture_and_analyze
        self.analyze_frame = analyze_frame or (lambda img: analyze_image(img, self.client.site_hints()))
        self.settings = settings or auto_settings()
        self.log = log or NullLog()
        self.clock = clock
        self._busy = threading.Lock()     # 분석 중이거나 창이 떠 있으면 잠겨 있다
        self.window = None
        self.orders = RecentOrders(self.settings['same_order_minutes'] * 60, clock=clock)
        self.gate = NoticeGate(self.settings['blocked_repeat_sec'], clock=clock)
        self.last_product = {}            # 쇼핑몰 → (상품명, 금액, 본 시각). 결제 화면의 상품명으로 쓴다
        self.last_frame_hash = None       # F4가 마지막으로 분석한 화면. 자동 감지는 이 화면을 다시 OCR하지 않는다
        self.was_shopping = False         # 자동 감지가 직전에 분석한 화면이 쇼핑 화면이었는지
        self._pending_timing = None       # 팝업을 요청한 회차의 시간 측정. 창이 만들어지면 로그에 남긴다
        self.pending = None               # 결제 금액 확인 중인 팝업 (PendingAmount). 떠 있는 동안 금액을 읽어 채운다
        self.waiting = None               # 금액을 몰라 팝업을 미룬 결제 화면 (AmountWait)
        self.round = 0                    # 분석 회차 번호 (오래된 결과를 거르고 로그에 남긴다)

    # ── F4 ─────────────────────────────────────────────────
    def on_hotkey(self):
        """keyboard 스레드에서 불린다. 오래 걸리는 일은 하지 않는다"""
        if not self._busy.acquire(blocking=False):
            print(f"\n[{config.HOTKEY.upper()}] 이전 분석이 끝나지 않았거나 알림 창이 열려 있어요. 창을 닫은 뒤 다시 눌러 주세요.")
            return
        print(f"\n[{config.HOTKEY.upper()} 감지] 화면 캡처 및 분석을 시작합니다...")
        threading.Thread(target=self.work, daemon=True).start()

    def _capture_and_analyze(self):
        with timing.measure('capture'):
            fr = capture.grab_for_detect()       # 자동 감지와 같이 맨 앞 창 영역 (F4를 누른 창)
        key = title_key(fr.foreground_title)
        img, fr.img = fr.img, None
        with timing.measure('hash'):
            h = frame.dhash(img)
        t = timing.current()
        if t is not None:
            t.info['화면'] = f'{img.shape[1]}x{img.shape[0]}'
        a = analyze_image(img, self.client.site_hints())
        del img                           # 캡처 이미지는 저장하지 않고 바로 버린다
        a.frame_hash = h
        a.title_key = key
        return a

    def _prepare(self):
        was_online = self.client.online
        if self.client.ensure_online() and not was_online:
            print_connection(self.client)
        self.client.get_setting()         # 1분 캐시. 사이트 이름을 사이트 찾기에 더한다

    def work(self):
        """F4 작업 스레드: 분석과 서버 요청. 창을 띄울 일이 있으면 main 스레드에 넘긴다"""
        with timing.active(timing.Timing('f4')) as t:
            shown = self._work()
            if not shown:
                self._log_timing(t)

    def _work(self):
        shown = False
        try:
            self._prepare()
            a, ocr_sec = timed_analysis(self.analyze)
            print_result(a)
            r = send_and_print(self.client, a)
            if r is not None and r.offline:
                print("  (오프라인이라 알림 창은 띄우지 않았습니다)")
            plan = popup_model.build(a, r, self.client.block_remain())
            if a.frame_hash is not None:
                self.last_frame_hash = a.frame_hash
            actions = order = None
            if a.is_checkout and plan and plan[0] == 'impulse':
                # F4로 띄운 결제 화면 팝업도 같은 주문으로 기억한다 (자동 감지가 같은 주문에 팝업을 또 띄우지 않게)
                site = a.page.site if a.page else ''
                order = self.orders.see(site, a.amount, a.frame_hash, a.title_key).order
                view = plan[1]
                self._link_record(order, view.bl_id, a.amount)
                actions = popup_model.Actions(self.client, view,
                                              on_decided=lambda d: self.orders.decide(order, d, view.bl_id))
            elif not a.is_checkout:
                self.orders.left()
            note = self._server_note(r) if r is not None else ''
            self.log.event('f4', a, action=plan[0] if plan else '', ocr_sec=ocr_sec, note=self._popup_note(plan, note))
            if plan:
                site = a.page.site if a.page else ''
                order = order if actions is not None else None
                self._post(lambda: self.show(*plan, actions=actions, site=site, source='f4', order=order))
                shown = True
        except Exception as e:
            print(f"!!! 분석 중 오류가 발생했습니다: {e}")
        finally:
            if not shown:
                self._busy.release()
        return shown

    # ── 시간 측정 (timing.py) ──────────────────────────────
    def _post(self, fn):
        """창 띄우기를 main 스레드에 넘긴다. 측정 중이면 요청 시각을 기억해 창이 만들어진 뒤 로그에 남긴다"""
        t = timing.current()
        if t is not None:
            t.post_at = timing.now()
            self._pending_timing = t
        self.ui.post(fn)

    def _log_timing(self, t):
        if t is not None:
            t.finish()
            self.log.info(t.line(), console=False)

    # ── 결제 금액 확인 중 팝업 (B-5) ────────────────────────
    def wants_amount(self):
        """'결제 금액 확인 중' 팝업이 떠 있고 아직 결정 전이면 True. 자동 감지가 쉬지 않고 금액만 읽는다"""
        p = self.pending
        w = p.window if p else None
        return bool(w and w.view.pending and not w.closed and not w.done and not w.busy)

    def run_amount(self, img, frame_hash, title=None, origin=None):
        """자동 감지 스레드: 팝업이 떠 있는 동안의 회차. 팝업 영역을 지우고 OCR해서 같은 주문의 결제 금액을 읽으면 채운다.
        잠금은 창이 잡고 있으므로 건드리지 않는다. 채웠으면 True"""
        p = self.pending
        if p is None:
            return False
        seq = self._next_round()
        try:
            origin = origin if origin is not None else capture.monitor_origin()
            box = covered_box(p.window.screen_rect, origin, img.shape)
            mask_rect(img, p.window.screen_rect, origin)
            a, ocr_sec = timed_analysis(self.analyze_frame, img)
            a.title_key = title_key(title)
            site = a.page.site if a.page else ''
            if not a.is_checkout or not a.amount:
                stage = a.stage.label if a.stage else '-'
                if box:
                    # 팝업이 브라우저 위에 겹친 부분은 지우고 읽었다: 결제 금액이 그 아래 있었으면 못 읽는다
                    pct = (box[2] - box[0]) * (box[3] - box[1]) * 100 // max(1, img.shape[0] * img.shape[1])
                    self.log.info(f'amount | 금액 못 읽음 ({stage}) | 팝업이 캡처 영역의 {pct}%를 가림 '
                                  f'({box[2] - box[0]}x{box[3] - box[1]}, 이미지 기준 {box[0]},{box[1]})', console=False)
                else:
                    self.log.debug(f'amount 팝업이 떠 있는 동안 금액 못 읽음 ({stage})')
                return False
            if not self.orders.fill(p.order, site, a.amount, frame_hash, a.title_key):
                self.log.event('auto', a, dup='other', ocr_sec=ocr_sec, note='팝업의 주문과 다른 주문이라 채우지 않음')
                return False
            amount, window = a.amount, p.window
            self.ui.post(lambda: window.fill_price(amount, seq))
            self.log.event('auto', a, dup='same', action='fill', ocr_sec=ocr_sec,
                           note='팝업 금액 채움, ' + self._send_amount(p.order))
            return True
        except Exception as e:
            print(f"!!! 결제 금액 확인 중 오류가 발생했습니다: {e}")
            return False
        finally:
            self._log_timing(timing.current())

    # ── 자동 감지 (auto_detect.AutoDetector가 부른다) ────────
    def paused(self):
        """알림 창이 떠 있거나 분석 중이면 자동 감지를 쉰다"""
        return self.window is not None or self._busy.locked()

    def try_begin(self):
        return self._busy.acquire(blocking=False)

    def still_same(self):
        """화면이 그대로라 OCR을 건너뛴 회차: 결제 화면에 계속 머무는 것으로 본다.
        금액을 기다리던 결제 화면이 CHECKOUT_AMOUNT_WAIT_SEC 동안 그대로면 '확인 중' 팝업을 띄운다"""
        self.orders.still_here()
        w = self.waiting
        if w is None or self.clock() - w.since < config.CHECKOUT_AMOUNT_WAIT_SEC or not self.try_begin():
            return False
        shown = False
        try:
            self.waiting = None
            shown = self._checkout_popup(w.analysis, w.order, None, '금액을 기다렸지만 못 읽어 확인 중으로 띄움')
        except Exception as e:
            print(f"!!! 자동 감지 분석 중 오류가 발생했습니다: {e}")
        finally:
            if not shown:
                self._busy.release()
        return shown

    def _next_round(self):
        self.round += 1
        t = timing.current()
        if t is not None:
            t.info['회차'] = self.round
        return self.round

    def run_auto(self, img, frame_hash, title=None):
        """자동 감지 스레드: try_begin()으로 잠금을 잡은 뒤 부른다. 창을 띄우지 않으면 여기서 잠금을 푼다"""
        shown = False
        self._next_round()
        try:
            self._prepare()
            a, ocr_sec = timed_analysis(self.analyze_frame, img)
            a.title_key = title_key(title)          # 제목 원문은 여기서 해시로만 바꾸고 버린다
            shown = self.handle_auto(a, frame_hash, ocr_sec)
        except Exception as e:
            print(f"!!! 자동 감지 분석 중 오류가 발생했습니다: {e}")
        finally:
            if not shown:
                self._busy.release()
                self._log_timing(timing.current())    # 창을 띄우면 창이 만들어진 뒤 show()에서 남긴다
        return shown

    def handle_auto(self, a, frame_hash, ocr_sec=None):
        """단계별 처리. 창을 띄우면 True (잠금은 창이 닫힐 때 풀린다)"""
        entering = a.is_shopping and not self.was_shopping
        self.was_shopping = a.is_shopping
        if not a.is_shopping:
            self._left()
            self.log.event('auto', a, ocr_sec=ocr_sec)
            self._sample(a)
            return False
        site = a.page.site if a.page else ''
        if entering:
            # 쇼핑 아님 → 쇼핑 화면: 캐시(1분)를 무시하고 차단 상태를 서버에 다시 묻는다
            # (상품 화면은 서버 check를 하지 않으므로, 막 시작한 차단을 놓치지 않게)
            self.client.get_setting(force=True)

        if self.client.is_blocking_for(site):
            if not self.gate.allow(site):
                self.log.event('auto', a, dup='wait', ocr_sec=ocr_sec,
                               note=f'차단 안내 {int(self.gate.wait_left(site))}초 뒤 다시')
                return False
            r = self.client.check(**check_params(a, self._item_name(a)))
            plan = popup_model.build(a, r, self.client.block_remain())
            if plan and plan[0] == 'blocked':
                self.log.event('auto', a, action='blocked', ocr_sec=ocr_sec, note=self._server_note(r))
                self._post(lambda: self.show(*plan, site=site))
                return True
            if r.offline:
                self.log.event('auto', a, ocr_sec=ocr_sec, note='서버 연결 안 됨: 알림 창 없음')
                return False
            # 설정 캐시와 달리 서버가 차단이 아니라고 하면 (차단 해제 직후 등) 아래 보통 처리로

        if a.is_checkout:
            return self._handle_checkout(a, frame_hash, ocr_sec)

        self._remember_product(a)         # 상품 화면: 서버 호출 없이 내부 상태와 로그만
        self._left()
        self.log.event('auto', a, ocr_sec=ocr_sec)
        self._sample(a)
        return False

    def _left(self):
        """결제 화면이 아닌 화면을 봤다: 지금 주문에서 떠났고, 금액 기다림도 그만둔다"""
        self.orders.left()
        self.waiting = None

    def _handle_checkout(self, a, frame_hash, ocr_sec):
        site = a.page.site if a.page else ''
        w = self.waiting
        if w is not None and site and w.order.site and site != w.order.site:
            self.waiting = w = None                 # 다른 쇼핑몰의 결제 화면으로 갔다
        if w is not None:
            return self._handle_waiting(w, a, site, frame_hash, ocr_sec)
        v = self.orders.see(site, a.amount, frame_hash, a.title_key)
        if not v.is_dup and not a.amount and self.orders.recent_known(site, exclude=v.order) is not None:
            # 같은 쇼핑몰의 최근 주문(금액 있음)에 다시 들어온 것일 수 있다 (주문서 주소가 새로 생겨 제목으로 구분 못 함).
            # 금액을 읽을 때까지 팝업을 미룬다. 못 읽으면 CHECKOUT_AMOUNT_WAIT_SEC 뒤 '확인 중' 팝업
            self.waiting = AmountWait(v.order, self.clock(), a)
            self.log.event('auto', a, dup='wait', ocr_sec=ocr_sec,
                           note=f'금액 모름: 최근 주문과 같은 주문인지 금액을 읽을 때까지 팝업을 미룸 '
                                f'(최대 {config.CHECKOUT_AMOUNT_WAIT_SEC}초)')
            return False
        if v.is_dup:
            note = f'{int(v.away_sec)}초 만에 다시 옴' if v.reason == 'revisit' else f'{v.order.count}번째'
            if v.order.decision:
                note += f', 결정: {v.order.decision}'
            if v.filled:
                note += f', 금액 확인 {v.order.amount:,}원 (같은 주문 기록에 채움, {self._send_amount(v.order)})'
            self.log.event('auto', a, dup=v.reason, ocr_sec=ocr_sec, note=note)
            return False
        return self._checkout_popup(a, v.order, ocr_sec)

    def _handle_waiting(self, w, a, site, frame_hash, ocr_sec):
        """금액을 기다리던 결제 화면의 다음 분석"""
        if a.amount:
            self.waiting = None
            v = self.orders.resolve(w.order, site, a.amount, frame_hash, a.title_key)
            if v.is_dup:
                note = '금액 확인 후 최근 주문과 같은 주문: 팝업 안 띄움'
                if v.order.decision:
                    note += f', 결정: {v.order.decision}'
                self.log.event('auto', a, dup='revisit', ocr_sec=ocr_sec, note=note)
                return False
            return self._checkout_popup(a, v.order, ocr_sec, '금액 확인 후 새 주문')
        self.orders.still_here()
        waited = self.clock() - w.since
        if waited >= config.CHECKOUT_AMOUNT_WAIT_SEC:
            self.waiting = None
            return self._checkout_popup(a, w.order, ocr_sec, '금액을 기다렸지만 못 읽어 확인 중으로 띄움')
        self.log.event('auto', a, dup='wait', ocr_sec=ocr_sec,
                       note=f'금액 확인 기다리는 중 ({int(waited)}/{config.CHECKOUT_AMOUNT_WAIT_SEC}초)')
        return False

    def _checkout_popup(self, a, order, ocr_sec, extra=''):
        """새 주문의 결제 화면: 서버 check + 팝업. 창을 띄우면 True"""
        site = a.page.site if a.page else ''
        name = self._item_name(a)
        r = self.client.check(**check_params(a, name))
        plan = popup_model.build(a, r, self.client.block_remain())
        if not plan:
            note = '서버 연결 안 됨: 알림 창 없음' if r.offline else self._server_note(r)
            self.log.event('auto', a, ocr_sec=ocr_sec, note=', '.join(x for x in (note, extra) if x))
            if r.offline:
                print("  (오프라인이라 알림 창은 띄우지 않았습니다)")
            return False
        kind, view = plan
        if kind == 'impulse':
            view.item_name = view.api_name = name or view.api_name
            self._link_record(order, view.bl_id, a.amount)
            actions = popup_model.Actions(self.client, view,
                                          on_decided=lambda d: self.orders.decide(order, d, view.bl_id))
            note = self._popup_note(plan, ', '.join(x for x in (self._server_note(r), extra) if x))
            self.log.event('auto', a, action='popup', ocr_sec=ocr_sec, note=note)
            self._post(lambda: self.show(kind, view, actions=actions, site=site, order=order))
        else:
            self.log.event('auto', a, action='blocked', ocr_sec=ocr_sec, note=self._server_note(r))
            self._post(lambda: self.show(kind, view, site=site))
        return True

    # ── 서버 감지 기록의 금액 (B-5) ─────────────────────────
    @staticmethod
    def _link_record(order, bl_id, amount):
        """팝업을 띄운 주문에 서버 감지 기록 번호를 잇는다. check 때 금액을 보냈으면 서버 기록에 금액이 있다"""
        if order is None:
            return
        if bl_id:
            order.bl_id = int(bl_id)
        order.price_sent = bool(amount)

    def _send_amount(self, order):
        """나중에 읽은 금액을 서버 감지 기록(금액 0)에 채운다 (amount action). 로그에 붙일 문구를 돌려준다"""
        if not order.bl_id:
            return '서버 감지 기록 없음'
        if order.price_sent:
            return '서버 감지 기록에는 이미 금액 있음'
        try:
            r = self.client.fill_amount(order.bl_id, order.amount)
        except Exception as e:                    # 서버 요청이 실패해도 팝업 금액 채우기는 그대로
            return f'서버 감지 기록에 금액을 채우지 못함 ({e})'
        if r.ok:
            order.price_sent = True
            return f'서버 감지 기록 {order.bl_id}번에 금액 채움'
        if r.status == 409:
            order.price_sent = True              # 이미 금액이 있거나 결제 화면 기록이 아님: 다시 보내지 않는다
            return f'서버 감지 기록 {order.bl_id}번은 채우지 않음 ({r.msg})'
        return f'서버 감지 기록에 금액을 채우지 못함 ({r.msg or "서버 연결 안 됨"}). 다음에 금액을 읽으면 다시 보냄'

    def _item_name(self, a):
        """상품명. 결제 화면은 같은 쇼핑몰에서 최근(30분) 본 상품 → 결제 화면에서 읽은 이름 → '쇼핑몰 이름 주문' 순서
        (결제 화면의 상품 영역은 상품명보다 브랜드명이 크게 잡히기도 해서 상품 화면에서 읽은 이름을 먼저 쓴다)"""
        name = a.page.item_name if a.page else ''
        if not a.is_checkout:
            return name
        site = a.page.site if a.page else ''
        seen = self.last_product.get(site)
        if seen and seen[0] and self.clock() - seen[2] <= config.CHECKOUT_NAME_MINUTES * 60:
            return seen[0]
        if name:
            return name
        site_name = (self.client.site_hints().get(site) or [''])[0] or site
        return f'{site_name} 주문' if site_name else '쇼핑몰 주문'

    def _remember_product(self, a):
        if a.page and (a.page.item_name or a.amount):
            self.last_product[a.page.site] = (a.page.item_name, a.amount, self.clock())

    def _sample(self, a):
        if self.log.save_ocr_text and a.boxes:
            self.log.sample(a, ocr.full_text(a.boxes))

    @staticmethod
    def _popup_note(plan, note):
        """로그에 팝업 제목을 남긴다 (사용자가 본 문구를 로그로 확인할 수 있게)"""
        if plan and plan[0] == 'impulse':
            return f"{note} | 팝업 제목 '{plan[1].title}'" if note else f"팝업 제목 '{plan[1].title}'"
        return note

    @staticmethod
    def _server_note(r):
        if r.ok:
            return f"{r.data.get('event', '')} 기록 {r.data.get('bl_id')}번"
        return '서버 연결 안 됨' if r.offline else f'서버 응답 실패: {r.msg}'

    # ── 창 ─────────────────────────────────────────────────
    def show(self, kind, view, actions=None, site='', source='auto', order=None):
        """main 스레드: 창 만들기. 창이 닫히면 잠금을 풀어 F4/자동 감지를 다시 받는다
        source: f4면 포커스를 가져오고, auto면 가져가지 않고 작업 표시줄만 깜빡인다 (popup.py 맨 위 설명)"""
        from . import popup
        take_focus = source == 'f4'
        t, self._pending_timing = self._pending_timing, None
        if kind == 'impulse' and view.pending and order is not None and order.amount:
            popup_model.fill_price(view, order.amount)   # 그 사이 금액을 알게 된 주문이면 '확인 중'으로 띄우지 않는다
        try:
            if kind == 'blocked':
                def closed():
                    self.gate.closed(site)    # 닫은 시각부터 blocked_repeat_sec 동안 같은 쇼핑몰은 다시 띄우지 않음
                    self._closed()
                self.window = popup.BlockedNotice(self.ui, view, on_closed=closed, take_focus=take_focus)
            else:
                self.window = popup.ImpulsePopup(self.ui, view, actions or popup_model.Actions(self.client, view),
                                                 on_closed=self._closed, take_focus=take_focus,
                                                 link_url=self.client.server + config.COOLDOWN_PAGE)
                if view.pending and order is not None:
                    self.pending = PendingAmount(order, self.window, site)
        except Exception:
            self._closed()
            raise
        finally:
            if t is not None and getattr(t, 'post_at', None) is not None:
                t.add('popup', timing.now() - t.post_at)
                self._log_timing(t)

    def _closed(self):
        self.window = None
        self.pending = None
        self._busy.release()


def main():
    import keyboard
    from . import popup
    from .auto_detect import AutoDetector
    capture.set_console_title(config.CONSOLE_TITLE)
    eng = ocr_engine()
    if eng.note:
        print(f"[OCR] {eng.note}")
    if eng.name == 'EasyOCR':
        print("화면 분석을 위한 OCR 모델을 로딩 중입니다. 최초 실행 시 약간의 시간이 걸립니다")
        ocr.get_reader()
    conf = load_config()
    auto = conf['auto']
    client = Client.from_config()
    client.connect()
    client.get_setting()
    log = DetectLog(save_ocr_text=auto['save_ocr_text'])
    log.info(f"프로그램 시작. OCR 엔진: {eng.name}{' (' + eng.note + ')' if eng.note else ''}."
             f" 자동 감지 설정: {conf['auto_source']} → {auto}", console=False)
    ui = popup.UiHost()                   # main 스레드에서 만든다
    app = App(client, ui, settings=auto, log=log)
    detector = (AutoDetector(app, auto['interval_sec'], log=log, exclude_programs=auto['exclude_programs'])
                if auto['enabled'] else None)
    print("\n" + "=" * 50)
    print("쇼핑몰 감지 프로그램이 실행되었습니다!")
    print_connection(client)
    print(f"OCR 엔진: {eng.name}")
    if detector:
        print(f"자동 감지: 켜짐 ({auto['interval_sec']}초 간격, 화면이 바뀌고 멈추면 분석)."
              f" 같은 주문은 {auto['same_order_minutes']}분 안에 다시 알리지 않습니다.")
    else:
        print("자동 감지: 꺼짐 (local_config.json의 auto_detect.enabled)")
    print(f"자동 감지 설정 출처: {conf['auto_source']}")
    if detector and auto['exclude_programs']:
        print(f"감지 제외 프로그램 (맨 앞 창일 때): {', '.join(auto['exclude_programs'])}")
    print(f"[{config.HOTKEY.upper()}] 키를 누르면 지금 화면을 바로 분석합니다 (디버그용, 중복 검사 없음).")
    print(f"감지 로그: {log.dir}" + (" / OCR 원문 저장: 켜짐 (개인정보 마스킹)" if auto['save_ocr_text'] else ''))
    print("종료하려면 콘솔 창에서 [Ctrl + C]를 누르세요.")
    print("=" * 50 + "\n")
    keyboard.add_hotkey(config.HOTKEY, app.on_hotkey)
    if detector:
        detector.start()
    # Ctrl+C: tkinter 콜백 안에서 KeyboardInterrupt가 나면 삼켜지므로, 신호를 받으면 mainloop를 끝내게 한다
    signal.signal(signal.SIGINT, lambda *_: ui.stop())
    try:
        ui.run()
    finally:
        keyboard.unhook_all()
        if detector:
            print("\n자동 감지를 멈추는 중입니다 (분석 중이면 끝날 때까지 잠시 기다립니다)...")
            ok = detector.stop()
            log.info(f"자동 감지 종료 ({'정상' if ok else '시간 초과, 프로그램과 함께 종료'}). 회차 요약: {detector.counts}")
        log.close()
        print("\n프로그램을 종료합니다.")


if __name__ == '__main__':
    main()
