# impulse-guard 크롬 확장 프로그램

쇼핑 사이트에서 결제 직전에 개입하는 확장 프로그램입니다 (Manifest V3).
서버는 그누보드의 `ipp/api/ext.php`를 사용하며, 로그인 세션 대신 회원별 API 토큰으로 인증합니다.

> 3-2단계 현재 지원 사이트: 쿠팡 (상품 상세, 장바구니)

## 파일

| 파일 | 역할 |
|---|---|
| `manifest.json` | 권한과 진입점 |
| `background.js` | 서버 호출을 전부 처리하는 service worker. `ippApi(action, data)` |
| `popup.html` / `popup.js` / `popup.css` | 서버 주소와 토큰을 입력하고 연결을 확인하는 팝업 |
| `sites.js` | **사이트별 선택자 설정.** 사이트 구조가 바뀌면 이 파일만 고친다 |
| `content.js` | 쇼핑 페이지에서 상품 정보 추출, 방문 기록, 결제 버튼 가로채기, 차단 팝업 |

## 쇼핑 페이지 동작 (content script)

1. **방문 기록**: 상품 상세 페이지를 떠날 때 상품명, 가격, 체류 시간(초)을 `visit`으로 한 번 기록합니다. 기록 URL에서는 검색어/추적용 쿼리를 뺍니다.
2. **결제 버튼 가로채기**: 상품 페이지의 **바로구매**, 장바구니의 **구매하기**를 누르면 원래 동작을 잠시 멈추고 서버 `check`를 호출합니다. (장바구니 담기는 가로채지 않습니다)
3. 차단 시간이거나 충동구매(키워드, 심야, 고액)로 판단되면 **차단 팝업**을 띄웁니다. 아니면 바로 원래 동작을 진행합니다.
   - **조금 더 생각하기**: 쿨다운(24시간 담아두기) 시작. 구매는 진행하지 않습니다.
   - **안 살래요**: 즉시 포기로 포인트 지급. 구매는 진행하지 않습니다.
   - **그래도 구매하기**: 원래 클릭을 그대로 다시 보냅니다.
   - 팝업을 닫거나 페이지를 떠날 때 팝업을 본 시간과 함께 `blocked`를 기록하고, 구매를 진행하면 `checkout`을 기록합니다.
4. 토큰이 없거나 서버가 꺼져 있으면 **막지 않고** 그대로 진행합니다. (서비스 워커 콘솔이 아니라 쇼핑 페이지 콘솔에 경고가 남습니다)

확장 프로그램을 새로고침(↻)한 뒤에는 **열려 있던 쿠팡 탭도 새로고침**해야 새 content script가 들어갑니다.

## 선택자 찾기 (쇼핑 사이트 구조가 바뀌었을 때)

`sites.js`의 선택자 중 `확인 필요`라고 적힌 것은 실제 쿠팡 페이지에서 확인하지 못한 값입니다. 크롬 개발자 도구로 이렇게 찾습니다.

### 1. 요소의 선택자 알아내기

1. 쿠팡 상품 페이지에서 상품명 위에 마우스를 올리고 오른쪽 클릭 → **검사** (또는 `F12` 후 왼쪽 위 화살표 아이콘으로 요소 클릭)
2. **Elements** 패널에 해당 태그가 파랗게 표시됩니다. 예:
   ```html
   <h1 class="product-title"><span>나이키 운동화</span></h1>
   ```
3. 태그 이름과 `class`/`id`를 조합해 선택자를 만듭니다.
   - `class="product-title"`인 `h1` → `h1.product-title`
   - `id="btnPay"` → `#btnPay`
   - class가 여러 개면(`class="price final-price-amount"`) 그중 **의미 있어 보이는 이름 하나**만 씁니다 → `.final-price-amount`
   - `css-1x2y3z`, `sc-abc123`처럼 **무작위로 보이는 class는 쓰지 않습니다.** 배포할 때마다 바뀝니다. 이때는 위쪽 부모 요소에서 의미 있는 이름을 찾아 `.prod-price strong`처럼 "부모 자식" 형태로 씁니다.
4. 오른쪽 클릭 → **Copy → Copy selector**도 있지만 `#contents > div:nth-child(3) > ...`처럼 길고 깨지기 쉬워서, 참고만 하고 위 방법으로 짧게 줄입니다.

### 2. 콘솔에서 확인하기

**Console** 탭에서 아래를 입력하면 바로 확인할 수 있습니다.

```js
document.querySelectorAll('h1.product-title').length   // 1이면 딱 맞음, 0이면 못 찾음, 여러 개면 범위가 넓음
document.querySelector('h1.product-title').textContent  // 읽히는 글자
```

### 3. 확장 프로그램이 실제로 읽는 값 확인 (`ippInspect()`)

1. Console 탭 위쪽의 **top** 드롭다운을 눌러 **impulse-guard**를 고릅니다. (content script가 도는 공간)
2. `ippInspect()`를 입력합니다.
3. `sites.js`의 선택자마다 찾은 개수와 첫 요소의 글자가 표로 나오고, 마지막에 실제 추출 결과(상품명, 가격, 이미지)가 나옵니다.

### 찾아야 할 것

