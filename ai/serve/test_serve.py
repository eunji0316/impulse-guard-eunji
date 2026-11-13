"""C-3 예측 서버 테스트 (서버를 켜지 않고 TestClient로)

실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m unittest serve.test_serve
"""
import json
import os
import shutil
import tempfile
import unittest
import warnings

with warnings.catch_warnings():
    warnings.simplefilter('ignore')   # starlette의 httpx 안내 경고
    from fastapi.testclient import TestClient

from risk.model import RiskModel

from . import config
from .app import create_app

LOCAL = ('127.0.0.1', 50000)


def client(model_file=None, addr=LOCAL):
    return TestClient(create_app(model_file), client=addr)


class TestPredict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client()
        cls.model = RiskModel.load(config.RISK_MODEL_FILE)

    def test_health(self):
        r = self.c.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['services']['risk'], {'model': self.model.data['version'], 'format': 'risk-logreg/1'})

    def test_json_examples(self):
        """모델 JSON의 예시 32개: 확률과 이유가 기준 구현(model.py)과 같다"""
        tests = self.model.data['tests']
        self.assertGreaterEqual(len(tests), 30)
        for t in tests:
            r = self.c.post('/risk/predict', json={'raw': t['raw']})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            prob, reasons, _ = self.model.predict(t['raw'])
            self.assertEqual(body['prob'], prob)
            self.assertAlmostEqual(body['prob'], t['prob'], places=5)
            self.assertEqual([g for g, _ in body['reasons']], t['reasons'])
            self.assertEqual(body['reasons'], [[g, c] for g, c in reasons])
            self.assertEqual(body['model'], self.model.data['version'])

    def test_missing_fields_are_unknown(self):
        """빠진 칸은 모름(null)과 같다"""
        a = self.c.post('/risk/predict', json={'raw': {}}).json()
        b = self.c.post('/risk/predict', json={'raw': {k: None for k in self.model.data['raw_fields']}}).json()
        self.assertEqual(a, b)
        self.assertEqual(a['prob'], self.model.predict({})[0])

    def test_rejects_extra_fields(self):
        """정해진 칸 말고는 받지 않는다 (회원 아이디, 상품명 등이 섞여 오면 거부)"""
        raw = dict(self.model.data['tests'][0]['raw'])
        for extra in ({'mb_id': 'user1'}, {'item_name': '상품'}):
            r = self.c.post('/risk/predict', json={'raw': {**raw, **extra}})
            self.assertEqual(r.status_code, 422)
        r = self.c.post('/risk/predict', json={'raw': raw, 'site': 'coupang'})
        self.assertEqual(r.status_code, 422)

    def test_rejects_non_numbers(self):
        for bad in ('12', True, [1], {'a': 1}):
            r = self.c.post('/risk/predict', json={'raw': {'hour': bad}})
            self.assertEqual(r.status_code, 422, bad)
        for text in ('NaN', 'Infinity'):
            r = self.c.post('/risk/predict', content='{"raw": {"amount": %s}}' % text,
                            headers={'Content-Type': 'application/json'})
            self.assertEqual(r.status_code, 422, text)

    def test_error_does_not_echo_input(self):
        r = self.c.post('/risk/predict', json={'raw': {'mb_id': 'secret-user'}})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn('secret-user', r.text)

    def test_local_only(self):
        c = client(addr=('192.168.0.10', 50000))
        self.assertEqual(c.get('/health').status_code, 403)
        self.assertEqual(c.post('/risk/predict', json={'raw': {}}).status_code, 403)


class TestModelFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'risk_model.json')
        shutil.copy(config.RISK_MODEL_FILE, self.path)
        self.c = client(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data, bump=True):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        if bump:   # 같은 시각 안에 두 번 쓰면 수정 시각이 같을 수 있어 일부러 바꾼다
            st = os.stat(self.path)
            os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))

    def test_reload_on_change(self):
        with open(self.path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(self.c.get('/health').json()['services']['risk']['model'], data['version'])
        data['version'] = 'test-new'
        self.write(data)
        self.assertEqual(self.c.get('/health').json()['services']['risk']['model'], 'test-new')
        self.assertEqual(self.c.post('/risk/predict', json={'raw': {}}).json()['model'], 'test-new')

    def test_missing_model(self):
        os.remove(self.path)
        self.assertIsNone(self.c.get('/health').json()['services']['risk'])
        self.assertEqual(self.c.post('/risk/predict', json={'raw': {}}).status_code, 503)

    def test_broken_model(self):
        self.write('{broken')
        self.assertEqual(self.c.post('/risk/predict', json={'raw': {}}).status_code, 503)
        with open(config.RISK_MODEL_FILE, encoding='utf-8') as f:
            data = json.load(f)
        data['format'] = 'other/9'
        self.write(data)
        self.assertEqual(self.c.post('/risk/predict', json={'raw': {}}).status_code, 503)


if __name__ == '__main__':
    unittest.main()
