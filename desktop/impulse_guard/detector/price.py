"""가격 분석: 화면의 가격을 할인가, 원가, 기타(배송비, 적립금 등)로 구분한다

순서
1. 후보 찾기: OCR 상자에서 가격(49,600원 / ₩35,000 / 56,000)과 할인율(58%)을 찾는다.
   숫자와 '원'이 다른 상자로 나뉘어 있으면 합친다.
2. 단서 점수: 후보마다 글자 크기, 취소선, 글자 색, 주변 단어, 할인율과의 거리, 위치 등을 0~1로 계산한다.
   단서 점수는 Candidate.features에 따로 남겨, 나중에 학습 모델의 특성으로 쓸 수 있게 한다.
3. 역할 점수: 단서 점수 × 가중치(config.ROLE_WEIGHTS)의 합으로 할인가/원가/기타 점수를 낸다.
4. 할인율 검산: 원가 × (1 − 할인율) ≈ 할인가인 조합을 찾는다. 검산에 맞지 않는 값은 OCR 오류로 제외한다.
5. 결과: 할인가, 원가, 할인율과 각각의 확신도 (PriceResult)

img를 주지 않으면 취소선과 색 단서는 0으로 두고 나머지 단서로만 판단한다.
"""
import math
import re
from dataclasses import dataclass, field

import numpy as np

from .. import config
from ..ocr import OcrBox

FEATURE_NAMES = ['size', 'strike', 'color_red', 'color_gray', 'ctx_sale', 'ctx_orig', 'ctx_other',
                 'near_rate', 'pos_top', 'repeat', 'ocr_conf', 'format_ok']
ROLES = ['sale', 'original', 'other']

# 가격: ₩ 접두사 또는 숫자(쉼표/마침표 포함) + '원'(선택)
PRICE_RE = re.compile(r'(₩\s?)?(\d[\d,.]*\d|\d)(\s?원)?')
RATE_RE = re.compile(r'(\d{1,2})\s?%')
COMMA_RE = re.compile(r'^\d{1,3}(,\d{3})+$')
DOT_RE = re.compile(r'^\d{1,3}(\.\d{3})+$')     # OCR이 쉼표를 마침표로 읽은 경우
PERCENT_MISREAD_RE = re.compile(r'(\d{1,2})(96|76)')
WON_AS_DIGIT_RE = re.compile(r'(\d{1,3}(?:,\d{3})+)\d')   # '258,0008' → '258,000' + 원
STRIKE_REREAD_MIN = 0.8                         # 이 점수 이상이면 취소선으로 보고 다시 읽는다


@dataclass
class Candidate:
    """가격 후보 하나"""
    value: int
    text: str                    # 원래 글자 (예: '49,600원')
    box: list                    # [x, y, x2, y2] (가격 부분만)
    ocr_conf: float
    features: dict = field(default_factory=dict)   # 단서 점수 (학습 특성)
    scores: dict = field(default_factory=dict)     # 역할 점수 sale/original/other
    role: str = ''               # 최종 역할: sale, original, other, excluded
    reason: str = ''             # 역할을 정한 이유나 제외 사유
    reread: str = ''             # 취소선 구간을 다시 읽어 얻은 후보면 첫 OCR 글자 (예: '#49G68원')

    @property
    def h(self):
        return self.box[3] - self.box[1]

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) / 2

    @property
    def top_role(self):
        return max(self.scores, key=self.scores.get) if self.scores else ''


@dataclass
class RateToken:
    """할인율 후보 하나"""
    value: int                   # % 값
    text: str
    box: list
    ocr_conf: float
    is_product: bool = True      # False면 쿠폰/적립/평가 등 상품 할인율이 아닌 %
    reason: str = ''

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) / 2


@dataclass
class PriceResult:
    sale_price: int = None
    original_price: int = None
    discount_rate: int = None    # % (화면에 보인 값. 화면에 없으면 원가와 할인가로 계산한 값)
    sale_conf: float = 0.0
    original_conf: float = 0.0
    rate_conf: float = 0.0
    verified: bool = False       # 할인율 검산을 통과했는지
    rate_shown: bool = False     # 할인율이 화면에 보였는지
    candidates: list = field(default_factory=list)
    rates: list = field(default_factory=list)


