"""화면 단계 판정과 결제 금액 찾기 테스트 (B-4)

실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import unittest

import cache
import checkout_samples as cs
from impulse_guard import config, main, ocr
from impulse_guard.detector import page, price, stage


class TestCheckoutScore(unittest.TestCase):
    def test_spacing_variants(self):
        """OCR 띄어쓰기가 달라도 같은 키워드"""
        for text in ('최종 결제금액', '최종결제금액', '최종 결제 금액'):
            self.assertEqual(stage.checkout_score(text)[1], [('최종결제금액', 3)])

    def test_no_double_count(self):
        """'배송지정보' 안의 '배송지', '총결제금액' 안의 '결제금액'은 따로 세지 않는다"""
        score, matched = stage.checkout_score('배송지정보 총결제금액')
        self.assertEqual(matched, [('총결제금액', 3), ('배송지정보', 2)])
        self.assertEqual(score, 5)

    def test_one_keyword_is_not_checkout(self):
        """3점 키워드 하나만 있어도 결제 화면이 아니다 (서로 다른 키워드 2개 필요)"""
        self.assertEqual(stage.classify('주문/결제 49,600원', True).stage, stage.PRODUCT)
        self.assertEqual(stage.classify('주문/결제', False).stage, stage.NONE)

    def test_threshold(self):
        r = stage.classify('배송지 받는분 수령인', True)          # 3점, 3개
        self.assertEqual((r.stage, r.score), (stage.PRODUCT, 3))
        r = stage.classify('배송지 받는분 수령인 약관동의', True)   # 4점, 4개
        self.assertEqual((r.stage, r.score), (stage.CHECKOUT, 4))

    def test_checkout_even_if_original_rule_says_no(self):
        self.assertEqual(stage.classify('주문서 결제수단', False).stage, stage.CHECKOUT)

    def test_evidence(self):
        r = stage.classify('주문서 결제수단 배송지', True)
        self.assertEqual(r.evidence(), f'점수 5/{config.CHECKOUT_MIN_SCORE} [결제수단 2, 주문서 2, 배송지 1]')   # 같은 점수는 긴 키워드 먼저
        self.assertEqual(r.label, '결제 화면')


class TestSamples(unittest.TestCase):
    def analyze(self, boxes):
        return main.analyze_boxes(boxes)

    def test_coupang_checkout(self):
        a = self.analyze(cs.COUPANG_CHECKOUT)
        self.assertEqual(a.stage.stage, stage.CHECKOUT)
        self.assertTrue(a.page.is_checkout)
        self.assertEqual((a.page.checkout_total, a.page.total_label), (cs.COUPANG_TOTAL, '총결제금액'))
        self.assertEqual(a.amount, cs.COUPANG_TOTAL)
        self.assertEqual(a.page.site, 'coupang')
        self.assertIn('주문결제', ''.join(a.stage.words).replace('/', ''))

    def test_musinsa_checkout(self):
        a = self.analyze(cs.MUSINSA_CHECKOUT)
        self.assertEqual(a.stage.stage, stage.CHECKOUT)
        self.assertEqual((a.page.checkout_total, a.page.total_label), (cs.MUSINSA_TOTAL, '최종결제금액'))
        self.assertEqual(a.page.site, 'musinsa')

    def test_product_with_pay_button(self):
        a = self.analyze(cs.PRODUCT_WITH_PAY_BUTTON)
        self.assertEqual(a.stage.stage, stage.PRODUCT)
        self.assertEqual(a.amount, 49600)
        self.assertFalse(a.page.is_checkout)

    def test_cart_is_product(self):
        self.assertEqual(self.analyze(cs.CART).stage.stage, stage.PRODUCT)

    def test_real_images(self):
        """실제 캡처: 상품 화면 3장과 뉴스는 결제 점수 0, 결제 화면 2장은 결제 화면"""
        expected = {'coupang_product': stage.PRODUCT, 'musinsa_product': stage.PRODUCT,
                    'zigzag_product': stage.PRODUCT, 'news_page': stage.NONE,
                    'checkout_musinsa': stage.CHECKOUT, 'checkout_zigzag': stage.CHECKOUT}
        for name in cache.names():
            with self.subTest(name=name):
                img, boxes, reread = cache.load(name)
                a = main.analyze_boxes(boxes, img, reread)
                self.assertEqual(a.stage.stage, expected[name])
                if expected[name] != stage.CHECKOUT:
                    self.assertEqual(a.stage.score, 0)

    def test_real_checkout_musinsa(self):
        """무신사 주문서: 총 결제 금액 79,000원 (OCR은 '28%6 79,000원'으로 읽음, 할인율이 같은 상자에 붙어 있음)"""
        img, boxes, reread = cache.load('checkout_musinsa')
        a = main.analyze_boxes(boxes, img, reread)
        self.assertGreaterEqual(a.stage.score, 10)
        self.assertEqual((a.page.site, a.amount, a.page.total_label), ('musinsa', 79000, '총결제금액'))

    def test_real_checkout_zigzag(self):
        """지그재그 결제: '총 결제금액'을 '좀 결제금억'으로 읽고, 결제 버튼은 못 읽는다.
        OCR 오인식 보정과 '결제 동의' 키워드로 결제 화면, 바로 아래 카드 광고 금액(174,010원)이 아니라 같은 줄의 224,910원"""
        img, boxes, reread = cache.load('checkout_zigzag')
        a = main.analyze_boxes(boxes, img, reread)
        self.assertIn(('총결제금액', 3), a.stage.matched)
        self.assertIn(('결제동의', 2), a.stage.matched)
        self.assertGreaterEqual(a.stage.score, config.CHECKOUT_MIN_SCORE + 2)     # 기준선에 겨우 걸리지 않게
        self.assertEqual((a.page.site, a.amount, a.page.total_label), ('zigzag', 224910, '총결제금액'))


class TestOcrFixes(unittest.TestCase):
    def test_misread_label(self):
        self.assertEqual(stage.normalize('좀 결제금억'), '총결제금액')
        self.assertEqual(stage.checkout_score('좀 결제금억')[1], [('총결제금액', 3)])
        b = cs.boxes([('좀 결제금억', 40, 300, 80), ('9,900원', 400, 300, 80)])
        self.assertEqual(price.find_checkout_total(b), (9900, '총결제금액'))


class TestCheckoutTotal(unittest.TestCase):
    def test_same_line_beats_closer_line_below(self):
        """같은 줄 오른쪽 끝의 금액이 바로 아래 줄의 광고 금액보다 우선"""
        b = cs.boxes([('총 결제금액', 40, 300, 80, 16), ('224,910원', 700, 300, 80, 16),
                      ('신한카드는 174,910원', 70, 340, 140, 14)])
        self.assertEqual(price.find_checkout_total(b)[0], 224910)

    def test_label_priority(self):
        """'최종 결제금액'이 '결제하기' 버튼의 금액보다 우선"""
        b = cs.boxes([('결제하기 10,000원', 40, 400, 200), ('최종 결제금액', 40, 300, 140), ('12,500원', 400, 300, 100)])
        self.assertEqual(price.find_checkout_total(b), (12500, '최종결제금액'))

    def test_inside_same_box(self):
        b = cs.boxes([('총 결제금액 33,000원', 40, 300, 240)])
        self.assertEqual(price.find_checkout_total(b), (33000, '총결제금액'))

    def test_nearest_on_line(self):
        b = cs.boxes([('결제금액', 40, 300, 80), ('5,000원', 300, 300, 80), ('9,000원', 700, 300, 80)])
        self.assertEqual(price.find_checkout_total(b)[0], 5000)

    def test_not_found(self):
        self.assertEqual(price.find_checkout_total(cs.boxes([('주문서', 40, 30), ('배송지', 40, 60)])), (None, ''))

    def test_far_below_is_ignored(self):
        b = cs.boxes([('최종 결제금액', 40, 300, 140, 20), ('12,500원', 40, 500, 100, 20)])
        self.assertEqual(price.find_checkout_total(b), (None, ''))


class TestPageCompat(unittest.TestCase):
    def test_find_checkout_uses_stage(self):
        ok, words = page.find_checkout('주문서 작성 배송지 변경 결제하기')
        self.assertTrue(ok)
        self.assertEqual(set(words), {'주문서', '배송지', '결제하기'})


if __name__ == '__main__':
    unittest.main()
