# impulse-guard 서버 API 명세

> 기준: 2026-11-11 (B-2단계), `feature/desktop-server` 브랜치 코드
> 응답 예시는 8001 서버에 실제로 호출한 결과입니다 (B-2, 임시 회원). 회원 아이디, 닉네임, 번호, 시각만 예시용 값으로 바꿨습니다.
> 팀원 프로젝트를 통합할 때 이 문서를 기준으로 연결합니다. API를 바꾸면 이 문서도 같이 고칩니다.

## 1. 개요

| 구분 | 주소 | 인증 | 요청 형식 | 쓰는 곳 |
|---|---|---|---|---|
| 외부 프로그램 API | `/ipp/api/client.php` | API 토큰 (`Authorization: Bearer`) | JSON 본문 | 데스크톱 감지 프로그램, 팀원 프로젝트 |
| (예전 주소) | `/ipp/api/ext.php` | 같음 | 같음 | 크롬 확장 프로그램 (보류). `client.php`와 같은 처리 |
| 웹 화면용 API | `/ipp/api/cooldown.php`, `reward.php`, `setting.php`, `mock_bank.php` | 그누보드 로그인 세션 (쿠키) | 폼 (`application/x-www-form-urlencoded`) | 그누보드 웹 화면 (`ipp/*.php`) |

- 서버 주소(로컬): `http://localhost:8001`
- 모든 응답은 JSON(UTF-8)이며 `ok`(true/false)가 들어 있습니다. 실패하면 `msg`에 한국어 안내가 들어 있습니다.
- 금액과 포인트는 원/포인트 단위 정수, 날짜와 시각은 서버 시각 `YYYY-MM-DD HH:MM:SS` 문자열입니다.
- **외부 프로그램(데스크톱, 팀원 프로젝트)은 `client.php`를 씁니다.** 웹 화면용 API는 로그인 쿠키가 있어야 해서 웹 화면 안에서만 씁니다.

### 기능 스위치 (`extend/ipp.extend.php`)

| 스위치 | 끄면 |
|---|---|
| `IPP_USE_CLIENT_API` | `client.php`, `ext.php` 전체가 403. 웹 설정 화면의 토큰 발급도 숨김 |
| `IPP_USE_EXTENSION` | `client: "extension"` 요청만 403 (지금은 **꺼져 있음**, 확장 프로그램 보류) |
| `IPP_USE_SETTING` | `setting`, `log`, `check`의 `log: true`가 403 |
| `IPP_USE_COOLDOWN` | `cooldown`, `giveup`이 403 |

## 2. 외부 프로그램 API: `POST /ipp/api/client.php`

### 2-1. 인증 (API 토큰)

1. 웹에서 로그인 → `/ipp/setting.php`의 **"외부 프로그램 연결 (데스크톱 감지 프로그램)"** 에서 **발급**
2. 서버 주소와 토큰(64자리 16진수)이 **한 번만** 보입니다. 서버에는 SHA-256 해시만 저장되므로 다시 볼 수 없고, 잃어버리면 재발급합니다.
3. 요청마다 헤더에 넣습니다.

```
POST /ipp/api/client.php HTTP/1.1
Host: localhost:8001
Content-Type: application/json
Authorization: Bearer 3f9a...(64자리)
```

- `Authorization` 헤더를 쓸 수 없는 환경이면 `X-IPP-Token: 3f9a...` 헤더도 받습니다.
- 로그인 쿠키는 무시합니다. 토큰으로 찾은 회원으로만 처리합니다.
- 재발급하면 이전 토큰은 바로 무효가 됩니다. 연결 해제, 탈퇴/차단 회원도 무효입니다.
- CORS 헤더를 보내지 않습니다. 브라우저 페이지의 JavaScript에서 직접 부르는 용도가 아닙니다.

### 2-2. 요청과 응답 공통

요청 본문은 JSON 객체입니다. `client`로 어느 프로그램인지, `action`으로 기능을 고릅니다.

```json
{ "client": "desktop", "action": "check", "site": "coupang", "item_name": "무선 이어폰", "price": 89000 }
```

| 칸 | 필수 | 설명 |
|---|---|---|
| `client` | O (`client.php`) | `desktop`(데스크톱 감지 프로그램), `extension`(크롬 확장 프로그램). 기록과 쿨다운의 출처로 저장됩니다. 목록은 `IPP_CLIENTS`. 예전 주소 `ext.php`는 없으면 `extension`으로 봅니다 |
| `action` | O | 아래 2-3 |

- 문자열 칸에 배열이나 객체를 보내면 빈 문자열로, 숫자 칸에 숫자가 아닌 값을 보내면 0으로 처리합니다.
- 참/거짓 칸(`is_checkout`, `log`)은 `true`, `1`, `"1"`, `"true"`만 참입니다.

| HTTP 상태 | 뜻 | 실제 응답 예 |
|---|---|---|
| 200 | 성공 | `{"ok": true, ...}` |
| 400 | 입력 오류, JSON 아님, `client` 없음/잘못됨, 알 수 없는 action | `{"ok": false, "msg": "client 값이 올바르지 않습니다. (extension, desktop)"}` |
| 401 | 토큰 없음/틀림 | `{"ok": false, "msg": "토큰이 올바르지 않습니다."}` |
| 403 | 기능 스위치가 꺼짐 | `{"ok": false, "msg": "확장 프로그램 연결 기능이 꺼져 있습니다."}` |
| 405 | POST가 아님 | `{"ok": false, "msg": "POST로 요청하세요."}` |
| 409 | 팝업 결정: 이미 결정했거나 내 감지 기록이 아님 (B-3) | `{"ok": false, "msg": "이미 처리했거나 찾을 수 없는 감지 기록입니다."}` |

