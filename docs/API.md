# impulse-guard 서버 API 명세

> 기준: 2026-11-11 (A-5단계), `dev` 브랜치 코드
> 팀원 프로젝트를 통합할 때 이 문서를 기준으로 연결합니다. API를 바꾸면 이 문서도 같이 고칩니다.

## 1. 개요

| 구분 | 주소 | 인증 | 요청 형식 | 쓰는 곳 |
|---|---|---|---|---|
| 프로그램용 API | `/ipp/api/ext.php` | API 토큰 (`Authorization: Bearer`) | JSON 본문 | 데스크톱 감지 프로그램 (예전: 크롬 확장 프로그램) |
| 웹 화면용 API | `/ipp/api/cooldown.php`, `reward.php`, `setting.php`, `mock_bank.php` | 그누보드 로그인 세션 (쿠키) | 폼 (`application/x-www-form-urlencoded`) | 그누보드 웹 화면 (`ipp/*.php`) |

- 서버 주소(로컬): `http://localhost:8001`
- 모든 응답은 JSON(UTF-8)이며 `ok`(true/false)가 들어 있습니다. 실패하면 `msg`에 한국어 안내가 들어 있습니다.
- 금액과 포인트는 원/포인트 단위 정수, 날짜와 시각은 서버 시각 `YYYY-MM-DD HH:MM:SS` 문자열입니다.
- **외부 프로그램(데스크톱, 팀원 프로젝트)은 프로그램용 API(`ext.php`)를 씁니다.** 웹 화면용 API는 로그인 쿠키가 있어야 해서 웹 화면 안에서만 씁니다.

## 2. 프로그램용 API: `POST /ipp/api/ext.php`

### 2-1. 인증 (API 토큰)

1. 웹에서 로그인 → `/ipp/setting.php`의 "확장 프로그램 연결"에서 **발급** (화면 문구는 아직 확장 프로그램 기준)
2. 서버 주소와 토큰(64자리 16진수)이 **한 번만** 보입니다. 서버에는 SHA-256 해시만 저장되므로 다시 볼 수 없고, 잃어버리면 재발급합니다.
3. 요청마다 헤더에 넣습니다.

```
POST /ipp/api/ext.php HTTP/1.1
Host: localhost:8001
Content-Type: application/json
Authorization: Bearer 3f9a...(64자리)
```

- `Authorization` 헤더를 쓸 수 없는 환경이면 `X-IPP-Token: 3f9a...` 헤더도 받습니다.
- 로그인 쿠키는 무시합니다. 토큰으로 찾은 회원으로만 처리합니다.
- 재발급하면 이전 토큰은 바로 무효가 됩니다. 연결 해제, 탈퇴/차단 회원도 무효입니다.
- CORS 헤더를 보내지 않습니다. 브라우저 페이지의 JavaScript에서 직접 부르는 용도가 아닙니다.

### 2-2. 요청과 응답 공통

요청 본문은 JSON 객체이고, `action`으로 기능을 고릅니다.

```json
{ "action": "check", "site": "coupang", "item_name": "무선 이어폰", "price": 89000 }
```

- 문자열 칸에 배열이나 객체를 보내면 빈 문자열로, 숫자 칸에 숫자가 아닌 값을 보내면 0으로 처리합니다.

| HTTP 상태 | 뜻 | 응답 예 |
|---|---|---|
| 200 | 성공 | `{"ok": true, ...}` |
| 400 | 입력 오류, JSON 아님, 알 수 없는 action | `{"ok": false, "msg": "알 수 없는 요청입니다."}` |
| 401 | 토큰 없음/틀림 | `{"ok": false, "msg": "토큰이 올바르지 않습니다."}` |
| 403 | 기능 스위치가 꺼짐 | `{"ok": false, "msg": "쿨다운 기능이 꺼져 있습니다."}` |
| 405 | POST가 아님 | `{"ok": false, "msg": "POST로 요청하세요."}` |

검사 순서: 기능 스위치(`IPP_USE_EXTENSION`) → POST 여부 → 토큰 → JSON 본문 → action

### 2-3. action 목록

| action | 하는 일 | 저장 | 필요한 기능 스위치 |
|---|---|---|---|
| `me` | 연결 확인, 회원과 포인트 | 없음 | - |
| `setting` | 차단 설정 조회 | 없음 | `IPP_USE_SETTING` |
| `check` | 상품 하나의 차단/충동구매 판단 | 없음 | - |
| `log` | 방문/차단/결제 진입 기록 | `g5_ipp_block_log` | `IPP_USE_SETTING` |
| `cooldown` | 24시간 담아두기 시작 | `g5_ipp_cooldown` | `IPP_USE_COOLDOWN` |
| `giveup` | 안 살래요 (즉시 포기, 포인트 지급) | `g5_ipp_cooldown`, 포인트 | `IPP_USE_COOLDOWN` |

#### `me`: 연결 확인

요청

```json
{ "action": "me" }
```

응답

```json
{
  "ok": true,
  "mb_id": "test01",
  "nick": "테스트",
  "point": 1250,
  "features": { "setting": true, "cooldown": true, "gifticon": true }
}
```

