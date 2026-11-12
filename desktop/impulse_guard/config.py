"""설정값 모음

원본(desktop/original/shopping_detector.py)에서 가져온 값은 원본과 똑같이 유지한다.
값을 바꾸면 원본과 판정 결과가 달라지므로 tests/test_shopping.py가 실패한다.
"""

# ── OCR (원본과 같음) ──────────────────────────────────────────
OCR_LANGS = ['ko', 'en']   # 한국어 + 영어
OCR_GPU = False            # CPU 모드
# OCR 엔진 (B-5): 'win' = Windows 내장 OCR (winocr.py, 화면 한 장 약 1초), 'easy' = EasyOCR (원본과 같음, 약 10초)
# 'win'이어도 한국어 Windows OCR을 쓸 수 없으면(언어팩/패키지 없음) EasyOCR로 바꿔 쓴다 (main.ocr_engine)
OCR_ENGINE = 'win'
# Windows 내장 OCR (winocr.py). 작은 글자에서 쉼표를 빠뜨려서 키워서 읽는다
WINOCR_LANG = 'ko'
WINOCR_SCALE = 2.0         # 키우는 배율 (1배: '224910원', 2배: '224,910원')
WINOCR_SPLIT_GAP = 1.5     # 한 줄 안에서 단어 사이가 줄 높이의 이 배수보다 멀면 다른 상자

# ── 캡처 (원본과 같음) ─────────────────────────────────────────
CAPTURE_MONITOR = 1        # mss의 monitors[1] = 주 모니터
# 자동 감지/F4는 맨 앞 창 영역만 캡처한다 (B-5). 옆 창의 글자를 읽지 않고(개인정보, 자기 화면 오인), 이미지가 작아 OCR이 빠르다.
# 창 영역을 못 구하거나(최소화 등) CAPTURE_MIN_SIZE보다 작으면 주 모니터 전체
CAPTURE_ACTIVE_WINDOW = True
CAPTURE_MIN_SIZE = 200     # px

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
                       '총', '합계', '무료', '첫 구매', '첫구매', '혜택']
# 상품 화면에서 혜택/적립 금액으로 보고 할인가·원가 후보에서 빼는 단어 (C-2).
# 결제 화면 목록(CHECKOUT_TOTAL_EXCLUDE)과 달리 '쿠폰', '할인'은 넣지 않는다 ('쿠폰할인가 44,800원'은 진짜 판매가).
# 판매가 라벨(CONTEXT_SALE_WORDS, '혜택가' 등)은 먼저 지우고 비교한다
PRICE_BENEFIT_WORDS = ['혜택', '적립', '적림', '포인트', '마일리지', '밀리지', '캐시백', '페이백', '리워드']
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

