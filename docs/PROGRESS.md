# impulse-guard 진행 상황

## 2026-10-28 · 3단계-1: 크롬 확장 프로그램 기본 구조와 인증 (feature/extension)

쇼핑 사이트 결제 직전에 개입할 크롬 확장 프로그램의 뼈대를 만들었다. 확장 프로그램은 그누보드 로그인 세션 없이 회원별 API 토큰으로 서버를 호출한다.

### 완료

- **DB** (`ipp/sql/004_ext_token.sql`)
  - `st_api_token`은 이제 SHA-256 해시이고, NULL이면 발급 안 됨이다. 발급 시각 `st_token_datetime`과 마지막 사용 시각 `st_token_used_datetime`을 추가했다.
  - 기존 평문 토큰은 무효화했다. 다시 실행해도 새로 발급한 토큰은 그대로 남는다.
- **설정** (`extend/ipp.extend.php`): 스위치 `IPP_USE_EXTENSION`, 사용 시각 갱신 간격 `IPP_TOKEN_TOUCH_SEC`(60초)
- **토큰 함수** (`ipp/lib/setting.lib.php`)
  - 기본행은 토큰 없이 만든다.
  - `ipp_setting_regen_token()`: 해시만 저장하고 평문을 한 번 반환한다.
  - `ipp_setting_revoke_token()`
  - `ipp_token_member()`: 형식 검사 → 해시 조회 → 탈퇴/차단 회원 거절 → 사용 시각 갱신
- **확장 프로그램 API** (`ipp/api/ext.php`)
  - 인증: `Authorization: Bearer`(또는 `X-IPP-Token`). 세션 회원은 무시하고 토큰 회원으로 덮어쓴다.
  - 입력: JSON 본문을 `php://input`으로 읽는다. 그누보드가 `$_POST`를 미리 escape하기 때문에 이중 escape를 피하려는 것이다.
  - 상태 코드: 401(토큰), 403(기능 꺼짐), 405(POST 아님), 400(입력 오류). CORS 헤더는 보내지 않는다.
  - action: `me`, `setting`, `check`, `log`, `cooldown`. 모두 기존 lib 함수(감지, 설정, 차단 기록, 쿨다운)를 재사용한다.
- **설정 화면** (`ipp/setting.php`, `ipp/api/setting.php`)
  - 확장 프로그램 연결 영역: 상태(발급/마지막 사용), 발급·재발급·연결 해제
  - 발급하면 새로고침 없이 서버 주소와 토큰을 한 번 보여 주고 복사 버튼을 둔다.
- **확장 프로그램** (`extension/`, Manifest V3, 빌드 도구 없음)
  - `background.js`: 서버 호출을 전부 처리한다. host_permissions로 CORS를 피하고, `credentials: 'omit'`, 10초 타임아웃을 쓴다. 메시지 `ipp:api`를 받는다.
  - 팝업: 서버 주소와 토큰을 `chrome.storage.local`에 저장하고 연결을 테스트한다. 기본 권한 밖의 서버는 권한을 요청한다.
  - 설치와 디버깅 방법은 `extension/README.md`에 정리했다.
- **테스트**
  - SQL을 두 번 실행해 오류가 없고, 기존 토큰이 무효화되는 것을 확인했다.
  - CLI 23개: 해시 저장, 맞는/틀린/형식 오류 토큰, 해시값 자체로는 인증 안 됨, 재발급 후 이전 토큰 거절, 해제, 차단/탈퇴 회원, 사용 시각 60초 간격
  - HTTP (임시 서버): 401/405/400/403, 세션 쿠키만으로는 401, 토큰 A와 세션 B를 같이 보내면 A로 처리, 5개 action, 따옴표 들어간 상품명 저장, 배열 주입 거절, CORS 헤더 없음, 웹 화면 발급→사용→해제
  - 브라우저 (사용자 확인): 크롬에 압축해제 로드, 팝업 저장과 연결 테스트, 재발급/해제 후 "토큰이 올바르지 않습니다", 서비스 워커 콘솔의 `ippApi()` 호출 모두 통과

### 남은 이슈

- [ ] **3-2 content script**: 6개 쇼핑 사이트의 상품명/가격/결제 버튼 감지, 차단 화면, `log`와 `cooldown` 호출, 쇼핑 사이트 host_permissions 추가
- [ ] **쿨다운 포기 API**: 바로 포인트가 지급되는 `gaveup`은 열지 않았다. 차단 화면 흐름과 함께 3-2에서 넣는다.
- [ ] **아이콘**: 확장 프로그램 아이콘이 없어 크롬 기본 글자 아이콘으로 보인다.

## 2026-10-28 · 2단계: 회원별 설정과 기록 확장 (feature/settings)

