"""서버 통신 테스트 (실제 서버 없이)

- 가짜 transport로 응답을 정해 두고 온라인/오프라인 전환, 401, 다시 연결, 설정 캐시를 확인한다
- 시간 초과는 일부러 늦게 응답하는 로컬 HTTP 서버로 실제 urllib 호출을 확인한다
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import http.server
import json
import os
import socket
import tempfile
import threading
import time
import unittest

import cache  # noqa: F401  (sys.path에 desktop 폴더 추가)
from impulse_guard import config, server_client
from impulse_guard.server_client import Client

ME = {'ok': True, 'mb_id': 'test01', 'nick': '테스트', 'point': 1250, 'client': 'desktop'}
SETTING = {'ok': True, 'is_blocking': True, 'block_until': '2026-11-11 23:59:59', 'block_remain': 3600,
           'sites': [{'code': 'coupang', 'name': '쿠팡', 'domain': 'coupang.com', 'on': True}],
           'keywords': ['특가'], 'risk_alert': True}
CHECK = {'ok': True, 'is_blocking': False, 'is_impulse': 1, 'keyword': '', 'point': 496, 'point2': 992, 'bl_id': 7}


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeServer:
    """transport 대신 쓰는 가짜 서버. responses[action] = (상태, 응답) 또는 예외"""
    def __init__(self, **responses):
        self.responses = {'me': (200, ME), 'setting': (200, SETTING), 'check': (200, CHECK), **responses}
        self.calls = []

    def __call__(self, url, body, token, timeout):
        self.calls.append(body)
        r = self.responses[body['action']]
        if isinstance(r, Exception):
            raise r
        return r

    def count(self, action):
        return sum(1 for b in self.calls if b['action'] == action)


def make(fake, token='a' * 64):
    clock = FakeClock()
    return Client('http://localhost:8001', token, 2.0, transport=fake, clock=clock), clock


class TestConfig(unittest.TestCase):
    def test_missing_file_is_offline(self):
        c = Client.from_config(os.path.join(tempfile.gettempdir(), 'ipp_no_such_config.json'), transport=FakeServer())
        self.assertEqual(c.token, '')
        r = c.connect()
        self.assertTrue(r.offline)
        self.assertFalse(c.online)
        self.assertIn('파일이 없습니다', c.last_error)

    def test_read_file(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({'server': 'http://example.test:8001/', 'token': ' abc ', 'timeout_sec': 1.5}, f)
        try:
            conf = server_client.load_config(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual((conf['server'], conf['token'], conf['timeout_sec']), ('http://example.test:8001', 'abc', 1.5))

    def test_example_file(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        conf = server_client.load_config(os.path.join(here, 'local_config.example.json'))
        self.assertEqual(conf['server'], config.DEFAULT_SERVER)
        self.assertEqual(conf['token'], '')
        self.assertEqual(conf['error'], '')


class TestConnection(unittest.TestCase):
    def test_connect_ok(self):
        fake = FakeServer()
        c, _ = make(fake)
        self.assertTrue(c.connect().ok)
        self.assertTrue(c.online)
        self.assertEqual(c.member['nick'], '테스트')
        self.assertEqual(fake.calls[0], {'client': 'desktop', 'action': 'me'})

    def test_no_token_never_calls(self):
        fake = FakeServer()
        c, _ = make(fake, token='')
        self.assertTrue(c.connect().offline)
        self.assertFalse(c.ensure_online())
        self.assertTrue(c.check('', '상품', 1000).offline)
        self.assertEqual(fake.calls, [])

    def test_connection_error_then_reconnect_after_60s(self):
        fake = FakeServer(me=ConnectionRefusedError('거부'))
        c, clock = make(fake)
        self.assertTrue(c.connect().offline)
        self.assertFalse(c.online)
        # 60초가 지나기 전에는 다시 시도하지 않는다 (F4마다 2초씩 기다리지 않게)
        clock.t += 30
        self.assertTrue(c.check('', '상품', 1000).offline)
        self.assertEqual(fake.count('me'), 1)
        # 서버가 켜지고 60초가 지나면 다시 연결
        fake.responses['me'] = (200, ME)
        clock.t += 31
        r = c.check('', '상품', 1000)
        self.assertTrue(r.ok)
        self.assertEqual(fake.count('me'), 2)
        self.assertTrue(c.online)

    def test_401_stops_retrying(self):
        fake = FakeServer(me=(401, {'ok': False, 'msg': '토큰이 올바르지 않습니다.'}))
        c, clock = make(fake)
        c.connect()
        self.assertTrue(c.auth_failed)
        clock.t += 1000
        self.assertFalse(c.ensure_online())
        self.assertEqual(fake.count('me'), 1)

    def test_server_error_is_not_exception(self):
        fake = FakeServer(check=(400, {'ok': False, 'msg': '알 수 없는 사이트입니다.'}))
        c, _ = make(fake)
        c.connect()
        r = c.check('foo', '상품', 1000)
        self.assertFalse(r.ok)
        self.assertFalse(r.offline)
        self.assertEqual((r.status, r.msg), (400, '알 수 없는 사이트입니다.'))
        self.assertTrue(c.online)          # 입력 오류는 연결이 끊긴 게 아님

    def test_broken_json_is_offline(self):
        fake = FakeServer(check=ValueError('Expecting value'))
        c, _ = make(fake)
        c.connect()
        self.assertTrue(c.check('', '상품', 1000).offline)

    def test_check_body(self):
        fake = FakeServer()
        c, _ = make(fake)
        c.connect()
        r = c.check('coupang', '패딩', 49600, 119000, 58, True, page='product')
        self.assertTrue(r.ok)
        self.assertEqual(fake.calls[-1], {'client': 'desktop', 'action': 'check', 'site': 'coupang', 'item_name': '패딩',
                                          'price': 49600, 'orig_price': 119000, 'discount_rate': 58,
                                          'is_checkout': True, 'page': 'product', 'log': True})


class TestSettingCache(unittest.TestCase):
    def test_cache_5_minutes(self):
        fake = FakeServer()
        c, clock = make(fake)
        c.connect()
        self.assertTrue(c.get_setting()['is_blocking'])
        clock.t += config.SETTING_CACHE_SEC - 1
        c.get_setting()
        self.assertEqual(fake.count('setting'), 1)      # 5분 안에는 캐시
        clock.t += 2
        c.get_setting()
        self.assertEqual(fake.count('setting'), 2)      # 5분이 지나면 다시 받는다
        c.get_setting(force=True)
        self.assertEqual(fake.count('setting'), 3)

    def test_block_remain_counts_down(self):
        c, clock = make(FakeServer())
        c.connect()
        c.get_setting()
        self.assertEqual(c.block_remain(), 3600)
        clock.t += 100
        self.assertEqual(c.block_remain(), 3500)
        clock.t += 5000
        self.assertEqual(c.block_remain(), 0)

    def test_keep_old_cache_when_offline(self):
        fake = FakeServer()
        c, clock = make(fake)
        c.connect()
        c.get_setting()
        fake.responses['setting'] = TimeoutError('timed out')
        clock.t += config.SETTING_CACHE_SEC + 1
        self.assertEqual(c.get_setting()['keywords'], ['특가'])   # 실패하면 예전 캐시
        self.assertFalse(c.online)

    def test_site_hints(self):
        c, _ = make(FakeServer())
        c.connect()
        c.get_setting()
        self.assertEqual(c.site_hints(), {'coupang': ['쿠팡']})


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    delay = 3.0

    def do_POST(self):
        time.sleep(self.delay)
        body = json.dumps(ME).encode()
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass                               # 클라이언트가 먼저 끊음

    def log_message(self, *args):
        pass


class TestRealHttp(unittest.TestCase):
    """실제 urllib 호출: 늦게 응답하는 서버, 아무도 없는 포트"""
    @classmethod
    def setUpClass(cls):
        cls.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _SlowHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.httpd.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_timeout_2s(self):
        c = Client(self.url, 'a' * 64, timeout=2.0)
        start = time.monotonic()
        r = c.connect()
        sec = time.monotonic() - start
        self.assertTrue(r.offline)
        self.assertIn('시간 초과', r.msg)
        self.assertLess(sec, 2.8)
        self.assertGreaterEqual(sec, 1.9)

    def test_fast_response(self):
        _SlowHandler.delay = 0.1
        try:
            c = Client(self.url, 'a' * 64, timeout=2.0)
            self.assertTrue(c.connect().ok)
        finally:
            _SlowHandler.delay = 3.0

    def test_connection_refused(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()                              # 아무도 듣지 않는 포트
        c = Client(f'http://127.0.0.1:{port}', 'a' * 64, timeout=2.0)
        start = time.monotonic()
        r = c.connect()
        self.assertTrue(r.offline)
        # Windows는 닫힌 포트에도 SYN을 몇 번 다시 보내서 2초 시간 초과가 먼저 날 수 있다
        self.assertTrue('연결 실패' in r.msg or '시간 초과' in r.msg, r.msg)
        self.assertLess(time.monotonic() - start, 2.8)


if __name__ == '__main__':
    unittest.main()