# ── 1. 후보 찾기 ───────────────────────────────────────────────

def _sub_box(box: OcrBox, start, end):
    """상자 글자 중 [start, end) 부분의 대략적인 좌표 (글자 수 비율로 가로를 나눈다)"""
    n = max(len(box.text), 1)
    x0 = box.x + box.w * start / n
    x1 = box.x + box.w * end / n
    return [int(x0), box.y, int(math.ceil(x1)), box.y2]


def _parse_number(num):
    """'49,600' → (49600, format_ok). 쉼표가 세 자리마다 있거나 1000 미만이면 format_ok"""
    if COMMA_RE.match(num):
        return int(num.replace(',', '')), True
    if DOT_RE.match(num):
        return int(num.replace('.', '')), True
    if num.isdigit():
        value = int(num)
        return value, value < 1000      # 쉼표 없는 4자리 이상 숫자는 형식 이상 (예: 444366원)
    return None, False


def _same_line(a_y, a_y2, b_y, b_y2):
    h = max(a_y2 - a_y, b_y2 - b_y, 1)
    return abs((a_y + a_y2) / 2 - (b_y + b_y2) / 2) <= h * config.SAME_LINE_RATIO


def _next_is_won(box, boxes):
    """box 바로 오른쪽 같은 줄에 '원'으로 시작하는 상자가 있으면 그 상자"""
    for other in boxes:
        if other is box or not other.text.strip().startswith('원'):
            continue
        gap = other.x - box.x2
        if -box.h * 0.3 <= gap <= box.h * config.MERGE_GAP_RATIO and _same_line(box.y, box.y2, other.y, other.y2):
            return other
    return None


def find_tokens(boxes):
    """OCR 상자에서 가격 후보와 할인율 후보를 찾는다"""
    prices, rates = [], []
    for box in boxes:
        text = box.text
        rate_spans = []
        for m in RATE_RE.finditer(text):
            rate_spans.append(m.span())
            rates.append(RateToken(value=int(m.group(1)), text=m.group(0),
                                   box=_sub_box(box, *m.span()), ocr_conf=box.conf))
        for m in PRICE_RE.finditer(text):
            if any(s <= m.start() < e for s, e in rate_spans):
                continue                       # '58%'의 58은 가격이 아님
            won, num, suffix = m.group(1), m.group(2), m.group(3)
            # 바로 뒤가 다른 숫자/%/단위면 가격이 아님 (예: 11/12, 93%, 3.14)
            after = text[m.end():m.end() + 1]
            if after in ('%', '/', '.', '-', ':') or after.isdigit():
                continue
            value, format_ok = _parse_number(num)
            if value is None:
                continue
            # 앞에 영문/숫자/기호가 붙어 있으면 깨진 글자의 일부 (예: '35B,888원'의 888, '#49G68원'의 68)
            before = text[m.start() - 1] if m.start() > 0 else ' '
            if before.isascii() and (before.isalnum() or before in ',.#'):
                format_ok = False
            sub = _sub_box(box, *m.span())
            has_won = bool(won or suffix)
            if not has_won and m.end() == len(text.rstrip()):
                won_box = _next_is_won(box, boxes)   # 숫자와 '원'이 다른 상자로 나뉜 경우 합친다
                if won_box is not None:
                    has_won = True
                    sub[2] = max(sub[2], won_box.x2)
            # '원'/'₩'이 없으면 쉼표 형식일 때만 가격으로 본다 (리뷰 수 332, 연도 2026 등 제외)
            if not has_won and ',' not in num:
                continue
            prices.append(Candidate(value=value, text=m.group(0).strip(), box=sub, ocr_conf=box.conf,
                                    features={'format_ok': 1.0 if format_ok else 0.0}))

    # EasyOCR은 '%'를 '96'(가끔 '76')으로 읽는다 (예: 58% → '5896').
    # 상자 하나가 통째로 '숫자+96'이고 바로 오른쪽 같은 줄에 가격이 있을 때만 할인율로 보정한다
    for box in boxes:
        m = PERCENT_MISREAD_RE.fullmatch(box.text.strip())
        if not m:
            continue
        for c in prices:
            gap = c.box[0] - box.x2
            if -box.h * 0.3 <= gap <= box.h * 2 and _same_line(box.y, box.y2, c.box[1], c.box[3]):
                rates.append(RateToken(value=int(m.group(1)), text=box.text, box=[box.x, box.y, box.x2, box.y2],
                                       ocr_conf=box.conf * 0.8, reason=f"'%' 오인식 보정 ({box.text} → {m.group(1)}%)"))
                break
    return prices, rates


