# 팀 저장소(impulse-guard)에 합칠 때

이 저장소는 팀 공용 impulse-guard에서 2026-11-11에 분리한 개인 프로젝트다. 분리 기준 커밋은 `71bb0a2`(4-1 AI 환경과 데이터 준비)로 보고,
그 뒤 바뀐 것을 정리했다 (`git diff --stat 71bb0a2 HEAD`).

> **팀 저장소 실제 코드와의 비교는 아직 하지 않았다.** 팀 저장소 위치를 받으면 읽기만 해서 아래 '겹치는 부분'을 실제 코드와 맞춰 본다.
> 그 전까지 이 문서는 분리 시점 기준이다.

## 1. 실행할 SQL (`ipp/sql/`, 번호 순서)

분리 시점 팀 DB에는 001~005가 있다고 본다. 실행 전 DB를 백업한다.

| 파일 | 하는 일 | 다시 실행 |
|---|---|---|
| `006_client_source.sql` | 감지 기록 `bl_client`, `bl_orig_price`, `bl_discount_rate`, `bl_is_checkout`, 쿨다운 `cd_client` 등 | 안전 (`ADD COLUMN IF NOT EXISTS`) |
| `007_popup_decision.sql` | 팝업 결정 `bl_decision`, `bl_decision_datetime`, `bl_cd_id` | 안전 |
| `008_block_all.sql` | 쇼핑몰 전체 차단 `st_block_all` | 안전 |
| `009_block_log_price_fill.sql` | 나중에 채운 결제 금액 시각 `bl_price_filled_datetime` | 안전 |
| `010_block_log_risk.sql` | 위험도 `bl_risk`, `bl_risk_level`, `bl_risk_model`, `bl_risk_reasons`, `bl_risk_raw`, 인덱스 `idx_mb_checkout_dt` | 안전 (`ADD INDEX IF NOT EXISTS`) |
| `011_block_log_risk_update.sql` | 다시 계산한 위험도의 처음 값 `bl_risk_*_first`, `bl_risk_updated_datetime` | 안전 |

- 모두 `ALTER TABLE ... ADD ... IF NOT EXISTS`라 MariaDB 10.0.2 이상이 필요하다. 개인 DB에서 각각 두 번 실행해 오류 없음을 확인했다
- 팀 저장소에 같은 번호의 다른 SQL이 생겼다면 번호를 다시 매긴다 (내용은 그대로)
- `002_gifticon.sql`은 다시 실행하면 시연 리워드가 중복으로 들어간다 (분리 전부터 있던 문제)

## 2. 설정값 (`extend/ipp.extend.php`)

| 상수 | 값 | 팀에 미치는 영향 |
|---|---|---|
| `IPP_USE_CLIENT_API` (새로 생김) | `true` | 외부 프로그램 API(`client.php`, `ext.php`) 전체 스위치 |
| `IPP_USE_EXTENSION` (뜻이 바뀜) | **`false`** | 예전에는 `ext.php` 전체 스위치였다. 이제는 `client: "extension"` 요청만 막는다. **확장 프로그램을 쓰는 팀원은 `true`로 바꿔야 한다** |
| `IPP_CLIENTS` | `['extension', 'desktop']` | 팀원 프로그램은 여기에 client 값을 추가해야 API를 부를 수 있다 (`bl_client`는 VARCHAR(10)) |
| `IPP_USE_RISK_MODEL`, `IPP_RISK_MODEL_FILE`, `IPP_RISK_LEVEL_MID`(0.3), `IPP_RISK_LEVEL_HIGH`(0.55), `IPP_RISK_REASON_MAX`(3) | 켜짐 | 결제 화면 `check`에 위험도 칸이 추가됨 (기존 칸은 그대로) |
| `IPP_RISK_SERVER` 등 5개 | `off` (환경변수 `IPP_RISK_SERVER=on`일 때만 on) | 예측 서버가 없어도 그대로 동작 |
| `IPP_USE_LLM` 등 5개 | `false` (환경변수 `IPP_USE_LLM=1`일 때만 true) | 통계 화면 AI 요약 버튼. 꺼져 있으면 화면 변화 없음 |

## 3. 의존성

