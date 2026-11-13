# impulse-guard-eunji

영카트5(그누보드 5.6.43) 기반 충동구매 방지 서비스의 개인 프로젝트입니다.
화면 OCR로 쇼핑 화면을 감지하는 **데스크톱 프로그램**과, 포인트/쿨다운/기프티콘/통계를 맡는 **그누보드 서버와 웹**으로 이루어져 있습니다.

- 기능 정리: [docs/FEATURES.md](docs/FEATURES.md)
- 서버 API 명세: [docs/API.md](docs/API.md)
- 진행 상황: [docs/PROGRESS.md](docs/PROGRESS.md)
- AI 파이프라인 (발표용): [docs/AI.md](docs/AI.md)
- 개인정보 처리 원칙: [docs/PRIVACY.md](docs/PRIVACY.md)
- 알려진 한계: [docs/LIMITATIONS.md](docs/LIMITATIONS.md)
- 시연 시나리오: [docs/DEMO.md](docs/DEMO.md)
- 팀 저장소에 합칠 때: [docs/INTEGRATION.md](docs/INTEGRATION.md)

## 빠른 시작 (세팅이 끝난 뒤)

아래 '처음 세팅하기'와 '데스크톱 감지 프로그램 실행'을 한 번 마쳤다면, 저장소 루트의 PowerShell에서 세 프로그램을 한 번에 켜고 끕니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1          # 웹 서버(8001), 예측 서버(8002), 데스크톱을 새 창으로
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1           # start.ps1이 켠 것만 끔
```

| 옵션 | 뜻 |
|---|---|
| `-Demo` | 시연 모드: 위험도를 예측 서버로 계산, 데스크톱은 데모 회원으로 연결 (먼저 `php scripts\demo_seed.php add`) |
| `-Demo -Llm` | + 통계 화면 AI 요약 버튼 (API 키는 아래 'AI 주간 리포트 요약 켜기') |
| `-NoAi`, `-NoDesktop` | 예측 서버 또는 데스크톱을 켜지 않음 |
| `-DryRun` | 실행할 명령만 보여 줌 |

- 이미 켜져 있는 서버(포트 사용 중)는 다시 켜지 않습니다. 시연 모드 값은 스크립트가 켠 웹 서버에만 환경변수로 넘기고 `extend/ipp.extend.php`는 바꾸지 않습니다
- 로그인하면 맨 위 줄(FAQ 앞)과 쇼핑몰 마이페이지에 **통계 · 포인트·리워드 · 담아두기 · 차단 설정** 메뉴가 생깁니다 (`extend/ipp.menu.extend.php`)
- 데모 회원: `php scripts\demo_seed.php add | remove | status` (아이디 `demo`, 비밀번호 `demo1234`, 최근 2주 기록). 시연 순서는 [docs/DEMO.md](docs/DEMO.md)

## 폴더 구조

| 폴더 | 내용 |
|---|---|
| `ipp/` | 서버와 웹 코드 (화면, API, lib, SQL) |
| `extend/ipp.extend.php` | 설정값과 기능 스위치 |
| `desktop/` | 데스크톱 감지 프로그램 (Python). `desktop/original/`은 팀원 원본 코드로 수정하지 않습니다 |
| `ai/` | AI 모델 (화면 분류 `screen/`, 위험도 `risk/`, 예측 서버 `serve/`) |
| `scripts/` | 한 번에 켜기·끄기(`start.ps1`, `stop.ps1`), 데모 회원 시드(`demo_seed.php`) |
| `extension/` | 크롬 확장 프로그램 (**보류**, 코드만 보존) |

## 개발 환경

- PHP 8.x
- MariaDB
- Python 3.13 (데스크톱 프로그램, AI)
- Git

## 처음 세팅하기 (서버와 웹)

### 1. 저장소 내려받기

```
git clone https://github.com/eunji0316/impulse-guard-eunji.git
cd impulse-guard-eunji
```

### 2. data 폴더 만들기

`data/` 폴더는 DB 비밀번호(`dbconfig.php`), 세션, 캐시, 업로드 파일이 들어 있어서 저장소에 포함하지 않습니다.
그누보드를 설치하려면 이 폴더가 있어야 하므로 직접 만들어 주세요.

```
mkdir data
```

### 3. DB 만들기

MariaDB에서 개인 프로젝트용 DB를 만듭니다.

```sql
CREATE DATABASE impulse_eunji_db DEFAULT CHARACTER SET utf8mb4;
```

#### 팀 공용 DB(`youngcart_db`)를 복사해서 쓰는 경우 (HeidiSQL)

이미 설치된 팀 공용 DB의 데이터를 그대로 가져오는 방법입니다. 이 경우 5단계 그누보드 설치는 건너뜁니다.

1. 위의 `CREATE DATABASE impulse_eunji_db ...`로 빈 DB를 만듭니다.
2. HeidiSQL에서 `youngcart_db`를 오른쪽 클릭 → **데이터베이스를 SQL로 내보내기**
3. 내보내기 설정
   - 데이터베이스: **생성 해제** (`impulse_eunji_db`를 이미 만들었으므로)
   - 테이블: **생성** 체크
   - 데이터: **INSERT**
   - 출력: **데이터베이스** → `impulse_eunji_db`
4. 내보내기를 실행하면 테이블과 데이터가 `impulse_eunji_db`로 복사됩니다.
5. `data/dbconfig.php`의 DB 이름을 바꿉니다.

   ```php
   define('G5_MYSQL_DB', 'impulse_eunji_db');
   ```

> **참고: 명령어로 복사하기 (mysqldump)**
>
> HeidiSQL이 없으면 명령어로도 복사할 수 있습니다. 위 1, 5단계는 같습니다.
>
> ```
> mysqldump -u root -p youngcart_db > youngcart_db.sql
> mysql -u root -p impulse_eunji_db < youngcart_db.sql
> ```

### 4. 서버 실행

```
php -S localhost:8001
```

### 5. 그누보드 설치

브라우저에서 `http://localhost:8001`에 접속하면 설치 화면이 나옵니다.

