# C-1 쇼핑 화면 분류 모델

OCR 글자로 화면을 **쇼핑 아님(none) / 상품 화면(product) / 결제 화면(checkout)** 으로 나눈다.
B-4의 키워드 점수 방식(`desktop/impulse_guard/detector/stage.py`)보다 처음 보는 쇼핑몰에서도 잘 맞히는 것이 목표다.

```
가상 데이터 만들기 (generate) → 학습 + JSON 내보내기 (train) → 평가 (evaluate)
                                   ↓
              desktop/impulse_guard/models/screen_classifier.json
                                   ↓
   데스크톱 detector/classifier.py (numpy만 사용) → stage.decide (저신뢰/실패 시 키워드 판정)
```

## 실행 (ai 폴더에서)

```powershell
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install scikit-learn==1.9.1 numpy==2.5.4
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m screen.generate      # → data/screen/synthetic.jsonl (Git 제외)
.\.venv\Scripts\python.exe -m screen.train         # → desktop/impulse_guard/models/screen_classifier.json
.\.venv\Scripts\python.exe -m screen.evaluate      # → 화면 출력 + data/screen/report.md (약 1분)
.\.venv\Scripts\python.exe -m screen.evaluate --quick   # 실측과 속도만
```

실측 평가 이미지를 추가했으면 먼저 데스크톱 폴더에서 OCR 캐시를 만든다:
`.\.venv\Scripts\python.exe tests\make_screen_cache.py` (정답은 파일 이름으로 정한다. 아래 '실측 평가 데이터')

## 분류 기준

| 분류 | 화면 |
|---|---|
| 상품 화면 | 상품 상세, 상품 목록/검색 결과(쇼핑몰 안), **장바구니**, 배달앱 가게/메뉴 화면 |
| 결제 화면 | 주문서/결제 화면, 배달앱 주문(결제) 화면 |
| 쇼핑 아님 | 쇼핑몰이 아닌 모든 화면 + 쇼핑몰 안의 **주문 완료, 주문 내역, 배송 조회**, 고객센터 |

주문 완료와 주문 내역을 쇼핑 아님으로 둔 이유: 이미 산 뒤라 개입할 의미가 없고, 차단 기간에 배송 조회를 할 때 차단 창이 뜨면 안 된다.

## 1. 가상 데이터 (`vocab.py`, `pages.py`, `noise.py`, `generate.py`)

- **가상 쇼핑몰 40곳** (분야 8가지 × 5곳): 몰마다 이름, 주소, 메뉴, 버튼 문구, 가격 표기(`39,000원`, `₩39,000`, `KRW 39,000` 등), 결제 버튼 문구, 간편결제 목록이 다르다.
  실제 쇼핑몰 이름(무신사, 지그재그, 쿠팡 등)은 넣지 않는다.
- **화면 한 장 = 영역 조각을 이어 붙인 것**: 브라우저 주소창/탭 → 머리(몰 이름, 메뉴, 검색) → 본문 → 하단 사업자 정보
  - 상품 상세: 상품명, 정가/할인율/할인가, 리뷰, 혜택, 배송, 옵션, 버튼, 탭, 상세 설명, 추천 상품
  - 결제: 주문자, 배송지(가짜 이름/주소/전화), 주문 상품, 쿠폰/포인트, 결제 수단과 카드 혜택, 결제 금액, 약관 동의, 결제 버튼
  - 쇼핑몰 안 쇼핑 아님: 주문 완료, 주문 내역, 배송 조회, 고객센터 (같은 몰 머리/하단을 쓰므로 본문으로 구분해야 한다)
- **헷갈리는 쇼핑 아님 화면 18종**: 쇼핑/가격 뉴스, 내돈내산 블로그, 핫딜 커뮤니티, 은행 이체(받는 분, 금액), 카드 명세서(결제예정금액),
  가계부, 메일(주문 확인 메일 포함), 주식(매수, 수량, 주문 가능 금액), 부동산, 검색 결과, 유튜브(하울/언박싱, 광고), VS Code(결제 관련 코드),
  문서, 메신저, 관리자 화면(주문내역, 결제금액), 웹툰, 지도, 스프레드시트