def _box_of(c):
    return OcrBox(text=c[0], conf=c[1], bbox=[[c[2][0], c[2][1]], [c[2][2], c[2][1]], [c[2][2], c[2][3]], [c[2][0], c[2][3]]])


def apply_reread(boxes, prices, img, reread):
    """취소선이 있는 상자는 선 구간만 다시 읽어 가격 후보를 바꾼다

    reread(img, [x0, y0, x1, y1]) → [(글자, 확신도), ...]. 실제 실행은 ocr.read_struck, 테스트는 캐시
    """
    for box in boxes:
        if not any(ch.isdigit() for ch in box.text):
            continue
        score, seg = strike_segment(img, [box.x, box.y, box.x2, box.y2])
        if score < STRIKE_REREAD_MIN or seg is None:
            continue
        seg_box = [seg[0], box.y, seg[1], box.y2]
        results = reread(img, seg_box) or []
        # 선 구간 안에 있던 첫 OCR 후보(깨진 값)는 버린다
        prices = [c for c in prices
                  if not (seg[0] - 2 <= c.cx <= seg[1] + 2 and box.y <= c.cy <= box.y2)]
        for text, conf in results:
            # 숫자만 허용해 다시 읽으면 '원'을 숫자 하나로 읽기도 한다 (예: 258,000원 → '258,0008')
            fixed = WON_AS_DIGIT_RE.fullmatch(text.strip())
            if fixed:
                text = fixed.group(1) + '원'
            found, _ = find_tokens([_box_of((text, conf, seg_box))])
            for c in found:
                c.box = seg_box
                c.reread = box.text
                prices.append(c)
    return prices


# ── 2. 단서 점수 ───────────────────────────────────────────────

def _context_text(target_box, boxes, own_box=None, own_span_text='', same_line_only=False):
    """target_box 주변(같은 줄 좌우, 바로 위아래)의 글자"""
    x0, y0, x1, y1 = target_box
    h = max(y1 - y0, 1)
    parts = []
    for b in boxes:
        if b is own_box:
            parts.append(b.text.replace(own_span_text, ' ', 1))
            continue
        same = _same_line(y0, y1, b.y, b.y2)
        dx = max(b.x - x1, x0 - b.x2, 0)
        dy = max(b.y - y1, y0 - b.y2, 0)
        if same and dx <= h * config.CONTEXT_X_RATIO:
            parts.append(b.text)
        elif not same_line_only and not same and dy <= h * config.CONTEXT_Y_RATIO and dx <= h * 3:
            parts.append(b.text)
    return ' '.join(parts)


def _without_sale_words(text):
    """'쿠폰적용가'처럼 판매가 라벨 안의 '쿠폰'이 기타 단어로 잡히지 않게 판매가 라벨을 먼저 지운다"""
    for w in sorted(config.CONTEXT_SALE_WORDS, key=len, reverse=True):
        text = text.replace(w, ' ')
    return text


def _has_word(text, words):
    return 1.0 if any(w in text for w in words) else 0.0


def _owner(cand_box, boxes):
    """후보 좌표를 담고 있는 OCR 상자"""
    cx, cy = (cand_box[0] + cand_box[2]) / 2, (cand_box[1] + cand_box[3]) / 2
    for b in boxes:
        if b.x <= cx <= b.x2 and b.y <= cy <= b.y2:
            return b
    return None


def _crop(img, box, pad=1):
    if img is None:
        return None
    x0, y0, x1, y1 = box
    hgt, wid = img.shape[:2]
    x0, y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    x1, y1 = min(wid, int(x1) + pad), min(hgt, int(y1) + pad)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return img[y0:y1, x0:x1]


def _foreground(crop):
    """글자 픽셀 마스크: 테두리 픽셀의 중간값을 배경으로 보고, 배경과 밝기 차이가 큰 픽셀"""
    gray = crop.astype(np.int16).mean(axis=2)
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    bg = np.median(border)
    return np.abs(gray - bg) > 40


