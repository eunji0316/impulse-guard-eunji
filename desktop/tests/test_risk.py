"""C-2 위험도 연결 테스트

- risk_features: 상품 화면 숫자 특성 (반복 방문, 머문 시간, 압박 문구, 할인율), 원문을 두지 않는지
- check_params / Client.check: 결제 화면에만 features를 보낸다
- popup_model: 위험 단계별 제목·배지·문구, 이유는 보통 이상만, risk가 없으면 예전 팝업 그대로
- popup: 배지와 제목 색 (실제 tkinter 창)
- main.App: 상품 화면 → 결제 화면에서 서버에 보낸 features, 팝업, 로그
- 금액을 나중에 채우면 서버(amount)가 다시 계산한 위험도로 팝업 배지·제목·부제·이유를 바꾼다
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np

import cache
import checkout_samples as cs
from impulse_guard import config, main, popup, popup_model, risk_features, server_client
from impulse_guard.detect_log import DetectLog
from impulse_guard.risk_features import ProductTracker, has_pressure, item_key
from impulse_guard.server_client import ApiResult
from test_auto import CHECKOUT_RESULT, H1, NOT_BLOCKING, Clock
from test_popup import FakeActions, TkCase, quiet
from test_server_client import FakeServer, make

RISK_REASONS = [{'code': 'amount_ratio', 'text': '평소 결제 금액의 5배예요.'},
                {'code': 'history', 'text': "지난 팝업에서 '그래도 구매'를 고른 적이 많아요."},
                {'code': 'frequency', 'text': '최근 7일 동안 결제 화면에 3번 들어갔어요.'}]


def risk_result(level, risk, show=None, reasons=RISK_REASONS, **kw):
    msg = {'high': '충동구매일 가능성이 높아 보여요.', 'mid': '조금 서두르는 것 같아요.', 'low': '한 번만 확인해요.'}[level]
    return {**CHECKOUT_RESULT, 'risk': risk, 'risk_level': level, 'risk_message': msg, 'risk_reasons': reasons,
            'risk_show_reasons': level != 'low' if show is None else show, 'risk_model': 'test', **kw}


class T:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.clock = T()
        self.tr = ProductTracker(self.clock)

    def test_pressure_words(self):
        self.assertEqual(has_pressure('오늘의 타임 딜 상품'), 1)        # 공백 무시
        self.assertEqual(has_pressure('품절 임박! 서두르세요'), 1)
        self.assertEqual(has_pressure('지금 37명이 보고 있어요'), 1)
        self.assertEqual(has_pressure('세일 20% 할인 쿠폰'), 0)        # 일반 할인 단어는 압박 문구가 아님
        self.assertEqual(has_pressure(''), 0)

    def test_no_product_screen(self):
        """상품 화면 없이 결제 화면: 머문 시간·할인율 모름, 수는 0"""
        self.assertEqual(self.tr.features('coupang'), {'discount_rate': None, 'pressure': 0, 'product_views_24h': 0,
                                                       'same_item_views_24h': 0, 'browse_sec': None})

    def test_scroll_is_same_view(self):
        """같은 상품 화면을 5분 안에 다시 분석(스크롤)하면 한 번. 할인율과 압박 문구는 읽은 값을 남긴다"""
        self.tr.see('coupang', '무선 이어폰', None, '상품 화면')
        self.clock.t += 20
        self.tr.see('coupang', '무선 이어폰', 58, '타임딜 진행 중')
        self.clock.t += 20
        self.tr.see('coupang', '무선 이어폰', None, '리뷰')               # 못 읽어도 앞에서 읽은 58은 남는다
        self.clock.t += 30
        f = self.tr.features('coupang')
        self.assertEqual(f, {'discount_rate': 58, 'pressure': 1, 'product_views_24h': 1,
                             'same_item_views_24h': 1, 'browse_sec': 70})

    def test_repeat_visits_and_session(self):
        """다른 상품을 보다 돌아오면 다시 본 것. 머문 시간은 30분 안에 이어 본 묶음의 처음부터"""
        self.tr.see('coupang', 'A 상품', 10, '')
        self.clock.t += 3600                                            # 1시간 뒤 (이전 묶음과 끊김)
        self.tr.see('coupang', 'B 상품', None, '')
        self.clock.t += 60
        self.tr.see('coupang', 'A 상품', 20, '')
        self.clock.t += 60
        self.tr.see('musinsa', 'A 상품', 30, '')                        # 다른 쇼핑몰은 따로 센다
        self.clock.t += 60
        f = self.tr.features('coupang')
        self.assertEqual((f['product_views_24h'], f['same_item_views_24h'], f['browse_sec'], f['discount_rate']),
                         (3, 2, 180, 20))

    def test_session_expires(self):
        """마지막 상품 화면이 30분보다 오래면 머문 시간·할인율은 모름 (24시간 수는 남음)"""
        self.tr.see('coupang', 'A', 10, '타임딜')
        self.clock.t += config.RISK_SESSION_GAP_MIN * 60 + 1
        f = self.tr.features('coupang')
        self.assertEqual((f['browse_sec'], f['discount_rate'], f['pressure'], f['product_views_24h']), (None, None, 0, 1))

    def test_24h_trim(self):
        self.tr.see('coupang', 'A', 10, '')
        self.clock.t += 24 * 3600 + 1
        self.assertEqual(self.tr.features('coupang')['product_views_24h'], 0)
        self.assertEqual(self.tr.views, [])

    def test_no_raw_text_kept(self):
        """상품명과 OCR 원문은 메모리에도 두지 않는다 (해시와 숫자만)"""
        self.tr.see('coupang', '비밀 상품명', 10, '타임딜 홍길동 010-1234-5678')
        kept = repr(self.tr.views)
        for s in ('비밀', '홍길동', '010'):
            self.assertNotIn(s, kept)
        self.assertEqual(self.tr.views[0].item, item_key('비밀  상품명'))   # 공백 차이는 같은 상품
        self.assertIsNone(item_key(''))
        f = self.tr.features('coupang')
        self.assertTrue(all(v is None or isinstance(v, int) for v in f.values()))

    def test_summary(self):
        self.assertIn('머문 시간 모름', risk_features.summary(self.tr.features('x')))


class TestParams(unittest.TestCase):
    def test_features_only_for_checkout(self):
        img, boxes, reread = cache.load('coupang_product')
        product = main.analyze_boxes(boxes, img, reread)
        checkout = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        f = {'discount_rate': 10, 'pressure': 0, 'product_views_24h': 1, 'same_item_views_24h': 1, 'browse_sec': 5}
        self.assertNotIn('features', main.check_params(product, features=f))
        self.assertEqual(main.check_params(checkout, features=f)['features'], f)
        self.assertNotIn('features', main.check_params(checkout))

    def test_client_sends_features(self):
        fake = FakeServer()
        client, _ = make(fake)
        client.connect()
        client.check('coupang', '', 1000, is_checkout=True, features={'discount_rate': None, 'browse_sec': 3})
        self.assertEqual(fake.calls[-1]['features'], {'discount_rate': None, 'browse_sec': 3})
        client.check('coupang', '', 1000)
        self.assertNotIn('features', fake.calls[-1])          # 없으면 보내지 않는다 (예전 요청과 같음)


class TestBuildRisk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        img, boxes, reread = cache.load('coupang_product')
        cls.product = main.analyze_boxes(boxes, img, reread)

    def build(self, data, a=None):
        return popup_model.build(a or self.checkout, ApiResult(True, data))

    def test_high(self):
        kind, v = self.build(risk_result('high', 0.65))
        style = config.POPUP_RISK_STYLES['high']
        self.assertEqual(kind, 'impulse')
        self.assertEqual((v.title, v.subtitle, v.risk_badge, v.title_color, v.risk_level, v.risk),
                         (style[0], '충동구매일 가능성이 높아 보여요.', '위험 높음', style[2], 'high', 0.65))
        self.assertEqual(v.reasons, [r['text'] for r in RISK_REASONS])     # 규칙 이유(결제 직전) 대신 위험도 이유
        self.assertEqual(v.point, 496)                                     # 포인트는 그대로

    def test_mid_with_keyword(self):
        """회원 키워드 이유는 함께 보이고, 이유는 최대 3개"""
        d = risk_result('mid', 0.4)
        d['reasons'] = d['reasons'] + [{'code': 'keyword', 'text': "'특가' 키워드가 들어 있어요."}]
        _, v = self.build(d)
        self.assertEqual(v.title, config.POPUP_RISK_STYLES['mid'][0])
        self.assertEqual(v.reasons, ["'특가' 키워드가 들어 있어요.", RISK_REASONS[0]['text'], RISK_REASONS[1]['text']])

    def test_low_no_reasons(self):
        """낮음: 이유가 응답에 있어도 보이지 않고 확인 문구만"""
        _, v = self.build(risk_result('low', 0.1))
        self.assertEqual((v.title, v.subtitle, v.reasons, v.risk_badge),
                         (config.POPUP_RISK_STYLES['low'][0], '한 번만 확인해요.', [], '위험 낮음'))

    def test_low_pending(self):
        a = dataclasses.replace(self.checkout, page=dataclasses.replace(self.checkout.page, checkout_total=None, total_label=''))
        _, v = self.build(risk_result('low', 0.1), a)
        self.assertEqual(v.reasons, [popup_model.CHECKOUT_PENDING_REASON])
        self.assertTrue(popup_model.fill_price(v, 1000))
        self.assertEqual(v.reasons, [])

    def test_no_risk_is_old_popup(self):
        """risk가 없거나(예전 서버) null이거나 이상하면 예전 팝업 그대로"""
        old = popup_model.build(self.checkout, ApiResult(True, CHECKOUT_RESULT))[1]
        for extra in ({}, {'risk': None, 'risk_level': ''}, {'risk': 'abc', 'risk_level': 'high'},
                      {'risk': True, 'risk_level': 'high'}, {'risk': 0.5, 'risk_level': 'unknown'}):
            _, v = self.build({**CHECKOUT_RESULT, **extra})
            self.assertEqual((v.title, v.subtitle, v.reasons, v.risk_badge, v.title_color),
                             (old.title, old.subtitle, old.reasons, '', ''), extra)
        self.assertEqual(old.title, '결제하기 전에 잠깐만요!')

    def test_product_screen_ignores_risk(self):
        """상품 화면(F4)은 위험도를 쓰지 않는다 (서버도 계산하지 않음)"""
        d = {**risk_result('high', 0.9), 'reasons': [{'code': 'big', 'text': '큰 금액'}]}
        _, v = self.build(d, self.product)
        self.assertEqual((v.risk_badge, v.reasons), ('', ['큰 금액']))

    def pending_view(self, data):
        a = dataclasses.replace(self.checkout, page=dataclasses.replace(self.checkout.page, checkout_total=None, total_label=''))
        return popup_model.build(a, ApiResult(True, data))[1]

    def test_apply_risk(self):
        """낮음(금액 모름) → 금액을 채운 뒤 높음: 제목·부제·배지·이유가 바뀌고 '확인 중' 안내는 그대로 둔다"""
        d = risk_result('low', 0.2)
        d['reasons'] = d['reasons'] + [{'code': 'keyword', 'text': "'특가' 키워드"}]
        v = self.pending_view(d)
        self.assertEqual(v.reasons, [popup_model.CHECKOUT_PENDING_REASON])
        self.assertTrue(popup_model.apply_risk(v, {'risk_updated': True, **risk_result('high', 0.7)}))
        self.assertEqual((v.title, v.risk_level, v.risk_badge, v.risk, v.risk_updated),
                         (config.POPUP_RISK_STYLES['high'][0], 'high', '위험 높음', 0.7, True))
        self.assertEqual(v.subtitle, '충동구매일 가능성이 높아 보여요.')
        self.assertEqual(v.reasons, ["'특가' 키워드", RISK_REASONS[0]['text'], RISK_REASONS[1]['text'],
                                     popup_model.CHECKOUT_PENDING_REASON])
        self.assertTrue(popup_model.apply_risk(v, risk_result('low', 0.1)))     # 낮아지면 이유를 다시 숨긴다
        self.assertEqual(v.reasons, [popup_model.CHECKOUT_PENDING_REASON])

    def test_apply_risk_without_risk_keeps_view(self):
        """amount 응답에 위험도가 없으면(예전 서버, check 때 모델 없음) 처음 내용 그대로"""
        v = self.pending_view(risk_result('mid', 0.4))
        before = dataclasses.replace(v)
        for data in ({'ok': True, 'bl_id': 200, 'price': 49600}, {'risk': None, 'risk_level': '', 'risk_updated': False}):
            self.assertFalse(popup_model.apply_risk(v, data))
            self.assertEqual(v, before)

    def test_risk_note(self):
        self.assertEqual(popup_model.risk_note(risk_result('high', 0.6512)),
                         '위험도 0.65 높음 (amount_ratio,history,frequency)')
        self.assertEqual(popup_model.risk_note(risk_result('low', 0.05)),
                         '위험도 0.05 낮음 (amount_ratio,history,frequency, 이유 안 보임)')
        self.assertEqual(popup_model.risk_note(CHECKOUT_RESULT), '')


class TestPopupRisk(TkCase):
    def open(self, data):
        _, v = popup_model.build(main.analyze_boxes(cs.COUPANG_CHECKOUT), ApiResult(True, data))
        w = popup.ImpulsePopup(self.host, v, FakeActions(), take_focus=False)
        self.root.update()
        return w

    def test_badge_and_title_color(self):
        for level in ('high', 'mid', 'low'):
            w = self.open(risk_result(level, 0.5))
            _, badge, fg, bg = config.POPUP_RISK_STYLES[level]
            self.assertEqual(w.badge_label.cget('text').strip(), badge)
            self.assertEqual((w.badge_label.cget('fg'), w.badge_label.cget('bg')), (fg, bg))
            self.assertEqual(w.title_label.cget('fg'), fg)
            with quiet():
                w.destroy()

    def test_update_risk_redraws(self):
        """떠 있는 팝업이 다시 계산한 위험도로 배지·제목 색·부제·이유 줄을 바꾼다"""
        w = self.open(risk_result('low', 0.2))
        self.assertEqual(w.reason_labels, [])
        self.assertTrue(w.update_risk(risk_result('high', 0.7)))
        self.root.update()
        _, badge, fg, bg = config.POPUP_RISK_STYLES['high']
        self.assertEqual((w.badge_label.cget('text').strip(), w.badge_label.cget('fg'), w.badge_label.cget('bg')), (badge, fg, bg))
        self.assertEqual((w.title_label.cget('text'), w.title_label.cget('fg')), (config.POPUP_RISK_STYLES['high'][0], fg))
        self.assertEqual(w.subtitle_label.cget('text'), '충동구매일 가능성이 높아 보여요.')
        self.assertEqual([lb.reason for lb in w.reason_labels], [r['text'] for r in RISK_REASONS])
        # 이유 줄은 포인트 줄 위에 있다
        order = w.ask.pack_slaves()
        self.assertLess(order.index(w.reason_labels[-1]), order.index(w.point_label))
        self.assertFalse(w.update_risk({'risk': None}))                   # 위험도 없는 응답은 무시
        w.done = True
        self.assertFalse(w.update_risk(risk_result('low', 0.1)))          # 결정 뒤(결과 화면)에는 바꾸지 않음
        self.assertEqual(w.view.risk_level, 'high')
        with quiet():
            w.destroy()

    def test_update_risk_adds_badge_to_old_popup(self):
        """처음엔 위험도가 없던 팝업도 다시 계산한 위험도를 받으면 배지를 단다"""
        w = self.open(CHECKOUT_RESULT)
        self.assertTrue(w.update_risk(risk_result('mid', 0.4)))
        self.root.update()
        self.assertEqual(w.badge_label.cget('text').strip(), '위험 보통')
        self.assertLess(w.ask.pack_slaves().index(w.badge_label), w.ask.pack_slaves().index(w.title_label))
        with quiet():
            w.destroy()

    def test_old_popup_has_no_badge(self):
        w = self.open(CHECKOUT_RESULT)
        self.assertIsNone(w.badge_label)
        self.assertEqual(w.title_label.cget('fg'), config.POPUP_COLORS['text'])
        with quiet():
            w.destroy()


class TestAppRisk(TkCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        img, boxes, reread = cache.load('coupang_product')
        cls.product = main.analyze_boxes(boxes, img, reread)
        cls.checkout = main.analyze_boxes(cs.COUPANG_CHECKOUT)

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = DetectLog(self.dir, console=False)

    def tearDown(self):
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def make_app(self, check):
        self.fake = FakeServer(setting=(200, NOT_BLOCKING), check=(200, check), decide=(200, {'ok': True}))
        client, _ = make(self.fake)
        client.connect()
        client.get_setting()
        self.clock = Clock()
        return main.App(client, self.host, settings=server_client.auto_settings(), log=self.log, clock=self.clock)

    def run_auto(self, app, a, h):
        self.assertTrue(app.try_begin())
        shown = app.handle_auto(a, h)
        if shown:
            self.assertTrue(self.pump(lambda: app.window is not None))
        else:
            app._busy.release()
        return shown

    def log_text(self):
        with open(os.path.join(self.dir, config.LOG_FILE), encoding='utf-8') as f:
            return f.read()

    def test_product_then_checkout_sends_features(self):
        self.assertEqual(self.product.page.site, self.checkout.page.site)
        app = self.make_app(risk_result('high', 0.7))
        self.assertFalse(self.run_auto(app, self.product, H1))
        self.assertEqual(self.fake.count('check'), 0)                  # 상품 화면은 여전히 서버를 부르지 않는다
        self.clock.t += 95
        self.assertTrue(self.run_auto(app, self.checkout, 12345))
        body = [b for b in self.fake.calls if b['action'] == 'check'][-1]
        self.assertTrue(body['is_checkout'])
        self.assertEqual(body['features'], {'discount_rate': self.product.prices.discount_rate, 'pressure': 0,
                                            'product_views_24h': 1, 'same_item_views_24h': 1, 'browse_sec': 95})
        self.assertNotIn(self.product.page.item_name, json.dumps(body['features'], ensure_ascii=False))
        v = app.window.view
        self.assertEqual((v.risk_level, v.title), ('high', config.POPUP_RISK_STYLES['high'][0]))
        log = self.log_text()
        self.assertIn('위험도 0.70 높음', log)
        self.assertIn('머문 시간 95초', log)
        with quiet():
            app.window.destroy()
            self.pump(lambda: app.window is None)

    def pending_popup(self, amount_response):
        self.fake = FakeServer(setting=(200, NOT_BLOCKING), check=(200, risk_result('low', 0.2, bl_id=200)),
                               amount=(200, amount_response))
        client, _ = make(self.fake)
        client.connect()
        client.get_setting()
        self.clock = Clock()
        app = main.App(client, self.host, settings=server_client.auto_settings(), log=self.log, clock=self.clock)
        a = dataclasses.replace(self.checkout, page=dataclasses.replace(self.checkout.page, checkout_total=None, total_label=''))
        self.assertTrue(self.run_auto(app, a, H1))
        self.assertTrue(app.window.view.pending)
        self.assertEqual(app.window.view.risk_level, 'low')
        app.analyze_frame = lambda img: dataclasses.replace(self.checkout)
        with mock.patch.object(main.capture, 'monitor_origin', return_value=(0, 0)):
            self.assertTrue(app.run_amount(np.zeros((900, 1600, 3), np.uint8), 999, None))
        self.assertTrue(self.pump(lambda: app.window.view.price > 0))
        return app

    def test_amount_fill_updates_risk(self):
        """'확인 중'(낮음) 팝업에 금액을 채우면 서버가 다시 계산한 위험도(높음)로 배지·이유가 바뀐다"""
        resp = {'ok': True, 'bl_id': 200, 'price': 49600, 'risk_updated': True, **{k: v for k, v in risk_result('high', 0.72).items()
                                                                                   if k.startswith('risk')}}
        app = self.pending_popup(resp)
        self.assertTrue(self.pump(lambda: app.window.view.risk_level == 'high'))
        w = app.window
        self.assertEqual(w.badge_label.cget('text').strip(), '위험 높음')
        self.assertEqual([lb.reason for lb in w.reason_labels], [r['text'] for r in RISK_REASONS])
        self.assertEqual(w.price_label['text'], '49,600원')
        self.assertIn('위험도 다시 계산 위험도 0.72 높음', self.log_text())
        with quiet():
            w.destroy()
            self.pump(lambda: app.window is None)

    def test_amount_fill_without_risk_keeps_popup(self):
        """amount 응답에 위험도가 없으면(risk_updated false) 금액만 채우고 위험도 표시는 그대로"""
        app = self.pending_popup({'ok': True, 'bl_id': 200, 'price': 49600, 'risk_updated': False, 'risk': None, 'risk_level': ''})
        self.pump(lambda: False, timeout=0.2)
        w = app.window
        self.assertEqual((w.view.risk_level, w.view.risk_updated, w.badge_label.cget('text').strip()), ('low', False, '위험 낮음'))
        self.assertNotIn('위험도 다시 계산', self.log_text())
        with quiet():
            w.destroy()
            self.pump(lambda: app.window is None)

    def test_old_server_popup_unchanged(self):
        """예전 서버(위험도 칸 없음): 예전 팝업 그대로, 로그에 '위험도 없음'"""
        app = self.make_app(CHECKOUT_RESULT)
        self.assertTrue(self.run_auto(app, self.checkout, 12345))
        v = app.window.view
        self.assertEqual((v.title, v.risk_badge, v.reasons), ('결제하기 전에 잠깐만요!', '', [CHECKOUT_RESULT['reasons'][0]['text']]))
        self.assertIn('위험도 없음', self.log_text())
        with quiet():
            app.window.destroy()
            self.pump(lambda: app.window is None)


if __name__ == '__main__':
    unittest.main()
