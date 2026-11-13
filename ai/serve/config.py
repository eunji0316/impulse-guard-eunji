"""예측 서버 설정

- 받는 주소는 127.0.0.1로 고정한다 (같은 PC의 그누보드 서버만 부른다). 환경변수로도 바꾸지 않는다
- 포트와 모델 파일 위치만 환경변수로 바꿀 수 있다
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))   # 저장소 루트

HOST = '127.0.0.1'
PORT = int(os.environ.get('IPP_AI_PORT', '8002'))

# 요청을 받는 상대 주소 (127.0.0.1에서만 받지만, 앞에 프록시를 두는 실수를 막으려고 한 번 더 확인)
LOCAL_CLIENTS = frozenset({'127.0.0.1', '::1'})

# C-2 위험도 모델. 서버 PHP(IPP_RISK_MODEL_FILE)와 같은 파일을 읽는다
RISK_MODEL_FILE = os.environ.get('IPP_AI_RISK_MODEL', os.path.join(ROOT, 'ipp', 'model', 'risk_model.json'))
