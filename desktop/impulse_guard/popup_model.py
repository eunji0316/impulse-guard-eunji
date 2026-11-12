"""차단 팝업의 내용과 버튼 동작 (B-3)

tkinter 없이 동작하는 부분만 모았다. 화면(popup.py)은 이 결과를 그리기만 한다.
- build(): 분석 결과와 서버 check 응답으로 어떤 창을 띄울지 정한다
    blocked  차단 시간: 차단 안내 창 (충동구매 팝업보다 우선)
    impulse  충동구매 감지, 또는 쇼핑 화면인데 가격을 못 읽음: 충동구매 팝업
    None     충동구매 아님, 오프라인, 서버 오류: 팝업 없이 콘솔 출력만
- Actions: 버튼 세 개와 창 닫기(X)의 서버 요청. 작업 스레드에서 부르고, 결과(Outcome)를 화면에 넘긴다
"""
from dataclasses import dataclass, field

from . import config

NO_PRICE_TEXT = '가격을 읽지 못했어요'
NO_NAME_TEXT = '상품명을 읽지 못했어요'
NO_NAME_API = '상품명을 읽지 못한 상품'      # 쿨다운에는 상품명이 꼭 필요해서 대신 보내는 이름
NO_PRICE_REASON = '가격을 읽지 못해 큰 금액인지 확인할 수 없어요. 한 번 더 생각해 볼까요?'
# 결제 화면인데 결제 금액을 아직 못 읽었을 때 (B-5). 팝업이 떠 있는 동안 화면에서 총 결제금액을 읽으면 채운다 (fill_price)
CHECKOUT_PENDING_TEXT = '결제 금액 확인 중…'
CHECKOUT_PENDING_REASON = '화면에 총 결제금액이 보이면 금액을 채워 드려요.'
CHECKOUT_PENDING_POINT = '금액을 확인하면 담아두기와 포인트를 쓸 수 있어요.'
# 나중에 채운 금액: 서버 check는 금액 0으로 계산했으므로 포인트 숫자는 보이지 않는다 (버튼을 누르면 서버가 금액으로 계산)
FILLED_POINT_TEXT = '안 사면 포인트를 받아요 · 24시간 참으면 더 받아요'
# 결제 화면인데 서버가 checkout 이유를 주지 않을 때(예전 서버)만 쓰는 문구. 평소 문구는 서버(ipp_reason_text)가 정한다
CHECKOUT_FALLBACK_REASON = '결제 직전이에요. 정말 지금 필요한 물건인지 한 번만 더 생각해 봐요.'

# 팝업 제목과 부제: 첫 번째 이유 코드로 고른다. 결제 화면에 위험도(C-2)가 있으면 config.POPUP_RISK_STYLES와 risk_message가 대신한다
TITLES = {
    'checkout': ('결제하기 전에 잠깐만요!', '정말 지금 결제할까요? 한 번만 더 생각해 봐요.'),
    None:       ('잠깐! 충동구매일 수 있어요', '결제하기 전에 한 번만 더 생각해 볼까요?'),
}


@dataclass
class ImpulseView:
    item_name: str               # 화면에 보일 상품명 (못 읽었으면 NO_NAME_TEXT)
    api_name: str                # 서버에 보낼 상품명
    price: int                   # 할인가 (0 = 못 읽음)
    price_text: str
    orig_text: str = ''          # 원가 (할인가보다 클 때만)
    rate_text: str = ''          # 할인율
    reasons: list = field(default_factory=list)
    point: int = 0               # 지금 포기하면
    point2: int = 0              # 24시간 참으면
    point_text: str = ''
    can_hold: bool = True        # 담아두기는 가격이 있어야 한다 (서버가 가격을 요구함)
    bl_id: int = 0
    title: str = TITLES[None][0]
    subtitle: str = TITLES[None][1]
    is_checkout: bool = False
    pending: bool = False        # 결제 금액 확인 중 (결제 화면인데 금액을 아직 못 읽음)
    risk: object = None          # C-2 위험도 0~1 (None = 서버가 계산하지 않음 → 예전 팝업)
    risk_level: str = ''         # low / mid / high (config.POPUP_RISK_STYLES)
    risk_badge: str = ''         # '위험 높음' 등
    title_color: str = ''        # 제목·배지 글자색 ('' = 기본)
    badge_bg: str = ''
    keyword_reasons: list = field(default_factory=list)   # 회원 키워드 이유 (위험도를 다시 받아도 함께 보인다)
    risk_updated: bool = False   # 금액을 채운 뒤 서버가 다시 계산한 위험도로 바뀌었는지