검사 순서: `IPP_USE_CLIENT_API` → POST 여부 → JSON 본문 → `client` (extension이면 `IPP_USE_EXTENSION`) → 토큰 → action

### 2-3. action 목록

| action | 하는 일 | 저장 | 필요한 기능 스위치 |
|---|---|---|---|
| `me` | 연결 확인, 회원과 포인트 | 없음 | - |
| `setting` | 차단 설정 조회 | 없음 | `IPP_USE_SETTING` |
| `check` | 상품 하나의 차단/충동구매 판단과 이유. `log: true`면 기록도 저장 (차단 중이면 `blocked`, 아니면 `detect`) | `log: true`일 때 `g5_ipp_block_log` | (`log: true`면 `IPP_USE_SETTING`) |
| `log` | 방문/차단/결제 진입/감지 기록 | `g5_ipp_block_log` | `IPP_USE_SETTING` |
| `cooldown` | 24시간 담아두기 시작. `bl_id`를 주면 그 감지 기록에 `hold` | `g5_ipp_cooldown` (+ `g5_ipp_block_log`) | `IPP_USE_COOLDOWN` |
| `giveup` | 안 살래요 (즉시 포기, 포인트 지급). `bl_id`를 주면 그 감지 기록에 `giveup` | `g5_ipp_cooldown`, 포인트 (+ `g5_ipp_block_log`) | `IPP_USE_COOLDOWN` |
| `decide` | 팝업 결정을 기록만 (그래도 구매, 창 닫기, 가격 모를 때 안 살래요). 쿨다운과 포인트 없음 (B-3) | `g5_ipp_block_log` | `IPP_USE_SETTING` |
| `amount` | 결제 화면 감지 기록(금액 0)에 나중에 읽은 금액을 채움 (B-5) | `g5_ipp_block_log` | `IPP_USE_SETTING` |

#### `me`: 연결 확인

요청

```json
{ "client": "desktop", "action": "me" }
```

응답

```json
{
  "ok": true,
  "mb_id": "test01",
  "nick": "테스트",
  "point": 0,
  "client": "desktop",
  "server_time": "2026-11-11 02:57:18",
  "features": { "setting": true, "cooldown": true, "gifticon": true }
}
```

- `point`: 현재 보유 포인트 합계
- `client`: 서버가 받아들인 client 값
- `server_time`: 서버 시각. 프로그램의 시계가 틀렸는지 확인할 때 씁니다.
- `features`: 서버에서 켜진 기능. 꺼진 기능의 버튼은 숨기는 데 씁니다.

#### `setting`: 차단 설정 조회

요청

```json
{ "client": "desktop", "action": "setting" }
```

응답 (차단 중, 쇼핑몰 전체 차단 켬, 쿠팡을 차단 목록에서 끈 경우)

```json
{
  "ok": true,
  "is_blocking": true,
  "block_until": "2026-11-11 09:53:16",
  "block_remain": 3600,
  "block_all": true,
  "sites": [
    { "code": "naver",   "name": "네이버쇼핑", "domain": "shopping.naver.com", "on": true },
    { "code": "coupang", "name": "쿠팡",       "domain": "coupang.com",        "on": false },
    { "code": "gmarket", "name": "G마켓",      "domain": "gmarket.co.kr",      "on": true },
    { "code": "11st",    "name": "11번가",     "domain": "11st.co.kr",         "on": true },
    { "code": "zigzag",  "name": "지그재그",   "domain": "zigzag.kr",          "on": true },
    { "code": "musinsa", "name": "무신사",     "domain": "musinsa.com",        "on": true }
  ],
  "keywords": ["세일", "할인", "특가"],
  "risk_alert": true
}
```

- 차단 중이 아니면 `is_blocking: false`, `block_until: null`, `block_remain: 0`
- `block_remain`: 차단이 끝날 때까지 남은 초. PC 시계가 틀려도 맞도록, 종료 시각은 이 값으로 계산합니다.
- `block_all`: 쇼핑몰 전체 차단 (회원 설정 화면 맨 위 토글, 기본 켬). `true`면 차단 시간에 `sites[].on`과 상관없이 모든 쇼핑 화면을 차단합니다. 위 예시에서 쿠팡은 꺼져 있지만 전체 차단이 켜져 있어 쿠팡도 차단됩니다.
- `sites[].on`: 이 사이트가 차단 목록에 켜져 있는지. `block_all`이 `false`일 때만 차단에 쓰입니다. 사이트 목록은 `extend/ipp.extend.php`의 `IPP_BLOCK_SITES`
- `keywords`: 회원 차단 키워드 (최대 20개, 각 20자)
- 데스크톱 프로그램은 이 응답을 1분간 캐시합니다 (B-4에서 5분 → 1분). 자동 감지는 쇼핑 아님 → 쇼핑 화면으로 바뀔 때 캐시를 무시하고 다시 받습니다.

#### `check`: 상품 판단 (+ 감지 기록)

요청 (데스크톱이 쓰는 형식)