충동구매 감지 기준이 전역 상수로만 있던 것을 회원별 설정으로 넓혔다. 쇼핑 사이트 차단 기록과 통계를 쌓을 자리를 만들었다. 이 데이터는 이후 크롬 확장 프로그램, AI 모델, 통계 화면이 같이 쓴다.

### 완료

- **DB** (`ipp/sql/003_settings.sql`, `uninstall.sql`에 DROP 추가)
  - `g5_ipp_setting`: 회원당 1행. 차단 시작/종료 시각, 차단 사이트(JSON), 키워드(JSON), 위험도 알림, 확장 프로그램 토큰(유니크)
  - `g5_ipp_block_log`: 회원, 사이트 코드, URL, 상품명, 가격, 이벤트(`visit`/`blocked`/`checkout`), 체류 시간(초), 일시
  - 시연 데이터는 넣지 않아서 다시 실행해도 안전하다
- **설정** (`extend/ipp.extend.php`): 스위치 `IPP_USE_SETTING`, `IPP_USE_STATS`. 사이트 목록 `IPP_BLOCK_SITES`(코드 → 이름, 도메인). 기본 키워드, 키워드 개수/길이 상한, 직접 설정 최대 30일
- **`ipp/lib/setting.lib.php`**
  - `ipp_setting_get()`: 행이 없으면 기본값으로 생성(`INSERT IGNORE`)
  - `ipp_setting_save()`: 없는 사이트 코드를 버리고, 키워드의 공백/중복을 정리하고 개수/길이를 제한한다
  - `ipp_block_start()`(1h/today/week/custom), `ipp_block_stop()`, `ipp_is_blocking($mb_id, $site)`
  - `ipp_keyword_match()`, `ipp_block_log_add()`, `ipp_setting_regen_token()`
- **감지 확장**: `ipp_detect_impulse($amount, $category, $datetime, $text = '', $mb_id = '')`
  - 회원 키워드가 가맹점명/상품명에 들어 있으면 카테고리와 상관없이 감지한다
  - 인자 3개 호출은 기존과 결과가 같다
  - 결제 저장과 결제 전 검사 호출부에서 가맹점명과 회원을 넘긴다
- **`ipp/lib/stats.lib.php`** 지표 정의 (최근 7일 = 오늘 포함, 차단 지표는 `blocked`만 센다)
  - 오늘 차단 상품 수: `COUNT(DISTINCT bl_url)`
  - 최근 7일 예상 절약 금액: 쿨다운 `gaveup`/`success`의 `cd_amount` 합 (종료 시각 기준)
  - 일별 차단 횟수: 7일, 기록 없는 날은 0
  - 사이트별 차단 횟수: 많은 순
  - 평균 차단 시간: 차단 화면에서 페이지를 떠나기까지 머문 시간(`bl_stay_sec > 0`)의 평균
- **화면** (임시, 디자인은 6단계)
  - `ipp/setting.php`, `ipp/api/setting.php`(`save`, `block`, `unblock`, `regen_token`)
  - `ipp/stats.php`: 만료된 쿨다운을 먼저 정산한다
  - `cooldown.php`에 설정과 통계 링크 추가
- **테스트**: CLI로 40개 항목을 확인했다
  - 기본값 생성, 저장값 정리, 차단 프리셋과 거절 조건, 사이트별 차단 판단
  - 기존 3인자 감지와 키워드 감지
  - 통계 지표: 같은 URL, `visit`, 기간 밖, `failed` 제외
  - 기능 스위치 끄기
- **브라우저 테스트**: 로컬 서버에서 직접 눌러 보고 모두 통과했다.
  - 설정 저장, 차단 프리셋 4개와 해제, 토큰 재발급
  - `bank.php`에서 키워드 감지
  - 통계 화면 수치, 링크, 로그아웃/GET 요청 차단, 기능 스위치 끄기
- **참고 (OPcache)**: 로컬 PHP는 OPcache가 켜져 있고 2초마다 파일 변경을 확인한다(`revalidate_freq = 2`). 그래서 `extend/ipp.extend.php`의 스위치를 바꾸고 2초 안에 요청하면 이전 값으로 동작한다. 스위치를 테스트할 때는 저장하고 몇 초 기다린 뒤 확인한다.

### 남은 이슈

- [x] **확장 프로그램 API**: 3-1에서 `ipp/api/ext.php`로 추가했다 (`setting`, `log` 등).
- [ ] **차단 이력**: 설정 테이블은 마지막 차단 1건만 저장한다. "차단을 켜 둔 기간의 평균"이 필요하면 이력 테이블을 추가해야 한다.
- [ ] **회원별 감지 기준**: 심야 시간과 고액 기준(`IPP_DETECT_*`)은 아직 전역 상수다.
- [ ] **위험도 알림**: `st_risk_alert`는 저장만 한다. 실제 알림은 확장 프로그램/AI 단계에서 붙인다.
- [x] **토큰 보관**: 3-1에서 SHA-256 해시 저장으로 바꿨다.