- **OCR 노이즈 4단계** (none 10%, normal 35%, strong 30%, heavy 25%):
  실측에서 본 오인식(금액→금억/금역, 총→좀, 원→윈), 한글 음절 받침/모음 변형, 띄어쓰기, 글자/상자 빠짐, 쓰레기 토큰,
  아이콘을 글자로 읽은 상자(`수`, `口`, `〉`), 영역 순서 섞임, 화면 일부만 보임(작은 창이면 한 영역만)
- 5,760건: 결제 1,400 / 상품 1,800 / 쇼핑 아님 2,560 (쇼핑몰 안 560 + 일반 화면 2,000)
- 각 줄에 `group`(쇼핑몰/사이트)이 있어, 평가 때 같은 몰이 학습과 시험에 섞이지 않게 나눈다

## 2. 모델 (`train.py`)

- 전처리 (`desktop/.../classifier.preprocess`, 학습과 실행이 같은 함수): 공백 삭제 → 소문자 → OCR 오타 고침 → **숫자를 모두 0으로** (가격을 외우지 않게, 개인정보에도 유리)
- 문자 2~4-gram TF-IDF (sublinear tf, 특성 2만 개, min_df 3) + 로지스틱 회귀 (C=4, class_weight=balanced)
- 내보내기: 어휘, idf, 가중치, 절편을 JSON(약 920KB)으로. 데스크톱은 numpy로만 계산한다 (scikit-learn, pickle 없음).
  내보낸 뒤 sklearn과 확률 차이를 확인한다 (최대 약 2e-7)

## 3. 데스크톱 동작 (`stage.decide`)

1. 모델 확률이 가장 높은 분류의 확률 ≥ `SCREEN_MODEL_MIN_PROB`(0.5, 처음 0.6에서 실측 평가 후 조정) → 모델 판정
2. 그보다 낮으면, 모델 파일이 없거나 깨졌으면, 판정 중 오류가 나면 → 키워드 판정 (B-4 방식 그대로)
3. 로그 근거: `점수 0/4 [] | 모델 상품 화면 0.83` 또는 `... | 키워드 판정 (저신뢰: 모델 쇼핑 아님 0.52)`

설정 (`desktop/impulse_guard/config.py`): `SCREEN_MODEL_ENABLED`, `SCREEN_MODEL_PATH`, `SCREEN_MODEL_MIN_PROB`

## 4. 평가 (`evaluate.py`, 결과: `data/screen/report.md`)

1. 가상 데이터, 쇼핑몰/사이트 단위 5겹 교차검증: 키워드, char_lr(메인), word_lr, char_nb, char_lr+키워드(기준 0.4~0.8)
2. 새 시드 가상 데이터(몰 16곳, 노이즈 강도별)
3. 실측: EasyOCR(`desktop/tests/ocr_cache` + `screen_cache/easy`), Windows OCR(`screen_cache/win`)
4. 판정 시간

지표: macro F1, 결제 재현율(놓치면 개입 못 함), 쇼핑 아님 오탐률(일반 화면에 알림이 뜨는 비율)

### 실측 평가 데이터

`desktop/tests/images/`에 캡처를 넣고 `tests/make_screen_cache.py`를 실행한다. 정답은 파일 이름으로 정한다:
이름에 `checkout` → 결제 화면, `product` 또는 `cart` → 상품 화면, 그 밖은 쇼핑 아님 (예: `youtube_home.png`, `order_done_x.png`).
`tests/ocr_cache/`에는 넣지 않는다 (그 폴더는 가격/페이지 테스트 정답이 있는 7장 전용이라, 새 이미지를 넣으면 기존 테스트가 실패한다).

## 한계 (평가 결과를 읽을 때)

- **가상 데이터 점수는 낙관적이다.** 학습과 시험이 같은 생성기에서 나와, 처음 보는 몰이어도 어휘 풀은 같다.
- **실측 7장은 깨끗한 시험이 아니다.** 첫 모델이 Windows OCR에서 3장을 틀린 것을 보고 노이즈(아이콘 글자, heavy 강도, 작은 창)와
  결제 화면 혜택 문구를 추가했다. 문구를 옮기지는 않았지만 이 7장을 보며 생성기를 고쳤다. 새로 넣는 이미지가 처음 보는 시험 데이터가 된다.
- 실측에 쇼핑 아님이 1장(뉴스)뿐이라 오탐률은 아직 실측으로 말할 수 없다.
- 혜택 금액이 상품 화면 할인가로 잡히는 문제는 C-1에서 다루지 않는다 (가격 분석, 다음 단계).
