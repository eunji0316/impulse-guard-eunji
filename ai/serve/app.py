"""예측 서버 앱 조립

서비스마다 (라우터, 상태 함수)를 만들어 붙인다.
- risk: C-2 위험도 (risk_api.py)
- message: 5 LLM 주간 리포트 요약 (message_api.py). 키가 없으면 /health에 null, 요청은 503
새 서비스는 make_router()를 만들고 아래 services에 한 줄 더한다 (입력은 common.StrictBody 상속).
"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import config, message_api, risk_api
from .common import local_only, validation_error


def create_app(risk_model_file=None, message_service=None):
    app = FastAPI(title='impulse-guard 예측 서버', version='1')
    app.middleware('http')(local_only)
    app.add_exception_handler(RequestValidationError, validation_error)

    services = {
        'risk': risk_api.make_router(risk_model_file or config.RISK_MODEL_FILE),
        'message': message_api.make_router(message_service),
    }
    for router, _ in services.values():
        app.include_router(router)

    @app.get('/health')
    def health():
        """서비스별 상태. 쓸 수 없는 서비스는 null"""
        return {'services': {name: h() for name, (_, h) in services.items()}}

    return app