```json
{
  "client": "desktop",
  "action": "check",
  "site": "coupang",
  "item_name": "맨즈셀렉터 패딩",
  "price": 49600,
  "orig_price": 119000,
  "discount_rate": 58,
  "is_checkout": true,
  "log": true,
  "page": "product",
  "url": "",
  "features": { "discount_rate": 40, "pressure": 1, "product_views_24h": 8, "same_item_views_24h": 3, "browse_sec": 45 }
}
```

| 칸 | 필수 | 설명 |
|---|---|---|
| `site` | O | `IPP_BLOCK_SITES`의 코드 (`naver`, `coupang`, `gmarket`, `11st`, `zigzag`, `musinsa`). 그 밖이면 400. **`client: desktop`이면 `""`(사이트 모름)도 됩니다** |
| `item_name` | | 상품명. 회원 키워드 검사에 씁니다 |
| `price` | | 판매가(할인가, 원). 음수는 0. 0이면 고액 판단을 할 수 없습니다 |
| `orig_price` | | 원가(원). 음수는 0 (B-2 추가) |
| `discount_rate` | | 할인율 %. 0~99 밖이면 0 (B-2 추가) |
| `is_checkout` | | 결제 화면인지 (B-2 추가). `true`면 이유 `checkout`이 맨 앞에 붙어 `is_impulse`가 1이 됩니다 (B-4). 이때 `price`는 결제 금액, `page`는 `""` |
| `log` | | `true`면 기록 1건을 저장하고 `event`, `bl_id`를 돌려줍니다. 차단 중(`is_blocking: true`)이면 이벤트 `blocked`, 아니면 `detect`입니다 (B-3에서 바뀜). 기본 false (B-2 추가) |
| `page`, `url` | | `log: true`일 때 기록에 저장. `page`는 `product`, `cart`, `""` |
| `features` | | 결제 화면 위험도 입력 (C-2 추가). **숫자만** 보냅니다 (OCR 원문, 상품명, 주소 없음). 아래 표 |

`features` (모두 선택. 숫자가 아니면 모름으로 봅니다)

| 칸 | 값 | 없거나 `null`이면 |
|---|---|---|
| `discount_rate` | 같은 쇼핑몰에서 최근 본 상품의 할인율 0~99. **할인 없음은 0** | 모름. `features`가 아예 없으면(예전 데스크톱) 바깥 `discount_rate`가 1~99일 때만 그 값 (바깥 칸의 0은 '할인 없음'과 '모름'을 구분할 수 없어 모름) |
| `pressure` | 최근 본 상품 화면에 서두르게 하는 문구(타임딜, 품절임박, 오늘만 등)가 있으면 1 | 0 |
| `product_views_24h` | 최근 24시간 이 쇼핑몰 상품 화면 횟수 (0~1000) | 0 |
| `same_item_views_24h` | 최근 24시간 같은 상품 상품 화면 횟수 (0~1000) | 0 |
| `browse_sec` | 이 쇼핑몰 상품 화면을 처음 본 때부터 결제 화면까지 초 (0~86400) | 모름 (상품 화면 없이 결제 화면) |

`orig_price`는 저장만 합니다. `is_checkout`은 B-4부터 이유(`checkout`)에, C-2부터 위험도 계산에 씁니다.

응답

요청 `site: "coupang"`, `item_name: "[특가] 맨즈셀렉터 패딩"`, `price: 59600`, `orig_price: 119000`, `discount_rate: 50`, `log: true` (오전 8시 호출)

```json
{
  "ok": true,
  "is_blocking": false,
  "is_impulse": 1,
  "reasons": [
    { "code": "keyword", "text": "'특가' 키워드가 들어 있어요." },
    { "code": "big", "text": "50,000원 이상의 큰 금액이에요." }
  ],
  "keyword": "특가",
  "point": 500,
  "point2": 1000,
  "received": { "orig_price": 119000, "discount_rate": 50, "is_checkout": false },
  "event": "detect",
  "bl_id": 113
}
```

- `is_blocking`: 지금 차단 시간인지. 사이트는 이렇게 봅니다.

  | 쇼핑몰 전체 차단 (`block_all`) | `site`가 목록에 켜진 사이트 | 목록에서 끈 사이트 | `""` (사이트 모름) |
  |---|---|---|---|
  | 켬 (기본) | 차단 | **차단** | 차단 |
  | 끔 | 차단 | 차단 아님 | 차단 (차단 시간만 봄) |
- `is_impulse`: 충동구매 감지 1, 아니면 0 (숫자). 규칙: 회원 키워드가 상품명에 있거나, 심야(23시~4시 전) 또는 고액(50,000원 이상). `reasons`가 비어 있지 않으면 1입니다.
- `reasons`: 충동구매로 본 이유 목록 (B-3 추가). 중요한 것부터 `checkout`(결제 화면, B-4) → `keyword`(회원 키워드) → `big`(고액) → `night`(심야) 순서입니다. 결제 화면 문구: `"결제 직전이에요. 정말 지금 필요한 물건인지 한 번만 더 생각해 봐요."` 없으면 `[]`. `text`는 화면에 그대로 보여 줄 문구입니다 (심야: `"밤 11시~새벽 4시 사이의 심야 쇼핑이에요."`). 기준값은 `extend/ipp.extend.php`의 `IPP_DETECT_*`에서 가져옵니다.
  - 판단(어떤 `code`인지)과 문구(`ipp_reason_text()`)를 나눠 두었습니다. C-2 위험도는 이 목록을 바꾸지 않고 `risk_*` 칸으로 따로 돌려줍니다 (아래). 데스크톱 팝업 제목은 첫 번째 `code`로 고릅니다 (`checkout`이면 "결제하기 전에 잠깐만요!").