def _longest_run(row):
    """가로 한 줄에서 가장 긴 글자 픽셀 연속 구간 (시작, 끝+1). 1픽셀 끊김까지는 이어진 선으로 본다"""
    best = (0, 0)
    start, last = None, None
    for i, v in enumerate(row):
        if not v:
            continue
        if start is None or i - last > 2:
            start = i
        last = i
        if last + 1 - start > best[1] - best[0]:
            best = (start, last + 1)
    return best


def strike_segment(img, box, pad=1):
    """취소선 찾기. (점수 0~1, 선이 지나가는 가로 구간 [x0, x1] 이미지 좌표)

    상자 가운데 높이(config.STRIKE_ROW_RANGE)의 가로줄 중, 글자 픽셀이 가장 길게 이어진 구간을 찾는다.
    점수는 그 길이를 '선 구간 안의 글자 너비'와 비교한다. 상자에 다른 글자(할인율, 라벨)가 섞여 있어도
    선이 지나가는 부분만 본다. 선 길이가 글자 높이의 2배보다 짧으면 취소선으로 보지 않는다.
    """
    crop = _crop(img, box, pad)
    if crop is None:
        return 0.0, None
    fg = _foreground(crop)
    h = fg.shape[0]
    r0, r1 = int(h * config.STRIKE_ROW_RANGE[0]), int(math.ceil(h * config.STRIKE_ROW_RANGE[1]))
    best = (0, 0)
    for row in fg[r0:r1]:
        run = _longest_run(row)
        if run[1] - run[0] > best[1] - best[0]:
            best = run
    length = best[1] - best[0]
    if length < max(h * 2, 5):
        return 0.0, None
    # 선 구간 양 끝에서 글자가 더 이어지는지 본다 (선이 글자 너비 전체를 덮어야 취소선)
    cols = np.where(fg.any(axis=0))[0]
    margin = max(2, int(h * 0.3))
    seg_cols = cols[(cols >= best[0] - margin) & (cols < best[1] + margin)]
    width = seg_cols[-1] - seg_cols[0] + 1 if len(seg_cols) else length
    ratio = length / width
    score = float(np.clip((ratio - 0.4) / (config.STRIKE_MIN_RUN - 0.4), 0, 1))
    x_off = max(0, int(box[0]) - pad)
    return score, [x_off + best[0], x_off + best[1]]


def strike_score(img, box):
    """취소선 점수만 (취소선 없는 글자는 보통 0, 취소선이 글자 전체를 가로지르면 1)"""
    return strike_segment(img, box)[0]


def color_scores(img, box):
    """글자 대표 색 → (빨강 정도, 회색 정도). img는 BGR"""
    crop = _crop(img, box)
    if crop is None:
        return 0.0, 0.0
    fg = _foreground(crop)
    if fg.sum() < 5:
        return 0.0, 0.0
    b, g, r = [float(np.median(crop[:, :, i][fg])) for i in range(3)]
    red = float(np.clip((r - max(g, b) - 40) / 80, 0, 1))
    sat = max(r, g, b) - min(r, g, b)
    lum = (r + g + b) / 3
    # 회색: 채도가 낮고 너무 진하지도(검정) 너무 밝지도 않은 글자
    gray = 1.0 if (sat < 35 and 110 <= lum <= 215) else (0.5 if (sat < 35 and 90 <= lum < 110) else 0.0)
    return red, gray


def _rate_is_other(rate, boxes, owner):
    """할인율 같은 줄에 쿠폰/적립/평가 등이 있으면 상품 할인율이 아님"""
    ctx = _without_sale_words(_context_text(rate.box, boxes, owner, rate.text, same_line_only=True))
    return any(w in ctx for w in config.RATE_OTHER_WORDS), ctx