@dataclass
class BlockedView:
    remain_sec: int              # 창을 띄울 때의 남은 차단 시간 (모르면 0)
    item_name: str = ''


def won(v):
    return f'{int(v):,}원'


def hms(sec):
    """남은 시간 문구: 1시간 2분 3초"""
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return (f'{h}시간 ' if h else '') + (f'{m}분 ' if h or m else '') + f'{s}초'


def reason_texts(data):
    """서버 응답의 이유 문구. reasons가 없는 예전 서버면 keyword로 만든다"""
    texts = [r.get('text', '') for r in data.get('reasons') or [] if isinstance(r, dict) and r.get('text')]
    if not texts and data.get('keyword'):
        texts = [f"'{data['keyword']}' 키워드가 들어 있어요."]
    return texts


def reason_codes(data):
    return [r.get('code') for r in data.get('reasons') or [] if isinstance(r, dict)]


def risk_style(data):
    """서버 응답의 위험 단계 → config.POPUP_RISK_STYLES 값. 위험도가 없거나 모르는 단계면 None (예전 팝업)"""
    if not isinstance(data, dict) or isinstance(data.get('risk'), bool) or not isinstance(data.get('risk'), (int, float)):
        return None
    return config.POPUP_RISK_STYLES.get(data.get('risk_level'))


def risk_note(data):
    """로그와 콘솔용: '위험도 0.65 높음 (amount_ratio,history)'"""
    style = risk_style(data)
    if style is None:
        return ''
    codes = ','.join(r.get('code', '') for r in data.get('risk_reasons') or [] if isinstance(r, dict))
    shown = '' if data.get('risk_show_reasons') else ', 이유 안 보임'
    return f"위험도 {float(data['risk']):.2f} {style[1].replace('위험 ', '')} ({codes or '이유 없음'}{shown})"