- `keyword`: 상품명에서 찾은 첫 키워드. 없으면 `""` (예: 상품명 `[특가] 무선 이어폰` → `"특가"`)
- `point`: 지금 포기하면 받을 포인트, `point2`: 24시간 참으면 받을 포인트(2배). 하루 상한(1,000P)은 반영하지 않은 값입니다.
- `received`: 서버가 정리해서 받아들인 원가, 할인율, 결제 화면 여부
- `event`, `bl_id`: `log: true`일 때만 있습니다. `event`는 저장한 이벤트(`detect` 또는 `blocked`)입니다. 차단 중이면 아래처럼 `blocked`로 저장되어 통계의 차단 횟수에 들어갑니다.

  ```json
  { "ok": true, "is_blocking": true, "is_impulse": 1, "reasons": [{ "code": "big", "text": "50,000원 이상의 큰 금액이에요." }],
    "keyword": "", "point": 500, "point2": 1000, "received": { "orig_price": 0, "discount_rate": 0, "is_checkout": false },
    "event": "blocked", "bl_id": 116 }
  ```
- 결제 화면 (B-4): 데스크톱이 결제 화면을 감지하면 `is_checkout: true`, 결제 금액을 `price`로, `page: ""`로 보냅니다. 아래는 오전 10시에 키워드 없는 상품으로 호출한 실제 응답입니다. `checkout` 이유 하나로 `is_impulse`가 1이 되고, 기록은 `bl_is_checkout = 1`로 저장됩니다.

  ```json
  { "ok": true, "is_blocking": false, "is_impulse": 1,
    "reasons": [{ "code": "checkout", "text": "결제 직전이에요. 정말 지금 필요한 물건인지 한 번만 더 생각해 봐요." }],
    "keyword": "", "point": 496, "point2": 992, "received": { "orig_price": 0, "discount_rate": 0, "is_checkout": true },
    "event": "detect", "bl_id": 168 }
  ```
- **위험도 (C-2)**: `is_checkout: true`일 때만 계산합니다. 상품 화면이거나, 모델이 꺼졌거나(`IPP_USE_RISK_MODEL`), 모델 파일(`ipp/model/risk_model.json`)이 없거나 계산이 실패하면 `risk: null`, `risk_level: ""`, `risk_message: ""`, `risk_reasons: []`, `risk_show_reasons: false`, `risk_model: ""`이고 위의 규칙 이유(`reasons`)는 그대로입니다.

  | 칸 | 설명 |
  |---|---|
  | `risk` | 충동구매 위험도 0~1 (소수 4자리). 모델이 추정한 '팝업을 보고도 그대로 살' 확률 |
  | `risk_level` | `low`(< 0.3) / `mid`(0.3 이상) / `high`(0.55 이상). 기준 `IPP_RISK_LEVEL_MID`, `IPP_RISK_LEVEL_HIGH` |
  | `risk_message` | 단계별 팝업 머리 문구 (`ipp_risk_message()`) |
  | `risk_reasons` | 위험을 올린 이유 `[{code, text}]` 큰 순서, 최대 3개 (`IPP_RISK_REASON_MAX`). **낮음이어도 채웁니다** (분석용) |
  | `risk_show_reasons` | 팝업에 이유 문장을 보일지. **보통 이상만 `true`**. 낮음은 이유 없이 `risk_message`만 보입니다 |
  | `risk_model` | 모델 버전 (예: `20261113-synthetic`) |
  | `risk_source` | C-3: 확률과 이유를 계산한 곳. `server`(예측 서버) / `php`(서버 PHP 직접 계산). 위험도가 없으면 `""` |

  - 이유 `code`: `night`(심야), `evening`(늦은 저녁), `weekend`, `payday`(월급일 직후), `amount`(큰 금액), `amount_ratio`(평소 대비 금액), `discount`, `pressure`(서두르게 하는 문구), `views`(최근 상품 화면 수), `same_item`(같은 상품 반복), `browse`(짧게 보고 결제), `frequency`(최근 7일 결제 화면 수), `history`(지난 '그래도 구매' 비율), `cooldown`(담아두기 실패). 문구는 `ipp_risk_reason_text()`
  - 서버가 DB에서 만드는 값 (이번 기록 저장 전, 그 시점 이전 기록만): 이전 90일 결제 화면 금액 평균 대비 비율(3건 미만이면 1.0), 최근 7일 결제 화면 수, 180일 동안의 팝업 결정 중 '그래도 구매' 비율과 담아두기 실패 비율(기록이 적으면 평균 쪽으로 당김)
  - **예측 서버 (C-3)**: `IPP_RISK_SERVER`가 `on`이면 확률과 이유를 예측 서버(`ai/serve`, `127.0.0.1:8002`의 `POST /risk/predict`)에서 받고, 단계·문구·이유 문장·기록은 지금처럼 PHP가 합니다. 예측 서버가 꺼져 있거나 0.3초 안에 답하지 않거나 응답이 이상하거나 모델 버전이 다르면 PHP가 직접 계산하고(`risk_source: "php"`), 그 뒤 60초 동안은 예측 서버를 부르지 않습니다. 어느 쪽이든 칸과 값은 같습니다 (`ipp/tests/risk_server_test.php`). 예측 서버에는 원시 값 13개(숫자와 null)만 보냅니다
  - **포인트와 상관없습니다.** `point`, `point2`는 위험도와 관계없이 금액으로만 정합니다 (위험도를 일부러 올려 포인트를 받는 악용 방지)
  - `log: true`면 감지 기록에 `bl_risk`, `bl_risk_level`, `bl_risk_model`, `bl_risk_reasons`(이유 코드 모두), `bl_risk_raw`(예측에 쓴 원시 값, 숫자와 null만)를 저장합니다 (`ipp/sql/010_block_log_risk.sql`). 나중에 팝업 결정과 짝지어 실제 데이터로 다시 평가·학습합니다 (`ai/risk/README.md`)
  - 실제 응답 (HTTP 테스트, 과거 '그래도 구매'가 많은 임시 회원, 평소 3만 원대인데 15만 원 결제 화면. 위험도 칸만)

    ```json
    { "risk": 0.6512, "risk_level": "high",
      "risk_message": "충동구매일 가능성이 높아 보여요. 24시간만 담아 두고 다시 생각해 볼까요?",
      "risk_reasons": [{ "code": "amount_ratio", "text": "평소 결제 금액의 5배예요." },
                       { "code": "history", "text": "지난 팝업에서 '그래도 구매'를 고른 적이 많아요." },
                       { "code": "frequency", "text": "최근 7일 동안 결제 화면에 3번 들어갔어요." }],
      "risk_show_reasons": true, "risk_model": "20261113-synthetic" }
    ```

    낮음 예 (평소보다 훨씬 작은 금액, 1시간 살펴봄): `"risk": 0.0565, "risk_level": "low", "risk_message": "결제하기 전에 한 번만 확인해요. 꼭 필요한 물건인가요?", "risk_show_reasons": false`이고 `risk_reasons`에는 `discount`, `pressure`가 들어 있습니다 (화면에는 보이지 않음).
