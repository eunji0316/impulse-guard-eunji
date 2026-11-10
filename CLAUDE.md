# impulse-guard-eunji 프로젝트 규칙
- 영카트5(그누보드 5.6.43) 기반 충동구매 방지 서비스의 개인 프로젝트 (팀 공용 impulse-guard에서 분리)
- 중심: 화면 OCR로 쇼핑 화면을 감지하는 데스크톱 프로그램 + 그누보드 서버/웹. 기능 목록은 docs/FEATURES.md, API는 docs/API.md
- 로컬 서버: php -S localhost:8001, DB: MariaDB impulse_eunji_db

## 폴더
- ipp/: 서버와 웹 코드 (API, lib, sql)
- desktop/: 데스크톱 감지 프로그램 (Python, 가상환경 desktop/.venv)
- desktop/original/: 팀원이 만든 원본 OCR 감지 코드. 절대 수정하지 않는다. 고칠 내용은 desktop/의 새 모듈에 작성한다.
- ai/: 충동구매 위험도 모델 (데이터, 특성, 학습)
- extension/: 크롬 확장 프로그램. 보류 중이며 코드는 지우지 않는다. 서버의 토큰 API(ipp/api/ext.php)는 데스크톱이 재사용하므로 유지한다.

## 규칙
- 그누보드 기본 파일은 수정하지 않는다.
- extend/, adm/에 추가하는 파일은 이름 앞에 ipp를 붙인다.
- 설정값과 기능 스위치는 extend/ipp.extend.php에 상수로 둔다.
- 포인트 지급은 반드시 ipp_give_point()를 거친다.
- 외부 API(은행, 기프티콘)는 lib 파일의 함수 하나로 감싸 mock으로 만든다.
- DB 변경은 ipp/sql/에 번호를 붙인 새 SQL 파일로 추가한다.
- 서버 API를 바꾸면 docs/API.md도 같이 고친다.
- data/ 폴더와 .venv/는 Git에 올리지 않는다.
- 브랜치: main(안정), dev(통합), feature/기능명
- 설명과 주석은 한국어로 작성한다.