def build(analysis, result, block_remain=0):
    """('blocked', BlockedView) / ('impulse', ImpulseView) / None

    analysis: main.Analysis, result: client.check()의 ApiResult (None이면 쇼핑 화면 아님)
    block_remain: 차단 중일 때 남은 초 (client.block_remain())
    """
    if result is None or not result.ok or not analysis.is_shopping:
        return None
    d = result.data
    p, info = analysis.prices, analysis.page
    name = (info.item_name if info else '') or ''

    if d.get('is_blocking'):
        return 'blocked', BlockedView(int(block_remain or 0), name)

    price = int(analysis.amount or 0)
    product = not analysis.is_checkout              # 결제 화면이면 원가/할인율은 보이지 않는다 (상품 하나의 값이 아님)
    reasons = reason_texts(d)
    codes = reason_codes(d)
    if analysis.is_checkout and 'checkout' not in codes:
        reasons.insert(0, CHECKOUT_FALLBACK_REASON)  # 예전 서버: 결제 화면은 그래도 항상 팝업
        codes.insert(0, 'checkout')
    pending = analysis.is_checkout and price <= 0
    if pending:
        reasons.append(CHECKOUT_PENDING_REASON)
    elif price <= 0:
        reasons.append(NO_PRICE_REASON)
    elif not d.get('is_impulse') and not analysis.is_checkout:
        return None
    title, subtitle = TITLES.get(codes[0] if codes else None, TITLES[None])
    max_reasons = config.POPUP_MAX_REASONS
    style = risk_style(d) if analysis.is_checkout else None
    if style is not None:
        # C-2: 위험 단계별 제목과 머리 문구. 이유 문장은 보통 이상만 (낮음은 확인 문구만). 키워드 이유는 회원이 정한 것이라 함께 보인다
        keyword = [r.get('text', '') for r in d.get('reasons') or [] if isinstance(r, dict) and r.get('code') == 'keyword']
        title, subtitle, reasons = _risk_texts(d, style, keyword, subtitle)
        max_reasons = config.POPUP_MAX_RISK_REASONS + 1          # + 금액 확인 중 안내
        if pending:
            reasons.append(CHECKOUT_PENDING_REASON)

    v = ImpulseView(
        item_name=name or NO_NAME_TEXT, api_name=name or NO_NAME_API,
        price=price, price_text=won(price) if price else (CHECKOUT_PENDING_TEXT if pending else NO_PRICE_TEXT),
        reasons=reasons[:max_reasons],
        point=int(d.get('point') or 0), point2=int(d.get('point2') or 0),
        can_hold=price > 0, bl_id=int(d.get('bl_id') or 0),
        title=title, subtitle=subtitle, is_checkout=analysis.is_checkout, pending=pending)
    if style is not None:
        v.keyword_reasons = keyword
        _set_risk(v, d, style)
    if product and price and p.original_price and p.original_price > price:
        v.orig_text = won(p.original_price)
    if product and price and p.discount_rate:
        v.rate_text = f'{p.discount_rate}%'
    if price:
        v.point_text = f'안 사면 +{v.point:,}P · 24시간 참으면 +{v.point2:,}P'
    elif pending:
        v.point_text = CHECKOUT_PENDING_POINT
    else:
        v.point_text = '가격을 읽지 못해 담아두기와 포인트를 쓸 수 없어요.'
    return 'impulse', v


def _risk_texts(d, style, keyword, subtitle=''):
    """위험도 응답 → (제목, 부제, 이유 문장). 이유는 보통 이상만(risk_show_reasons), 회원 키워드 이유를 앞에"""
    risk_texts = [r.get('text', '') for r in d.get('risk_reasons') or [] if isinstance(r, dict) and r.get('text')]
    reasons = (list(keyword) + risk_texts)[:config.POPUP_MAX_RISK_REASONS] if d.get('risk_show_reasons') else []
    return style[0], d.get('risk_message') or subtitle, reasons


def _set_risk(view, d, style):
    view.risk, view.risk_level = float(d['risk']), d['risk_level']
    view.risk_badge, view.title_color, view.badge_bg = style[1], style[2], style[3]


def apply_risk(view, data):
    """금액을 채운 뒤 서버(amount)가 다시 계산한 위험도로 팝업 내용을 바꾼다. 바꿨으면 True
    결제 화면 팝업이고 응답에 위험도가 있을 때만 (없으면 처음 내용 그대로). '확인 중' 안내는 그대로 둔다"""
    style = risk_style(data)
    if style is None or not view.is_checkout:
        return False
    title, subtitle, reasons = _risk_texts(data, style, view.keyword_reasons, view.subtitle)
    pending = [r for r in view.reasons if r == CHECKOUT_PENDING_REASON]
    view.title, view.subtitle, view.reasons = title, subtitle, reasons + pending
    _set_risk(view, data, style)
    view.risk_updated = True
    return True


def fill_price(view, price):
    """결제 금액 확인 중이던 팝업에 나중에 읽은 금액을 채운다. 채웠으면 True
    담아두기/안 살래요는 view.price를 서버에 보내므로 채운 금액으로 쿨다운과 포인트가 계산된다"""
    if not view.pending or price <= 0:
        return False
    view.price, view.price_text, view.can_hold, view.pending = int(price), won(price), True, False
    view.reasons = [r for r in view.reasons if r != CHECKOUT_PENDING_REASON]
    view.point_text = FILLED_POINT_TEXT
    return True


