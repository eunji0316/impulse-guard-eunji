# impulse-guard 크롬 확장 프로그램

쇼핑 사이트에서 결제 직전에 개입하는 확장 프로그램입니다 (Manifest V3).
서버는 그누보드의 `ipp/api/ext.php`를 사용하며, 로그인 세션 대신 회원별 API 토큰으로 인증합니다.

> 3-1단계에서는 기본 구조와 인증만 만들었습니다. 쇼핑 페이지에 들어가는 content script와 차단 화면은 3-2단계에서 추가합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `manifest.json` | 권한과 진입점 |
| `background.js` | 서버 호출을 전부 처리하는 service worker. `ippApi(action, data)` |
| `popup.html` / `popup.js` / `popup.css` | 서버 주소와 토큰을 입력하고 연결을 확인하는 팝업 |

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
