"""설정값 모음

원본(desktop/original/shopping_detector.py)에서 가져온 값은 원본과 똑같이 유지한다.
값을 바꾸면 원본과 판정 결과가 달라지므로 tests/test_shopping.py가 실패한다.
"""

# ── OCR (원본과 같음) ──────────────────────────────────────────
OCR_LANGS = ['ko', 'en']   # 한국어 + 영어
OCR_GPU = False            # CPU 모드

# ── 캡처 (원본과 같음) ─────────────────────────────────────────
CAPTURE_MONITOR = 1        # mss의 monitors[1] = 주 모니터

# ── 단축키 (원본과 같음) ───────────────────────────────────────
HOTKEY = 'f4'

# ── 쇼핑 화면 판정 (원본과 같음) ───────────────────────────────
SHOPPING_KEYWORDS = [
    '장바구니', '구매하기', '바로구매', '결제하기', '주문하기',
    '옵션선택', '수량', '배송비', '상품상세', '찜하기', '쿠폰'
]
# 원본 정규식. ',원'처럼 숫자 없는 값도 잡히지만 원본과 결과를 맞추려고 그대로 둔다
SHOPPING_PRICE_REGEX = r'[\d,]+원|₩[\d,]+'
SHOPPING_MIN_KEYWORDS = 2  # 키워드가 이 개수 이상이면 쇼핑몰
SHOPPING_MIN_PRICES = 1    # 또는 가격 패턴이 이 개수 이상이면 쇼핑몰

# ── 가격 분석 (B-1 신규) ───────────────────────────────────────
PRICE_MIN = 100            # 이보다 작은 금액은 가격으로 보지 않음 (원)
PRICE_MAX = 10_000_000     # 이보다 큰 금액은 OCR 오류로 봄 (원)
RATE_MIN = 1               # 할인율 범위 (%)
RATE_MAX = 95

# 할인율 검산 허용 오차: |1 - 할인가/원가 - 할인율| <= 이 값
# 사이트가 할인율을 반올림/버림해서 보여 주므로 금액이 아니라 할인율(%p)로 비교한다
RATE_TOLERANCE = 0.015     # 1.5%p

# 같은 줄로 볼 세로 차이 (상자 높이의 비율)
SAME_LINE_RATIO = 0.6
# 숫자 상자와 '원' 상자를 합칠 최대 가로 간격 (상자 높이의 배수)
MERGE_GAP_RATIO = 0.8
# 주변 단어를 찾을 범위 (가격 상자 높이의 배수)
CONTEXT_X_RATIO = 12       # 같은 줄에서 왼쪽/오른쪽으로
CONTEXT_Y_RATIO = 1.5      # 위/아래로
# 할인율 상자가 '가까이 있다'고 볼 거리 (가격 상자 높이의 배수)
NEAR_RATE_RATIO = 6

# 주변 단어 (부분 일치)
CONTEXT_SALE_WORDS = ['판매가', '할인가', '쿠폰적용가', '적용가', '최종가', '혜택가', '특가']
CONTEXT_ORIG_WORDS = ['정가', '원가', '소비자가', '시중가', '정상가']
CONTEXT_OTHER_WORDS = ['배송비', '적립', '최대', '쿠폰', '포인트', '캐시', '머니', '할부',
                       '총', '합계', '무료', '첫 구매', '첫구매']
# 할인율 옆에 이런 단어가 있으면 상품 할인율이 아님 (예: '첫 구매 20% 쿠폰', '최대 20% 쿠폰팩')
RATE_OTHER_WORDS = ['쿠폰', '최대', '첫 구매', '첫구매', '적립', '신규', '카드', '만족', '평가']

# 역할 점수 가중치. 단서 점수(0~1)에 곱해서 더한다. 학습 모델로 바꾸기 전의 규칙 점수
ROLE_WEIGHTS = {
    'sale': {
        'size': 2.0, 'strike': -3.0, 'color_red': 1.0, 'color_gray': -1.0,
        'ctx_sale': 1.5, 'ctx_orig': -1.0, 'ctx_other': -2.0,
        'near_rate': 1.0, 'pos_top': 0.5, 'repeat': 0.3, 'ocr_conf': 0.5, 'format_ok': 1.0,
    },
    'original': {
        'size': -1.0, 'strike': 3.0, 'color_red': -1.0, 'color_gray': 1.0,
        'ctx_sale': -0.5, 'ctx_orig': 2.0, 'ctx_other': -2.0,
        'near_rate': 1.0, 'pos_top': 0.5, 'repeat': -0.3, 'ocr_conf': 0.5, 'format_ok': 1.0,
    },
    'other': {
        'size': -0.5, 'strike': -1.0, 'color_red': 0.0, 'color_gray': 0.0,
        'ctx_sale': -1.0, 'ctx_orig': -1.0, 'ctx_other': 3.0,
        'near_rate': -1.0, 'pos_top': -0.5, 'repeat': 0.0, 'ocr_conf': 0.0, 'format_ok': 0.0,
    },
}

# 취소선 판정: 상자 가운데 높이 범위에서 글자색 픽셀이 너비의 이 비율 이상 이어지면 취소선
STRIKE_ROW_RANGE = (0.30, 0.75)
STRIKE_MIN_RUN = 0.70