def score_candidates(prices, rates, boxes, img=None):
    """후보마다 단서 점수와 역할 점수를 채운다"""
    height = img.shape[0] if img is not None else max([b.y2 for b in boxes] or [1])

    for rate in rates:
        owner = _owner(rate.box, boxes)
        is_other, ctx = _rate_is_other(rate, boxes, owner)
        if not (config.RATE_MIN <= rate.value <= config.RATE_MAX):
            rate.is_product, rate.reason = False, '범위 밖'
        elif is_other:
            rate.is_product, rate.reason = False, '주변 단어(쿠폰/적립/평가 등)'
    product_rates = [r for r in rates if r.is_product]

    in_range = [c for c in prices if config.PRICE_MIN <= c.value <= config.PRICE_MAX]
    max_h = max([c.h for c in in_range] or [1])
    counts = {}
    for c in in_range:
        counts[c.value] = counts.get(c.value, 0) + 1

    for c in prices:
        if not (config.PRICE_MIN <= c.value <= config.PRICE_MAX):
            c.role, c.reason = 'excluded', f'금액 범위 밖 ({config.PRICE_MIN:,}~{config.PRICE_MAX:,}원)'
            continue
        owner = _owner(c.box, boxes)
        ctx = _context_text(c.box, boxes, owner, c.text)
        ctx_rest = _without_sale_words(ctx)
        red, gray = color_scores(img, c.box)
        near = 0.0
        for r in product_rates:
            d = math.hypot(c.cx - r.cx, c.cy - r.cy)
            near = max(near, 1 - d / (c.h * config.NEAR_RATE_RATIO))
        c.features.update({
            'size': c.h / max_h,
            'strike': strike_score(img, c.box),
            'color_red': red,
            'color_gray': gray,
            'ctx_sale': _has_word(ctx, config.CONTEXT_SALE_WORDS),
            'ctx_orig': _has_word(ctx_rest, config.CONTEXT_ORIG_WORDS),
            'ctx_other': _has_word(ctx_rest, config.CONTEXT_OTHER_WORDS),
            'near_rate': float(np.clip(near, 0, 1)),
            'pos_top': 1 - c.cy / max(height, 1),
            'repeat': min(counts[c.value] - 1, 2) / 2,
            'ocr_conf': c.ocr_conf,
        })
        c.features = {k: round(float(c.features.get(k, 0.0)), 3) for k in FEATURE_NAMES}
        c.scores = {role: round(sum(w * c.features[k] for k, w in config.ROLE_WEIGHTS[role].items()), 3)
                    for role in ROLES}
    return product_rates


# ── 3~5. 역할 정하기, 검산, 확신도 ─────────────────────────────

def _sigmoid(x):
    return 1 / (1 + math.exp(-x))


def _margin(c, role):
    """role 점수가 다른 역할 점수보다 얼마나 높은지 (0~1)"""
    others = [v for k, v in c.scores.items() if k != role]
    return _sigmoid(c.scores[role] - max(others))


def _conf(c, role, verified):
    return round(0.5 * _margin(c, role) + 0.3 * (1.0 if verified else 0.0) + 0.2 * c.ocr_conf, 3)


