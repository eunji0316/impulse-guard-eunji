"""화면 단계 판정 (B-4): 쇼핑 아님 / 상품 화면 / 결제 화면

- 결제 화면: OCR 글자에서 결제 키워드(config.CHECKOUT_KEYWORDS)를 찾아 점수를 더한다.
  점수 합이 CHECKOUT_MIN_SCORE 이상이고 서로 다른 키워드가 CHECKOUT_MIN_WORDS개 이상일 때만 결제 화면이다.
  키워드 하나(예: 상품 화면의 '결제하기' 버튼)로는 결제 화면이 되지 않는다.
- 상품 화면: 결제 화면은 아니지만 원본 규칙(detector/shopping.py)으로 쇼핑몰인 화면
- 쇼핑 아님: 둘 다 아님

판정 결과에는 근거(찾은 키워드와 점수, 기준 점수)를 함께 담는다. 로그와 나중의 분류 모델 학습에 쓴다.
"""
from dataclasses import dataclass, field

from .. import config

NONE, PRODUCT, CHECKOUT = 'none', 'product', 'checkout'
LABELS = {NONE: '쇼핑 아님', PRODUCT: '상품 화면', CHECKOUT: '결제 화면'}


@dataclass
class StageResult:
    stage: str                                     # none / product / checkout
    score: int = 0                                 # 결제 키워드 점수 합
    matched: list = field(default_factory=list)    # [(키워드, 점수), ...] 점수 큰 순
    threshold: int = config.CHECKOUT_MIN_SCORE

    @property
    def label(self):
        return LABELS[self.stage]

    @property
    def words(self):
        return [w for w, _ in self.matched]

    def evidence(self):
        """로그용 근거 문구: '점수 7/4 [최종결제금액 3, 결제수단 2, ...]'"""
        inner = ', '.join(f'{w} {p}' for w, p in self.matched)
        return f'점수 {self.score}/{self.threshold} [{inner}]'


def normalize(text):
    """공백을 모두 뺀다 (OCR 띄어쓰기 차이 무시)"""
    return ''.join(text.split())


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
