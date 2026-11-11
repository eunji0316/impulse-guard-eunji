"""차단 팝업 테스트 (B-3)

- popup_model: 어떤 창을 띄울지, 팝업 내용, 버튼별 서버 요청 (가짜 서버)
- popup: 실제 tkinter 창을 만들어 버튼을 코드로 누르고 화면이 바뀌는지 본다 (화면에 잠깐 떴다 사라진다)
- main.App: F4 콜백을 다른 스레드에서 불러도 창은 main 스레드에서만 만들어지는지, F4 중복을 막는지
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import contextlib
import dataclasses
import io
import threading
import time
import tkinter as tk
import unittest

import cache
import checkout_samples as cs
from impulse_guard import config, main, popup, popup_model
from impulse_guard.popup_model import Actions, BlockedView, ImpulseView, Outcome
from impulse_guard.server_client import ApiResult
from test_server_client import FakeServer, make

REASONS = [{'code': 'keyword', 'text': "'특가' 키워드가 들어 있어요."},
           {'code': 'big', 'text': '50,000원 이상의 큰 금액이에요.'},
           {'code': 'night', 'text': '밤 11시~새벽 4시 사이의 심야 쇼핑이에요.'}]
IMPULSE = {'ok': True, 'is_blocking': False, 'is_impulse': 1, 'reasons': REASONS, 'keyword': '특가',
           'point': 496, 'point2': 992, 'event': 'detect', 'bl_id': 7}


def coupang():
    img, boxes, reread = cache.load('coupang_product')
    return main.analyze_boxes(boxes, img, reread)


def no_price(a):
    """가격을 못 읽은 분석 결과"""
    return dataclasses.replace(a, prices=dataclasses.replace(a.prices, sale_price=None, original_price=None,
                                                             discount_rate=None))


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = coupang()

    def test_impulse_view(self):
        kind, v = popup_model.build(self.a, ApiResult(True, IMPULSE))
        self.assertEqual(kind, 'impulse')
        self.assertEqual(v.item_name, '맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩')
        self.assertEqual((v.price_text, v.orig_text, v.rate_text), ('49,600원', '119,000원', '58%'))
        self.assertEqual(v.reasons, ["'특가' 키워드가 들어 있어요.", '50,000원 이상의 큰 금액이에요.'])   # 2개까지
        self.assertEqual(v.point_text, '안 사면 +496P · 24시간 참으면 +992P')
        self.assertTrue(v.can_hold)
        self.assertEqual(v.bl_id, 7)

    def test_not_impulse_is_console_only(self):
        d = {**IMPULSE, 'is_impulse': 0, 'reasons': [], 'keyword': ''}
        self.assertIsNone(popup_model.build(self.a, ApiResult(True, d)))

    def test_blocking_first(self):
        kind, v = popup_model.build(self.a, ApiResult(True, {**IMPULSE, 'is_blocking': True}), block_remain=3600)
        self.assertEqual(kind, 'blocked')
        self.assertEqual(v.remain_sec, 3600)
        self.assertEqual(v.item_name, '맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩')

    def test_offline_or_error_no_popup(self):
        self.assertIsNone(popup_model.build(self.a, ApiResult(False, msg='응답 시간 초과', offline=True)))
        self.assertIsNone(popup_model.build(self.a, ApiResult(False, {'ok': False}, 400, '알 수 없는 요청')))
        self.assertIsNone(popup_model.build(self.a, None))

    def test_not_shopping(self):
        img, boxes, reread = cache.load('news_page')
        self.assertIsNone(popup_model.build(main.analyze_boxes(boxes, img, reread), ApiResult(True, IMPULSE)))

    def test_no_price(self):
        """가격을 못 읽으면 충동구매 판단과 상관없이 팝업. 담아두기는 끈다"""
        d = {**IMPULSE, 'is_impulse': 0, 'reasons': [], 'keyword': '', 'point': 10, 'point2': 20}
        kind, v = popup_model.build(no_price(self.a), ApiResult(True, d))
        self.assertEqual(kind, 'impulse')
        self.assertEqual(v.price_text, popup_model.NO_PRICE_TEXT)
        self.assertEqual((v.price, v.orig_text, v.rate_text), (0, '', ''))
        self.assertEqual(v.reasons, [popup_model.NO_PRICE_REASON])
        self.assertFalse(v.can_hold)
        self.assertIn('가격을 읽지 못해', v.point_text)

    def test_checkout_pending_price(self):
        """결제 화면인데 금액을 못 읽으면 '결제 금액 확인 중'. 나중에 fill_price로 채우면 담아두기를 켠다"""
        a = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        a = dataclasses.replace(a, page=dataclasses.replace(a.page, checkout_total=None, total_label=''))
        kind, v = popup_model.build(a, ApiResult(True, {**IMPULSE, 'reasons': [{'code': 'checkout', 'text': '결제 직전'}]}))
        self.assertEqual((kind, v.price, v.price_text, v.pending, v.can_hold),
                         ('impulse', 0, popup_model.CHECKOUT_PENDING_TEXT, True, False))
        self.assertEqual(v.reasons, ['결제 직전', popup_model.CHECKOUT_PENDING_REASON])
        self.assertEqual(v.point_text, popup_model.CHECKOUT_PENDING_POINT)
        self.assertTrue(popup_model.fill_price(v, 85400))
        self.assertEqual((v.price, v.price_text, v.pending, v.can_hold), (85400, '85,400원', False, True))
        self.assertEqual(v.reasons, ['결제 직전'])
        self.assertEqual(v.point_text, popup_model.FILLED_POINT_TEXT)
        self.assertFalse(popup_model.fill_price(v, 90000))      # 한 번 채우면 다시 바꾸지 않는다

    def test_product_no_price_is_not_pending(self):
        _, v = popup_model.build(no_price(self.a), ApiResult(True, IMPULSE))
        self.assertFalse(v.pending)
        self.assertFalse(popup_model.fill_price(v, 1000))

    def test_no_price_keeps_server_reason(self):
        d = {**IMPULSE, 'reasons': [REASONS[2]]}
        _, v = popup_model.build(no_price(self.a), ApiResult(True, d))
        self.assertEqual(v.reasons, [REASONS[2]['text'], popup_model.NO_PRICE_REASON])

    def test_no_name(self):
        a = dataclasses.replace(self.a, page=dataclasses.replace(self.a.page, item_name=''))
        _, v = popup_model.build(a, ApiResult(True, IMPULSE))
        self.assertEqual((v.item_name, v.api_name), (popup_model.NO_NAME_TEXT, popup_model.NO_NAME_API))

    def test_hms(self):
        self.assertEqual(popup_model.hms(3725), '1시간 2분 5초')
        self.assertEqual(popup_model.hms(59), '59초')
        self.assertEqual(popup_model.hms(-3), '0초')


def view(**kw):
    base = dict(item_name='겨울 패딩', api_name='겨울 패딩', price=49600, price_text='49,600원', orig_text='119,000원',
                rate_text='58%', reasons=["'특가' 키워드가 들어 있어요."], point=496, point2=992,
                point_text='안 사면 +496P · 24시간 참으면 +992P', can_hold=True, bl_id=7)
    base.update(kw)
    return ImpulseView(**base)


class TestActions(unittest.TestCase):
    def actions(self, v=None, **responses):
        fake = FakeServer(**responses)
        client, _ = make(fake)
        client.connect()
        return Actions(client, v or view()), fake

    def test_hold(self):
        act, fake = self.actions(cooldown=(200, {'ok': True, 'cd_id': 3, 'expire': '2026-11-12 08:30:00', 'point2': 992}))
        out = act.hold()
        self.assertEqual(fake.calls[-1], {'client': 'desktop', 'action': 'cooldown', 'item_name': '겨울 패딩',
                                          'price': 49600, 'bl_id': 7})
        self.assertEqual((out.title, out.text), ('타임머신에 담았어요', '2026-11-12 08:30까지 참으면 +992P를 받아요.'))
        self.assertTrue(out.show_link)
        self.assertFalse(out.close or out.error)

    def test_hold_fail_can_retry(self):
        act, _ = self.actions(cooldown=TimeoutError())
        out = act.hold()
        self.assertIn('서버에 연결하지 못했어요', out.error)
        act, _ = self.actions(cooldown=(409, {'ok': False, 'msg': '이미 처리했거나 찾을 수 없는 감지 기록입니다.'}))
        self.assertEqual(act.hold().error, '이미 처리했거나 찾을 수 없는 감지 기록입니다.')

    def test_hold_without_price_sends_nothing(self):
        act, fake = self.actions(view(price=0, can_hold=False))
        self.assertTrue(act.hold().error)
        self.assertEqual(fake.count('cooldown'), 0)

    def test_giveup(self):
        act, fake = self.actions(giveup=(200, {'ok': True, 'cd_id': 4, 'point': 496}))
        out = act.giveup()
        self.assertEqual(fake.calls[-1]['action'], 'giveup')
        self.assertEqual(fake.calls[-1]['bl_id'], 7)
        self.assertEqual((out.title, out.text), ('잘 참았어요!', '+496P를 받았어요.'))

    def test_giveup_daily_limit(self):
        act, _ = self.actions(giveup=(200, {'ok': True, 'cd_id': 4, 'point': 0}))
        self.assertEqual(act.giveup().text, '오늘 받을 수 있는 포인트는 모두 받았어요.')

    def test_giveup_without_price_is_record_only(self):
        act, fake = self.actions(view(price=0, can_hold=False), decide=(200, {'ok': True}))
        out = act.giveup()
        self.assertEqual(fake.calls[-1], {'client': 'desktop', 'action': 'decide', 'bl_id': 7, 'decision': 'giveup'})
        self.assertEqual(fake.count('giveup'), 0)
        self.assertIn('포인트는 없어요', out.text)

    def test_buy_and_close(self):
        for decision, method in (('buy', 'buy'), ('close', 'close')):
            act, fake = self.actions(decide=(200, {'ok': True}))
            out = getattr(act, method)()
            self.assertEqual(fake.calls[-1], {'client': 'desktop', 'action': 'decide', 'bl_id': 7, 'decision': decision})
            self.assertTrue(out.close)
            self.assertIn('기록함', out.console)

    def test_buy_closes_even_if_server_fails(self):
        act, _ = self.actions(decide=TimeoutError())
        out = act.buy()
        self.assertTrue(out.close)
        self.assertIn('기록 실패', out.console)

    def test_no_bl_id_sends_nothing(self):
        act, fake = self.actions(view(bl_id=0))
        self.assertTrue(act.buy().close)
        self.assertEqual(fake.count('decide'), 0)


class FakeActions:
    """버튼 요청 대신 정해 둔 Outcome을 돌려준다 (작업 스레드에서 불림)"""
    def __init__(self, delay=0.0, **outs):
        self.outs = outs
        self.delay = delay
        self.calls = []
        self.threads = []

    def _do(self, name):
        self.calls.append(name)
        self.threads.append(threading.current_thread())
        time.sleep(self.delay)
        return self.outs.get(name) or Outcome(close=name in ('buy', 'close'), console=f'[테스트] {name}')

    def hold(self):
        return self._do('hold')

    def giveup(self):
        return self._do('giveup')

    def buy(self):
        return self._do('buy')

    def close(self):
        return self._do('close')


class TkCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:
            raise unittest.SkipTest(f'화면이 없어 tkinter 테스트를 건너뜀: {e}')
        cls.host = popup.UiHost(cls.root)
        # 테스트는 창을 띄우자마자 버튼을 누르므로 입력 무시 시간을 끈다 (TestInputGuard에서 따로 확인)
        cls._guard = config.POPUP_INPUT_GUARD_SEC
        config.POPUP_INPUT_GUARD_SEC = 0

    @classmethod
    def tearDownClass(cls):
        config.POPUP_INPUT_GUARD_SEC = cls._guard
        cls.host.process()
        cls.host.close()
        cls.root.destroy()

    def pump(self, until, timeout=3.0):
        """main 스레드에서 화면 작업을 처리하며 조건을 기다린다"""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.host.process()
            self.root.update()
            if until():
                return True
            time.sleep(0.01)
        return False


class TestImpulsePopup(TkCase):
    def open(self, v=None, actions=None):
        self.closed = []
        actions = actions or FakeActions()
        p = popup.ImpulsePopup(self.host, v or view(), actions, on_closed=lambda: self.closed.append(1),
                               link_url='http://localhost:8001/ipp/cooldown.php')
        self.root.update()
        return p, actions

    def test_layout_and_font(self):
        p, _ = self.open()
        self.assertIn(self.host.family, config.POPUP_FONTS)          # 한글 글꼴을 찾았다
        self.assertEqual(tk.font.Font(font=p.name_label['font']).actual('family'), self.host.family)
        self.assertEqual(p.win.attributes('-topmost'), 1)
        self.assertEqual(p.name_label['text'], '겨울 패딩')
        self.assertEqual(p.price_label['text'], '49,600원')
        self.assertEqual([lb['text'] for lb in p.reason_labels], ["• '특가' 키워드가 들어 있어요."])
        self.assertEqual(p.point_label['text'], '안 사면 +496P · 24시간 참으면 +992P')
        self.assertEqual(str(p.hold_btn['state']), 'normal')
        self.assertEqual(p.hold_btn['bg'], config.POPUP_COLORS['primary'])
        self.assertEqual(p.giveup_btn['bg'], config.POPUP_COLORS['secondary'])
        self.assertEqual(tk.font.Font(font=p.buy_link['font']).actual('underline'), 1)
        self.assertLessEqual(p.win.winfo_y(), self.host.px(config.POPUP_TOP_MARGIN) + 40)    # 화면 위쪽
        p.destroy()

    def test_hold_shows_result(self):
        out = Outcome('타임머신에 담았어요', '2026-11-12 08:30까지 참으면 +992P를 받아요.', show_link=True)
        p, act = self.open(actions=FakeActions(delay=0.2, hold=out))
        p.hold_btn.invoke()
        p.hold_btn.invoke()                                          # 처리 중에 다시 눌러도 요청은 한 번
        self.assertEqual(str(p.giveup_btn['state']), 'disabled')
        self.assertEqual(p.msg['text'], '담는 중…')
        self.assertTrue(self.pump(lambda: p.done))
        self.assertEqual(act.calls, ['hold'])
        self.assertIsNot(act.threads[0], threading.main_thread())   # 서버 요청은 main 스레드 밖에서
        self.assertEqual(p.result_title['text'], '타임머신에 담았어요')
        self.assertIsNotNone(p.timemachine_link)
        p.on_x()                                                     # 결과 화면의 X는 기록 없이 닫기
        self.assertEqual(act.calls, ['hold'])
        self.assertEqual(self.closed, [1])

    def test_giveup_error_then_retry(self):
        act = FakeActions(giveup=Outcome(error='서버에 연결하지 못했어요. 잠시 뒤 다시 눌러 주세요.'))
        p, _ = self.open(actions=act)
        with quiet():
            p.giveup_btn.invoke()
            self.assertTrue(self.pump(lambda: str(p.giveup_btn['state']) == 'normal' and act.calls))
        self.assertIn('서버에 연결하지 못했어요', p.msg['text'])
        self.assertFalse(p.done)
        act.outs['giveup'] = Outcome('잘 참았어요!', '+496P를 받았어요.')
        p.giveup_btn.invoke()
        self.assertTrue(self.pump(lambda: p.done))
        self.assertEqual(p.result_text['text'], '+496P를 받았어요.')
        p.close_btn.invoke()
        self.assertTrue(p.closed)

    def test_buy_closes_at_once(self):
        p, act = self.open(actions=FakeActions(delay=0.2, buy=Outcome(close=True)))
        with quiet():
            p.buy_link.event_generate('<Button-1>')
            self.assertTrue(p.closed)                                # 기록을 기다리지 않고 바로 닫힌다
            self.assertTrue(self.pump(lambda: act.calls == ['buy']))
        self.assertEqual(self.closed, [1])

    def test_x_records_close(self):
        p, act = self.open()
        with quiet():
            p.on_x()
            self.assertTrue(self.pump(lambda: act.calls == ['close']))
        self.assertTrue(p.closed)

    def test_no_price(self):
        v = view(price=0, price_text=popup_model.NO_PRICE_TEXT, orig_text='', rate_text='', can_hold=False,
                 reasons=[popup_model.NO_PRICE_REASON], point_text='가격을 읽지 못해 담아두기와 포인트를 쓸 수 없어요.')
        p, _ = self.open(v)
        self.assertEqual(p.price_label['text'], '가격을 읽지 못했어요')
        self.assertEqual(str(p.hold_btn['state']), 'disabled')
        self.assertEqual(str(p.giveup_btn['state']), 'normal')
        p.destroy()


class TestFocusAndGuard(TkCase):
    """포커스와 입력 보호 (B-4)"""

    def test_input_guard(self):
        """창이 뜬 직후 누른 버튼(하던 클릭/키 입력)은 무시하고, 시간이 지나면 동작한다"""
        config.POPUP_INPUT_GUARD_SEC = 0.3
        try:
            act = FakeActions(buy=Outcome(close=True))
            p = popup.ImpulsePopup(self.host, view(), act, take_focus=False)
            p.giveup_btn.invoke()
            p.buy_link.event_generate('<Button-1>')
            self.root.update()
            self.assertEqual(act.calls, [])
            self.assertFalse(p.closed)
            time.sleep(0.35)
            p.buy_link.event_generate('<Button-1>')
            self.assertTrue(self.pump(lambda: act.calls == ['buy']))
            self.assertTrue(p.closed)
        finally:
            config.POPUP_INPUT_GUARD_SEC = 0

    def test_x_is_not_guarded(self):
        """X로 닫기는 바로 된다 (사용자가 의도한 동작)"""
        config.POPUP_INPUT_GUARD_SEC = 5
        try:
            act = FakeActions()
            p = popup.ImpulsePopup(self.host, view(), act, take_focus=False)
            with contextlib.redirect_stdout(io.StringIO()):
                p.on_x()
                self.assertTrue(self.pump(lambda: act.calls == ['close']))
        finally:
            config.POPUP_INPUT_GUARD_SEC = 0

    def test_auto_popup_does_not_take_focus(self):
        p = popup.ImpulsePopup(self.host, view(), FakeActions(), take_focus=False)
        self.root.update()
        self.assertEqual(p.win.attributes('-topmost'), 1)
        self.assertNotEqual(str(p.win.focus_get()), str(p.close_btn))
        p.destroy()

    def test_keep_on_top_timer(self):
        p = popup.ImpulsePopup(self.host, view(), FakeActions(), take_focus=False)
        self.assertIn('keep_top', p._afters)
        p.win.attributes('-topmost', False)
        p._keep_top()                                           # 예약된 작업이 하는 일
        self.assertEqual(p.win.attributes('-topmost'), 1)
        p.destroy()
        self.assertEqual(p._afters, {})                         # 닫으면 예약 취소

    def test_blocked_notice_tick_and_keep_top_coexist(self):
        w = popup.BlockedNotice(self.host, BlockedView(100), take_focus=False)
        self.assertEqual(set(w._afters), {'keep_top', 'tick'})
        w.tick()
        self.assertEqual(set(w._afters), {'keep_top', 'tick'})  # tick을 다시 불러도 하나씩만
        w.destroy()


class TestBlockedNotice(TkCase):
    def test_countdown(self):
        now = [100.0]
        closed = []
        w = popup.BlockedNotice(self.host, BlockedView(3600, '겨울 패딩'), on_closed=lambda: closed.append(1),
                                clock=lambda: now[0])
        self.root.update()
        self.assertEqual(w.time_label['text'], '1시간 0분 0초')
        self.assertEqual(w.win.attributes('-topmost'), 1)
        now[0] += 61
        w.tick()
        self.assertEqual(w.time_label['text'], '58분 59초')
        now[0] += 4000
        w.tick()
        self.assertEqual(w.time_label['text'], '차단 시간이 끝났어요')
        w.ok_btn.invoke()
        self.assertEqual(closed, [1])

    def test_unknown_remain(self):
        w = popup.BlockedNotice(self.host, BlockedView(0))
        self.assertEqual(w.time_label['text'], '확인하지 못했어요')
        w.destroy()


class TestApp(TkCase):
    def make_app(self, **responses):
        fake = FakeServer(**responses)
        client, _ = make(fake)
        client.connect()
        a = coupang()
        self.analyzed = []
        app = main.App(client, self.host, analyze=lambda: self.analyzed.append(1) or a)
        made_in = []
        orig_show = app.show
        app.show = lambda kind, v, **kw: (made_in.append(threading.current_thread()), orig_show(kind, v, **kw))
        return app, fake, made_in

    def press_f4(self, app):
        """keyboard 스레드처럼 다른 스레드에서 F4 콜백을 부른다"""
        t = threading.Thread(target=app.on_hotkey)
        t.start()
        t.join()

    def test_popup_from_other_thread(self):
        app, fake, made_in = self.make_app(check=(200, IMPULSE), decide=(200, {'ok': True}))
        with quiet():
            self.press_f4(app)
            self.assertTrue(self.pump(lambda: app.window is not None))
            self.assertEqual(made_in, [threading.main_thread()])        # 창은 main 스레드에서만
            self.assertIsInstance(app.window, popup.ImpulsePopup)
            self.assertTrue(app.window.take_focus)                    # F4 창은 포커스를 가져온다
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.press_f4(app)                                     # 창이 떠 있으면 무시
            self.assertIn('알림 창이 열려 있어요', out.getvalue())
            self.assertEqual(len(self.analyzed), 1)
            app.window.on_x()
            self.assertTrue(self.pump(lambda: fake.count('decide') == 1))
            self.assertIsNone(app.window)
            self.press_f4(app)                                         # 닫으면 다시 받는다
            self.assertTrue(self.pump(lambda: app.window is not None))
            app.window.destroy()

    def test_blocked_notice(self):
        app, _, _ = self.make_app(check=(200, {**IMPULSE, 'is_blocking': True, 'event': 'blocked'}))
        with quiet():
            self.press_f4(app)
            self.assertTrue(self.pump(lambda: app.window is not None))
        self.assertIsInstance(app.window, popup.BlockedNotice)
        # 가짜 서버 setting의 block_remain 3600 (창을 띄우는 사이 실제 시간이 1초 지났을 수 있다)
        self.assertIn(app.window.time_label['text'], ('1시간 0분 0초', '59분 59초'))
        app.window.ok_btn.invoke()
        self.assertIsNone(app.window)

    def test_offline_console_only(self):
        app, _, made_in = self.make_app(check=TimeoutError())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.press_f4(app)
            self.assertTrue(self.pump(lambda: app._busy.acquire(blocking=False)))   # 작업이 끝나 잠금이 풀림
        app._busy.release()
        self.assertIn('오프라인이라 알림 창은 띄우지 않았습니다', out.getvalue())
        self.assertEqual(made_in, [])

    def test_not_impulse_console_only(self):
        app, _, made_in = self.make_app(check=(200, {**IMPULSE, 'is_impulse': 0, 'reasons': [], 'keyword': ''}))
        with quiet():
            self.press_f4(app)
            self.assertTrue(self.pump(lambda: app._busy.acquire(blocking=False)))
        app._busy.release()
        self.assertEqual(made_in, [])


if __name__ == '__main__':
    unittest.main()