- 데스크톱 팝업 (B-3): `is_blocking`이면 차단 안내 창, 아니고 `is_impulse`가 1이면 충동구매 팝업을 띄웁니다. 가격을 못 읽었으면(`price: 0`) 충동구매가 아니어도 팝업을 띄웁니다. 결제 화면은 서버가 `checkout` 이유를 붙이므로 항상 팝업입니다 (B-4). 팝업에서 고른 결정은 `bl_id`로 `cooldown`, `giveup`, `decide`에 보냅니다.

#### `log`: 기록

요청

```json
{
  "client": "desktop",
  "action": "log",
  "site": "",
  "event": "detect",
  "price": 220590,
  "orig_price": 258000,
  "discount_rate": 15
}
```

| 칸 | 필수 | 값 |
|---|---|---|
| `site` | O | `IPP_BLOCK_SITES`의 코드. `client: desktop`이면 `""`도 됩니다 |
| `event` | O | `visit`(상품을 보고 떠남), `blocked`(차단 팝업/안내를 봄), `checkout`(그래도 구매 진행), `detect`(데스크톱이 쇼핑 화면을 감지함, B-2 추가) |
| `page` | | `product`(상품 상세), `cart`(장바구니), `""`(그 밖의 페이지, 기본값) |
| `url` | | 최대 500자 |
| `item_name` | | 최대 255자 |
| `price` | | 원, 음수는 0 |
| `orig_price`, `discount_rate`, `is_checkout` | | `check`와 같음 (B-2 추가) |
| `stay_sec` | | 머문 시간(초). `blocked`의 평균 차단 시간 통계에 씁니다 |

응답

```json
{ "ok": true, "bl_id": 84 }
```

- `site`, `event`, `page`가 목록에 없으면 400 `"사이트, 이벤트, 페이지 값이 올바르지 않습니다."`
- 통계 화면은 `blocked`만 셉니다. `detect`는 통계 숫자에 들어가지 않습니다.
- 데스크톱은 `check`의 `log: true`를 쓰므로 `log`를 따로 부르지 않습니다.

#### `cooldown`: 24시간 담아두기

요청

```json
{ "client": "desktop", "action": "cooldown", "item_name": "[특가] 맨즈셀렉터 패딩", "price": 59600, "bl_id": 113 }
```

| 칸 | 필수 | 설명 |
|---|---|---|
| `item_name` | O | 최대 255자 |
| `price` | O | 원, 1 이상 |
| `bl_id` | | 데스크톱 팝업의 '조금 더 생각하기' (B-3 추가). `check`가 준 감지 기록 번호. 그 기록에 `bl_decision = hold`, `bl_cd_id = cd_id`를 적습니다 |

응답

```json
{ "ok": true, "cd_id": 31, "expire": "2026-11-12 08:24:41", "point2": 1000 }
```

- `item_name`이 비었거나 `price`가 0 이하면 400 `"상품명과 가격을 보내 주세요."` (이때 감지 기록은 바뀌지 않습니다)
- `bl_id`가 이미 결정된 기록이거나, 내 `detect` 기록이 아니면 409이고 쿨다운을 만들지 않습니다. 같은 기록으로 두 번 보내도 쿨다운은 하나입니다.
- `point2`: 24시간을 참으면 받을 포인트 (B-3 추가)
- `expire`: 쿨다운 종료 시각 (`IPP_COOLDOWN_HOURS` 뒤). 끝나면 웹의 쿨다운 화면에서 정산되어 성공 시 2배 포인트를 줍니다.
- 출처가 `cd_client`에 저장됩니다 (`desktop`, `extension`. 웹 화면에서 만든 것은 `web`)