- `point`: 현재 보유 포인트 합계
- `features`: 서버에서 켜진 기능. 꺼진 기능의 버튼은 숨기는 데 씁니다.

#### `setting`: 차단 설정 조회

요청

```json
{ "action": "setting" }
```

응답 (차단 중일 때)

```json
{
  "ok": true,
  "is_blocking": true,
  "block_until": "2026-11-11 23:59:59",
  "block_remain": 5400,
  "sites": [
    { "code": "naver",   "name": "네이버쇼핑", "domain": "shopping.naver.com", "on": true },
    { "code": "coupang", "name": "쿠팡",       "domain": "coupang.com",        "on": true },
    { "code": "gmarket", "name": "G마켓",      "domain": "gmarket.co.kr",      "on": false },
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
- `sites[].on`: 이 사이트가 차단 목록에 켜져 있는지. 사이트 목록은 `extend/ipp.extend.php`의 `IPP_BLOCK_SITES`
- `keywords`: 회원 차단 키워드 (최대 20개, 각 20자)

#### `check`: 상품 판단

요청

```json
{ "action": "check", "site": "coupang", "item_name": "[특가] 무선 이어폰", "price": 89000 }
```

| 칸 | 필수 | 설명 |
|---|---|---|
| `site` | O | `IPP_BLOCK_SITES`의 코드 (`naver`, `coupang`, `gmarket`, `11st`, `zigzag`, `musinsa`). 그 밖이면 400 |
| `item_name` | | 상품명. 회원 키워드 검사에 씁니다 |
| `price` | | 가격(원). 음수는 0. 0이면 고액 판단을 할 수 없습니다 |

응답

```json
{
  "ok": true,
  "is_blocking": false,
  "is_impulse": 1,
  "keyword": "특가",
  "point": 500,
  "point2": 1000
}
```

- `is_blocking`: 지금 차단 시간이고 이 사이트가 차단 목록에 켜져 있으면 true
- `is_impulse`: 충동구매 감지 1, 아니면 0 (숫자). 규칙: 회원 키워드가 상품명에 있거나, 심야(23시~4시 전) 또는 고액(50,000원 이상)
- `keyword`: 상품명에서 찾은 첫 키워드. 없으면 `""`
- `point`: 지금 포기하면 받을 포인트, `point2`: 24시간 참으면 받을 포인트(2배). 하루 상한(1,000P)은 반영하지 않은 값입니다.
- 위험 판단: `is_blocking`이 true이거나 `is_impulse`가 1이면 팝업을 띄웁니다.

#### `log`: 기록

요청

```json
{
  "action": "log",
  "site": "coupang",
  "event": "blocked",
  "page": "product",
  "url": "https://www.coupang.com/vp/products/123456",
  "item_name": "무선 이어폰",
  "price": 89000,
  "stay_sec": 12
}
```

| 칸 | 필수 | 값 |
|---|---|---|
| `site` | O | `IPP_BLOCK_SITES`의 코드 |
| `event` | O | `visit`(상품을 보고 떠남), `blocked`(차단 팝업/안내를 봄), `checkout`(그래도 구매 진행) |
| `page` | | `product`(상품 상세), `cart`(장바구니), `""`(그 밖의 페이지, 기본값) |
| `url` | | 최대 500자 |
| `item_name` | | 최대 255자 |
| `price` | | 원, 음수는 0 |
| `stay_sec` | | 머문 시간(초). `blocked`의 평균 차단 시간 통계에 씁니다 |

응답

```json
{ "ok": true, "bl_id": 42 }
```

- `site`, `event`, `page`가 목록에 없으면 400 `"사이트, 이벤트, 페이지 값이 올바르지 않습니다."`

#### `cooldown`: 24시간 담아두기

요청

```json
{ "action": "cooldown", "item_name": "무선 이어폰", "price": 89000 }
```

응답

```json
{ "ok": true, "cd_id": 17, "expire": "2026-11-12 14:30:00" }
```

- `item_name`이 비었거나 `price`가 0 이하면 400 `"상품명과 가격을 보내 주세요."`
- `expire`: 쿨다운 종료 시각 (`IPP_COOLDOWN_HOURS` 뒤). 끝나면 웹의 쿨다운 화면에서 정산되어 성공 시 2배 포인트를 줍니다.
- 지금은 출처가 `cd_source = 'manual'`로 저장됩니다. 데스크톱 출처 구분은 예정(FEATURES.md 3번)

#### `giveup`: 안 살래요

요청

```json
{ "action": "giveup", "item_name": "무선 이어폰", "price": 89000 }
```

응답

```json
{ "ok": true, "cd_id": 18, "point": 500 }
```

- 쿨다운을 만들고 바로 포기(`gaveup`) 처리해 포인트를 지급합니다 (`ipp_give_point()`를 거침).
- `point`: 실제 지급된 포인트. 하루 상한을 넘으면 줄어들거나 0입니다.
- 입력 오류는 `cooldown`과 같습니다.

### 2-4. 호출 예시

curl (Git Bash)

```bash
curl -X POST http://localhost:8001/ipp/api/ext.php \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <토큰>" \
  -d '{"action":"me"}'
