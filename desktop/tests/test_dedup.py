"""화면 해시와 중복 방지 테스트 (B-4)

실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import unittest

import cv2
import numpy as np

import cache
from impulse_guard import config, frame
from impulse_guard.dedup import NoticeGate, RecentOrders


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class TestFrameHash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = cache.load('coupang_product')[0]
        cls.h = frame.dhash(cls.img)

    def test_same_image(self):
        self.assertEqual(frame.distance(self.h, frame.dhash(self.img.copy())), 0)

    def test_small_changes_are_same_screen(self):
        """커서, 시계 글자, 약한 잡음은 같은 화면"""
        img = self.img.copy()
        h, w = img.shape[:2]
        cv2.rectangle(img, (w // 2, h // 2), (w // 2 + 20, h // 2 + 30), (0, 0, 0), -1)
        cv2.putText(img, '12:34', (w - 200, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        noise = np.random.default_rng(0).integers(-6, 7, img.shape)
        img = np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)
        self.assertLessEqual(frame.distance(self.h, frame.dhash(img)), config.FRAME_SAME_DISTANCE)

    def test_scroll_and_other_pages_differ(self):
        scrolled = np.vstack([self.img[40:], self.img[:40]])
        self.assertGreater(frame.distance(self.h, frame.dhash(scrolled)), config.ORDER_SAME_DISTANCE)
        for name in ('musinsa_product', 'news_page', 'zigzag_product'):
            self.assertGreater(frame.distance(self.h, frame.dhash(cache.load(name)[0])), 50)

    def test_none(self):
        self.assertEqual(frame.distance(None, self.h), config.FRAME_HASH_SIZE ** 2)


H1 = 0b1010 << 200            # 임의의 해시 값
H1_NEAR = H1 ^ 0b111          # 3비트 차이
H_FAR = (1 << 256) - 1        # 많이 다름


class TestRecentOrders(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.orders = RecentOrders(window_sec=600, clock=self.clock)

    def test_new_then_stay(self):
        v = self.orders.see('coupang', 49600, H1)
        self.assertFalse(v.is_dup)
        self.clock.t += 3
        v = self.orders.see('coupang', 49600, H_FAR)       # 스크롤해도 쇼핑몰+금액이 같으면 같은 주문
        self.assertTrue(v.is_dup)
        self.assertEqual((v.reason, v.order.count), ('same', 2))

    def test_staying_long_never_repeats(self):
        """같은 결제 화면에 30분 머물러도 (화면이 안 바뀌어 still_here만 불려도) 다시 새 주문이 되지 않는다"""
        self.orders.see('coupang', 49600, H1)
        for _ in range(60):
            self.clock.t += 30
            self.orders.still_here()
        self.assertTrue(self.orders.see('coupang', 49600, H1).is_dup)

    def test_leave_and_come_back_within_window(self):
        self.orders.see('coupang', 49600, H1)
        self.orders.left()
        self.clock.t += 9 * 60
        v = self.orders.see('coupang', 49600, H1)
        self.assertTrue(v.is_dup)
        self.assertEqual(v.reason, 'revisit')
        self.assertAlmostEqual(v.away_sec, 540)

    def test_leave_longer_than_window_is_new(self):
        self.orders.see('coupang', 49600, H1)
        self.orders.left()
        self.clock.t += 11 * 60
        self.assertFalse(self.orders.see('coupang', 49600, H1).is_dup)

    def test_different_amount_or_site(self):
        self.orders.see('coupang', 49600, H1)
        self.assertFalse(self.orders.see('coupang', 52000, H1).is_dup)
        self.assertFalse(self.orders.see('musinsa', 49600, H1).is_dup)

    def test_unknown_amount_uses_hash(self):
        self.orders.see('coupang', 0, H1)
        self.assertTrue(self.orders.see('coupang', 0, H1_NEAR).is_dup)
        self.assertFalse(self.orders.see('coupang', 0, H_FAR).is_dup)

    def test_amount_filled_later(self):
        """처음엔 금액을 못 읽고 다음 회차에 읽으면 같은 화면이면 같은 주문으로 이어진다"""
        self.orders.see('coupang', 0, H1)
        v = self.orders.see('coupang', 49600, H1_NEAR)
        self.assertTrue(v.is_dup)
        self.assertEqual(v.order.amount, 49600)

    def test_decision_kept(self):
        """'안 살래요' 뒤 같은 화면이 다시 감지돼도 중복 (팝업 안 띄움), 결정은 남아 있다"""
        v = self.orders.see('coupang', 49600, H1)
        self.orders.decide(v.order, 'giveup', 131)
        self.orders.left()
        self.clock.t += 5
        v = self.orders.see('coupang', 49600, H1)
        self.assertTrue(v.is_dup)
        self.assertEqual((v.reason, v.order.decision, v.order.bl_id), ('revisit', 'giveup', 131))


class TestNoticeGate(unittest.TestCase):
    def test_repeat_interval_per_site(self):
        clock = Clock()
        gate = NoticeGate(repeat_sec=60, clock=clock)
        self.assertTrue(gate.allow('coupang'))
        gate.closed('coupang')
        clock.t += 59
        self.assertFalse(gate.allow('coupang'))
        self.assertAlmostEqual(gate.wait_left('coupang'), 1)
        self.assertTrue(gate.allow('musinsa'))           # 쇼핑몰마다 따로
        clock.t += 1
        self.assertTrue(gate.allow('coupang'))


if __name__ == '__main__':
    unittest.main()
