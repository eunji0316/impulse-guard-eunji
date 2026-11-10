# impulse-guard-eunji

영카트5(그누보드 5.6.43) 기반 충동구매 방지 서비스의 개인 프로젝트입니다.
화면 OCR로 쇼핑 화면을 감지하는 **데스크톱 프로그램**과, 포인트/쿨다운/기프티콘/통계를 맡는 **그누보드 서버와 웹**으로 이루어져 있습니다.

- 기능 정리: [docs/FEATURES.md](docs/FEATURES.md)
- 서버 API 명세: [docs/API.md](docs/API.md)
- 진행 상황: [docs/PROGRESS.md](docs/PROGRESS.md)

## 폴더 구조

| 폴더 | 내용 |
|---|---|
| `ipp/` | 서버와 웹 코드 (화면, API, lib, SQL) |
| `extend/ipp.extend.php` | 설정값과 기능 스위치 |
| `desktop/` | 데스크톱 감지 프로그램 (Python). `desktop/original/`은 팀원 원본 코드로 수정하지 않습니다 |
| `ai/` | 충동구매 위험도 모델 (데이터, 특성, 학습) |
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

팀 공용 DB(`youngcart_db`)의 데이터를 그대로 가져오려면 덤프해서 넣습니다. 이 경우 5단계 설치는 건너뛰고 `data/dbconfig.php`의 DB 이름만 `impulse_eunji_db`로 맞춥니다.

```
mysqldump -u root -p youngcart_db > youngcart_db.sql
mysql -u root -p impulse_eunji_db < youngcart_db.sql
```

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

`ipp/sql/` 폴더의 SQL 파일을 번호 순서대로 실행합니다.

## 데스크톱 감지 프로그램 실행 (Windows)

자세한 내용은 [desktop/README.md](desktop/README.md)를 참고하세요.

```powershell
cd desktop
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # 최초 1회 (PyTorch 포함이라 오래 걸림)
.\.venv\Scripts\python.exe original\shopping_detector.py         # 팀원 원본 실행
```

- 첫 실행 때 OCR 모델을 내려받느라 몇 분 걸립니다.
- 쇼핑몰 화면을 주 모니터에 띄우고 `F4`를 누르면 분석 결과가 콘솔에 나옵니다. 종료는 `Ctrl + C`
- `F4`에 반응이 없으면 터미널을 관리자 권한으로 실행합니다.
- 서버와 연결하는 기능은 B단계에서 추가합니다. 연결에는 웹의 `/ipp/setting.php`에서 발급한 API 토큰을 씁니다 ([docs/API.md](docs/API.md)).

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