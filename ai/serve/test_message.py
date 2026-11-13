"""5 LLM 주간 리포트 요약 테스트 (가짜 클라이언트, 실제 API를 부르지 않음)

실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m unittest serve.test_message
"""
import json
import unittest
import warnings
from datetime import date
from types import SimpleNamespace

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    from fastapi.testclient import TestClient

from .app import create_app
from .message_api import WeeklyService

LOCAL = ('127.0.0.1', 50000)

WEEK = {'checkouts': 5, 'buy': 1, 'giveup': 2, 'hold': 1, 'hold_success': 1, 'hold_failed': 0,
        'saved_amount': 32000, 'risk_high': 1, 'risk_mid': 2, 'risk_low': 2, 'night': 3, 'malls': 2, 'blocked': 4}
LAST = {**WEEK, 'checkouts': 3, 'night': 1, 'saved_amount': 10000, 'giveup': 1}
# 서버 PHP ipp_report_derived와 같은 값 (5/3 = 1.67 → 1.7배, 참은 비율 3/4 = 75%, 2/3 = 67%)
DERIVED = {'checkouts_diff': 2, 'night_diff': 2, 'blocked_diff': 0, 'buy_diff': 0, 'giveup_diff': 1, 'saved_amount_diff': 22000,
           'checkouts_ratio': 1.7, 'night_ratio': 3.0, 'blocked_ratio': 1.0,
           'resist_rate_this': 75, 'resist_rate_last': 67, 'hold_success_rate_this': 100, 'hold_success_rate_last': 100}
BODY = {'this_week': WEEK, 'last_week': LAST, 'top_reasons': [{'code': 'night', 'count': 3}, {'code': 'discount', 'count': 2}],
        'derived': DERIVED}

GOOD = {'headline': '이번 주 2번 참았어요',
        'summary': '결제 화면이 5번 나왔고 2번은 안 살래요를 골랐어요. 예상 절약 금액은 32,000원이에요. 심야 결제 화면이 지난주보다 2번 늘었어요.',
        'tip': '밤 11시 이후에는 장바구니에만 담아 두고 다음 날 다시 봐요.'}


def reply(data=None, stop='end_turn', text=None):
    text = json.dumps(data, ensure_ascii=False) if text is None else text
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type='thinking', thinking=''),
                                                      SimpleNamespace(type='text', text=text)])


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r


def setup(*replies, credentials='api_key', limit=50):
    fake = FakeClient(*replies)
    svc = WeeklyService(client_factory=lambda: fake, model='claude-haiku-5-5', daily_limit=limit, credentials=credentials)
    return TestClient(create_app(message_service=svc), client=LOCAL), fake, svc


