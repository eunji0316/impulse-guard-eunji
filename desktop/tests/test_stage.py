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
                    'checkout_musinsa': stage.CHECKOUT, 'checkout_zigzag': stage.CHECKOUT,
                    'checkout_zigzag_benefit': stage.CHECKOUT}
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


    def test_real_checkout_zigzag_benefit(self):
        """버그 화면 (detect.log 12:03:18에 15,006원으로 기록, 실제 224,910원): 구매 혜택 영역의 금액
        ('최대 1,630원', 마일리지 '최대 1,630M', '최대 1,630원 혜택')은 후보에서 빠지고 총 결제금액 줄의 224,910원"""
        img, boxes, reread = cache.load('checkout_zigzag_benefit')
        a = main.analyze_boxes(boxes, img, reread)
        self.assertEqual(a.stage.stage, stage.CHECKOUT)
        self.assertEqual((a.page.site, a.amount, a.page.total_label), ('zigzag', 224910, '총결제금액'))
        benefit = {c.value for c in price.find_tokens(boxes)[0] if price.benefit_word(c, boxes)}
        self.assertEqual(benefit, {1630})

    def test_real_checkout_zigzag_benefit_label_unread(self):
        """같은 화면에서 OCR이 금액 라벨을 못 읽은 경우 (0.9배에서 '결서금역'으로 읽음):
        상품 화면용 할인가가 구매 혜택 금액(630원)을 고르므로, 결제 화면에서는 할인가로 대신하지 않고 금액 모름"""
        img, boxes, reread = cache.load('checkout_zigzag_benefit')
        broken = [b for b in boxes if '결제금' not in stage.normalize(b.text)]
        a = main.analyze_boxes(broken, img, reread)
        self.assertEqual(a.stage.stage, stage.CHECKOUT)
        self.assertIsNone(a.page.checkout_total)
        a.prices.sale_price = 630          # 0.9배 OCR에서 상품 화면용 분석이 고른 할인가 ('최대 1,630원'을 630원으로 읽음)
        self.assertEqual(a.amount, 0)      # 예전에는 630을 결제 금액으로 기록했다
        self.assertIn('금액 라벨 못 찾음', self.log_line(a))

    def log_line(self, a):
        import tempfile
        from impulse_guard.detect_log import DetectLog
        with tempfile.TemporaryDirectory() as d:
            log = DetectLog(log_dir=d, console=False)
            try:
                return log.event('auto', a)
            finally:
                log.close()

    def test_log_has_amount_label(self):
        """결제 화면 로그 줄에 금액을 찾은 라벨을 남긴다 (금액을 잘못 골랐을 때 원인 추적)"""
        img, boxes, reread = cache.load('checkout_zigzag_benefit')
        line = self.log_line(main.analyze_boxes(boxes, img, reread))
        self.assertIn('| 224,910원 |', line)
        self.assertIn('| 금액 라벨 총결제금액', line)


class TestOcrFixes(unittest.TestCase):
    def test_misread_label(self):
        self.assertEqual(stage.normalize('좀 결제금억'), '총결제금액')
        self.assertEqual(stage.normalize('총 결제금역'), '총결제금액')      # Windows OCR 1.5배
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

    # ── 혜택/적립/쿠폰/할인 금액 제외 (실제 버그: 지그재그 결제 금액을 구매 혜택 금액 15,006원으로 기록) ──
    def test_benefit_badge_on_same_line_is_not_total(self):
        """라벨 아래에 결제 금액, 같은 줄 오른쪽에 적립 배지: 같은 줄이 우선이어도 적립 금액은 고르지 않는다"""
        b = cs.boxes([('총 결제금액', 40, 300, 80, 16), ('최대 15,006원 적립', 700, 300, 130, 16),
                      ('224,910원', 40, 322, 90, 20)])
        self.assertEqual(price.find_checkout_total(b), (224910, '총결제금액'))

    def test_benefit_row_label_excluded(self):
        """두 단 화면: 왼쪽 '총 결제금액'(금액은 아래)과 같은 줄 오른쪽 단의 '구매 혜택 … 최대 | 15,006원'.
        항목 이름이 금액과 떨어져 있고 사이에 꾸밈말 상자가 있어도 혜택 금액으로 보고 뺀다"""
        b = cs.boxes([('총 결제금액', 40, 300, 80, 16),
                      ('구매 혜택', 500, 300, 70, 16), ('최대', 650, 300, 30, 16), ('15,006원', 690, 300, 70, 16),
                      ('224,910원', 40, 322, 90, 20)])
        self.assertEqual(price.find_checkout_total(b), (224910, '총결제금액'))

    def test_discount_coupon_point_rows_excluded(self):
        for label in ('쿠폰 할인', '포인트 사용', '즉시 할인', '마일리지', '카드 캐시백'):
            with self.subTest(label=label):
                b = cs.boxes([('총 결제금액', 40, 300, 80, 16), (label, 500, 300, 80, 16), ('-15,006원', 690, 300, 70, 16),
                              ('224,910원', 40, 322, 90, 20)])
                self.assertEqual(price.find_checkout_total(b)[0], 224910)

    def test_benefit_only_gives_none(self):
        """결제 금액 근처에 혜택 금액밖에 없으면 잘못 고르지 않고 '모름' (같은 주문은 해시 거리로 판단)"""
        b = cs.boxes([('총 결제금액', 40, 300, 80, 16), ('최대 15,006원 적립', 700, 300, 130, 16)])
        self.assertEqual(price.find_checkout_total(b), (None, ''))

    def test_total_label_with_discount_word_kept(self):
        """결제 금액 라벨 자체에 '할인'이 들어 있으면 빼지 않는다"""
        b = cs.boxes([('총 결제금액(할인 포함)', 40, 300, 160, 16), ('33,000원', 700, 300, 80, 16)])
        self.assertEqual(price.find_checkout_total(b), (33000, '총결제금액'))
        b = cs.boxes([('총 결제금액 33,000원 (쿠폰 적용)', 40, 300, 260, 16)])
        self.assertEqual(price.find_checkout_total(b)[0], 33000)

    def test_benefit_word_reasons(self):
        b = cs.boxes([('구매 혜택', 40, 300, 70, 16), ('최대', 650, 300, 30, 16), ('630원', 690, 300, 50, 16),
                      ('최대 1,630원 혜택', 40, 340, 130, 16), ('미버심 적림', 40, 380, 90, 16), ('1,130원', 690, 380, 60, 16),
                      ('상품 금액', 40, 420, 70, 16), ('224,910원', 690, 420, 80, 16)])
        found = {c.value: price.benefit_word(c, b) for c in price.find_tokens(b)[0]}
        self.assertEqual(found, {630: '혜택', 1630: '혜택', 1130: '적림', 224910: ''})

    def test_real_zigzag_benefit_area_not_total(self):
        """실제 캡처 지그재그: 구매 혜택 영역(최대 630원, 최대 1,630원 혜택)의 금액은 결제 금액 후보가 아니다"""
        _, boxes, _ = cache.load('checkout_zigzag')
        reasons = {c.text: price.benefit_word(c, boxes) for c in price.find_tokens(boxes)[0]}
        self.assertEqual(reasons['630원'], '혜택')
        self.assertTrue(reasons['1,630원'])
        self.assertEqual(reasons['224,910원'], '')

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