## 2026-10-28 · 기프티콘 리워드 교환 (feature/gifticon)

영카트 쇼핑몰 상품으로 임시 구현했던 리워드를 별도 교환 페이지로 바꿨다. 기프티콘은 배송이 없어 주문서를 거치지 않는다.

### 완료

- **DB** (`ipp/sql/002_gifticon.sql`)
  - `g5_ipp_reward`: 이름, 브랜드, 필요 포인트, 이미지 URL, 상품 코드, 재고(-1은 무제한), 사용 여부, 정렬
  - `g5_ipp_coupon`: 회원, 리워드, 주문번호(유니크), 쿠폰번호, 상태, 유효기간, 발급일
  - 쿠폰 상태: `pending` → `issued`(사용 전) → `used`(사용 완료) / `expired`(만료), 발급 실패 시 `failed`(환불)
  - 시연용 리워드 5개 (1,500P ~ 18,000P, 아이스크림만 재고 3개)
  - `uninstall.sql`에 두 테이블 DROP 추가
- **기프티콘 API 경계** (`ipp/lib/gifticon.lib.php`)
  - `ipp_gifticon_issue()` 하나로 감싼 mock. 임의 쿠폰번호와 30일 유효기간을 반환한다.
  - 실제 API로 바꿀 때는 이 함수 내부만 교체하고 반환 형식은 유지한다.
- **교환 처리** (`ipp/lib/reward.lib.php`)
  - `insert_point()` 음수로 차감 (`rel_table = ipp_reward`, `rel_action = exchange`)
  - 잔액 부족, 품절, 사용하지 않는 상품이면 거절
  - 중복 차감 방지: 버튼 비활성화, 페이지마다 주문번호 1개(유니크 키), 회원 단위 `GET_LOCK`으로 잔액 확인부터 차감까지 직렬화
  - 발급 실패 시 같은 금액을 환불(`rel_action = refund`)하고 재고를 되돌림
- **하루 획득 상한**: `ipp_today_point()`에서 `ipp_reward`를 제외해 환불이 "오늘 획득"으로 잡히지 않게 했다.
- **화면**
  - `ipp/reward.php`: 교환 목록
  - `ipp/coupon.php`: 내 쿠폰함 (유효기간 지난 쿠폰은 열 때 만료 처리, 시연용 "사용 완료로 표시" 버튼)
  - `ipp/api/reward.php`: `exchange`, `use`
  - `ipp/cooldown.php`의 리워드샵 링크를 `reward.php`로 교체
- **설정** (`extend/ipp.extend.php`): 기능 스위치 `IPP_USE_GIFTICON`, 쿠폰 유효기간 `IPP_GIFTICON_EXPIRE_DAYS`
- **테스트**: 정상 교환, 중복 요청, 동시 요청 잔액 부족, 재고 소진, 발급 실패 환불과 하루 상한 유지, 만료와 사용 처리, 기능 스위치 끄기를 로컬에서 확인했다.

### 남은 이슈

- [ ] **실제 기프티콘 API 연동**: 업체 선정 후 `ipp_gifticon_issue()` 교체. 바코드 이미지(`cp_barcode_url`)는 지금 비어 있다.
- [ ] **사용 여부 동기화**: 지금은 회원이 직접 "사용 완료"를 누른다. 실제 API에서는 사용 여부 조회로 바꿔야 한다.
- [ ] **`pending`으로 남는 쿠폰**: 포인트를 차감한 뒤 발급 API 응답 전에 요청이 끊기면 쿠폰이 `pending`으로 남고 포인트는 환불되지 않는다. 일정 시간이 지난 `pending`을 찾아 API 조회 후 발급 완료 또는 환불(`cancelled`)하는 정리 작업이 필요하다.
- [ ] **관리자 페이지**: 리워드 등록/수정, 재고, 노출 관리를 위한 `adm/ipp_reward_*.php`가 없어 지금은 DB에서 직접 고친다.
- [ ] **리워드 이미지**: 시연 데이터의 `rw_image`가 비어 있어 기본 아이콘(🎁)으로 표시된다.
- [ ] **기존 리워드샵 상품 정리**: 영카트 쇼핑몰의 임시 리워드 상품(`ca_id=10`)이 아직 남아 있다. 숨김 또는 삭제 결정 필요.
- [ ] **만료 쿠폰 정책**: 쓰지 않고 만료된 쿠폰의 포인트를 돌려줄지 결정 필요 (현재는 환불 없음).
- [ ] **시연 SQL 반복 실행**: `002_gifticon.sql`을 다시 실행하면 시연 리워드가 중복으로 들어간다.