def analyze(boxes, img=None, reread=None):
    """OCR 상자(와 이미지)에서 할인가, 원가, 할인율을 찾는다

    reread: 취소선 구간을 다시 읽는 함수. 실제 실행은 ocr.read_struck, 테스트는 캐시에서 꺼내는 함수.
            None이면 다시 읽지 않는다.
    """
    prices, rates = find_tokens(boxes)
    if img is not None and reread is not None:
        prices = apply_reread(boxes, prices, img, reread)
    product_rates = score_candidates(prices, rates, boxes, img)
    result = PriceResult(candidates=prices, rates=rates)
    pool = [c for c in prices if c.role != 'excluded']
    if not pool:
        return result

    # 할인율 검산: (원가, 할인가, 할인율) 조합 중 오차가 허용 범위 안이고 점수 합이 가장 큰 것
    best = None
    for rate in product_rates:
        for o in pool:
            for s in pool:
                if o.value <= s.value:
                    continue
                err = abs(1 - s.value / o.value - rate.value / 100)
                if err > config.RATE_TOLERANCE:
                    continue
                total = o.scores['original'] + s.scores['sale'] - err * 50
                if best is None or total > best[0]:
                    best = (total, o, s, rate, err)

    if best:
        _, o, s, rate, err = best
        result.sale_price, result.original_price, result.discount_rate = s.value, o.value, rate.value
        result.verified = result.rate_shown = True
        result.sale_conf = _conf(s, 'sale', True)
        result.original_conf = _conf(o, 'original', True)
        result.rate_conf = round((0.5 * (1 - err / config.RATE_TOLERANCE) + 0.3 + 0.2 * rate.ocr_conf), 3)
        rate.reason = '검산 통과'
    else:
        # 검산할 수 없으면 역할 점수만으로 정한다
        sales = [c for c in pool if c.top_role == 'sale']
        if sales:
            s = max(sales, key=lambda c: c.scores['sale'])
            result.sale_price, result.sale_conf = s.value, _conf(s, 'sale', False)
            origs = [c for c in pool if c.top_role == 'original' and c.value > s.value]
            if origs:
                o = max(origs, key=lambda c: c.scores['original'])
                result.original_price, result.original_conf = o.value, _conf(o, 'original', False)
                result.discount_rate = round((1 - s.value / o.value) * 100)
                result.rate_conf = round(min(result.sale_conf, result.original_conf) * 0.8, 3)
            if product_rates and result.original_price:
                result.rate_shown = True

    # 후보마다 최종 역할과 사유 기록
    for c in pool:
        if c.value == result.sale_price and c.top_role != 'other':
            c.role, c.reason = 'sale', '검산 통과' if result.verified else '역할 점수'
        elif c.value == result.original_price and c.top_role != 'other':
            c.role, c.reason = 'original', '검산 통과' if result.verified else '역할 점수'
        elif c.top_role == 'other':
            c.role, c.reason = 'other', '기타 점수가 가장 높음'
        elif c.features.get('format_ok', 1) < 1:
            c.role, c.reason = 'excluded', '쉼표 형식 이상 (OCR 오류 의심)'
        elif result.verified:
            c.role, c.reason = 'excluded', '할인율 검산 불일치 (OCR 오류 의심)'
        else:
            c.role, c.reason = 'other', '선택되지 않음'
    return result


# ── 결제 화면의 결제 금액 (B-4) ────────────────────────────────

from .stage import normalize  # noqa: E402  (stage는 price를 쓰지 않으므로 순환 없음)

def find_checkout_total(boxes):
    """결제 화면에서 결제 금액 (금액, 라벨). 못 찾으면 (None, '')

    config.CHECKOUT_TOTAL_LABELS 순서(최종 결제금액 → 총 결제금액 → ... → 결제하기 버튼)로 라벨을 찾고,
    라벨과 같은 상자 안 → 같은 줄 오른쪽 → 바로 아래(상자 높이의 CHECKOUT_TOTAL_BELOW배 안) 순서로, 같은 순위에서는 가장 가까운 가격을 고른다.
    같은 줄의 금액은 멀리 있어도 아래 줄보다 우선한다 (실제 캡처: 지그재그 '총 결제금액 … 224,910원' 바로 아래에
    '신한카드는 174,910원' 광고 줄이 있다).
    """
    prices = [c for c in find_tokens(boxes)[0]
              if config.PRICE_MIN <= c.value <= config.PRICE_MAX and c.features.get('format_ok')]
    if not prices:
        return None, ''
    for label in config.CHECKOUT_TOTAL_LABELS:
        best = None
        for b in boxes:
            if label not in normalize(b.text):            # 공백 무시, OCR 오인식 보정 ('좀 결제금억' → '총결제금액')
                continue
            h = max(b.h, 1)
            for c in prices:
                inside = b.x - 1 <= c.box[0] and c.box[2] <= b.x2 + 1 and _same_line(b.y, b.y2, c.box[1], c.box[3])
                if inside:
                    rank = (0, 0)
                elif _same_line(b.y, b.y2, c.box[1], c.box[3]) and c.box[0] >= b.x2 - h:
                    rank = (1, c.box[0] - b.x2)                                         # 같은 줄 오른쪽
                elif 0 <= c.box[1] - b.y2 <= h * config.CHECKOUT_TOTAL_BELOW and c.box[2] >= b.x and c.box[0] <= b.x2 + h * 4:
                    rank = (2, (c.box[1] - b.y2) * 3 + abs(c.box[0] - b.x))             # 바로 아래
                else:
                    continue
                if best is None or rank < best[0]:
                    best = (rank, c.value)
        if best is not None:
            return best[1], label
    return None, ''