#### `giveup`: 안 살래요

요청

```json
{ "client": "desktop", "action": "giveup", "item_name": "무선 이어폰", "price": 89000, "bl_id": 114 }
```

응답

```json
{ "ok": true, "cd_id": 32, "point": 500 }
```

- 쿨다운을 만들고 바로 포기(`gaveup`) 처리해 포인트를 지급합니다 (`ipp_give_point()`를 거침).
- `point`: 실제 지급된 포인트. 하루 상한을 넘으면 줄어들거나 0입니다.
- `bl_id`(선택, B-3 추가): 그 감지 기록에 `bl_decision = giveup`, `bl_cd_id = cd_id`를 적습니다. 결정을 포인트보다 먼저 적으므로 같은 기록으로 두 번 보내면 두 번째는 409이고 **포인트가 다시 나가지 않습니다**.
- 입력 오류는 `cooldown`과 같습니다.

#### `decide`: 팝업 결정 기록 (B-3 추가)

쿨다운과 포인트 없이 감지 기록에 결정만 남깁니다.

요청

```json
{ "client": "desktop", "action": "decide", "bl_id": 115, "decision": "buy" }
```

| 칸 | 필수 | 값 |
|---|---|---|
| `bl_id` | O | `check`가 준 감지 기록 번호 |
| `decision` | O | `buy`(그래도 구매할래요), `close`(창의 X로 닫음), `giveup`(가격을 못 읽어 포인트 없이 안 살래요) |

응답

```json
{ "ok": true, "bl_id": 115, "decision": "buy" }
```

- `bl_id`가 없으면 400 `"bl_id를 보내 주세요."`, `decision`이 목록 밖이면(`hold` 포함) 400 `"decision 값이 올바르지 않습니다. (buy, close, giveup)"`
- 이미 결정된 기록, 다른 회원의 기록, `blocked` 기록, 없는 기록은 409입니다.

**감지 기록의 결정 칸** (`ipp/sql/007_popup_decision.sql`)

| `bl_decision` | 버튼 | 함께 생기는 것 |
|---|---|---|
| `''` | 아직 결정 없음 (팝업을 띄우지 않음) | - |
| `hold` | 조금 더 생각하기 (`cooldown`) | 쿨다운 `waiting`, `bl_cd_id` |
| `giveup` | 안 살래요 (`giveup`, 가격을 모르면 `decide`) | 쿨다운 `gaveup`과 포인트, `bl_cd_id` (가격을 모르면 없음) |
| `buy` | 그래도 구매할래요 (`decide`) | 없음 |
| `close` | 창의 X (`decide`) | 없음 (포인트 없음) |

`bl_decision_datetime`에 결정한 시각이 저장됩니다.

#### `amount`: 결제 금액 채우기 (B-5 추가)

데스크톱은 결제 화면 맨 위처럼 총 결제금액이 안 보이면 금액 0으로 `check`(`is_checkout: true`)를 하고 '결제 금액 확인 중' 팝업을 띄웁니다. 그 뒤 화면에서 금액을 읽으면 이 action으로 같은 감지 기록에 금액을 채웁니다. 팝업 결정(`bl_decision`)과는 상관없습니다.

요청

```json
{ "client": "desktop", "action": "amount", "bl_id": 208, "price": 149000 }
```

| 칸 | 필수 | 값 |
|---|---|---|
| `bl_id` | O | `check`가 준 감지 기록 번호 |
| `price` | O | 화면에서 읽은 결제 금액(원). 1 이상 |

응답

```json
{ "ok": true, "bl_id": 208, "price": 149000, "risk_updated": true,
  "risk": 0.6979, "risk_level": "high", "risk_message": "충동구매일 가능성이 높아 보여요. 24시간만 담아 두고 다시 생각해 볼까요?",
  "risk_reasons": [{ "code": "amount_ratio", "text": "평소 결제 금액의 5배예요." }, ...], "risk_show_reasons": true, "risk_model": "20261113-synthetic" }
```

- **위험도 다시 계산 (C-2)**: 금액을 채우면 서버가 위험도를 다시 계산해 `check`와 같은 `risk_*` 칸으로 돌려줍니다. 데스크톱은 떠 있는 팝업의 배지·제목·부제·이유를 이 값으로 바꿉니다.
  - check 때 저장한 원시 값(`bl_risk_raw`)에서 **금액과 금액 비율만** 바꿉니다. 금액 비율은 check 시각(`bl_datetime`) 이전 기록으로 계산하고, 시각·상품 화면 숫자·과거 기록 특성은 check 때 값 그대로입니다.
  - `risk_updated`: 다시 계산했으면 `true`. check 때 위험도를 계산하지 않았거나(모델 꺼짐/없음) 지금 모델이 없으면 `false`이고 `risk: null` (금액은 그래도 채웁니다)
  - 기록: `bl_risk`, `bl_risk_level`, `bl_risk_reasons`, `bl_risk_raw`가 새 값으로 바뀌고, check 때 값은 `bl_risk_first`, `bl_risk_level_first`, `bl_risk_reasons_first`에, 다시 계산한 시각은 `bl_risk_updated_datetime`에 남습니다 (`ipp/sql/011_block_log_risk_update.sql`). 다시 계산하지 않은 기록은 `bl_risk_updated_datetime`이 NULL입니다. 팝업 결정이 다시 계산 전인지 후인지는 `bl_decision_datetime`과 비교합니다.