- DB 정보: DB 이름 `impulse_eunji_db`, 본인 계정, 비밀번호
- 테이블 접두사: `g5_` (변경하지 말 것)
- 쇼핑몰 테이블 설치: 체크
- 관리자 계정: 자유롭게

### 6. 커스텀 테이블 추가

`ipp/sql/` 폴더의 SQL 파일을 번호 순서대로 실행합니다. 팀 공용 DB를 복사해 왔다면 복사 이후에 추가된 번호만 실행합니다 (예: B-2의 `006_client_source.sql`, B-3의 `007_popup_decision.sql`, `008_block_all.sql`, B-5의 `009_block_log_price_fill.sql`, C-2의 `010_block_log_risk.sql`, `011_block_log_risk_update.sql`). 모두 다시 실행해도 안전합니다 (002 제외, [docs/INTEGRATION.md](docs/INTEGRATION.md)).

## 데스크톱 감지 프로그램 실행 (Windows)

자세한 내용은 [desktop/README.md](desktop/README.md)를 참고하세요.

```powershell
cd desktop
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회 (PyTorch 포함이라 오래 걸림)
.\.venv\Scripts\python.exe -m impulse_guard.main                 # 감지 프로그램 (서버 연동)
.\.venv\Scripts\python.exe original\shopping_detector.py         # 팀원 원본 (참고용)
```

- 첫 실행 때 OCR 모델을 내려받느라 몇 분 걸립니다.
- 쇼핑몰 화면을 주 모니터에 띄우고 `F4`를 누르면 분석 결과가 콘솔에 나옵니다. 종료는 `Ctrl + C`
- `F4`에 반응이 없으면 터미널을 관리자 권한으로 실행합니다.

### 서버와 연결하기 (API 토큰)

데스크톱 프로그램은 로그인 대신 회원별 **API 토큰**으로 서버에 연결합니다. 토큰이 없거나 서버가 꺼져 있으면 오프라인 모드로 감지만 합니다.

1. 서버를 켭니다: `php -S localhost:8001`
2. 브라우저에서 `http://localhost:8001`에 로그인하고 `http://localhost:8001/ipp/setting.php`를 엽니다.
3. **외부 프로그램 연결 (데스크톱 감지 프로그램)** 에서 **발급**을 누릅니다. 서버 주소와 토큰이 **한 번만** 보이니 바로 복사합니다. 잃어버리면 **재발급**합니다 (이전 토큰은 무효가 됩니다).
4. `desktop/local_config.example.json`을 복사해 `desktop/local_config.json`을 만들고 값을 넣습니다. 이 파일은 Git에 올라가지 않습니다.

   ```json
   {
     "server": "http://localhost:8001",
     "token": "발급받은 64자리 토큰",
     "timeout_sec": 2
   }
   ```

5. `.\.venv\Scripts\python.exe -m impulse_guard.main`을 실행하면 `[서버] 연결됨: ... / 닉네임(아이디) / 포인트`가 나옵니다.

API 명세는 [docs/API.md](docs/API.md)를 참고하세요.

## 예측 서버 켜기 (시연용, 선택)

충동구매 위험도는 기본으로 그누보드 서버(PHP)가 계산합니다. 시연에서 "AI 예측 서버"를 보여 줄 때만 예측 서버(FastAPI)를 켭니다.
켜지 않아도, 켰다가 꺼져도 팝업은 똑같이 뜹니다 (자세한 내용은 [ai/serve/README.md](ai/serve/README.md)).

1. 예측 서버를 켭니다 (새 터미널, 끌 때는 `Ctrl + C`)

   ```powershell
   cd ai
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회
   .\.venv\Scripts\python.exe -m serve                              # http://127.0.0.1:8002
   ```

