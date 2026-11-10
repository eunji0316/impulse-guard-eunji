"""서버 통신 (B-2에서 채울 빈 틀)

그누보드 서버의 토큰 인증 API(ipp/api/ext.php)를 부른다. 명세는 docs/API.md.
서버 없이도 테스트할 수 있도록 실제 호출은 call() 하나로 감싸고, 나중에 mock으로 바꿀 수 있게 한다.
캡처 이미지는 보내지 않는다. 상품명, 가격 등 필요한 값만 보낸다.
"""

SERVER_URL = 'http://localhost:8001'
API_PATH = '/ipp/api/ext.php'


def call(action, data=None, token=''):
    """POST {SERVER_URL}{API_PATH}, JSON 본문 {"action": action, ...}, 헤더 Authorization: Bearer <token>"""
    raise NotImplementedError('서버 통신은 B-2에서 구현합니다.')


def me(token):
    """연결 확인 (action: me)"""
    return call('me', token=token)


def check(token, site, item_name, price):
    """상품 하나의 차단/충동구매 판단 (action: check)"""
    return call('check', {'site': site, 'item_name': item_name, 'price': price}, token)
