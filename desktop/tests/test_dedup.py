"""화면 해시와 중복 방지 테스트 (B-4)

실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import unittest

import cv2
import numpy as np

import cache
from impulse_guard import config, frame
from impulse_guard.dedup import NoticeGate, RecentOrders, title_key


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
        """금액을 모르고 다른 화면에 갔다 왔으면 화면 해시가 거의 같을 때만 같은 주문"""
        self.orders.see('coupang', 0, H1)
        self.orders.left()
        self.assertTrue(self.orders.see('coupang', 0, H1_NEAR).is_dup)
        self.orders.left()
        self.assertFalse(self.orders.see('coupang', 0, H_FAR).is_dup)

    # ── B-5: 제목 해시, 머무는 중, 해시 기준 ──
    def test_unknown_amount_mid_distance_is_new_after_leaving(self):
        """실제 버그: 결제 페이지 맨 위(금액 모름)는 장바구니가 달라도 비슷하다 (B-4 기준 20 이하).
        다른 화면에 갔다 온 뒤에는 같은 화면 수준(ORDER_SAME_DISTANCE)이 아니면 새 주문"""
        self.orders.see('zigzag', 0, H1)
        self.orders.left()
        mid = H1 ^ ((1 << 15) - 1)                      # 15비트 차이
        self.assertFalse(self.orders.see('zigzag', 0, mid).is_dup)

    def test_scroll_on_same_page_fills_amount(self):
        """결제 화면에 머무르며 맨 위(금액 모름) → 스크롤(총 결제금액): 화면이 많이 달라도 같은 주문, 금액을 채운다"""
        self.orders.see('zigzag', 0, H1)
        v = self.orders.see('zigzag', 85400, H_FAR)
        self.assertTrue(v.is_dup)
        self.assertTrue(v.filled)
        self.assertEqual((v.reason, v.order.amount), ('same', 85400))
        self.assertFalse(self.orders.see('zigzag', 85400, H_FAR).filled)    # 두 번째부터는 채운 것이 아님

    def test_different_title_same_amount_is_same_order(self):
        """금액을 둘 다 읽었으면 금액으로 판단한다. 지그재그는 같은 장바구니라도 '구매하기'마다 주문서 주소(탭 제목)가
        새로 생겨서, 제목이 다르다고 새 주문으로 보면 같은 주문에 팝업이 또 뜬다 (실제 로그 02:21:13)"""
        a = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        b = title_key('zigzag.kr/checkout/order-sheets/f6e7d8c9b0')
        self.orders.see('zigzag', 85400, H1, a)
        self.orders.left()
        self.assertTrue(self.orders.see('zigzag', 85400, H_FAR, b).is_dup)

    def test_different_title_unknown_amount_is_new_order(self):
        """금액을 모를 때는 탭 제목이 다르면 다른 주문 (화면 해시가 같아도)"""
        a = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        b = title_key('zigzag.kr/checkout/order-sheets/f6e7d8c9b0')
        self.orders.see('zigzag', 0, H1, a)
        self.assertFalse(self.orders.see('zigzag', 0, H1, b).is_dup)

    def test_resolve_merges_into_recent_order(self):
        """금액을 몰라 보류한 주문이 금액을 읽어 보니 최근 주문과 같으면 그 주문으로 합친다 (보류 주문은 지움)"""
        first = self.orders.see('zigzag', 149000, H1).order
        self.orders.decide(first, 'close')
        self.orders.left()
        waiting = self.orders.see('zigzag', 0, H_FAR, title_key('zigzag.kr/checkout/order-sheets/f6e7d8c9b0')).order
        self.assertIsNot(waiting, first)
        v = self.orders.resolve(waiting, 'zigzag', 149000, H1)
        self.assertEqual((v.is_dup, v.reason, v.order.decision), (True, 'revisit', 'close'))
        self.assertEqual(self.orders.orders, [first])

    def test_resolve_new_amount_is_new_order(self):
        self.orders.see('zigzag', 149000, H1)
        self.orders.left()
        waiting = self.orders.see('zigzag', 0, H_FAR).order
        v = self.orders.resolve(waiting, 'zigzag', 85400, H_FAR)
        self.assertEqual((v.is_dup, v.filled, v.order.amount), (False, True, 85400))
        self.assertEqual(len(self.orders.orders), 2)

    def test_recent_known(self):
        self.assertIsNone(self.orders.recent_known('zigzag'))
        o = self.orders.see('zigzag', 149000, H1).order
        self.orders.see('musinsa', 79000, H1)
        self.assertIs(self.orders.recent_known('zigzag'), o)
        self.assertIsNone(self.orders.recent_known('zigzag', exclude=o))

    def test_specific_title_matches_without_amount(self):
        """주문서 번호가 든 제목이 같으면 금액을 모르고 화면이 달라도 같은 주문 (다른 화면에 갔다 와도)"""
        a = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        self.orders.see('zigzag', 0, H1, a)
        self.orders.left()
        self.assertTrue(self.orders.see('zigzag', 0, H_FAR, a).is_dup)

    def test_generic_title_needs_hash(self):
        """주문마다 같은 제목(무신사 order-form)은 제목만으로 같은 주문이라 하지 않는다"""
        a = title_key('musinsa.com/order/order-form')
        self.assertFalse(a.specific)
        self.orders.see('musinsa', 0, H1, a)
        self.orders.left()
        self.assertFalse(self.orders.see('musinsa', 0, H_FAR, a).is_dup)

    def test_missing_title_is_ignored(self):
        """제목을 모르는 쪽(F4 예전 기록, 제목 없는 창)은 제목 규칙을 쓰지 않는다"""
        a = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        self.orders.see('zigzag', 85400, H1)
        self.assertTrue(self.orders.see('zigzag', 85400, H1, a).is_dup)
        self.assertIsNone(title_key('  '))

    def test_title_key_keeps_no_text(self):
        """제목 원문은 남지 않는다 (해시와 고유 값 여부만)"""
        k = title_key('zigzag.kr/checkout/order-sheets/a1b2c3d4e5')
        self.assertEqual(set(vars(k)), {'digest', 'specific'})
        self.assertNotIn('a1b2c3d4e5', repr(k))
        self.assertEqual(k, title_key('  ZIGZAG.kr/checkout/order-sheets/A1B2C3D4E5 '))

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
