# impulse-guard

영카트5(그누보드 5.6.43) 기반 충동구매 방지 서비스

## 개발 환경

- PHP 8.x
- MariaDB
- Git

## 처음 세팅하기

### 1. 저장소 내려받기

```
git clone https://github.com/eunji0316/impulse-guard.git
cd impulse-guard
```

### 2. data 폴더 만들기

`data/` 폴더는 DB 비밀번호(`dbconfig.php`), 세션, 캐시, 업로드 파일이 들어 있어서 저장소에 포함하지 않습니다.
그누보드를 설치하려면 이 폴더가 있어야 하므로 직접 만들어 주세요.

```
mkdir data
```

### 3. DB 만들기

MariaDB에서 각자 사용할 DB를 만듭니다.

```sql
CREATE DATABASE youngcart_db DEFAULT CHARACTER SET utf8mb4;
```

### 4. 서버 실행

```
php -S localhost:8000
```

### 5. 그누보드 설치

브라우저에서 `http://localhost:8000`에 접속하면 설치 화면이 나옵니다.

- DB 정보: 3단계에서 만든 DB 이름, 본인 계정, 비밀번호
- 테이블 접두사: `g5_` (변경하지 말 것)
- 쇼핑몰 테이블 설치: 체크
- 관리자 계정: 각자 자유롭게

### 6. 커스텀 테이블 추가

`ipp/sql/` 폴더의 SQL 파일을 번호 순서대로 실행합니다.

## 작업 규칙

### 폴더

- 우리가 만드는 코드는 `ipp/` 폴더에 둡니다.
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