@dataclass
class Outcome:
    """버튼 처리 결과
    close=True면 창을 바로 닫는다. 아니면 title/text로 결과 화면을 보여 준다.
    error가 있으면 같은 화면에 빨간 안내를 띄우고 버튼을 다시 누를 수 있게 한다.
    """
    title: str = ''
    text: str = ''
    error: str = ''
    close: bool = False
    show_link: bool = False      # 결과 화면에 '타임머신 보기'
    console: str = ''            # 콘솔에 남길 한 줄


def _fail_msg(r):
    if r.offline:
        return '서버에 연결하지 못했어요. 잠시 뒤 다시 눌러 주세요.'
    return r.msg or f'요청이 실패했어요 (HTTP {r.status}).'


class Actions:
    """팝업 버튼의 서버 요청. 각 메서드는 서버 요청이 있어 작업 스레드에서 부른다"""

    def __init__(self, client, view, on_decided=None):
        self.client = client
        self.view = view
        self.on_decided = on_decided     # 결정이 정해지면 on_decided('hold' 등). 자동 감지의 중복 방지가 기억한다

    def _decided(self, decision):
        if self.on_decided:
            self.on_decided(decision)

    def hold(self):
        """조금 더 생각하기 (24시간 담아두기) → 서버 cooldown"""
        v = self.view
        if not v.can_hold:
            return Outcome(error='가격을 읽지 못해 담아둘 수 없어요.')
        r = self.client.cooldown(v.api_name, v.price, v.bl_id)
        if not r.ok:
            return Outcome(error=_fail_msg(r), console=f'[팝업] 담아두기 실패: {r.msg}')
        self._decided('hold')
        expire = str(r.data.get('expire', ''))[:16]
        point2 = int(r.data.get('point2') or v.point2)
        return Outcome('타임머신에 담았어요', f'{expire}까지 참으면 +{point2:,}P를 받아요.', show_link=True,
                       console=f'[팝업] 조금 더 생각하기 → 쿨다운 {r.data.get("cd_id")}번 ({expire}까지)')

    def giveup(self):
        """안 살래요 → 서버 giveup (가격을 모르면 포인트 없이 decide giveup)"""
        v = self.view
        if v.price <= 0:
            r = self.client.decide(v.bl_id, 'giveup')
            if not r.ok:
                return Outcome(error=_fail_msg(r), console=f'[팝업] 안 살래요 기록 실패: {r.msg}')
            self._decided('giveup')
            return Outcome('잘 참았어요!', '이번 구매를 건너뛰었어요. (가격을 몰라 포인트는 없어요)',
                           console='[팝업] 안 살래요 → 기록만 (가격 모름)')
        r = self.client.giveup(v.api_name, v.price, v.bl_id)
        if not r.ok:
            return Outcome(error=_fail_msg(r), console=f'[팝업] 안 살래요 실패: {r.msg}')
        self._decided('giveup')
        point = int(r.data.get('point') or 0)
        text = f'+{point:,}P를 받았어요.' if point > 0 else '오늘 받을 수 있는 포인트는 모두 받았어요.'
        return Outcome('잘 참았어요!', text, console=f'[팝업] 안 살래요 → {point}P 받음 (쿨다운 {r.data.get("cd_id")}번)')

    def buy(self):
        """그래도 구매할래요 → 기록만 남기고 닫는다 (서버 실패여도 구매를 막지 않는다)"""
        return self._record('buy', '그래도 구매할래요')

    def close(self):
        """창의 X → 기록만 남기고 닫는다. 포인트 없음"""
        return self._record('close', '창 닫기')

    def _record(self, decision, label):
        self._decided(decision)          # 구매/닫기는 서버 기록이 실패해도 결정으로 본다
        if not self.view.bl_id:
            return Outcome(close=True, console=f'[팝업] {label} (기록 번호가 없어 기록하지 않음)')
        r = self.client.decide(self.view.bl_id, decision)
        console = f'[팝업] {label} → 기록함' if r.ok else f'[팝업] {label} → 기록 실패: {_fail_msg(r)}'
        return Outcome(close=True, console=console)