- `bl_id`나 `price`가 없거나 0 이하면 400 `"bl_id와 금액을 보내 주세요."`
- 다른 회원의 기록, 데스크톱 결제 화면 `detect` 기록이 아닌 것(상품 화면, `blocked`, 확장 프로그램), **이미 금액이 있는 기록**, 없는 기록은 409 `"이미 금액이 있거나 찾을 수 없는 결제 화면 감지 기록입니다."` (금액은 한 번만 채우고 바꾸지 않습니다)
- 채우면 `bl_price`와 `bl_price_filled_datetime`(채운 시각, `ipp/sql/009_block_log_price_fill.sql`)이 저장됩니다. `bl_price_filled_datetime`이 NULL이면 `check` 때 받은 금액(또는 끝내 모름)입니다. C단계 학습 데이터에서 둘을 구분할 때 씁니다.

### 2-4. 호출 예시

curl (Git Bash)

```bash
curl -X POST http://localhost:8001/ipp/api/client.php \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <토큰>" \
  -d '{"client":"desktop","action":"me"}'
```

Python: 데스크톱 프로그램은 `desktop/impulse_guard/server_client.py`의 `Client`를 씁니다 (2초 timeout, 실패해도 예외 없이 오프라인 결과).

```python
from impulse_guard.server_client import Client

client = Client.from_config()          # desktop/local_config.json
client.connect()                       # me
r = client.check(site='coupang', item_name='무선 이어폰', price=89000, orig_price=119000, discount_rate=25)
if r.ok:
    print(r.data['is_impulse'], r.data['bl_id'])
elif r.offline:
    print('서버 연결 안 됨:', r.msg)

# 팝업 버튼 (B-3): 기록 하나에 셋 중 하나만 성공한다 (두 번째부터 409). 모두 bl_id를 함께 보낸다
client.cooldown('무선 이어폰', 89000, r.data['bl_id'])   # 조금 더 생각하기
client.giveup('무선 이어폰', 89000, r.data['bl_id'])     # 안 살래요
client.decide(r.data['bl_id'], 'buy')                    # 그래도 구매할래요 (창 X는 'close')
```

## 3. 웹 화면용 API (로그인 세션)

그누보드에 로그인한 브라우저에서 웹 화면이 부르는 API입니다. 외부 프로그램 연동용이 아닙니다.

- 요청: `POST`, 폼 형식, 로그인 쿠키 필요
- 응답: **항상 HTTP 200**이고 성공/실패는 `ok`로만 구분합니다. 로그인하지 않았으면 `{"ok": false, "msg": "로그인이 필요합니다."}`
- 기능 스위치가 꺼져 있으면 `{"ok": false, "msg": "...기능이 꺼져 있습니다."}`

### `/ipp/api/cooldown.php` (`IPP_USE_COOLDOWN`)

| action | 요청 칸 | 실제 성공 응답 |
|---|---|---|
| `hold` | `item`(상품명), `amount`(원, 1 이상) | `{"ok": true, "cd_id": 21}` |
| `giveup` | `item`, `amount` | `{"ok": true, "point": 500}` |

- 웹에서 만든 쿨다운은 `cd_client = 'web'`으로 저장됩니다.

### `/ipp/api/reward.php` (`IPP_USE_GIFTICON`)

| action | 요청 칸 | 실제 성공 응답 |
|---|---|---|
| `exchange` | `rw_id`(리워드 번호), `order_no`(영문/숫자 10~40자, 중복 요청 방지용) | `{"ok": true, "cp_id": 1, "point": 600}` (`point`: 교환 후 잔액, 숫자) |
| `use` | `cp_id` | `{"ok": true}` |

실제 실패 응답

| 경우 | 응답 |
|---|---|
| 같은 `order_no`로 다시 요청 (중복 클릭) | `{"ok": false, "msg": "이미 처리된 요청입니다."}` |
| 포인트 부족 | `{"ok": false, "msg": "포인트가 부족합니다."}` |
| 재고 0 | `{"ok": false, "msg": "품절된 상품입니다."}` |
| `order_no` 형식 오류 | `{"ok": false, "msg": "잘못된 요청입니다."}` |
| 이미 사용했거나 내 쿠폰이 아님 (`use`) | `{"ok": false, "msg": "사용 처리할 수 없는 쿠폰입니다."}` |

- 교환하면 쿠폰이 `issued`로 바로 발급됩니다 (기프티콘 발급은 mock: 쿠폰번호 `0000-0000-0000` 형식, 유효기간 30일).
- 재고 `-1`(무제한)은 교환해도 그대로, 유한 재고는 1씩 줄어듭니다.

### `/ipp/api/setting.php` (`IPP_USE_SETTING`)

