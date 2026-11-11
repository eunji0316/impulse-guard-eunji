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
import unittest

import cache
import checkout_samples as cs
from impulse_guard import auto_detect, config, main, popup, popup_model, server_client
from impulse_guard.capture import Frame
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
        self.run_delay = 0.0

    def paused(self):
        return self.is_paused

    def try_begin(self):
        return not self.busy

    def still_same(self):
        self.same += 1

    def run_auto(self, img, h):
        self.runs.append(h)
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

    def log_lines(self):
        with open(os.path.join(self.dir, config.LOG_FILE), encoding='utf-8') as f:
            return f.read().splitlines()

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

    def test_example_file(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        conf = server_client.load_config(os.path.join(here, 'local_config.example.json'))
        self.assertEqual(conf['auto'], config.AUTO_DETECT_DEFAULTS)


if __name__ == '__main__':
    unittest.main()
