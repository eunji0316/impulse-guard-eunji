"""F4로 화면을 분석하는 진입점

원본 shopping_detector.py와 같은 판정 + 가격 분석(B-1) + 서버 연동(B-2) + 차단 팝업(B-3)
- 시작할 때 local_config.json의 토큰으로 회원을 확인한다. 실패하면 오프라인 모드로 감지만 한다.
- 쇼핑 화면이면 서버 check로 위험도를 묻고 기록을 남긴다 (차단 시간이면 blocked, 아니면 detect).
- 충동구매로 판단하면 충동구매 팝업, 차단 시간이면 차단 안내 창을 띄운다. 오프라인이면 콘솔 안내만 한다.

스레드 (popup.py 맨 위 설명도 참고)
    main 스레드      tkinter mainloop (창은 이 스레드만 다룬다)
    keyboard 스레드  F4 콜백. 작업 스레드를 띄우기만 하고 바로 끝난다
    작업 스레드      캡처 → OCR → 서버 check → 띄울 창을 main 스레드에 넘김
    F4는 분석 중이거나 창이 떠 있으면 무시한다 (한 번에 하나씩)

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe -m impulse_guard.main
"""
import signal
import threading
from dataclasses import dataclass

from . import capture, config, ocr, popup_model
from .detector import page as page_info, price, shopping
from .popup_model import hms as _hms
from .server_client import Client


@dataclass
class Analysis:
    shop: shopping.ShoppingResult
    prices: price.PriceResult = None
    page: page_info.PageInfo = None
    boxes: list = None


def analyze_boxes(boxes, img=None, reread=None, site_hints=None):
    """OCR 상자로 쇼핑 판정, 가격 분석, 페이지 정보를 만든다 (테스트는 OCR 캐시로 부른다)"""
    text = ocr.full_text(boxes)
    shop = shopping.judge(text)
    if not shop.is_mall:
        return Analysis(shop, boxes=boxes)
    prices = price.analyze(boxes, img, reread=reread)
    info = page_info.analyze(boxes, text, prices, site_hints)
    return Analysis(shop, prices, info, boxes)


def analyze_image(img, site_hints=None):
    """이미지 한 장을 OCR부터 분석한다"""
    return analyze_boxes(ocr.read(img), img, reread=ocr.read_struck, site_hints=site_hints)


def _won(v):
    return f'{v:,}원' if v else '찾지 못함'


def print_result(a):
    """원본과 같은 판정 출력 + 가격 분석"""
    print("-" * 40)
    if a.shop.is_mall:
        print("⭕ [판정 결과] 쇼핑몰 사이트입니다!")
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
    else:
        print("❌ [판정 결과] 쇼핑몰이 아닙니다.")
        print("  - 쇼핑몰 특유의 구매 버튼이나 가격 정보가 충분히 발견되지 않았습니다.")


def send_and_print(client, a):
    """쇼핑 화면이면 서버에 위험도를 묻고 기록을 남긴 뒤 결과를 출력한다. 서버 결과(ApiResult 또는 None)를 돌려준다"""
    if not a.shop.is_mall:
        print("-" * 40)
        return None
    p, info = a.prices, a.page
    r = client.check(site=info.site, item_name=info.item_name, price=p.sale_price or 0,
                     orig_price=p.original_price or 0,
                     discount_rate=p.discount_rate if p.discount_rate is not None else 0,
                     is_checkout=info.is_checkout, page='product', log=True)
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
        if p.sale_price:
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
    """F4 → 분석 → 창 띄우기. ui는 popup.UiHost (main 스레드에서 만든 것)"""

    def __init__(self, client, ui, analyze=None):
        self.client = client
        self.ui = ui
        self.analyze = analyze or self._capture_and_analyze
        self._busy = threading.Lock()     # 분석 중이거나 창이 떠 있으면 잠겨 있다
        self.window = None

    def on_hotkey(self):
        """keyboard 스레드에서 불린다. 오래 걸리는 일은 하지 않는다"""
        if not self._busy.acquire(blocking=False):
            print(f"\n[{config.HOTKEY.upper()}] 이전 분석이 끝나지 않았거나 알림 창이 열려 있어요. 창을 닫은 뒤 다시 눌러 주세요.")
            return
        print(f"\n[{config.HOTKEY.upper()} 감지] 화면 캡처 및 분석을 시작합니다...")
        threading.Thread(target=self.work, daemon=True).start()

    def _capture_and_analyze(self):
        img = capture.grab_screen()
        a = analyze_image(img, self.client.site_hints())
        del img                           # 캡처 이미지는 저장하지 않고 바로 버린다
        return a

    def work(self):
        """작업 스레드: 분석과 서버 요청. 창을 띄울 일이 있으면 main 스레드에 넘긴다"""
        shown = False
        try:
            was_online = self.client.online
            if self.client.ensure_online() and not was_online:
                print_connection(self.client)
            self.client.get_setting()     # 5분 캐시. 사이트 이름을 사이트 찾기에 더한다
            a = self.analyze()
            print_result(a)
            r = send_and_print(self.client, a)
            if r is not None and r.offline:
                print("  (오프라인이라 알림 창은 띄우지 않았습니다)")
            plan = popup_model.build(a, r, self.client.block_remain())
            if plan:
                self.ui.post(lambda: self.show(*plan))
                shown = True
        except Exception as e:
            print(f"!!! 분석 중 오류가 발생했습니다: {e}")
        finally:
            if not shown:
                self._busy.release()

    def show(self, kind, view):
        """main 스레드: 창 만들기. 창이 닫히면 F4를 다시 받는다"""
        from . import popup
        try:
            if kind == 'blocked':
                self.window = popup.BlockedNotice(self.ui, view, on_closed=self._closed)
            else:
                self.window = popup.ImpulsePopup(self.ui, view, popup_model.Actions(self.client, view),
                                                 on_closed=self._closed,
                                                 link_url=self.client.server + config.COOLDOWN_PAGE)
        except Exception:
            self._closed()
            raise

    def _closed(self):
        self.window = None
        self._busy.release()


def main():
    import keyboard
    from . import popup
    print("화면 분석을 위한 OCR 모델을 로딩 중입니다. 최초 실행 시 약간의 시간이 걸립니다")
    ocr.get_reader()
    client = Client.from_config()
    client.connect()
    client.get_setting()
    ui = popup.UiHost()                   # main 스레드에서 만든다
    app = App(client, ui)
    print("\n" + "=" * 50)
    print("쇼핑몰 감지 프로그램이 실행되었습니다!")
    print_connection(client)
    print(f"웹서핑 중 쇼핑몰 화면에서 [{config.HOTKEY.upper()}] 키를 누르면 즉시 분석합니다.")
    print("종료하려면 콘솔 창에서 [Ctrl + C]를 누르세요.")
    print("=" * 50 + "\n")
    keyboard.add_hotkey(config.HOTKEY, app.on_hotkey)
    # Ctrl+C: tkinter 콜백 안에서 KeyboardInterrupt가 나면 삼켜지므로, 신호를 받으면 mainloop를 끝내게 한다
    signal.signal(signal.SIGINT, lambda *_: ui.stop())
    try:
        ui.run()
    finally:
        keyboard.unhook_all()
        print("\n프로그램을 종료합니다.")


if __name__ == '__main__':
    main()