2. 웹 서버가 예측 서버를 쓰게 합니다: `scripts\start.ps1 -Demo`로 켜면 됩니다 (웹 서버에 환경변수 `IPP_RISK_SERVER=on`을 넘김). 직접 켠 서버라면 그 터미널에서 `$env:IPP_RISK_SERVER = "on"` 뒤 `php -S localhost:8001`. `extend/ipp.extend.php`는 바꾸지 않습니다
3. 확인
   - 브라우저에서 `http://127.0.0.1:8002/health` → 모델 버전이 보이면 정상. `http://127.0.0.1:8002/docs`는 API 화면 (발표용)
   - 저장소 루트에서 `php ipp/tests/risk_server_test.php` → `실패 0개`면 PHP 계산과 결과가 같습니다
   - 결제 화면 `check` 응답의 `risk_source`가 `server`면 예측 서버가 계산한 것, `php`면 서버 PHP가 계산한 것입니다
4. 시연이 끝나면 환경변수 없이 웹 서버를 다시 켭니다 (`stop.ps1` 뒤 `start.ps1`). 환경변수가 없으면 `off`입니다

- 예측 서버가 꺼져 있거나 0.3초 안에 답하지 않으면 자동으로 PHP가 계산하고, 그 뒤 60초 동안은 예측 서버를 부르지 않습니다 (`data/ipp_risk_server_down.txt`에 실패 시각).
  예측 서버를 다시 켜면 60초 뒤부터 다시 씁니다
- 예측 서버에는 위험도 계산에 필요한 숫자 13개만 보냅니다. 회원 아이디, 상품명, 쇼핑몰은 보내지 않습니다

## AI 주간 리포트 요약 켜기 (선택)

통계 화면(`/ipp/stats.php`)에 **AI 요약 보기** 버튼을 띄워, 이번 주와 지난주 기록을 Claude API가 짧게 요약하게 합니다. 기본은 꺼져 있고, 꺼져 있으면 통계 화면은 지금 그대로입니다.

1. [Claude Console](https://console.anthropic.com)에서 API 키를 만듭니다. 사용 한도(Limits)도 걸어 두는 것을 권합니다
2. 예측 서버를 켤 때 키를 환경변수로 넣습니다. 키는 이 터미널에만 두고 파일이나 Git에는 적지 않습니다

   ```powershell
   cd ai
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회 (anthropic 포함)
   $env:ANTHROPIC_API_KEY = "sk-ant-..."                          # 이 터미널에서만
   .\.venv\Scripts\python.exe -m serve                              # '주간 리포트 요약: claude-haiku-5-5, 하루 50번'이 보이면 정상
   ```

   `ant auth login`으로 로그인해 두었다면 키 대신 `$env:IPP_AI_LLM_PROFILE = "1"`을 넣습니다
3. AI 요약 버튼을 켭니다: `scripts\start.ps1 -Demo -Llm`으로 켜면 됩니다 (웹 서버에 환경변수 `IPP_USE_LLM=1`을 넘김). 직접 켠 서버라면 그 터미널에서 `$env:IPP_USE_LLM = "1"` 뒤 `php -S localhost:8001`
4. 확인
   - 브라우저에서 `http://127.0.0.1:8002/health` → `"message": {"model": "claude-haiku-5-5", ...}` (키가 없으면 `null`)
   - 로그인 → 통계 화면 → **AI 요약 보기** → 제목, 요약, 제안 한 줄이 보입니다. 기록이 없으면 '최근 2주 동안 쇼핑 기록이 없어요.'
5. 끄려면 환경변수 없이 웹 서버를 다시 켭니다 (`stop.ps1` 뒤 `start.ps1`)

- 보내는 값은 집계 숫자와 위험도 이유 코드뿐입니다. 회원 아이디, 상품명, 주소, 쇼핑몰 이름은 보내지 않고(쇼핑몰은 개수만), 요약은 저장하지 않습니다
- 요약 한 번에 1원 안팎(Haiku 5.5)이고, 예측 서버가 하루 50번까지만 부릅니다(`IPP_AI_LLM_DAILY_LIMIT`). 같은 기록이면 7일 동안 다시 부르지 않습니다
- `php -S`는 요청을 하나씩 처리해서, 요약을 기다리는 몇 초 동안(최대 10초) 데스크톱의 감지 요청도 기다립니다. 그래서 버튼을 눌렀을 때만 부릅니다. 쇼핑 감지를 시연하는 중에는 누르지 않는 것이 좋습니다

## 작업 규칙

### 폴더

- 서버와 웹 코드는 `ipp/` 폴더에 둡니다.
- `desktop/original/`(팀원 원본 코드)은 수정하지 않습니다.
- 그누보드 기본 파일은 수정하지 않습니다.
- `extend/`, `adm/`에 추가하는 파일은 이름 앞에 `ipp`를 붙입니다.

### 브랜치

- `main`: 시연 가능한 안정 버전
- `dev`: 통합 개발 브랜치
- `feature/기능명`: 개인 작업 브랜치 (`dev`에서 생성)

작업이 끝나면 `feature`에서 `dev`로 PR을 올립니다.

### DB 변경

테이블 구조를 바꿀 때는 기존 SQL 파일을 고치지 말고, 다음 번호로 새 파일을 추가합니다.
예: `002_add_column.sql`