class TestWeekly(unittest.TestCase):
    def test_success(self):
        c, fake, _ = setup(reply(GOOD))
        r = c.post('/message/weekly', json=BODY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {**GOOD, 'model': 'claude-haiku-5-5', 'cached': False})
        kw = fake.calls[0]
        self.assertEqual(kw['model'], 'claude-haiku-5-5')
        self.assertEqual(kw['output_config']['effort'], 'low')
        self.assertEqual(kw['output_config']['format']['type'], 'json_schema')
        self.assertNotIn('temperature', kw)
        self.assertNotIn('thinking', kw)

    def test_prompt_has_only_numbers_and_reason_meanings(self):
        """API로 보내는 내용: 숫자와 이유의 뜻만 (회원·쇼핑몰·상품 정보 칸이 없다)"""
        c, fake, _ = setup(reply(GOOD))
        c.post('/message/weekly', json=BODY)
        kw = fake.calls[0]
        self.assertEqual(set(kw), {'model', 'max_tokens', 'system', 'messages', 'output_config'})
        content = kw['messages'][0]['content']
        data = json.loads(content.split('\n', 1)[1])
        for week in ('이번 주(최근 7일)', '지난주(그 전 7일)'):
            self.assertTrue(all(isinstance(v, int) for v in data[week].values()))
        self.assertIn('심야(밤 11시~새벽 4시) 결제 시도', data['이번 주 위험을 올린 이유 (횟수)'])
        pre = data['미리 계산한 값 (이 숫자만 쓰고 직접 계산하지 마세요)']
        self.assertEqual(pre['결제 화면 감지 배수(이번 주 ÷ 지난주)'], 1.7)
        self.assertEqual(pre['이번 주 참은 비율(%, 안 살래요·담아두기 ÷ 팝업 결정)'], 75)
        self.assertIn('직접 계산하지 않습니다', kw['system'])
        for word in ('mb_id', 'coupang', '쿠팡', 'admin', 'url'):
            self.assertNotIn(word, content)

    def test_rejects_extra_fields(self):
        c, fake, _ = setup(reply(GOOD))
        for body in ({**BODY, 'mb_id': 'admin'},
                     {**BODY, 'this_week': {**WEEK, 'site': 'coupang'}},
                     {**BODY, 'top_reasons': [{'code': 'night', 'count': 1, 'item': '상품'}]},
                     {**BODY, 'top_reasons': [{'code': 'coupang', 'count': 1}]},
                     {**BODY, 'this_week': {**WEEK, 'checkouts': '5'}},
                     {**BODY, 'this_week': {**WEEK, 'checkouts': -1}},
                     {**BODY, 'top_reasons': [{'code': 'night', 'count': 1}] * 6}):
            self.assertEqual(c.post('/message/weekly', json=body).status_code, 422)
        self.assertEqual(fake.calls, [])

    def test_cache(self):
        c, fake, svc = setup(reply(GOOD))
        c.post('/message/weekly', json=BODY)
        r = c.post('/message/weekly', json=BODY)
        self.assertTrue(r.json()['cached'])
        self.assertEqual(len(fake.calls), 1)
        other = {**BODY, 'this_week': {**WEEK, 'blocked': 9}, 'derived': None}   # 파생 값 없이 (있으면 두 주와 맞아야 함)
        fake.replies = [reply({**GOOD})]
        self.assertFalse(c.post('/message/weekly', json=other).json()['cached'])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(svc.health()['calls_today'], 2)

    def test_daily_limit(self):
        c, fake, svc = setup(reply(GOOD), limit=1)
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 200)
        other = {**BODY, 'this_week': {**WEEK, 'blocked': 9}, 'derived': None}   # 파생 값 없이 (있으면 두 주와 맞아야 함)
        self.assertEqual(c.post('/message/weekly', json=other).status_code, 503)
        self.assertEqual(len(fake.calls), 1)
        svc._today = lambda: date(2099, 1, 1)   # 다음 날이면 다시
        self.assertEqual(c.post('/message/weekly', json=other).status_code, 200)

    def test_no_credentials(self):
        c, fake, _ = setup(reply(GOOD), credentials='')
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 503)
        self.assertIsNone(c.get('/health').json()['services']['message'])
        self.assertEqual(fake.calls, [])

    def test_health(self):
        c, _, _ = setup(reply(GOOD))
        h = c.get('/health').json()['services']
        self.assertEqual(h['message'], {'model': 'claude-haiku-5-5', 'credentials': 'api_key', 'calls_today': 0, 'daily_limit': 50})
        self.assertIsNotNone(h['risk'])

    def test_bad_outputs(self):
        """응답 검사: 지어낸 숫자, 너무 김, 칸 모양, 태그, JSON 아님, 거절·잘림 → 502"""
        cases = {
            '지어낸 숫자': reply({**GOOD, 'summary': '결제 화면이 13번 나왔어요.'}),
            '퍼센트 계산': reply({**GOOD, 'tip': '심야 결제를 33% 줄여 봐요.'}),
            '너무 긴 제목': reply({**GOOD, 'headline': '가' * 41}),
            '빈 칸': reply({**GOOD, 'tip': ' '}),
            '칸 빠짐': reply({'headline': 'a', 'summary': 'b'}),
            '칸 더 있음': reply({**GOOD, 'extra': 'x'}),
            '태그': reply({**GOOD, 'summary': '<b>잘했어요</b>'}),
            'JSON 아님': reply(text='잘했어요'),
            '거절': reply(GOOD, stop='refusal'),
            '잘림': reply(GOOD, stop='max_tokens'),
        }
        for name, r in cases.items():
            c, _, _ = setup(r)
            self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 502, name)

    def test_allowed_numbers(self):
        """입력 값, 두 주 차이(심야 3-1=2), 금액 쉼표, 7일·24시간은 통과"""
        ok = {**GOOD, 'summary': '심야 결제 화면이 2번 늘었어요. 32,000원을 아꼈어요. 최근 7일 동안 4번 막았어요.',
              'tip': '24시간 담아 두기를 써 봐요.'}
        c, _, _ = setup(reply(ok))
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 200)

    def test_derived_values_in_answer(self):
        """PHP가 보낸 파생 값(증감, 배수, 비율)을 쓴 정상 응답은 통과"""
        ok = {'headline': '참은 비율이 67%에서 75%로 올랐어요',
              'summary': '결제 화면은 지난주보다 2번 늘어 1.7배였지만 참은 비율은 75%예요. 예상 절약 금액은 32,000원으로 22,000원 늘었어요. '
                         '심야 결제 화면은 3.0배예요.',
              'tip': '담아두기 성공 비율 100%를 다음 주에도 이어 가 봐요.'}
        c, _, _ = setup(reply(ok))
        r = c.post('/message/weekly', json=BODY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['summary'], ok['summary'])

    def test_self_computed_values_rejected(self):
        """보내지 않은 배수·비율을 LLM이 직접 계산해 쓰면 버린다"""
        for text in ('결제 화면이 1.67배로 늘었어요.', '안 살래요 비율은 50%예요.', '결제 화면이 2.5배예요.'):
            c, _, _ = setup(reply({**GOOD, 'summary': text}))
            self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 502, text)
        # 파생 값을 보내지 않으면 배수도 쓸 수 없다
        c, _, _ = setup(reply({**GOOD, 'summary': '결제 화면이 1.7배예요.'}))
        no_derived = {k: v for k, v in BODY.items() if k != 'derived'}
        self.assertEqual(c.post('/message/weekly', json=no_derived).status_code, 502)

    def test_derived_must_match_weeks(self):
        """파생 값이 두 주 숫자와 다르면 422 (반올림 차이만 허용), null은 지난주 0일 때만"""
        c, fake, _ = setup(reply(GOOD))
        for bad in ({'checkouts_diff': 3}, {'checkouts_ratio': 2.0}, {'resist_rate_this': 50}, {'night_ratio': None},
                    {'checkouts_ratio': '1.7'}, {'resist_rate_this': 101}, {'mb_id': 'admin'}):
            r = c.post('/message/weekly', json={**BODY, 'derived': {**DERIVED, **bad}})
            self.assertEqual(r.status_code, 422, bad)
        missing = dict(DERIVED); del missing['night_diff']
        self.assertEqual(c.post('/message/weekly', json={**BODY, 'derived': missing}).status_code, 422)
        self.assertEqual(fake.calls, [])
        # 반올림 차이 (PHP 반올림 1.67 → 1.7, 66.7 → 67)와 지난주 0이면 배수 null
        zero_last = {**LAST, 'night': 0}
        d = {**DERIVED, 'night_diff': 3, 'night_ratio': None}
        r = c.post('/message/weekly', json={**BODY, 'last_week': zero_last, 'derived': d})
        self.assertEqual(r.status_code, 200, r.text)

    def test_api_errors(self):
        import anthropic
        import httpx2
        req = httpx2.Request('POST', 'https://api.anthropic.com/v1/messages')
        c, fake, svc = setup(anthropic.APIConnectionError(request=req))
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 502)
        self.assertTrue(svc.available())

        resp = httpx2.Response(401, request=req)
        c, fake, svc = setup(anthropic.AuthenticationError('bad key', response=resp, body=None))
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 503)
        self.assertFalse(svc.available())   # 키가 틀리면 다시 부르지 않음
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 503)
        self.assertEqual(len(fake.calls), 1)

    def test_error_not_cached(self):
        c, fake, _ = setup(reply(GOOD, stop='refusal'), reply(GOOD))
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 502)
        self.assertEqual(c.post('/message/weekly', json=BODY).status_code, 200)


if __name__ == '__main__':
    unittest.main()
