# 예측 서버 (C-3, FastAPI)

C-2 위험도 모델(`ipp/model/risk_model.json`)을 API로 제공한다. 그누보드 서버의 결제 화면 `check`가 이 서버에 확률과 이유를 묻고,
서버가 꺼져 있거나 실패하면 지금처럼 PHP가 직접 계산한다. 그래서 켜든 끄든 데스크톱이 받는 응답은 같다.

```
데스크톱 ──check──▶ 그누보드(PHP) ──원시 값 13개──▶ 예측 서버 /risk/predict ──▶ 확률, 이유 코드
                     │  DB 과거 기록 조회, 단계·문구·이유 문장, 기록       (실패하면 PHP가 같은 JSON으로 계산)
```

## 왜 이렇게 나눴나

- 모델이 로지스틱 회귀라 PHP로도 같은 값을 낼 수 있다. 그래서 예측 서버는 **꺼져 있어도 되는 부품**으로 두고, 기본값은 꺼짐(`IPP_RISK_SERVER = 'off'`)이다
- 계산은 기준 구현 `ai/risk/model.py`를 그대로 불러 쓴다. 학습 코드와 서비스 코드가 같은 계산 규칙을 쓴다
- 단계 기준(0.3/0.55), 문구, 이유 문장, DB 조회는 PHP에만 둔다 (기준값이 두 곳에 생기지 않게)
- 5단계 LLM 문구, PHP로 옮기기 어려운 모델(부스팅 등)도 이 서버에 서비스로 붙인다

## 켜기와 끄기

```powershell
# ai 폴더에서 (처음 한 번: .venv\Scripts\python.exe -m pip install -r requirements.txt)
.venv\Scripts\python.exe -m serve        # http://127.0.0.1:8002, Ctrl+C로 끔
```

그누보드가 이 서버를 쓰게 하려면 `extend/ipp.extend.php`에서 `IPP_RISK_SERVER`를 `'on'`으로 바꾼다.

| 설정 (extend/ipp.extend.php) | 기본값 | 뜻 |
|---|---|---|
| `IPP_RISK_SERVER` | `'off'` | `'on'`이면 예측 서버에 묻는다 |
| `IPP_RISK_SERVER_URL` | `http://127.0.0.1:8002` | 127.0.0.1, localhost, [::1]만 허용. 다른 주소면 부르지 않는다 |
| `IPP_RISK_SERVER_TIMEOUT` | 0.3 | 초. 이 시간 안에 답이 없으면 PHP 계산 |
| `IPP_RISK_SERVER_SKIP_SEC` | 60 | 한 번 실패하면 이 시간 동안 예측 서버를 부르지 않는다 |
| `IPP_RISK_SERVER_DOWN_FILE` | `data/ipp_risk_server_down.txt` | 마지막 실패 시각 (php -S는 요청끼리 메모리를 나누지 않아 파일로) |

예측 서버 쪽 환경변수: `IPP_AI_PORT`(기본 8002), `IPP_AI_RISK_MODEL`(기본 `ipp/model/risk_model.json`). 받는 주소는 127.0.0.1로 고정이다.

## 자동 전환 (PHP `ipp_risk_result`)

예측 서버 → PHP 계산 → 규칙 이유만(`risk: null`, 모델 파일이 없을 때) 순서. 아래 경우 PHP가 계산하고 응답의 `risk_source`가 `php`다.

- 연결 실패, 0.3초 초과, HTTP 200이 아님, JSON이 아님
- 확률이 0~1 밖이거나 숫자가 아님, 이유 코드가 모델에 없는 group, 이유 모양이 틀림
- **모델 버전이 PHP가 읽은 JSON 버전과 다름** (다른 모델로 계산한 값을 섞지 않는다)
- 위 실패 뒤 60초 안 (부르지 않음)

모델 파일을 바꾸면 예측 서버는 다음 요청에서 다시 읽는다 (수정 시각과 크기로 판단). 다시 읽기 전 짧은 순간 버전이 다르면 PHP 계산으로 넘어간다.

## API

| 주소 | 요청 | 응답 |
|---|---|---|
| `GET /health` | - | `{"services": {"risk": {"model": "20261113-synthetic", "format": "risk-logreg/1"}}}` (모델이 없으면 `"risk": null`) |
| `POST /risk/predict` | `{"raw": {"hour": 23, "amount": 89000, "discount_rate": null, ...}}` | `{"prob": 0.6979, "reasons": [["amount_ratio", 0.8123], ...], "model": "20261113-synthetic"}` |

- `raw` 칸은 `ai/risk/schema.py`의 원시 값 13개. 빠진 칸은 모름(null)
- 다른 칸, 문자열, true/false, NaN이면 422. 오류 응답에는 받은 값을 넣지 않고 칸 이름과 오류 종류만
- 127.0.0.1이 아닌 곳에서 온 요청은 403. 모델이 없거나 형식이 틀리면 503
- `/docs`에서 API 화면을 볼 수 있다 (발표용)

## 개인정보

- PHP는 원시 값 13개(숫자와 null)만 보낸다. 회원 아이디, 기록 번호, 쇼핑몰, 상품명, OCR 원문은 보내지 않는다 (`ipp_risk_server_body`)
- 예측 서버는 정해진 칸 밖을 받지 않고(422), 요청을 저장하거나 로그에 남기지 않는다 (uvicorn access log 끔, log_level warning)
- 127.0.0.1에서만 받는다

## 서비스 붙이는 방법 (5단계 LLM 문구 등)

1. `serve/message_api.py`에 `make_router(...)`를 만들어 `(APIRouter(prefix='/message'), 상태 함수)`를 돌려준다
2. 요청 본문은 `common.StrictBody`를 상속한다 (정해진 칸만, 숫자는 `common.Num`)
3. `app.py`의 `services`에 한 줄 더한다. `/health`에 자동으로 나온다
4. PHP 쪽은 `ipp_risk_predict_remote`처럼 시간 제한, 응답 확인, 실패하면 지금 방식(고정 문구), 60초 건너뛰기를 둔다

## 테스트

```powershell
# ai 폴더에서 (서버를 켜지 않아도 됨)
.venv\Scripts\python.exe -m unittest serve.test_serve risk.test_risk

# 저장소 루트에서 (서버를 켜 둔 상태): PHP 계산과 서버 결과 비교, 자동 전환, 입력 거부
php ipp/tests/risk_server_test.php
```

- `serve.test_serve` 11개: 모델 JSON 예시 32개가 `model.py`와 같음, 빠진 칸 = 모름, 다른 칸·문자열·true·NaN 거부, 오류에 입력을 되돌려 주지 않음, 로컬 전용, 모델 파일 바뀌면 다시 읽기, 모델 없음/깨짐 503
- `risk_server_test.php`: 예시 32 + 가상 데이터 2,000 + 무작위 1,000개(모름·경계·범위 밖)의 확률 차이 1e-9 미만, 이유 순서 같음, 기여 차이 1e-4 이하.
  `ipp_risk_result`의 단계·문구·이유 문장이 PHP와 같음, 버전 다름 → PHP, 60초 건너뛰기와 다시 연결, 다른 칸·문자열 422
- 서버 없이 되는 자동 전환 테스트(응답 확인, 주소 제한, 닫힌 포트 시간 제한, 60초 건너뛰기, 보내는 칸)는 `ipp/tests/risk_test.php`에 있다