| action | 요청 칸 | 실제 성공 응답 |
|---|---|---|
| `save` | `sites[]`(사이트 코드 여러 개), `keywords`(쉼표 구분), `risk_alert`(값이 있으면 켬) | `{"ok": true, "sites": ["coupang", "musinsa"], "keywords": ["세일", "특가"]}` |
| `block_all` | `on`: `1` 켬, `0` 끔 (쇼핑몰 전체 차단 토글. 설정 화면에서 바꾸면 바로 저장) | `{"ok": true, "block_all": false}` |
| `block` | `preset`: `1h`, `today`(오늘 23:59:59까지), `week`, `custom` / `until`: custom일 때 종료 시각 (지금 이후 30일 이내) | `{"ok": true, "until": "2026-11-11 04:02:26"}` |
| `unblock` | 없음 | `{"ok": true}` |
| `regen_token` | 없음 | `{"ok": true, "token": "3f9a...(64자리)", "server": "http://localhost:8001"}` (`IPP_USE_CLIENT_API` 필요) |
| `revoke_token` | 없음 | `{"ok": true}` |

### `/ipp/api/report.php` (`IPP_USE_STATS` + `IPP_USE_LLM`, 5 LLM 주간 리포트 요약)

통계 화면의 'AI 요약 보기' 버튼이 부릅니다. 요청 칸은 없습니다 (`POST`, 로그인 쿠키).

| 경우 | 응답 |
|---|---|
| 요약을 받음 | `{"ok": true, "summary": {"headline": "...", "summary": "...", "tip": "..."}, "msg": ""}` |
| 최근 2주 결제 화면·차단 기록이 없음 | `{"ok": true, "summary": null, "msg": "최근 2주 동안 쇼핑 기록이 없어요."}` (예측 서버를 부르지 않음) |
| 예측 서버 꺼짐, API 키 없음, 하루 상한, 시간 초과(`IPP_LLM_TIMEOUT` 10초), 요약 검사 실패 | `{"ok": true, "summary": null, "msg": "지금은 요약을 만들 수 없어요."}` |
| `IPP_USE_LLM`이 false (기본값) | `{"ok": false, "msg": "AI 요약 기능이 꺼져 있습니다."}` (통계 화면에 버튼도 없음) |

- 서버 PHP가 회원의 이번 주(오늘 포함 최근 7일)·지난주(그 전 7일) 숫자를 집계해 예측 서버 `POST /message/weekly`로 보냅니다 (`ipp/lib/report.lib.php`). 보내는 칸: 결제 화면 수, 팝업 결정별 수, 담아두기 결과, 예상 절약 금액(1,000원 단위), 위험 단계별 수, 심야 결제 화면 수, **쇼핑몰 수(이름 없음)**, 차단 횟수, 이번 주 위험도 이유 코드 횟수 상위 5개, 그리고 미리 계산한 파생 값(지난주 대비 차이·배수, 참은 비율·담아두기 성공 비율). LLM은 숫자를 직접 계산하지 않고 보낸 값만 씁니다. 회원 아이디, 상품명, 주소, 시각은 보내지 않습니다
- 예측 서버가 Claude API(`claude-haiku-5-5`)로 요약을 만들고, 입력에 없는 숫자나 너무 긴 문장이면 버립니다. 요약은 DB에 저장하지 않습니다 (예측 서버 메모리 캐시 7일)
- 연결 실패·시간 초과·503 뒤 60초(`IPP_LLM_SKIP_SEC`)는 예측 서버를 부르지 않습니다

### `/ipp/api/mock_bank.php` (`IPP_USE_BANK`)

은행 연동 mock입니다. 실제 은행 API로 바꿀 때는 `ipp/lib/bank.lib.php`의 함수만 교체합니다.

| action | 요청 칸 | 실제 성공 응답 |
|---|---|---|
| `link` | `bank`(은행 이름) | `{"ok": true, "ac_id": 2}` |
| `check` | `amount`, `merchant`(가맹점), `category`(`shopping`, `fashion`, `game`, `delivery` 등), `datetime`(생략하면 지금) | `{"ok": true, "is_impulse": 1, "point": 500, "point2": 1000}` (저장하지 않음) |
| `pay` | `check`와 같음 (계좌 연결 필요) | `{"ok": true, "tr_id": 10, "is_impulse": 1}` (거래 저장) |

## 4. 통합할 때 참고

- **팀원 프로그램은 `client.php` + API 토큰으로 연결합니다.** 회원마다 웹에서 토큰을 발급받아 프로그램에 입력합니다.
- 팀원 프로그램을 새 `client` 값으로 구분하려면 `extend/ipp.extend.php`의 `IPP_CLIENTS`에 추가합니다 (예: `mobile`). 기록의 `bl_client`, 쿨다운의 `cd_client`는 VARCHAR(10)입니다.
- 앞으로 바뀔 부분 (FEATURES.md 3번)
  - 위험도 (C-2 완료): 결제 화면 `check`가 `risk`, `risk_level`, `risk_message`, `risk_reasons`, `risk_show_reasons`, `risk_model`을 돌려줍니다. 서버 PHP 계산(`ipp/lib/risk.lib.php`). C-3 예측 서버(`ai/serve`)는 같은 JSON 모델을 쓰고, 켜면 확률·이유를 대신 계산합니다 (`risk_source`)
  - 사이트 토글(`sites[].on`): "차단 사이트 목록"에서 "쇼핑몰 감지 예외 목록"으로 의미가 바뀝니다.
  - 통계: 감지 출처(`bl_client`)별로 나눠 보기
- 바꿀 때는 기존 칸의 이름과 뜻은 유지하고 새 칸을 추가하는 방식으로 합니다. 칸을 없애거나 뜻을 바꿔야 하면 이 문서에 먼저 적고 팀원과 맞춥니다.
