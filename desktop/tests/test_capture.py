"""캡처 영역 테스트 (B-5: 맨 앞 창만 캡처)

실행 (desktop 폴더에서): .venv\Scripts\python.exe -m unittest discover -s tests -p test_capture.py -v
"""
import unittest
from unittest import mock

import numpy as np

from impulse_guard import capture, config

SCREEN = {'left': -1920, 'top': 0, 'width': 3840, 'height': 1080}     # 왼쪽에 보조 모니터가 있는 두 모니터


class TestClipRegion(unittest.TestCase):
    def test_window_inside(self):
        self.assertEqual(capture.clip_region((100, 50, 1300, 1000), SCREEN),
                         {'left': 100, 'top': 50, 'width': 1200, 'height': 950})

    def test_window_on_secondary_monitor(self):
        self.assertEqual(capture.clip_region((-1800, 0, -200, 900), SCREEN),
                         {'left': -1800, 'top': 0, 'width': 1600, 'height': 900})

    def test_partly_off_screen_is_clipped(self):
        self.assertEqual(capture.clip_region((1500, -30, 2500, 1200), SCREEN),
                         {'left': 1500, 'top': 0, 'width': 420, 'height': 1080})

    def test_too_small_or_none(self):
        self.assertIsNone(capture.clip_region((0, 0, 150, 900), SCREEN))
        self.assertIsNone(capture.clip_region(None, SCREEN))
        self.assertIsNone(capture.clip_region((3000, 0, 3500, 500), SCREEN))   # 화면 밖


class FakeShot:
    def __init__(self, region):
        self.region = region

    def __array__(self, dtype=None, copy=None):
        return np.zeros((self.region['height'], self.region['width'], 4), np.uint8)


class FakeMss:
    monitors = [SCREEN, {'left': 0, 'top': 0, 'width': 1920, 'height': 1080}]

    def __init__(self):
        self.grabbed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def grab(self, region):
        self.grabbed.append(region)
        return FakeShot(region)


class TestGrabActive(unittest.TestCase):
    def grab(self, rect):
        fake = FakeMss()
        with mock.patch('mss.mss', return_value=fake), mock.patch.object(capture, 'foreground_rect', return_value=rect):
            img, origin, scope = capture.grab_active()
        return img, origin, scope

    def test_active_window(self):
        img, origin, scope = self.grab((100, 50, 1300, 1000))
        self.assertEqual((img.shape, origin, scope), ((950, 1200, 3), (100, 50), 'window'))

    def test_fallback_to_monitor(self):
        img, origin, scope = self.grab(None)
        self.assertEqual((img.shape, origin, scope), ((1080, 1920, 3), (0, 0), 'monitor'))

    def test_frame_has_origin_and_scope(self):
        with mock.patch.object(capture, 'grab_active', return_value=(np.zeros((10, 10, 3), np.uint8), (5, 6), 'window')),                 mock.patch.object(capture, 'foreground_title', return_value='t'),                 mock.patch.object(capture, 'foreground_exe', return_value='chrome.exe'),                 mock.patch.object(config, 'CAPTURE_ACTIVE_WINDOW', True):
            fr = capture.grab_for_detect()
        self.assertEqual((fr.origin, fr.scope, fr.foreground_exe), ((5, 6), 'window', 'chrome.exe'))


class TestGrabWindow(unittest.TestCase):
    def test_gone_or_minimized_window(self):
        """창이 없어졌거나 최소화됐으면 None (모니터 전체로 대신하지 않는다: 팝업까지 찍히므로)"""
        with mock.patch.object(capture, 'window_rect', return_value=None):
            self.assertIsNone(capture.grab_window(77))
        self.assertIsNone(capture.grab_window(0))

    def test_window_frame(self):
        with mock.patch.object(capture, 'window_rect', return_value=(100, 50, 1300, 1000)), \
                mock.patch.object(capture, 'grab_active', return_value=(np.zeros((950, 1200, 3), np.uint8), (100, 50), 'window')) as ga, \
                mock.patch.object(capture, 'window_title', return_value='zigzag.kr/checkout/x'), \
                mock.patch.object(capture, 'window_exe', return_value='chrome.exe'):
            fr = capture.grab_window(77)
        ga.assert_called_once_with(77)
        self.assertEqual((fr.hwnd, fr.origin, fr.scope, fr.foreground_exe), (77, (100, 50), 'window', 'chrome.exe'))


if __name__ == '__main__':
    unittest.main()
