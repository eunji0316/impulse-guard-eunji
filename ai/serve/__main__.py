"""예측 서버 실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m serve

127.0.0.1:8002에서만 받는다. 요청 로그(access log)는 남기지 않는다
"""
import uvicorn

from . import config
from .app import create_app


def main():
    app = create_app()
    print(f'예측 서버: http://{config.HOST}:{config.PORT}  (위험도 모델 {config.RISK_MODEL_FILE})')
    uvicorn.run(app, host=config.HOST, port=config.PORT, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
