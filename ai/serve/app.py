"""예측 서버 앱 조립

서비스마다 (라우터, 상태 함수)를 만들어 붙인다. 지금은 위험도(risk)뿐이다.
5단계 LLM 문구는 serve/message_api.py에 make_router()를 만들고 아래 services에 한 줄 더하면 된다
(입력은 common.StrictBody 상속, 주소 앞부분 /message, 실패하면 서버 PHP가 지금 문구를 쓴다).
"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import config, risk_api
from .common import local_only, validation_error


def create_app(risk_model_file=None):
    app = FastAPI(title='impulse-guard 예측 서버', version='1')
    app.middleware('http')(local_only)
    app.add_exception_handler(RequestValidationError, validation_error)

    services = {
        'risk': risk_api.make_router(risk_model_file or config.RISK_MODEL_FILE),
    }
    for router, _ in services.values():
        app.include_router(router)

    @app.get('/health')
    def health():
        """서비스별 상태. 쓸 수 없는 서비스는 null"""
        return {'services': {name: h() for name, (_, h) in services.items()}}

    return app