| 구분 | 필요한 것 |
|---|---|
| PHP | 기존과 같음 + **curl 확장** (예측 서버를 부를 때만. 없으면 PHP 계산으로 자동 전환) |
| 데스크톱 (`desktop/requirements.txt`) | Python 3.13, easyocr(torch 포함), mss, numpy, keyboard, winrt-* (Windows 내장 OCR, 한국어 OCR 언어팩 필요) |
| AI (`ai/requirements.txt`) | fastapi 0.162.0, uvicorn 0.54.0, httpx 0.28.1, anthropic 2.8.0, scikit-learn, pandas, numpy, matplotlib, PyMySQL |
| 모델 파일 (Git에 포함) | `ipp/model/risk_model.json` (위험도, 서버 PHP·예측 서버 공용), `desktop/impulse_guard/models/screen_classifier.json` (화면 분류, 921KB) |
| Git 제외 (각자 만듦) | `desktop/local_config.json`(서버 주소, 토큰), `data/dbconfig.php` |

## 4. 바뀐 API (`docs/API.md`)

기존 칸의 이름과 뜻은 바꾸지 않고 칸을 더했다.

| API | 변경 |
|---|---|
| `POST /ipp/api/client.php` (새로 생김) | 토큰 인증 외부 프로그램 API. `ext.php`는 예전 주소라 같은 동작으로 남겨 둠. 요청에 `client` 필수 |
| `check` | 요청 `features`(숫자 5개, 선택), `is_checkout`, `orig_price`, `discount_rate`, `log`. 응답 `risk`, `risk_level`, `risk_message`, `risk_reasons`, `risk_show_reasons`, `risk_model`, `risk_source`, `event`, `bl_id` |
| `decide` (새 action) | 팝업 결정 기록 (`buy`, `giveup`, `hold`, `close`) |
| `amount` (새 action) | 나중에 읽은 결제 금액 채우기 + 위험도 다시 계산 |
| `cooldown`, `giveup` | `bl_id`를 함께 받아 기록과 연결 |
| `POST /ipp/api/setting.php` | `block_all`, `regen_token`, `revoke_token` action |
| `POST /ipp/api/report.php` (새로 생김) | AI 주간 요약 (`IPP_USE_LLM`) |

## 5. 팀원 코드와 겹치는 부분 (분리 시점 기준)

| 위치 | 상태 |
|---|---|
| 그누보드 기본 파일 | **바꾸지 않음** (분리 이후 `ipp/`, `extend/ipp.extend.php`, `ai/`, `desktop/`, `scripts/`, `extension/`, 문서 밖의 변경 없음) |
| `desktop/original/shopping_detector.py` (팀원 원본 OCR 감지) | **바꾸지 않음** (추가한 커밋 `714ce8f` 하나뿐). 고친 내용은 `desktop/impulse_guard/`의 새 모듈에 있음 |
| `ipp/api/ext.php` | `client.php`로 옮기고 같은 동작으로 남김 (B-2) |
| `ipp/lib/setting.lib.php` | 토큰 발급·해제, 감지 기록(결정, 금액 채우기, 쿨다운 연결), 전체 차단 (B-2~B-5) |
| `ipp/lib/bank.lib.php` | 결제 화면 `checkout` 이유 추가 (B-3, B-4) |
| `ipp/lib/cooldown.lib.php`, `reward.lib.php`, `ipp/api/reward.php` | 출처(`cd_client`) 구분, 작은 정리 (B-2) |
| `ipp/lib/stats.lib.php`, `ipp/stats.php` | 사이트 모름 표시, 최근 7일 결제 화면 팝업 칸, AI 요약 칸 |
| `ipp/setting.php`, `ipp/api/setting.php` | 외부 프로그램 토큰 발급, 전체 차단 토글 |
| `extension/content.js` | 전체 차단 설정을 따르도록 한 줄 (보류 중) |
| `ai/` | 4-1(`features.py`, `data/`)은 그대로 두고 `screen/`, `risk/`, `serve/`를 추가 |
| 새 파일 | `ipp/lib/risk.lib.php`, `report.lib.php`, `ipp/api/client.php`, `report.php`, `ipp/model/`, `ipp/tests/`, `desktop/impulse_guard/`, `scripts/` |

## 6. 합치는 방법 (제안)

1. 팀 저장소에 `feature/eunji-desktop` 같은 브랜치를 만들어 이 저장소의 main을 올리고 PR로 합친다 (팀 main에 바로 넣지 않음)
2. SQL 006~011을 팀 DB에 실행 (번호가 겹치면 다시 매김)
3. 확장 프로그램을 계속 쓰는 팀원이 있으면 `IPP_USE_EXTENSION`을 `true`로
4. 테스트: `php ipp/tests/risk_test.php`, `php ipp/tests/report_test.php`, 데스크톱 `python -m unittest discover -s tests`, ai `python -m unittest serve.test_serve serve.test_message risk.test_risk`
