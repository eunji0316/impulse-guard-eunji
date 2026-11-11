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
  "url": ""
}
```

| 칸 | 필수 | 설명 |
|---|---|---|
| `site` | O | `IPP_BLOCK_SITES`의 코드 (`naver`, `coupang`, `gmarket`, `11st`, `zigzag`, `musinsa`). 그 밖이면 400. **`client: desktop`이면 `""`(사이트 모름)도 됩니다** |
| `item_name` | | 상품명. 회원 키워드 검사에 씁니다 |
| `price` | | 판매가(할인가, 원). 음수는 0. 0이면 고액 판단을 할 수 없습니다 |
| `orig_price` | | 원가(원). 음수는 0 (B-2 추가) |
| `discount_rate` | | 할인율 %. 0~99 밖이면 0 (B-2 추가) |
| `is_checkout` | | 결제 화면인지 (B-2 추가) |
| `log` | | `true`면 기록 1건을 저장하고 `event`, `bl_id`를 돌려줍니다. 차단 중(`is_blocking: true`)이면 이벤트 `blocked`, 아니면 `detect`입니다 (B-3에서 바뀜). 기본 false (B-2 추가) |
| `page`, `url` | | `log: true`일 때 기록에 저장. `page`는 `product`, `cart`, `""` |

`orig_price`, `discount_rate`, `is_checkout`은 **지금은 저장만 하고 위험도에는 쓰지 않습니다** (C단계에서 반영).

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
- `reasons`: 충동구매로 본 이유 목록 (B-3 추가). 중요한 것부터 `keyword`(회원 키워드) → `big`(고액) → `night`(심야) 순서입니다. 없으면 `[]`. `text`는 화면에 그대로 보여 줄 문구입니다 (심야: `"밤 11시~새벽 4시 사이의 심야 쇼핑이에요."`). 기준값은 `extend/ipp.extend.php`의 `IPP_DETECT_*`에서 가져옵니다.
- `keyword`: 상품명에서 찾은 첫 키워드. 없으면 `""` (예: 상품명 `[특가] 무선 이어폰` → `"특가"`)
- `point`: 지금 포기하면 받을 포인트, `point2`: 24시간 참으면 받을 포인트(2배). 하루 상한(1,000P)은 반영하지 않은 값입니다.
- `received`: 서버가 정리해서 받아들인 원가, 할인율, 결제 화면 여부
- `event`, `bl_id`: `log: true`일 때만 있습니다. `event`는 저장한 이벤트(`detect` 또는 `blocked`)입니다. 차단 중이면 아래처럼 `blocked`로 저장되어 통계의 차단 횟수에 들어갑니다.

  ```json
  { "ok": true, "is_blocking": true, "is_impulse": 1, "reasons": [{ "code": "big", "text": "50,000원 이상의 큰 금액이에요." }],
    "keyword": "", "point": 500, "point2": 1000, "received": { "orig_price": 0, "discount_rate": 0, "is_checkout": false },
    "event": "blocked", "bl_id": 116 }
  ```
- 데스크톱 팝업 (B-3): `is_blocking`이면 차단 안내 창, 아니고 `is_impulse`가 1이면 충동구매 팝업을 띄웁니다. 가격을 못 읽었으면(`price: 0`) 충동구매가 아니어도 팝업을 띄웁니다. 팝업에서 고른 결정은 `bl_id`로 `cooldown`, `giveup`, `decide`에 보냅니다.

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
  - 위험도: `check`의 `orig_price`, `discount_rate`, `is_checkout`을 위험도에 반영 (C단계). 응답에 위험도 점수 칸이 추가될 예정입니다.
  - 사이트 토글(`sites[].on`): "차단 사이트 목록"에서 "쇼핑몰 감지 예외 목록"으로 의미가 바뀝니다.
  - 통계: 감지 출처(`bl_client`)별로 나눠 보기
- 바꿀 때는 기존 칸의 이름과 뜻은 유지하고 새 칸을 추가하는 방식으로 합니다. 칸을 없애거나 뜻을 바꿔야 하면 이 문서에 먼저 적고 팀원과 맞춥니다.