# ── 페이지 정보 (B-2 신규): 사이트, 상품명, 결제 화면 ──────────
# 사이트 코드는 서버의 IPP_BLOCK_SITES와 같다. 화면 글자에 이 단어가 있으면 그 사이트로 본다 (대소문자 무시)
# 서버 setting 응답의 사이트 이름도 실행 중에 더해진다
SITE_HINTS = {
    'coupang': ['coupang', '쿠팡'],
    'musinsa': ['musinsa', '무신사'],
    'zigzag':  ['zigzag', '지그재그'],
    'naver':   ['네이버쇼핑', 'naver'],
    'gmarket': ['gmarket', 'g마켓'],
    '11st':    ['11번가', '11st'],
}
# 상품명: 할인가 위쪽에서 찾는다
ITEM_NAME_SEARCH_UP = 10      # 할인가 상자 높이의 몇 배 위까지 볼지
ITEM_NAME_ALIGN_X = 4         # 할인가와 왼쪽 끝이 이 배수(상자 높이 기준) 안에 있어야 같은 영역
ITEM_NAME_MIN_LETTERS = 4     # 글자(한글/영문) 수가 이보다 적으면 상품명이 아님
ITEM_NAME_EXCLUDE = ['리뷰', '상품평', '만족', '별점', '평점', '도착', '배송', '쿠폰', '판매자']
# ── 화면 단계: 쇼핑 아님 / 상품 화면 / 결제 화면 (B-4, detector/stage.py) ──
# 결제 화면 키워드와 점수. 공백을 모두 뺀 글자로 비교한다 (OCR이 '최종 결제 금액'/'최종결제금액'으로 다르게 읽어도 맞게)
# 긴 키워드부터 찾고, 찾은 부분은 지워서 '배송지정보' 안의 '배송지'를 두 번 세지 않는다
CHECKOUT_KEYWORDS = {
    # 3점: 결제 화면에만 나오는 말
    '주문/결제': 3, '주문결제': 3, '최종결제금액': 3, '총결제금액': 3, '결제예정금액': 3, '최종결제': 3,
    # 2점: 결제 화면에 거의 항상 있는 말
    '결제하기': 2, '결제수단': 2, '결제방법': 2, '주문자정보': 2, '주문서': 2, '배송지정보': 2, '구매조건확인': 2,
    '결제금액': 2, '주문상품': 2, '주문정보': 2,
    # 1점: 다른 화면에도 나올 수 있는 말
    '배송지': 1, '받는분': 1, '받는사람': 1, '수령인': 1, '배송요청사항': 1, '약관동의': 1, '주문자': 1,
    '휴대폰번호': 1, '포인트사용': 1, '쿠폰사용': 1, '할부': 1,
    # 실제 캡처 보정 (지그재그): 결제 버튼(검은 바탕 흰 글자)을 OCR이 못 읽을 때가 있어 동의 문구도 센다
    '결제동의': 2, '결제에동의': 2,
}
CHECKOUT_MIN_SCORE = 4     # 점수 합이 이 이상이고
CHECKOUT_MIN_WORDS = 2     # 서로 다른 키워드가 이 개수 이상일 때만 결제 화면 (키워드 하나로는 판정하지 않음)
# ── 쇼핑 화면 분류 모델 (C-1, detector/classifier.py, 학습: ai/screen/) ──
# 모델이 정한 분류의 확률이 SCREEN_MODEL_MIN_PROB보다 낮거나, 모델 파일이 없거나, 오류가 나면 위의 키워드 판정을 쓴다
SCREEN_MODEL_ENABLED = True
SCREEN_MODEL_PATH = 'models/screen_classifier.json'   # impulse_guard 폴더 기준 (절대 경로도 됨)
SCREEN_MODEL_MIN_PROB = 0.5   # 0.6에서 시작, 실측 18장(처음 보는 이미지 11장 포함) 평가 후 0.5로 (2026-11-13, docs/PROGRESS.md)
# 결제 키워드 우선: 키워드 판정이 결제 화면인데 모델이 '상품 화면'을 이 확률 미만으로 말하면 결제 화면으로 본다.
# 결제 화면을 상품 화면으로 놓치는 것을 줄인다 (실제: 11번가 결제 화면을 상품 화면 0.61, 0.71로 판정, 2026-11-13).
# 모델이 '쇼핑 아님'일 때는 쓰지 않는다 (코드 편집기에 결제 키워드 목록이 보일 때 등). 0이면 끈다
SCREEN_KEYWORD_CHECKOUT_MAX_PROB = 0.8
# OCR이 자주 틀리는 글자 (공백을 뺀 글자에서 바꾼 뒤 키워드와 금액 라벨을 비교한다)
# 실제 캡처: 지그재그 '총 결제금액' → '좀 결제금억' (EasyOCR), '총 결제금역' (Windows OCR 1.5배)
CHECKOUT_OCR_FIXES = {'금억': '금액', '금역': '금액', '좀결제': '총결제', '촘결제': '총결제', '결재': '결제'}
# 결제 금액 라벨 (앞에 있을수록 우선). 라벨과 같은 줄 오른쪽이나 바로 아래의 가격을 결제 금액으로 본다
CHECKOUT_TOTAL_LABELS = ['최종결제금액', '총결제금액', '결제예정금액', '최종결제', '총주문금액', '결제금액', '결제하기']
CHECKOUT_TOTAL_BELOW = 3   # 라벨 아래로 상자 높이의 몇 배까지 볼지
# 결제 금액 후보에서 빼는 금액: 금액 상자나 그 줄의 항목 이름(왼쪽에서 가장 가까운 글자)에 이 단어가 있으면
# 혜택/적립/쿠폰/할인 금액이다 (실제 버그: 지그재그 '구매 혜택' 영역의 금액을 결제 금액으로 골라 15,006원으로 기록).
# 공백을 빼고 OCR 보정(CHECKOUT_OCR_FIXES)을 한 글자와 비교한다. '적림', '밀리지'는 실제 캡처의 오인식
CHECKOUT_TOTAL_EXCLUDE = ['혜택', '적립', '적림', '쿠폰', '포인트', '할인', '마일리지', '밀리지', '캐시백', '페이백', '리워드']
# 금액 앞의 꾸밈말. 항목 이름을 찾을 때 건너뛴다 ('구매 혜택 … 최대 630원'의 '최대')
CHECKOUT_TOTAL_FILLER = ['최대', '최소', '약', '총', '+', '-', '~']

