"""페이지 정보: 어느 사이트인지, 상품명, 결제 화면인지

서버 check 요청에 넣을 값을 OCR 결과에서 찾는 간단한 규칙이다.
- site: 화면 글자에서 사이트 이름/로고 글자(config.SITE_HINTS)를 찾는다. 못 찾으면 ''(모름)
- item_name: 할인가 바로 위쪽에서 같은 영역에 있는 가장 큰 글자 줄. 못 찾으면 ''
- is_checkout: 결제 화면인지. 화면 단계 판정(detector/stage.py, 키워드 점수)을 따른다 (B-4)
- checkout_total: 결제 화면이면 '최종 결제금액' 등 라벨 옆의 결제 금액 (price.find_checkout_total)
"""
import re
from dataclasses import dataclass

from .. import config
from . import stage as stage_mod
from .price import PRICE_RE, RATE_RE, find_checkout_total

LETTER_RE = re.compile(r'[가-힣A-Za-z]')


@dataclass
class PageInfo:
    site: str = ''
    item_name: str = ''
    is_checkout: bool = False
    checkout_words: tuple = ()
    checkout_total: int = None   # 결제 화면의 결제 금액 (못 찾으면 None)
    total_label: str = ''        # 결제 금액을 찾은 라벨 (예: '최종결제금액')


def find_site(text, extra_hints=None):
    """화면 글자에서 사이트 코드 찾기. 단어가 가장 많이 나온 사이트, 없으면 ''

    extra_hints: {사이트 코드: [이름, ...]} 서버 setting 응답에서 받은 이름 등
    """
    hints = {code: list(words) for code, words in config.SITE_HINTS.items()}
    for code, words in (extra_hints or {}).items():
        hints.setdefault(code, []).extend(w for w in words if w)
    lower = text.lower()
    counts = {code: sum(lower.count(w.lower()) for w in set(words)) for code, words in hints.items()}
    best = max(counts, key=counts.get) if counts else ''
    return best if best and counts[best] > 0 else ''


def find_checkout(text):
    """(결제 화면인지, 찾은 키워드). 판정은 stage.classify와 같다"""
    st = stage_mod.classify(text, is_mall=False)
    return st.stage == stage_mod.CHECKOUT, tuple(st.words)


def _sale_box(price_result):
    """할인가로 고른 후보 중 할인가 점수가 가장 높은 것의 좌표"""
    sales = [c for c in price_result.candidates if c.role == 'sale']
    if not sales:
        return None
    return max(sales, key=lambda c: c.scores.get('sale', 0)).box


def find_item_name(boxes, price_result):
    """할인가 위쪽, 왼쪽 끝이 비슷한 위치에 있는 글자 줄 중 가장 큰 것"""
    if price_result is None:
        return ''
    sale = _sale_box(price_result)
    if sale is None:
        return ''
    x0, y0, _, y1 = sale
    h = max(y1 - y0, 1)
    best = None
    for b in boxes:
        if b.y2 > y0 or b.y < y0 - h * config.ITEM_NAME_SEARCH_UP:
            continue                                     # 할인가보다 위, 정해진 범위 안
        if abs(b.x - x0) > h * config.ITEM_NAME_ALIGN_X:
            continue                                     # 같은 영역(왼쪽 끝이 비슷)
        text = b.text.strip()
        if len(LETTER_RE.findall(text)) < config.ITEM_NAME_MIN_LETTERS:
            continue
        if PRICE_RE.search(text) and ('원' in text or ',' in text) or RATE_RE.search(text):
            continue                                     # 가격/할인율 줄
        if any(w in text for w in config.ITEM_NAME_EXCLUDE):
            continue
        key = (b.h, b.y)                                 # 큰 글자 우선, 같으면 할인가에 가까운 것
        if best is None or key > best[0]:
            best = (key, text)
    return best[1] if best else ''


def analyze(boxes, full_text, price_result=None, extra_site_hints=None, stage_result=None):
    """stage_result: stage.classify 결과 (없으면 여기서 판정)"""
    st = stage_result or stage_mod.classify(full_text, is_mall=True)
    info = PageInfo(
        site=find_site(full_text, extra_site_hints),
        item_name=find_item_name(boxes, price_result),
        is_checkout=st.stage == stage_mod.CHECKOUT,
        checkout_words=tuple(st.words),
    )
    if info.is_checkout:
        info.checkout_total, info.total_label = find_checkout_total(boxes)
    return info