| 페이지 | 항목 | 설명 |
|---|---|---|
| 상품 상세 `www.coupang.com/vp/products/...` | 상품명 | 페이지 위쪽 큰 제목 |
| | 가격 | **최종 판매가** (와우/쿠폰 할인가가 따로 있으면 실제 결제되는 쪽). 정가(줄 그어진 가격)가 아님 |
| | 대표 이미지 | 왼쪽 큰 상품 사진의 `<img>` |
| | 바로구매 버튼 | `<button>`이면 버튼 자체, 안에 `<span>`이 있어도 바깥 `<button>`의 선택자 |
| 장바구니 `cart.coupang.com/cartView.pang` | 상품명 | 담긴 상품 각각의 이름 (여러 개 잡혀야 함) |
| | 가격 | 아래쪽 **총 결제 예정 금액** |
| | 이미지 | 상품 썸네일 |
| | 구매하기 버튼 | 맨 아래 결제 진행 버튼 |

찾은 선택자는 `sites.js`의 해당 배열 **맨 앞**에 넣고, 확장 프로그램과 쿠팡 탭을 새로고침합니다.
버튼은 선택자가 틀려도 버튼 글자(`texts`)로 한 번 더 찾고, 상품명/이미지는 `og:title`/`og:image` 메타 태그로 대신하지만, 가격은 대체값이 없어 선택자가 맞아야 합니다.

## 설치 (압축해제된 확장 프로그램 로드)

1. 그누보드 서버를 켭니다.
   ```powershell
   cd c:\projects\youngcart\gnuboard5.6.43
   php -S localhost:8000
   ```
2. 크롬 주소창에 `chrome://extensions`를 입력합니다.
3. 오른쪽 위 **개발자 모드**를 켭니다.
4. **압축해제된 확장 프로그램을 로드합니다**를 누르고 저장소의 `extension` 폴더를 선택합니다.
5. 목록에 **impulse-guard**가 나타납니다. 툴바의 퍼즐 아이콘 → 핀으로 고정하면 팝업을 열기 편합니다.

코드를 고친 뒤에는 `chrome://extensions`의 impulse-guard 카드에서 **새로고침(↻)**을 눌러야 반영됩니다.
팝업 파일(`popup.*`)만 고쳤다면 팝업을 다시 여는 것으로 충분합니다.

## 연결

1. http://localhost:8000/ipp/setting.php 에 로그인한 상태로 들어갑니다.
2. **확장 프로그램 연결**에서 **발급**(이미 있으면 **재발급**)을 누릅니다.
3. 나타난 **서버 주소**와 **토큰**을 복사합니다. 토큰은 이 화면에서 한 번만 보이며, 서버에는 해시만 저장됩니다.
4. 확장 프로그램 팝업에 두 값을 붙여 넣고 **저장 후 연결 테스트**를 누릅니다.
5. "연결됨: 닉네임 (포인트)"가 나오면 성공입니다.

- 서버 주소가 `localhost`나 `127.0.0.1`이 아니면 저장할 때 그 주소에 대한 접근 권한을 묻습니다. 허용해야 연결됩니다.
- 토큰을 잃어버렸거나 다른 PC에서 쓰려면 재발급하세요. 재발급하면 이전 토큰은 바로 쓸 수 없게 됩니다.
- 토큰은 `chrome.storage.local`에 저장됩니다. 구글 계정 동기화(`storage.sync`)는 쓰지 않습니다.

## 디버깅

- **백그라운드 로그와 직접 호출**: `chrome://extensions` → impulse-guard → **서비스 워커** 링크 → 콘솔에서 아래처럼 서버를 직접 부를 수 있습니다.
  ```js
  await ippApi('me')
  await ippApi('setting')
  await ippApi('check', { site: 'coupang', item_name: '특가 운동화', price: 89000 })
  await ippApi('log', { site: 'coupang', url: 'https://www.coupang.com/vp/products/1', item_name: '운동화', price: 89000, event: 'blocked', stay_sec: 12 })
  ```
- **팝업 콘솔**: 팝업 위에서 오른쪽 클릭 → **검사**
- **content script 콘솔**: 쇼핑 페이지에서 `F12` → Console. 상단 드롭다운에서 **impulse-guard**를 고르면 `ippInspect()`를 쓸 수 있습니다.
- 서비스 워커는 쉬고 있다가 메시지가 오면 깨어납니다. 링크 옆에 "(비활성)"이 보여도 정상입니다.

## 서버 API 요약 (`POST /ipp/api/ext.php`)

- 헤더: `Authorization: Bearer <토큰>`, `Content-Type: application/json`
- 본문: `{"action": "...", ...}`
- 상태 코드: 200 성공, 400 잘못된 입력, 401 토큰 오류, 403 기능 꺼짐, 405 POST 아님

| action | 입력 | 응답 |
|---|---|---|
| `me` | - | mb_id, nick, point, features |
| `setting` | - | is_blocking, block_until, sites, keywords, risk_alert |
| `check` | site, item_name, price | is_blocking, is_impulse, keyword, point, point2 |
| `log` | site, url, item_name, price, event(visit/blocked/checkout), stay_sec | bl_id |
| `cooldown` | item_name, price | cd_id, expire |
| `giveup` | item_name, price | cd_id, point (안 살래요, 포인트 바로 지급) |