# ── 서버 연결 (B-2 신규) ───────────────────────────────────────
LOCAL_CONFIG = 'local_config.json'   # desktop 폴더 기준. 서버 주소와 토큰 (Git에 올리지 않음)
DEFAULT_SERVER = 'http://localhost:8001'
API_PATH = '/ipp/api/client.php'
CLIENT_NAME = 'desktop'              # 서버에 보내는 client 값
SERVER_TIMEOUT_SEC = 2.0             # 응답이 이 시간을 넘으면 실패로 보고 감지만 계속
RECONNECT_SEC = 60                   # 오프라인일 때 다시 연결을 시도하는 간격
SETTING_CACHE_SEC = 60               # 회원 설정(차단 시간, 키워드) 캐시 1분 (B-4에서 5분 → 1분)

# ── 차단 팝업 (B-3 신규) ───────────────────────────────────────
POPUP_MAX_REASONS = 2                # 팝업에 보여 줄 이유 개수
# 모든 알림 창은 주 모니터 작업 영역(작업 표시줄 제외)의 오른쪽 아래 (B-5). 브라우저 가운데의 결제 금액을 가리지 않게
POPUP_EDGE_MARGIN = 16               # 작업 영역 오른쪽/아래 끝에서 창까지 거리 (px, 화면 배율 곱함)
POPUP_TITLEBAR = 40                  # 창 제목 표시줄과 테두리 여유 (px, 화면 배율 곱함)
POPUP_WIDTH = 420                    # 창 너비 (px, 높이는 내용에 맞춤)
POPUP_MASK_MARGIN = 24              # 팝업이 떠 있는 동안 금액을 읽을 때 팝업 영역 둘레로 더 지우는 여유 (px, 화면 배율 곱함)
POPUP_UI_POLL_MS = 100               # 다른 스레드가 보낸 화면 작업을 확인하는 간격
POPUP_INPUT_GUARD_SEC = 0.7          # 창이 뜬 뒤 이 시간 동안 버튼 입력 무시 (하던 클릭/키 입력이 버튼에 들어가지 않게)
POPUP_KEEP_TOP_MS = 2000             # 창이 떠 있는 동안 맨 위로 다시 올리는 간격
COOLDOWN_PAGE = '/ipp/cooldown.php'  # '타임머신 보기'로 여는 웹 화면
# 한글 글꼴 후보 (앞에서부터 설치된 것을 쓴다. 없으면 tkinter 기본 글꼴)
POPUP_FONTS = ['맑은 고딕', 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic']
# 색 (팀 UI 시안의 차단 알림: 흰 카드, 파란 주 버튼, 회색 보조 버튼, 밑줄 텍스트 버튼)
POPUP_COLORS = {
    'back': '#f3f5fa',        # 창 바탕
    'card': '#ffffff',        # 카드
    'border': '#e5e7eb',
    'item': '#f6f7f9',        # 상품 상자
    'text': '#111827',
    'sub': '#6b7280',         # 보조 글자 (원가, 링크)
    'primary': '#3b6cf6',     # 주 버튼
    'primary_active': '#2f5be0',
    'primary_off': '#c7d2fe',
    'secondary': '#eef0f3',   # 회색 보조 버튼
    'secondary_active': '#e2e5ea',
    'secondary_text': '#374151',
    'danger': '#c62828',      # 이유, 할인율, 오류 안내
    'point': '#2448c4',
}

# ── 자동 감지 (B-4) ────────────────────────────────────────────
# 사람마다 바꾸는 값은 local_config.json의 "auto_detect"에서 덮어쓴다 (없으면 아래 기본값)
AUTO_DETECT_DEFAULTS = {
    'enabled': True,             # 자동 감지 켜기/끄기 (F4는 항상 동작)
    'interval_sec': 3,           # 화면을 확인하는 간격. OCR은 화면이 바뀌고 한 간격 동안 멈췄을 때만 한다
    'same_order_minutes': 10,    # 같은 주문을 마지막으로 본 뒤 이 시간 안에는 다시 기록/팝업하지 않는다
    'blocked_repeat_sec': 60,    # 차단 안내 창을 닫은 뒤 같은 쇼핑몰에서 다시 띄우기까지의 시간
    'save_ocr_text': False,      # C-1 학습용 OCR 원문 저장 (상품 화면/쇼핑 아님만, 개인정보 마스킹)
    # 맨 앞 창이 이 프로그램이면 자동 감지를 건너뛴다 (실행 파일 이름, 대소문자 무시)
    # 코드 편집기와 터미널: 감지 결과나 가격 글자가 보여 쇼핑 화면으로 오인할 수 있다
    'exclude_programs': ['Code.exe', 'WindowsTerminal.exe', 'OpenConsole.exe', 'conhost.exe',
                         'cmd.exe', 'powershell.exe', 'pwsh.exe'],
}
AUTO_STOP_WAIT_SEC = 10          # 종료할 때 진행 중인 OCR을 기다리는 최대 시간
# 화면 지각 해시 (frame.py): 16×16 dHash = 256비트
FRAME_HASH_SIZE = 16
FRAME_SAME_DISTANCE = 6          # 직전 분석 화면과 이 이하로 다르면 같은 화면 (OCR 생략)
FRAME_SETTLE_DISTANCE = 12       # 바로 앞 회차와 이 이하로 다르면 화면이 멈춘 것으로 본다 (광고 배너 등 작은 움직임 허용)
AUTO_SETTLE_SEC = 1.0            # 화면이 바뀌는 중이면 interval_sec를 다 기다리지 않고 이 시간 뒤 다시 확인
# 창 제목으로 빨리 확인 (B-5). 제목은 기다리는 시간만 바꾸고 판정에는 쓰지 않는다 (판정은 OCR). 제목 글자는 로그에 남기지 않는다
# 탭 제목이 따로 없으면 주소가 제목이 된다. 지그재그 'zigzag.kr/checkout/order-sheets/...',
# 무신사 'musinsa.com/order/order-form', 쿠팡 'checkout.coupang.com/.../order/...'(직접 확인 못 함)
# 'order'만 쓰면 'border', 'recorder' 같은 제목에도 걸려서 주소 경로 모양('/order', 'order-sheet', 'order-form')으로 찾는다
CHECKOUT_TITLE_WORDS = ['결제', '주문서', '주문하기', '구매하기', 'checkout', 'payment',
                        'order-sheet', 'ordersheet', 'order-form', 'orderform', '/order']   # 대소문자 무시
AUTO_TITLE_POLL_SEC = 0.2        # 기다리는 동안 맨 앞 창 제목을 확인하는 간격. 결제 페이지 제목으로 바뀌면 바로 확인
AUTO_FAST_SETTLE_SEC = 0.5       # 제목이 결제 페이지일 때 멈춤 확인 간격 (AUTO_SETTLE_SEC 대신)
AUTO_CHECKOUT_INTERVAL_SEC = 1.0 # 제목이 결제 페이지인 동안의 확인 간격 (interval_sec 대신). 결제 페이지 안에서 스크롤하면 빨리 본다
# 결제 금액을 못 읽었을 때 화면 해시가 이 이하로 다르면 같은 주문 (B-5: 20 → 6, 같은 화면 수준).
# 실제 로그: 지그재그 결제 페이지 맨 위(금액이 안 보임)는 장바구니가 달라도 비슷해서 20이면 다른 주문을 같은 주문으로 봤다
ORDER_SAME_DISTANCE = 6
# 탭 제목에 이 모양(숫자가 3개 이상 든 8자 이상 영문/숫자 덩어리)이 있으면 주문서 번호처럼 주문마다 다른 제목으로 본다
ORDER_TITLE_ID_RE = r'(?=[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{8,}'
CHECKOUT_NAME_MINUTES = 30       # 결제 화면의 상품명: 같은 쇼핑몰에서 이 시간 안에 본 마지막 상품 이름을 쓴다
CONSOLE_TITLE = 'impulse-guard 감지 프로그램'   # 콘솔 창 제목. 맨 앞 창이 이 제목이면 자동 감지를 건너뛴다
# 이 프로그램의 알림 창 제목 (popup.py). 맨 앞 창이면 캡처하지 않는다 (B-5: 팝업을 클릭하면 팝업만 캡처하던 문제)
OWN_WINDOW_TITLES = ['충동구매 방지', '충동구매 알림', '쇼핑 차단 중']
# 결제 화면인데 금액을 못 읽었고 같은 쇼핑몰의 최근 주문(금액 있음)이 있으면, 같은 주문인지 금액을 읽을 때까지
# 이 시간만큼 팝업을 미룬다 (B-5. 지그재그는 '구매하기'마다 주문서 주소(탭 제목)가 새로 생겨 제목으로는 구분할 수 없다)
CHECKOUT_AMOUNT_WAIT_SEC = 3
# 로그 (desktop 폴더 기준, Git에 올리지 않음). 캡처 이미지는 어디에도 저장하지 않는다
LOG_DIR = 'logs'
LOG_FILE = 'detect.log'          # 감지 결과 한 줄씩 (1MB × 5개 순환)
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 5
OCR_SAMPLE_FILE = 'ocr_samples.jsonl'   # save_ocr_text가 true일 때만. 상품 화면/쇼핑 아님, 개인정보 마스킹