```

Python (데스크톱 프로그램)

```python
import requests

resp = requests.post(
    "http://localhost:8001/ipp/api/ext.php",
    json={"action": "check", "site": "coupang", "item_name": "무선 이어폰", "price": 89000},
    headers={"Authorization": f"Bearer {token}"},
    timeout=10,
)
data = resp.json()   # 실패해도 JSON이 온다. resp.status_code와 data["ok"]를 함께 본다
```

## 3. 웹 화면용 API (로그인 세션)

그누보드에 로그인한 브라우저에서 웹 화면이 부르는 API입니다. 외부 프로그램 연동용이 아닙니다.

- 요청: `POST`, 폼 형식, 로그인 쿠키 필요
- 응답: **항상 HTTP 200**이고 성공/실패는 `ok`로만 구분합니다. 로그인하지 않았으면 `{"ok": false, "msg": "로그인이 필요합니다."}`
- 기능 스위치가 꺼져 있으면 `{"ok": false, "msg": "...기능이 꺼져 있습니다."}`

### `/ipp/api/cooldown.php` (`IPP_USE_COOLDOWN`)

| action | 요청 칸 | 성공 응답 |
|---|---|---|
| `hold` | `item`(상품명), `amount`(원, 1 이상) | `{"ok": true, "cd_id": 17}` |
| `giveup` | `item`, `amount` | `{"ok": true, "point": 500}` |

### `/ipp/api/reward.php` (`IPP_USE_GIFTICON`)

| action | 요청 칸 | 성공 응답 |
|---|---|---|
| `exchange` | `rw_id`(리워드 번호), `order_no`(영문/숫자 10~40자, 중복 요청 방지용) | `{"ok": true, "cp_id": 5, "point": 750}` (`point`: 교환 후 잔액) |
| `use` | `cp_id` | `{"ok": true}` |

- `exchange` 실패 예: `{"ok": false, "msg": "포인트가 부족합니다."}` (잔액 부족, 품절, 판매 중지 등)

### `/ipp/api/setting.php` (`IPP_USE_SETTING`)

| action | 요청 칸 | 성공 응답 |
|---|---|---|
| `save` | `sites[]`(사이트 코드 여러 개), `keywords`(쉼표 구분), `risk_alert`(값이 있으면 켬) | `{"ok": true, "sites": ["coupang"], "keywords": ["세일", "특가"]}` |
| `block` | `preset`: `1h`, `today`(오늘 23:59:59까지), `week`, `custom` / `until`: custom일 때 종료 시각 (지금 이후 30일 이내) | `{"ok": true, "until": "2026-11-11 15:30:00"}` |
| `unblock` | 없음 | `{"ok": true}` |
| `regen_token` | 없음 | `{"ok": true, "token": "3f9a...(64자리)", "server": "http://localhost:8001"}` (`IPP_USE_EXTENSION` 필요) |
| `revoke_token` | 없음 | `{"ok": true}` |

### `/ipp/api/mock_bank.php` (`IPP_USE_BANK`)

은행 연동 mock입니다. 실제 은행 API로 바꿀 때는 `ipp/lib/bank.lib.php`의 함수만 교체합니다.

| action | 요청 칸 | 성공 응답 |
|---|---|---|
| `link` | `bank`(은행 이름) | `{"ok": true, "ac_id": 1}` |
| `check` | `amount`, `merchant`(가맹점), `category`(`shopping`, `fashion`, `game`, `delivery` 등), `datetime`(생략하면 지금) | `{"ok": true, "is_impulse": 1, "point": 500, "point2": 1000}` (저장하지 않음) |
| `pay` | `check`와 같음 (계좌 연결 필요) | `{"ok": true, "tr_id": 31, "is_impulse": 1}` (거래 저장) |

## 4. 통합할 때 참고

- **팀원 프로그램은 `ext.php` + API 토큰으로 연결합니다.** 회원마다 웹에서 토큰을 발급받아 프로그램에 입력합니다.
- 바뀔 예정인 부분 (FEATURES.md 3번 "수정" 항목)
  - `check`의 `site`: 지금은 `IPP_BLOCK_SITES` 코드만 받습니다. 데스크톱은 OCR로 판별하므로 목록에 없는 쇼핑몰도 들어올 수 있어 값을 넓혀야 합니다.
  - 감지 출처: `log`와 쿨다운에 출처(데스크톱/웹 등) 칸을 추가할 예정입니다.
  - 사이트 토글(`sites[].on`): "차단 사이트 목록"에서 "쇼핑몰 감지 예외 목록"으로 의미가 바뀝니다.
  - 토큰 발급 화면의 "확장 프로그램" 문구를 데스크톱 공용으로 정리합니다.
- 바꿀 때는 기존 칸의 이름과 뜻은 유지하고 새 칸을 추가하는 방식으로 합니다. 칸을 없애거나 뜻을 바꿔야 하면 이 문서에 먼저 적고 팀원과 맞춥니다.
