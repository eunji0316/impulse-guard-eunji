"""화면 단계 판정 (B-4): 쇼핑 아님 / 상품 화면 / 결제 화면

- 결제 화면: OCR 글자에서 결제 키워드(config.CHECKOUT_KEYWORDS)를 찾아 점수를 더한다.
  점수 합이 CHECKOUT_MIN_SCORE 이상이고 서로 다른 키워드가 CHECKOUT_MIN_WORDS개 이상일 때만 결제 화면이다.
  키워드 하나(예: 상품 화면의 '결제하기' 버튼)로는 결제 화면이 되지 않는다.
- 상품 화면: 결제 화면은 아니지만 원본 규칙(detector/shopping.py)으로 쇼핑몰인 화면
- 쇼핑 아님: 둘 다 아님

판정 결과에는 근거(찾은 키워드와 점수, 기준 점수)를 함께 담는다. 로그와 나중의 분류 모델 학습에 쓴다.

C-1부터 실제 판정은 decide(): 분류 모델(detector/classifier.py)이 정하고, 모델이 없거나 확률이
config.SCREEN_MODEL_MIN_PROB보다 낮거나 오류가 나면 위의 키워드 판정(classify)을 쓴다.
모델은 장바구니를 상품 화면, 주문 완료/주문 내역/배송 조회를 쇼핑 아님으로 본다 (ai/screen/README.md).
"""
from dataclasses import dataclass, field

from .. import config

NONE, PRODUCT, CHECKOUT = 'none', 'product', 'checkout'


def is_checkout_title(title):
    """창 제목(브라우저 탭 제목)이 결제 페이지 같으면 True (B-5). 자동 감지의 대기 시간만 줄이고 판정에는 쓰지 않는다"""
    t = (title or '').lower()
    return any(w.lower() in t for w in config.CHECKOUT_TITLE_WORDS)
LABELS = {NONE: '쇼핑 아님', PRODUCT: '상품 화면', CHECKOUT: '결제 화면'}


@dataclass
class StageResult:
    stage: str                                     # none / product / checkout
    score: int = 0                                 # 결제 키워드 점수 합
    matched: list = field(default_factory=list)    # [(키워드, 점수), ...] 점수 큰 순
    threshold: int = config.CHECKOUT_MIN_SCORE
    source: str = 'keyword'                        # 단계를 정한 방법: model / keyword (C-1)
    model_stage: str = None                        # 모델이 고른 분류 (모델을 못 썼으면 None)
    prob: float = None                             # 모델이 고른 분류의 확률
    fallback: str = ''                             # 키워드 판정으로 바꾼 이유 (저신뢰, 모델 없음 등)

    @property
    def label(self):
        return LABELS[self.stage]

    @property
    def words(self):
        return [w for w, _ in self.matched]

    def evidence(self):
        """로그용 근거 문구: '점수 7/4 [최종결제금액 3, 결제수단 2, ...]'

        모델을 거쳤으면 뒤에 붙인다: '| 모델 결제 화면 0.93' 또는 '| 키워드 판정 (저신뢰: 모델 상품 화면 0.52)'
        모델 파일이 없을 때는 붙이지 않는다 (프로그램 시작 때 한 번 기록한다)
        """
        inner = ', '.join(f'{w} {p}' for w, p in self.matched)
        text = f'점수 {self.score}/{self.threshold} [{inner}]'
        if self.source == 'model':
            text += f' | 모델 {LABELS[self.model_stage]} {self.prob:.2f}'
        elif self.model_stage:
            text += f' | 키워드 판정 ({self.fallback}: 모델 {LABELS[self.model_stage]} {self.prob:.2f})'
        return text


def normalize(text):
    """공백을 모두 빼고 OCR이 자주 틀리는 글자를 고친다 (config.CHECKOUT_OCR_FIXES, 예: '좀 결제금억' → '총결제금액')"""
    text = ''.join(text.split())
    for wrong, right in config.CHECKOUT_OCR_FIXES.items():
        text = text.replace(wrong, right)
    return text


def checkout_score(text, keywords=None):
    """(점수 합, [(키워드, 점수), ...]). 긴 키워드부터 찾고 찾은 부분은 지워 겹쳐 세지 않는다"""
    keywords = config.CHECKOUT_KEYWORDS if keywords is None else keywords
    rest = normalize(text)
    matched = []
    for word in sorted(keywords, key=len, reverse=True):
        key = normalize(word)
        if key and key in rest:
            matched.append((key, keywords[word]))
            rest = rest.replace(key, '\0')
    matched.sort(key=lambda m: -m[1])
    return sum(p for _, p in matched), matched


def classify(text, is_mall):
    """OCR 전체 글자와 원본 쇼핑 판정(is_mall)으로 단계를 정한다"""
    score, matched = checkout_score(text)
    if score >= config.CHECKOUT_MIN_SCORE and len(matched) >= config.CHECKOUT_MIN_WORDS:
        stage = CHECKOUT                           # 결제 화면은 원본 규칙과 상관없이 쇼핑 화면
    elif is_mall:
        stage = PRODUCT
    else:
        stage = NONE
    return StageResult(stage, score, matched)


def decide(text, is_mall):
    """C-1: 분류 모델로 단계를 정한다. 모델을 못 쓰거나 확신이 낮으면 키워드 판정(classify)

    결제 키워드 우선: 키워드 판정이 결제 화면이고 모델이 상품 화면을
    SCREEN_KEYWORD_CHECKOUT_MAX_PROB 미만으로 말하면 결제 화면 (결제 화면을 놓치지 않게)
    키워드 점수와 찾은 키워드는 어느 쪽이든 근거로 함께 남긴다.
    """
    kw = classify(text, is_mall)
    if not config.SCREEN_MODEL_ENABLED:
        return kw
    from . import classifier                       # stage는 모델 없이도 쓰이므로 여기서 불러온다
    pred = classifier.predict(text)
    if pred is None:
        kw.fallback = classifier.last_error() or '모델 판정 못 함'
        return kw
    label, prob, _ = pred
    kw.model_stage, kw.prob = label, prob
    if prob < config.SCREEN_MODEL_MIN_PROB:
        kw.fallback = '저신뢰'
        return kw
    if kw.stage == CHECKOUT and label == PRODUCT and prob < config.SCREEN_KEYWORD_CHECKOUT_MAX_PROB:
        kw.fallback = '결제 키워드 우선'
        return kw
    kw.stage, kw.source = label, 'model'
    return kw
