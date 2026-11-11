"""자동 감지 테스트 (B-4)

- AutoDetector: 일시 중지, 자기 콘솔, 같은 화면(OCR 생략), 바뀌는 중(기다림), 분석, 종료
- App.handle_auto: 단계별 정책 (상품 화면은 서버 호출 없음, 결제 화면은 팝업 한 번, 차단 안내 재표시 간격)
  가짜 서버 + 실제 tkinter 창
- DetectLog: 로그 파일, 콘솔 줄 줄이기, OCR 원문 저장(끔/켬, 결제 화면 제외, 마스킹), 캡처 이미지 저장 안 함
- auto_settings: local_config.json의 auto_detect 값
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import dataclasses
import unittest
from unittest import mock

import numpy as np

import cache
import checkout_samples as cs
from impulse_guard import auto_detect, config, main, popup, popup_model, server_client, timing
from impulse_guard.capture import Frame
from impulse_guard.dedup import title_key
from impulse_guard.detect_log import DetectLog, mask_private
from test_popup import TkCase
from test_server_client import FakeServer, make

NOT_BLOCKING = {'ok': True, 'is_blocking': False, 'block_until': None, 'block_remain': 0, 'block_all': True,
                'sites': [{'code': 'coupang', 'name': '쿠팡', 'domain': 'coupang.com', 'on': True},
                          {'code': 'musinsa', 'name': '무신사', 'domain': 'musinsa.com', 'on': False}],
                'keywords': ['특가'], 'risk_alert': True}
BLOCKING = {**NOT_BLOCKING, 'is_blocking': True, 'block_until': '2026-11-11 23:59:59', 'block_remain': 3600}
CHECKOUT_RESULT = {'ok': True, 'is_blocking': False, 'is_impulse': 1,
                   'reasons': [{'code': 'checkout', 'text': '결제 직전이에요. 정말 지금 필요한 물건인지 한 번만 더 생각해 봐요.'}],
                   'keyword': '', 'point': 496, 'point2': 992, 'event': 'detect', 'bl_id': 200}
BLOCKED_RESULT = {**CHECKOUT_RESULT, 'is_blocking': True, 'event': 'blocked', 'bl_id': 201}

H1, H2, H3 = 0, (1 << 128) - 1, ((1 << 256) - 1) ^ ((1 << 128) - 1)   # 서로 128비트 이상 다름


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


# ── 자동 감지 루프 ──────────────────────────────────────────────

class FakeApp:
    def __init__(self):
        self.is_paused = False
        self.busy = False
        self.same = 0
        self.runs = []
        self.timings = []
        self.titles = []
        self.run_delay = 0.0

    def paused(self):
        return self.is_paused

    def try_begin(self):
        return not self.busy

    def still_same(self):
        self.same += 1

    def run_auto(self, img, h, title=None):
        self.runs.append(h)
        self.titles.append(title)
        self.timings.append(timing.current())
        time.sleep(self.run_delay)


class Script:
    """캡처 순서를 정해 두는 가짜 grab/hasher. 이미지 대신 해시 값을 넣는다"""
    def __init__(self, *hashes, title='', exe='chrome.exe'):
        self.hashes = list(hashes)
        self.title = title
        self.exe = exe
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        h = self.hashes.pop(0) if len(self.hashes) > 1 else self.hashes[0]
        return Frame(img=h, foreground_title=self.title, foreground_exe=self.exe)

    @staticmethod
    def hasher(img):
        return img


class TestAutoDetectorTick(unittest.TestCase):
    def detector(self, script, app=None):
        app = app or FakeApp()
        return auto_detect.AutoDetector(app, 3, grab=script.grab, hasher=script.hasher), app

    def test_waits_until_stable_then_analyzes_once(self):
        d, app = self.detector(Script(H1, H1, H1, H1))
        results = [d.tick() for _ in range(4)]
        self.assertEqual(results, ['changing', 'analyzed', 'same', 'same'])
        self.assertEqual(app.runs, [H1])                 # 같은 화면은 한 번만 OCR
        self.assertEqual(app.same, 2)                    # 머무는 동안 still_same으로 알린다

    def test_scrolling_waits(self):
        d, app = self.detector(Script(H1, H2, H3, H3))
        self.assertEqual([d.tick() for _ in range(4)], ['changing', 'changing', 'changing', 'analyzed'])
        self.assertEqual(app.runs, [H3])

    def test_timing_passed_to_analysis(self):
        """B-5: 분석 회차에 기다린 시간(간격, 멈춤 확인)과 캡처/해시 시간이 담긴 측정이 넘어간다"""
        d, app = self.detector(Script(H1, H1, H1, H2, H3, H3))
        self.assertEqual([d.tick() for _ in range(6)], ['changing', 'analyzed', 'same', 'changing', 'changing', 'analyzed'])
        t = app.timings[-1]
        self.assertIsInstance(t, timing.Timing)
        self.assertEqual(t.changing, 2)                  # H2, H3에서 바뀌는 중
        for key in ('interval_wait', 'settle_wait', 'capture', 'hash'):
            self.assertIn(key, t.sec)
        self.assertIsNotNone(t.detected_at)
        self.assertIsNone(d.change_at)                   # 분석한 뒤에는 지운다
        self.assertIsNone(timing.current())              # 측정은 분석하는 동안만

    # ── 제목으로 빨리 확인 (B-5) ──
    def test_checkout_title_shortens_settle(self):
        d, _ = self.detector(Script(H1, H2, title='주문/결제 | 지그재그'))
        self.assertEqual(d.tick(), 'changing')
        self.assertTrue(d.checkout_title)
        self.assertEqual(d.next_wait(), config.AUTO_FAST_SETTLE_SEC)

    def test_other_title_keeps_settle(self):
        d, _ = self.detector(Script(H1, H2, title='뉴스 - 오늘의 소식'))
        self.assertEqual(d.tick(), 'changing')
        self.assertEqual(d.next_wait(), config.AUTO_SETTLE_SEC)

    def test_title_info_in_timing_without_title_text(self):
        d, app = self.detector(Script(H1, H1, title='주문서 작성 - 무신사'))
        self.assertEqual([d.tick(), d.tick()], ['changing', 'analyzed'])
        t = app.timings[-1]
        self.assertEqual(t.info['제목'], '결제 페이지')
        self.assertNotIn('무신사', t.line())

    def wait_detector(self, titles):
        titles = list(titles)
        d, _ = self.detector(Script(H1))
        d.title_fn = lambda: titles.pop(0) if len(titles) > 1 else titles[0]
        d.last_title = '상품 상세 - 지그재그'
        return d

    def test_wait_wakes_when_title_becomes_checkout(self):
        d = self.wait_detector(['상품 상세 - 지그재그', '결제 - 지그재그'])
        started = time.perf_counter()
        with mock.patch.object(config, 'AUTO_TITLE_POLL_SEC', 0.01):
            self.assertFalse(d.wait(5))
        self.assertLess(time.perf_counter() - started, 1)
        self.assertTrue(d.title_woke)
        self.assertTrue(d.checkout_title)

    def test_wait_full_when_title_not_checkout(self):
        d = self.wait_detector(['상품 상세 - 지그재그', '장바구니 - 지그재그'])
        started = time.perf_counter()
        with mock.patch.object(config, 'AUTO_TITLE_POLL_SEC', 0.01):
            self.assertFalse(d.wait(0.15))
        self.assertGreaterEqual(time.perf_counter() - started, 0.14)
        self.assertFalse(d.title_woke)

    def test_wait_stops_on_stop(self):
        d = self.wait_detector(['상품 상세 - 지그재그'])
        d._stop_event.set()
        self.assertTrue(d.wait(5))

    def test_own_popup_window_not_captured(self):
        """팝업을 클릭해 팝업이 맨 앞 창이면 캡처/분석하지 않는다 (실제 로그: 422x556 팝업만 캡처)"""
        for title in config.OWN_WINDOW_TITLES:
            d, app = self.detector(Script(H1, H1, title=title))
            self.assertEqual([d.tick(), d.tick()], ['own-console', 'own-console'])
            self.assertEqual(app.runs, [])

    # ── 팝업이 맨 앞 창일 때 (B-5 버그: 확인 중 팝업에 금액이 안 채워짐) ──
    def popup_front_detector(self, behind, amount=True):
        """맨 앞 창은 우리 팝업, 그 전에 본 브라우저 창(hwnd 77). behind: grab_window가 돌려줄 Frame (None이면 못 구함)"""
        frames = [Frame(img=H1, foreground_title='zigzag.kr/checkout/order-sheets/a1', foreground_exe='chrome.exe', hwnd=77)]
        popup_frame = Frame(img=H3, foreground_title='충동구매 알림', foreground_exe='python.exe', hwnd=99)
        grabs = []

        def grab():
            return frames.pop(0) if frames else popup_frame

        def grab_window(hwnd):
            grabs.append(hwnd)
            return behind() if callable(behind) else behind
        app = FakeApp()
        app.amount_runs = []
        app.run_amount = lambda img, h, title=None, origin=None: app.amount_runs.append((h, title, origin))
        d = auto_detect.AutoDetector(app, 3, grab=grab, hasher=Script.hasher, grab_window=grab_window)
        self.assertEqual(d.tick(), 'changing')            # 브라우저를 본다 → target_hwnd 77
        self.assertEqual(d.target_hwnd, 77)
        app.is_paused = True                              # 팝업이 떴다
        app.wants_amount = lambda: amount
        return d, app, grabs

    def test_popup_in_front_captures_browser_behind(self):
        """실제 버그 (02:40:47~02:41:05 own-console 7번): 확인 중 팝업이 맨 앞 창이 되면 금액 확인 회차를 모두 건너뛰었다.
        마우스 휠 스크롤은 맨 앞 창을 바꾸지 않으므로, 팝업 아래의 브라우저 창(target_hwnd)을 직접 캡처한다"""
        browser = Frame(img=H2, foreground_title='zigzag.kr/checkout/order-sheets/a1', foreground_exe='chrome.exe',
                        origin=(10, 20), scope='window', hwnd=77)
        d, app, grabs = self.popup_front_detector(lambda: dataclasses.replace(browser))
        self.assertEqual([d.tick(), d.tick()], ['changing', 'amount'])    # 스크롤해서 바뀌고 → 멈추면 금액 확인
        self.assertEqual(grabs, [77, 77])
        self.assertTrue(d.behind_popup)
        self.assertEqual(app.amount_runs, [(H2, 'zigzag.kr/checkout/order-sheets/a1', (10, 20))])
        self.assertEqual(d.target_hwnd, 77)

    def test_popup_in_front_without_browser_skips(self):
        d, app, grabs = self.popup_front_detector(None)
        self.assertEqual(d.tick(), 'own-console')
        self.assertEqual(grabs, [77])

    def test_popup_in_front_not_waiting_amount_skips(self):
        """금액 확인 중이 아니면(금액 팝업, 차단 안내) 예전처럼 쉰다"""
        d, app, grabs = self.popup_front_detector(None, amount=False)
        self.assertEqual(d.tick(), 'paused')
        self.assertEqual(grabs, [])

    def test_target_hwnd_not_from_excluded_program(self):
        frames = [Frame(img=H1, foreground_title='zigzag', foreground_exe='chrome.exe', hwnd=77),
                  Frame(img=H2, foreground_title='코드', foreground_exe='Code.exe', hwnd=55)]
        d = auto_detect.AutoDetector(FakeApp(), 3, grab=lambda: frames.pop(0), hasher=Script.hasher,
                                     exclude_programs=['Code.exe'])
        self.assertEqual([d.tick(), d.tick()], ['changing', 'excluded'])
        self.assertEqual(d.target_hwnd, 77)

    def test_checkout_title_shortens_interval(self):
        """제목이 결제 페이지인 동안은 확인 간격도 짧게 (결제 페이지 안 스크롤을 빨리 본다)"""
        d, _ = self.detector(Script(H1, H1, H1, title='zigzag.kr/checkout/order-sheets/a1b2c3d4e5'))
        self.assertEqual([d.tick(), d.tick(), d.tick()], ['changing', 'analyzed', 'same'])
        self.assertEqual(d.next_wait(), config.AUTO_CHECKOUT_INTERVAL_SEC)
        d2, _ = self.detector(Script(H1, H1, H1, title='뉴스'))
        [d2.tick() for _ in range(3)]
        self.assertEqual(d2.next_wait(), 3)

    def test_amount_mode_while_pending_popup(self):
        """'결제 금액 확인 중' 팝업이 떠 있으면 쉬지 않고, 화면이 멈추면 run_amount (잠금은 잡지 않음)"""
        app = FakeApp()
        app.is_paused = True
        app.wants_amount = lambda: True
        app.amount_runs = []
        app.run_amount = lambda img, h, title=None, origin=None: app.amount_runs.append((h, title, origin))
        d, _ = self.detector(Script(H1, H1, H1, title='zigzag.kr/checkout/order-sheets/a1b2c3d4e5'), app)
        self.assertEqual([d.tick(), d.tick(), d.tick()], ['changing', 'amount', 'same'])
        self.assertEqual(app.amount_runs, [(H1, 'zigzag.kr/checkout/order-sheets/a1b2c3d4e5', (0, 0))])
        self.assertEqual(app.runs, [])
        app.wants_amount = lambda: False                 # 결정했거나 금액을 채우면 다시 쉰다
        self.assertEqual(d.tick(), 'paused')

    def test_new_screen_after_analysis(self):
        d, app = self.detector(Script(H1, H1, H2, H2))
        self.assertEqual([d.tick() for _ in range(4)], ['changing', 'analyzed', 'changing', 'analyzed'])
        self.assertEqual(app.runs, [H1, H2])

    def test_paused_does_not_capture(self):
        script = Script(H1)
        d, app = self.detector(script)
        app.is_paused = True
        self.assertEqual(d.tick(), 'paused')
        self.assertEqual(script.grabs, 0)

    def test_excluded_programs(self):
        """맨 앞 창이 감지 제외 프로그램이면 캡처만 하고 분석하지 않는다 (대소문자 무시)"""
        script = Script(H1, exe='code.EXE')
        app = FakeApp()
        d = auto_detect.AutoDetector(app, 3, grab=script.grab, hasher=script.hasher,
                                     exclude_programs=['Code.exe', 'WindowsTerminal.exe'])
        self.assertEqual([d.tick(), d.tick(), d.tick()], ['excluded'] * 3)
        self.assertEqual(app.runs, [])
        script.exe = 'chrome.exe'                        # 브라우저로 돌아오면 멈췄는지 처음부터 본다
        self.assertEqual([d.tick(), d.tick()], ['changing', 'analyzed'])

    def test_no_exclusion_by_default(self):
        d, app = self.detector(Script(H1, H1, exe='Code.exe'))
        self.assertEqual([d.tick(), d.tick()], ['changing', 'analyzed'])

    def test_own_console_skipped(self):
        d, app = self.detector(Script(H1, title=config.CONSOLE_TITLE))
        self.assertEqual([d.tick(), d.tick()], ['own-console', 'own-console'])
        self.assertEqual(app.runs, [])

    def test_busy(self):
        d, app = self.detector(Script(H1, H1, H1))
        app.busy = True
        self.assertEqual([d.tick(), d.tick()], ['changing', 'busy'])
        app.busy = False
        self.assertEqual(d.tick(), 'analyzed')           # 바쁠 때 못 한 분석은 다음 회차에

    def test_small_animation_counts_as_settled(self):
        """광고 배너처럼 조금씩 움직이는 화면도 멈춘 것으로 본다 (같은 화면 기준 6비트보다 느슨한 12비트)"""
        moving = H1 ^ 0b1111111111                     # 10비트 차이
        d, app = self.detector(Script(H1, moving))
        self.assertEqual([d.tick(), d.tick()], ['changing', 'analyzed'])

    def test_wait_short_while_changing(self):
        """바뀌는 중이면 1초 뒤 다시 보고, 그 밖에는 설정한 간격"""
        d, _ = self.detector(Script(H1, H1, H1))
        self.assertEqual(d.next_wait(), 3)
        d.tick()                                       # changing
        self.assertEqual(d.next_wait(), config.AUTO_SETTLE_SEC)
        d.tick()                                       # analyzed
        self.assertEqual(d.next_wait(), 3)

    def test_screen_analyzed_by_f4_is_not_analyzed_again(self):
        d, app = self.detector(Script(H2, H2))
        app.last_frame_hash = H2                       # F4가 방금 이 화면을 분석함
        self.assertEqual(d.tick(), 'same')
        self.assertEqual(app.runs, [])

    def test_counts(self):
        d, _ = self.detector(Script(H1, H1, H1))
        for _ in range(3):
            d.tick()
        self.assertEqual(d.counts, {'changing': 1, 'analyzed': 1, 'same': 1})


class TestAutoDetectorThread(unittest.TestCase):
    def test_start_and_stop(self):
        app = FakeApp()
        d = auto_detect.AutoDetector(app, 0.01, grab=Script(H1).grab, hasher=Script.hasher)
        d.start()
        time.sleep(0.1)
        started = time.monotonic()
        self.assertTrue(d.stop())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertFalse(d.is_alive())
        self.assertEqual(app.runs, [H1])

    def test_stop_while_analyzing(self):
        """OCR 중이면 기다리는 시간만큼만 기다리고, 분석이 끝나면 스레드도 끝난다"""
        app = FakeApp()
        app.run_delay = 0.5
        d = auto_detect.AutoDetector(app, 0.01, grab=Script(H1).grab, hasher=Script.hasher)
        d.start()
        while not app.runs:
            time.sleep(0.005)
        self.assertFalse(d.stop(wait=0.05))
        d.join(2)
        self.assertFalse(d.is_alive())
        self.assertEqual(len(app.runs), 1)               # 멈춘 뒤에는 더 분석하지 않는다

    def test_start_is_logged(self):
        tmp = tempfile.mkdtemp()
        log = DetectLog(tmp, console=False)
        d = auto_detect.AutoDetector(FakeApp(), 0.01, grab=Script(H1).grab, hasher=Script.hasher, log=log,
                                     exclude_programs=['Code.exe'])
        d.start()
        time.sleep(0.05)
        d.stop()
        log.close()
        with open(os.path.join(tmp, config.LOG_FILE), encoding='utf-8') as f:
            first = f.readline()
        shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("자동 감지 시작: 0.01초 간격", first)
        self.assertIn("['code.exe']", first)

    def test_error_in_tick_keeps_running(self):
        calls = []

        def grab():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('캡처 실패')
            return Frame(img=H1)
        d = auto_detect.AutoDetector(FakeApp(), 0.01, grab=grab, hasher=Script.hasher)
        with quiet():
            d.start()
            time.sleep(0.1)
            d.stop()
        self.assertGreater(len(calls), 2)


# ── 단계별 정책 ────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


class TestHandleAuto(TkCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        img, boxes, reread = cache.load('coupang_product')
        cls.product = main.analyze_boxes(boxes, img, reread)
        img, boxes, reread = cache.load('news_page')
        cls.news = main.analyze_boxes(boxes, img, reread)
        cls.checkout = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        cls.musinsa_checkout = main.analyze_boxes(cs.MUSINSA_CHECKOUT)

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = DetectLog(self.dir, console=False)

    def tearDown(self):
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def make_app(self, setting=NOT_BLOCKING, **responses):
        self.fake = FakeServer(setting=(200, setting), **responses)
        client, _ = make(self.fake)
        client.connect()
        client.get_setting()
        self.clock = Clock()
        app = main.App(client, self.host, settings=server_client.auto_settings(), log=self.log, clock=self.clock)
        return app

    def handle(self, app, a, h):
        """자동 감지 스레드처럼 잠금을 잡고 처리한다. 창이 뜨면 기다린다"""
        self.assertTrue(app.try_begin())
        shown = app.handle_auto(a, h)
        if shown:
            self.assertTrue(self.pump(lambda: app.window is not None))
        else:
            app._busy.release()
        return shown

    def close_window(self, app):
        with quiet():
            app.window.destroy()
            self.pump(lambda: app.window is None)

    def log_lines(self, timing_lines=False):
        """감지 결과 줄 (timing_lines=True면 B-5 시간 측정 줄만)"""
        with open(os.path.join(self.dir, config.LOG_FILE), encoding='utf-8') as f:
            lines = f.read().splitlines()
        return [line for line in lines if (' INFO timing ' in line) == timing_lines]

    def test_product_screen_no_server_call(self):
        app = self.make_app()
        self.assertFalse(self.handle(app, self.product, H1))
        self.assertEqual(self.fake.count('check'), 0)
        self.assertEqual(app.last_product['coupang'][:2], ('맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩', 49600))
        self.assertIn('auto | 상품 화면 | coupang | 49,600원 | 점수 0/4 [] | new', self.log_lines()[-1])

    def test_checkout_popup_once(self):
        app = self.make_app(check=(200, CHECKOUT_RESULT), giveup=(200, {'ok': True, 'cd_id': 9, 'point': 496}))
        self.handle(app, self.product, H1)
        self.assertTrue(self.handle(app, self.checkout, H2))
        sent = self.fake.calls[-1]
        self.assertEqual((sent['action'], sent['is_checkout'], sent['price'], sent['page']), ('check', True, 49600, ''))
        self.assertEqual(sent['item_name'], '맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩')   # 최근 본 상품 이름
        self.assertEqual((sent['orig_price'], sent['discount_rate']), (0, 0))
        w = app.window
        self.assertIsInstance(w, popup.ImpulsePopup)
        self.assertFalse(w.take_focus)                            # 자동 감지 창은 포커스를 가져가지 않는다
        self.assertEqual(w.title_label['text'], '결제하기 전에 잠깐만요!')
        self.assertEqual(w.price_label['text'], '49,600원')
        self.assertEqual(w.view.orig_text, '')
        # 안 살래요 → 결정을 기억
        with quiet():
            w.giveup_btn.invoke()
            self.assertTrue(self.pump(lambda: w.done))
        self.close_window(app)
        self.assertEqual(app.orders.orders[0].decision, 'giveup')
        # 같은 결제 화면 (머무름), 다른 화면에 갔다 옴 → 다시 뜨지 않고 서버도 부르지 않음
        checks = self.fake.count('check')
        self.assertFalse(self.handle(app, self.checkout, H2))
        self.handle(app, self.news, H3)
        self.clock.t += 120
        self.assertFalse(self.handle(app, self.checkout, H2))
        self.assertEqual(self.fake.count('check'), checks)
        lines = self.log_lines()
        self.assertIn('| same |', lines[-3])
        self.assertIn('| revisit |', lines[-1])
        self.assertIn('120초 만에 다시 옴, 결정: giveup', lines[-1])
        # 10분 넘게 떠나 있다 돌아오면 새 시도
        self.handle(app, self.news, H3)
        self.clock.t += 11 * 60
        self.assertTrue(self.handle(app, self.checkout, H2))
        self.assertEqual(self.fake.count('check'), checks + 1)
        self.close_window(app)

    def test_checkout_prefers_recent_product_name(self):
        """결제 화면에서 읽은 이름(브랜드명이 잡히기도 함)보다 같은 쇼핑몰에서 최근 본 상품 이름을 먼저 쓴다"""
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        img, boxes, reread = cache.load('checkout_musinsa')
        real = main.analyze_boxes(boxes, img, reread)
        self.assertTrue(real.page.item_name)                     # 결제 화면에서도 무언가 읽힌다
        app.last_product['musinsa'] = ('밍크퍼 후드 집업 자켓', 109000, self.clock())
        self.handle(app, real, H1)
        self.assertEqual(self.fake.calls[-1]['item_name'], '밍크퍼 후드 집업 자켓')
        self.assertEqual(self.fake.calls[-1]['price'], 79000)
        self.close_window(app)

    def test_f4_checkout_then_auto_does_not_popup_again(self):
        """F4로 결제 화면 팝업을 띄우고 닫은 뒤, 자동 감지가 같은 주문을 보면 다시 띄우지 않는다 (사용자 테스트에서 발견)"""
        app = self.make_app(check=(200, CHECKOUT_RESULT), decide=(200, {'ok': True}))
        self.checkout.frame_hash = H1
        app.analyze = lambda: self.checkout
        self.assertTrue(app._busy.acquire(blocking=False))
        with quiet():
            app.work()                                          # F4 작업 스레드가 하는 일
            self.assertTrue(self.pump(lambda: app.window is not None))
        self.assertEqual(app.window.title_label['text'], '결제하기 전에 잠깐만요!')   # F4도 결제 화면 문구
        self.assertTrue(app.window.take_focus)
        self.assertIn("팝업 제목 '결제하기 전에 잠깐만요!'", self.log_lines()[-1])
        self.assertEqual(app.last_frame_hash, H1)
        with quiet():
            app.window.on_x()
            self.assertTrue(self.pump(lambda: app.window is None and self.fake.count('decide') == 1))
        self.assertEqual(app.orders.orders[0].decision, 'close')
        checks = self.fake.count('check')
        self.assertFalse(self.handle(app, self.checkout, H2))  # 자동 감지: 같은 쇼핑몰+금액 → 같은 주문
        self.assertEqual(self.fake.count('check'), checks)
        self.assertIn('결정: close', self.log_lines()[-1])
        self.checkout.frame_hash = None

    def test_auto_popup_title_logged(self):
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        self.handle(app, self.checkout, H1)
        self.assertIn("→ popup", self.log_lines()[-1])
        self.assertIn("팝업 제목 '결제하기 전에 잠깐만요!'", self.log_lines()[-1])
        self.close_window(app)

    def test_checkout_without_known_product_uses_site_name(self):
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        self.handle(app, self.musinsa_checkout, H1)
        self.assertEqual(self.fake.calls[-1]['item_name'], '무신사 주문')
        self.assertEqual(self.fake.calls[-1]['price'], cs.MUSINSA_TOTAL)
        self.close_window(app)

    def test_checkout_popup_even_if_old_server_says_not_impulse(self):
        old = {**CHECKOUT_RESULT, 'is_impulse': 0, 'reasons': []}
        app = self.make_app(check=(200, old))
        self.assertTrue(self.handle(app, self.checkout, H1))
        self.assertEqual(app.window.view.reasons[0], popup_model.CHECKOUT_FALLBACK_REASON)
        self.close_window(app)

    def test_checkout_offline(self):
        app = self.make_app(check=TimeoutError())
        with quiet():
            self.assertFalse(self.handle(app, self.checkout, H1))
        self.assertIsNone(app.window)
        self.assertIn('서버 연결 안 됨', self.log_lines()[-1])

    def test_blocked_notice_repeat_interval(self):
        app = self.make_app(setting=BLOCKING, check=(200, BLOCKED_RESULT))
        self.assertTrue(self.handle(app, self.product, H1))     # 차단 중에는 상품 화면도 차단 안내
        self.assertIsInstance(app.window, popup.BlockedNotice)
        self.assertEqual(self.fake.calls[-1]['action'], 'check')
        self.close_window(app)
        checks = self.fake.count('check')
        self.clock.t += 59
        self.assertFalse(self.handle(app, self.product, H2))    # 60초 안에는 다시 띄우지 않고 기록도 안 함
        self.assertEqual(self.fake.count('check'), checks)
        self.assertIn('| wait |', self.log_lines()[-1])
        self.clock.t += 1
        self.assertTrue(self.handle(app, self.product, H3))
        self.close_window(app)

    def test_blocked_repeat_from_settings(self):
        app = self.make_app(setting=BLOCKING, check=(200, BLOCKED_RESULT))
        app.gate.repeat = 5                                      # local_config.json의 blocked_repeat_sec
        self.handle(app, self.product, H1)
        self.close_window(app)
        self.clock.t += 5
        self.assertTrue(self.handle(app, self.product, H2))
        self.close_window(app)

    def test_block_all_off_only_listed_sites(self):
        setting = {**BLOCKING, 'block_all': False}
        app = self.make_app(setting=setting)
        musinsa_product = main.analyze_boxes(*cache.load('musinsa_product')[1:2])
        self.assertFalse(self.handle(app, musinsa_product, H1))  # 무신사는 꺼져 있음 → 차단 아님, 상품 화면
        self.assertEqual(self.fake.count('check'), 0)

    def test_setting_refreshed_when_entering_shopping(self):
        """쇼핑 아님 → 쇼핑 화면이면 캐시(1분)를 무시하고 설정을 다시 받는다. 쇼핑 화면이 이어지면 캐시를 쓴다"""
        app = self.make_app()
        base = self.fake.count('setting')
        self.handle(app, self.product, H1)                      # 처음 본 쇼핑 화면 (직전: 쇼핑 아님)
        self.assertEqual(self.fake.count('setting'), base + 1)
        self.handle(app, self.product, H2)                      # 쇼핑 화면 → 쇼핑 화면: 다시 받지 않음
        self.assertEqual(self.fake.count('setting'), base + 1)
        self.handle(app, self.news, H3)                         # 쇼핑 아님
        self.assertEqual(self.fake.count('setting'), base + 1)
        self.handle(app, self.product, H1)                      # 다시 들어옴
        self.assertEqual(self.fake.count('setting'), base + 2)

    def test_block_started_just_now_is_caught(self):
        """설정 캐시는 차단 전 것이어도, 쇼핑 화면에 들어서는 순간 다시 받아 차단 안내를 띄운다"""
        app = self.make_app(check=(200, BLOCKED_RESULT))
        self.handle(app, self.news, H1)
        self.fake.responses['setting'] = (200, BLOCKING)        # 웹에서 방금 차단 시작
        self.assertTrue(self.handle(app, self.product, H2))
        self.assertIsInstance(app.window, popup.BlockedNotice)
        self.close_window(app)

    def test_cache_is_one_minute(self):
        self.assertEqual(config.SETTING_CACHE_SEC, 60)

    def test_not_shopping(self):
        app = self.make_app()
        self.assertFalse(self.handle(app, self.news, H1))
        self.assertEqual(self.fake.count('check'), 0)
        self.assertIn('쇼핑 아님', self.log_lines()[-1])

    def test_run_auto_releases_lock(self):
        app = self.make_app()
        self.assertTrue(app.try_begin())
        app.analyze_frame = lambda img: self.product
        self.assertFalse(app.run_auto(object(), H1))
        self.assertFalse(app.paused())

    def test_run_auto_error_releases_lock(self):
        app = self.make_app()
        self.assertTrue(app.try_begin())

        def boom(img):
            raise RuntimeError('OCR 실패')
        app.analyze_frame = boom
        with quiet():
            app.run_auto(object(), H1)
        self.assertFalse(app.paused())

    # ── 결제 금액 확인 중 팝업 (B-5) ──
    def no_amount(self):
        a = self.checkout
        return dataclasses.replace(a, page=dataclasses.replace(a.page, checkout_total=None, total_label=''))

    def pending_app(self):
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        a = self.no_amount()
        self.assertEqual(a.amount, 0)
        self.assertTrue(self.handle(app, a, H1))
        self.assertTrue(app.window.view.pending)
        self.assertEqual(app.window.price_label['text'], popup_model.CHECKOUT_PENDING_TEXT)
        self.assertEqual(str(app.window.hold_btn['state']), 'disabled')
        self.assertTrue(app.wants_amount())
        return app

    def test_pending_popup_filled_when_amount_read(self):
        """금액을 못 읽은 결제 화면도 팝업('결제 금액 확인 중'), 떠 있는 동안 금액을 읽으면 팝업과 주문 기록에 채운다"""
        app = self.pending_app()
        seen = []
        app.analyze_frame = lambda img: seen.append(img) or dataclasses.replace(self.checkout)
        img = np.zeros((900, 1600, 3), np.uint8)
        with mock.patch.object(main.capture, 'monitor_origin', return_value=(0, 0)):
            self.assertTrue(app.run_amount(img, H2, None))
        self.assertTrue(self.pump(lambda: app.window.view.price == 49600))
        w = app.window
        self.assertEqual(w.price_label['text'], '49,600원')
        self.assertEqual(str(w.hold_btn['state']), 'normal')
        self.assertNotIn(popup_model.CHECKOUT_PENDING_REASON, [lb.reason for lb in w.reason_labels])
        self.assertEqual(app.orders.orders[0].amount, 49600)
        self.assertFalse(app.wants_amount())
        x0, y0, x1, y1 = w.screen_rect                   # 팝업 영역은 지우고 OCR (팝업 자기 글자를 읽지 않게)
        cy, cx = min((y0 + y1) // 2, 899), min((x0 + x1) // 2, 1599)
        self.assertTrue((seen[0][cy, cx] == 255).all())
        self.assertIn('팝업 금액 채움', self.log_lines()[-1])
        self.close_window(app)

    def test_pending_popup_not_filled_by_other_order(self):
        """팝업이 떠 있는 동안 다른 주문서(탭 제목이 다름)로 가서 읽은 금액은 채우지 않는다"""
        app = self.pending_app()
        app.pending.order.title = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        app.analyze_frame = lambda img: dataclasses.replace(self.checkout)
        with mock.patch.object(main.capture, 'monitor_origin', return_value=(0, 0)):
            self.assertFalse(app.run_amount(np.zeros((900, 1600, 3), np.uint8), H2,
                                            'zigzag.kr/checkout/order-sheets/f6e7d8c9b0'))
        self.assertTrue(app.window.view.pending)
        self.assertEqual(app.orders.orders[0].amount, 0)
        self.assertIn('다른 주문이라 채우지 않음', self.log_lines()[-1])
        self.close_window(app)

    def test_pending_cleared_on_close(self):
        app = self.pending_app()
        self.close_window(app)
        self.assertIsNone(app.pending)
        self.assertFalse(app.wants_amount())

    def test_pending_popup_mask_uses_capture_origin(self):
        """맨 앞 창만 캡처했으면 그 창의 왼쪽 위(origin) 기준으로 팝업 영역을 지운다"""
        app = self.pending_app()
        seen = []
        app.analyze_frame = lambda img: seen.append(img) or dataclasses.replace(self.checkout)
        x0, y0, x1, y1 = app.window.screen_rect
        origin = (x0 - 10, y0 - 10)                      # 창이 팝업보다 조금 왼쪽 위에서 시작
        app.run_amount(np.zeros((y1 - y0 + 40, x1 - x0 + 40, 3), np.uint8), H2, None, origin)
        self.assertTrue((seen[0][10:10 + y1 - y0, 10:10 + x1 - x0] == 255).all())
        self.assertEqual(int(seen[0][:10].sum()), 0)
        self.close_window(app)

    # ── 팝업 순서 (B-5 버그: '확인 중' 팝업이 금액 팝업보다 뒤에 뜸) ──
    T1 = 'zigzag.kr/checkout/order-sheets/a1b2c3d4e5'
    T2 = 'zigzag.kr/checkout/order-sheets/f6e7d8c9b0'

    def checkout_titled(self, a, title):
        a = dataclasses.replace(a)
        a.title_key = title_key(title)
        return a

    def first_popup_closed(self):
        """실제 로그 02:20:19: 금액이 보이는 결제 화면 → 금액 팝업(조금 더 생각하기 켜짐) → X로 닫음"""
        app = self.make_app(check=(200, CHECKOUT_RESULT), decide=(200, {'ok': True}))
        self.assertTrue(self.handle(app, self.checkout_titled(self.checkout, self.T1), H1))
        self.assertFalse(app.window.view.pending)
        with quiet():
            app.window.on_x()
            self.assertTrue(self.pump(lambda: app.window is None))
        self.assertEqual(self.fake.count('check'), 1)
        return app

    def test_reentry_unknown_amount_waits_then_same_order(self):
        """재현 (02:20:36~02:21:13): 같은 장바구니로 다시 들어오면 주문서 주소(탭 제목)가 바뀌고, 맨 위라 금액을 모른다.
        예전: 새 주문 → '확인 중' 팝업이 금액 팝업 뒤에 또 뜸. 지금: 금액을 읽을 때까지 미루고, 같은 금액이면 팝업 없음"""
        app = self.first_popup_closed()
        self.assertFalse(self.handle(app, self.checkout_titled(self.no_amount(), self.T2), H2))
        self.assertIsNone(app.window)                     # '확인 중' 팝업을 바로 띄우지 않는다
        self.assertIsNotNone(app.waiting)
        self.assertIn('| wait |', self.log_lines()[-1])
        self.clock.t += 2
        self.assertFalse(self.handle(app, self.checkout_titled(self.checkout, self.T2), H3))   # 스크롤해서 금액을 읽음
        self.assertIsNone(app.window)
        self.assertIsNone(app.waiting)
        self.assertEqual(self.fake.count('check'), 1)    # 서버 기록도 다시 하지 않는다
        self.assertEqual(len(app.orders.orders), 1)
        self.assertIn('금액 확인 후 최근 주문과 같은 주문', self.log_lines()[-1])
        self.clock.t += 5                                  # 다시 '구매하기' (같은 금액, 또 다른 제목)
        app.orders.left()
        self.assertFalse(self.handle(app, self.checkout_titled(self.checkout, 'zigzag.kr/checkout/order-sheets/x9y8z7w6v5'), H1))
        self.assertIn('| revisit |', self.log_lines()[-1])

    def test_reentry_different_amount_is_new_popup_with_amount(self):
        """기다리는 동안 읽은 금액이 다르면 다른 장바구니: 바로 금액이 채워진 팝업 (확인 중을 거치지 않음)"""
        app = self.first_popup_closed()
        self.handle(app, self.checkout_titled(self.no_amount(), self.T2), H2)
        other = dataclasses.replace(self.checkout, page=dataclasses.replace(self.checkout.page, checkout_total=85400))
        self.assertTrue(self.handle(app, self.checkout_titled(other, self.T2), H3))
        self.assertFalse(app.window.view.pending)
        self.assertEqual(app.window.price_label['text'], '85,400원')
        self.assertIn('금액 확인 후 새 주문', self.log_lines()[-1])
        self.close_window(app)

    def test_wait_expires_then_pending_popup(self):
        """금액을 끝내 못 읽으면 CHECKOUT_AMOUNT_WAIT_SEC 뒤 '확인 중' 팝업 (화면이 그대로여도: still_same)"""
        app = self.first_popup_closed()
        self.handle(app, self.checkout_titled(self.no_amount(), self.T2), H2)
        self.assertFalse(app.still_same())                # 아직 기다리는 중
        self.clock.t += config.CHECKOUT_AMOUNT_WAIT_SEC
        with quiet():
            self.assertTrue(app.still_same())
            self.assertTrue(self.pump(lambda: app.window is not None))
        self.assertTrue(app.window.view.pending)
        self.assertIn('못 읽어 확인 중으로 띄움', self.log_lines()[-1])
        self.close_window(app)

    def test_no_wait_without_recent_order(self):
        """같은 쇼핑몰의 최근 주문이 없으면 미루지 않고 바로 '확인 중' 팝업"""
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        self.assertTrue(self.handle(app, self.checkout_titled(self.no_amount(), self.T1), H1))
        self.assertTrue(app.window.view.pending)
        self.assertIsNone(app.waiting)
        self.close_window(app)

    def test_leaving_cancels_wait(self):
        app = self.first_popup_closed()
        self.handle(app, self.checkout_titled(self.no_amount(), self.T2), H2)
        self.assertFalse(self.handle(app, self.news, H3))
        self.assertIsNone(app.waiting)

    def test_fill_is_one_way_and_ignores_stale_round(self):
        """팝업 상태는 '확인 중 → 금액'으로만. 늦게 도착한 오래된 회차 결과는 버린다"""
        app = self.pending_app()
        w = app.window
        self.assertTrue(w.fill_price(85400, seq=5))
        self.assertFalse(w.fill_price(149000, seq=3))      # 오래된 회차
        self.assertFalse(w.fill_price(149000, seq=6))      # 이미 금액 표시: 다시 바꾸지 않음
        self.assertEqual((w.view.price, w.view.pending, w.price_label['text']), (85400, False, '85,400원'))
        self.close_window(app)

    def test_pending_view_for_known_order_shows_amount(self):
        """팝업을 띄우는 사이 그 주문의 금액을 알게 됐으면 '확인 중'이 아니라 금액으로 띄운다"""
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        a = self.no_amount()
        order = app.orders.see('coupang', 0, H1)
        order.order.amount = 49600
        _, view = popup_model.build(a, server_client.ApiResult(True, CHECKOUT_RESULT))
        self.assertTrue(view.pending)
        self.assertTrue(app.try_begin())
        app.show('impulse', view, site='coupang', order=order.order)
        self.assertEqual((app.window.view.pending, app.window.price_label['text']), (False, '49,600원'))
        self.close_window(app)

    def test_rounds_numbered_in_timing(self):
        app = self.make_app()
        app.analyze_frame = lambda img: self.product
        for _ in range(2):
            self.assertTrue(app.try_begin())
            with timing.active(timing.Timing('auto')) as t:
                app.run_auto(object(), H1)
        self.assertEqual(t.info['회차'], 2)
        self.assertIn('회차 2', self.log_lines(timing_lines=True)[-1])

    def test_covered_popup_logged_when_amount_not_read(self):
        """팝업이 캡처 영역에 겹치면 그 부분은 지우고 읽는다. 금액을 못 읽었으면 팝업이 가린 영역을 로그에 남긴다"""
        app = self.pending_app()
        app.analyze_frame = lambda img: dataclasses.replace(self.no_amount())
        x0, y0, x1, y1 = app.window.screen_rect
        origin = (x0 - 100, y0 - 100)                    # 브라우저 창이 팝업을 덮는 위치
        self.assertFalse(app.run_amount(np.zeros((y1 - y0 + 200, x1 - x0 + 200, 3), np.uint8), H2, None, origin))
        line = [l for l in self.log_lines() if 'amount |' in l][-1]
        self.assertIn('금액 못 읽음 (결제 화면) | 팝업이 캡처 영역의', line)
        self.assertIn(f'({x1 - x0}x{y1 - y0}, 이미지 기준 100,100)', line)
        self.close_window(app)

    def test_not_covered_no_info_log(self):
        """팝업이 캡처 영역 밖(브라우저 옆)이면 가림 로그를 남기지 않는다"""
        app = self.pending_app()
        app.analyze_frame = lambda img: dataclasses.replace(self.no_amount())
        x0, y0, x1, y1 = app.window.screen_rect
        self.assertFalse(app.run_amount(np.zeros((300, 300, 3), np.uint8), H2, None, (x0 - 1000, y0)))
        self.assertFalse([l for l in self.log_lines() if 'amount |' in l])
        self.close_window(app)

    def test_covered_box(self):
        self.assertEqual(main.covered_box((150, 40, 400, 60), (100, 0), (100, 200)), (50, 40, 200, 60))
        self.assertIsNone(main.covered_box((500, 40, 600, 60), (100, 0), (100, 200)))
        self.assertIsNone(main.covered_box(None, (0, 0), (100, 200)))

    def test_mask_rect(self):
        img = np.zeros((100, 200, 3), np.uint8)
        main.mask_rect(img, (150, 40, 400, 60), origin=(100, 0))     # 화면 좌표 → 이미지 좌표, 밖으로 나간 곳은 자름
        self.assertTrue((img[40:60, 50:200] == 255).all())
        self.assertEqual(int(img[:40].sum()) + int(img[60:].sum()) + int(img[40:60, :50].sum()), 0)
        self.assertIs(main.mask_rect(img, None), img)

    # ── 시간 측정 (B-5) ──
    def run_timed(self, app, t):
        self.assertTrue(app.try_begin())
        with timing.active(t):
            return app.run_auto(object(), H1)

    def test_timing_line_without_popup(self):
        """팝업이 없으면 분석이 끝날 때 한 줄. 화면 글자나 이미지는 남기지 않는다"""
        app = self.make_app()
        app.analyze_frame = lambda img: self.product
        self.assertFalse(self.run_timed(app, timing.Timing('auto')))
        line = self.log_lines(timing_lines=True)[-1]
        self.assertIn('timing auto | 판정 ', line)
        self.assertIn('| 전체 ', line)
        self.assertNotIn('coupang', line)

    def test_timing_line_after_popup_shown(self):
        """결제 화면 팝업: 서버 시간(action별), 팝업 표시, 감지→팝업이 창이 만들어진 뒤 한 줄로 남는다"""
        app = self.make_app(check=(200, CHECKOUT_RESULT))
        app.analyze_frame = lambda img: self.checkout
        t = timing.Timing('auto')
        t.detected_at = timing.now() - 2.0
        t.add('interval_wait', 3.0)
        t.add('settle_wait', 2.0)
        t.changing = 1
        self.assertTrue(self.run_timed(app, t))
        self.assertTrue(self.pump(lambda: app.window is not None))
        line = self.log_lines(timing_lines=True)[-1]
        for part in ('간격 대기 ≤3.00', '멈춤 확인 2.00 (바뀌는 중 1회)', '판정 ', '서버 ', 'check ', '팝업 표시 ',
                     '감지→팝업 ', '화면 바뀜→팝업 ≤'):
            self.assertIn(part, line)
        self.assertGreaterEqual(t.total, 2.0)
        self.close_window(app)


# ── 로그와 개인정보 ─────────────────────────────────────────────

class TestDetectLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_console_only_on_change(self):
        log = DetectLog(self.dir, console=True, clock=lambda: 0)
        a = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            log.event('auto', a, action='popup', ocr_sec=8.7, note='detect 기록 200번')
            log.event('auto', a, dup='same')
            log.event('auto', a, dup='same')
            log.event('auto', a, dup='revisit')
        log.close()
        printed = out.getvalue().splitlines()
        self.assertEqual(len(printed), 2)                       # popup, revisit (same은 파일에만)
        with open(os.path.join(self.dir, config.LOG_FILE), encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn('auto | 결제 화면 | coupang | 49,600원 | 점수 ', lines[0])
        self.assertIn('| new | → popup | OCR 8.7초 | detect 기록 200번', lines[0])

    def test_no_ocr_text_by_default(self):
        log = DetectLog(self.dir, console=False)
        a = main.analyze_boxes(cs.PRODUCT_WITH_PAY_BUTTON)
        self.assertFalse(log.sample(a, '겨울 패딩 49,600원'))
        log.close()
        self.assertFalse(os.path.exists(os.path.join(self.dir, config.OCR_SAMPLE_FILE)))

    def test_ocr_text_masked_and_no_checkout(self):
        log = DetectLog(self.dir, console=False, save_ocr_text=True)
        product = main.analyze_boxes(cs.PRODUCT_WITH_PAY_BUTTON)
        checkout = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        self.assertTrue(log.sample(product, '홍길동님 추천 겨울 패딩 49,600원 문의 010-1234-5678'))
        self.assertFalse(log.sample(checkout, '받는 분 김무신 서울특별시 강남구 테헤란로 123'))
        log.close()
        with open(os.path.join(self.dir, config.OCR_SAMPLE_FILE), encoding='utf-8') as f:
            rows = [json.loads(line) for line in f]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['stage'], 'product')
        self.assertEqual(rows[0]['text'], '[이름]님 추천 겨울 패딩 49,600원 문의 [전화번호]')

    def test_no_image_files(self):
        """로그 폴더에는 로그 파일만 생긴다 (캡처 이미지 없음)"""
        log = DetectLog(self.dir, console=False, save_ocr_text=True)
        log.event('auto', main.analyze_boxes(cs.COUPANG_CHECKOUT))
        log.close()
        self.assertEqual(os.listdir(self.dir), [config.LOG_FILE])


class TestMask(unittest.TestCase):
    def test_checkout_samples(self):
        from impulse_guard import ocr
        text = mask_private(ocr.full_text(cs.COUPANG_CHECKOUT) + ' ' + ocr.full_text(cs.MUSINSA_CHECKOUT))
        for secret in ('홍길동', '김무신', '010-1234-5678', '010 9876 5432', '테헤란로', '아차산로', '1234-5678-9012-3456'):
            self.assertNotIn(secret, text)
        for kept in ('49,600원', '220,590원', '결제하기', '구매자정보', '받는사람정보', '배송 요청사항'):
            self.assertIn(kept, text)

    def test_patterns(self):
        cases = {
            '이름: 홍길동': '이름: [이름]',
            '수령인:박영희': '수령인:[이름]',
            '받는 분 정보 입력': '받는 분 정보 입력',
            '카드 1234-56**-****-3456': '카드 [카드번호]',
            '02-123-4567': '[전화번호]',
            '경기도 성남시 분당구 판교역로 235': '[주소]',
            'test.user@example.com': '[이메일]',
            '49,600원 무료배송 2026.11.11 리뷰 1,234개': '49,600원 무료배송 2026.11.11 리뷰 1,234개',
        }
        for text, want in cases.items():
            self.assertEqual(mask_private(text), want, text)


class TestAutoSettings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(server_client.auto_settings(None), config.AUTO_DETECT_DEFAULTS)

    def test_exclude_programs(self):
        self.assertIn('Code.exe', server_client.auto_settings(None)['exclude_programs'])
        s = server_client.auto_settings({'exclude_programs': [' chrome.exe ', '', 'Notepad.exe']})
        self.assertEqual(s['exclude_programs'], ['chrome.exe', 'Notepad.exe'])
        self.assertEqual(server_client.auto_settings({'exclude_programs': []})['exclude_programs'], [])
        self.assertEqual(server_client.auto_settings({'exclude_programs': 'Code.exe'})['exclude_programs'],
                         config.AUTO_DETECT_DEFAULTS['exclude_programs'])          # 목록이 아니면 기본값

    def test_override_and_invalid(self):
        s = server_client.auto_settings({'enabled': False, 'interval_sec': 5, 'same_order_minutes': 'x',
                                         'blocked_repeat_sec': 30, 'save_ocr_text': 1})
        self.assertEqual((s['enabled'], s['interval_sec'], s['blocked_repeat_sec']), (False, 5, 30))
        self.assertEqual(s['same_order_minutes'], 10)            # 잘못된 값은 기본값
        self.assertFalse(s['save_ocr_text'])                     # true/false만 받는다
        self.assertEqual(server_client.auto_settings({'interval_sec': 0.1})['interval_sec'], 3)

    def test_auto_source(self):
        """자동 감지 설정을 어디서 읽었는지 (사용자 local_config.json에 auto_detect가 없던 문제 확인용)"""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(server_client.load_config(os.path.join(here, 'local_config.example.json'))['auto_source'],
                         'local_config.json')
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({'server': 'http://localhost:8001', 'token': 'x'}, f)
        try:
            self.assertIn('auto_detect 없음', server_client.load_config(f.name)['auto_source'])
        finally:
            os.unlink(f.name)

    def test_example_file(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        conf = server_client.load_config(os.path.join(here, 'local_config.example.json'))
        self.assertEqual(conf['auto'], config.AUTO_DETECT_DEFAULTS)


if __name__ == '__main__':
    unittest.main()
