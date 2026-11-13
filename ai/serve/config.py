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

# 5 LLM 주간 리포트 요약 (message_api.py)
# 키는 이 프로세스의 환경변수 ANTHROPIC_API_KEY(또는 ANTHROPIC_AUTH_TOKEN)에만 둔다. PHP, local_config.json, Git에는 두지 않는다.
# `ant auth login` 프로필을 쓰려면 IPP_AI_LLM_PROFILE=1 (환경변수 키 없이도 서비스를 켠다)
LLM_MODEL       = os.environ.get('IPP_AI_LLM_MODEL', 'claude-haiku-5-5')
LLM_TIMEOUT     = float(os.environ.get('IPP_AI_LLM_TIMEOUT', '12'))     # 초. API 한 번 기다리는 시간 (재시도 1번)
LLM_DAILY_LIMIT = int(os.environ.get('IPP_AI_LLM_DAILY_LIMIT', '50'))   # 하루 API 호출 상한 (캐시 적중은 세지 않음)
LLM_CACHE_SEC   = 7 * 86400                                             # 같은 입력이면 이 시간 동안 다시 만들지 않음 (메모리)


def llm_credentials():
    """API 자격 증명이 있어 보이면 그 출처, 없으면 None"""
    if os.environ.get('ANTHROPIC_API_KEY'):
        return 'api_key'
    if os.environ.get('ANTHROPIC_AUTH_TOKEN'):
        return 'auth_token'
    if os.environ.get('IPP_AI_LLM_PROFILE') == '1':
        return 'profile'
    return None
