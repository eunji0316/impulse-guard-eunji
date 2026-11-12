"""가격 분석 테스트

1. 가짜 OCR 상자로 규칙 하나씩 확인 (이미지 없이: 취소선/색 단서는 0)
2. 테스트 이미지 4장의 결과 확인
   EXPECTED는 사용자가 실제 상품 페이지와 대조해 확인한 값이다 (2026-11-11).
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import unittest

import cache
from impulse_guard.ocr import OcrBox
from impulse_guard.detector import price


def box(text, x, y, w, h, conf=0.9):
    return OcrBox(text=text, conf=conf, bbox=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


class TestTokens(unittest.TestCase):
    def values(self, boxes):
        prices, _ = price.find_tokens(boxes)
        return [(c.value, c.features['format_ok']) for c in prices]

    def test_price_formats(self):
        self.assertEqual(self.values([box('49,600원', 0, 0, 90, 30)]), [(49600, 1.0)])
        self.assertEqual(self.values([box('₩35,000', 0, 0, 90, 30)]), [(35000, 1.0)])
        self.assertEqual(self.values([box('56,000', 0, 0, 60, 14)]), [(56000, 1.0)])      # 원 없어도 쉼표 형식이면 가격
        self.assertEqual(self.values([box('49.600원', 0, 0, 90, 30)]), [(49600, 1.0)])    # 쉼표를 마침표로 읽은 경우

    def test_not_price(self):
        self.assertEqual(self.values([box('332 개 상품평', 0, 0, 90, 20)]), [])   # 원 없는 숫자
        self.assertEqual(self.values([box('내일(목) 11/12 도착', 0, 0, 90, 20)]), [])
        self.assertEqual(self.values([box('3.7천', 0, 0, 30, 20)]), [])

    def test_ocr_error_format(self):
        """쉼표 없는 큰 숫자(444366원)와 깨진 글자 사이의 숫자는 형식 이상"""
        self.assertEqual(self.values([box('444366원', 0, 0, 90, 30)]), [(444366, 0.0)])
        self.assertEqual(self.values([box('구돈적용가0 35B,888원', 0, 0, 130, 18)]), [(888, 0.0)])

    def test_split_won_box(self):
        """숫자와 '원'이 다른 상자로 나뉘어도 가격으로 합친다"""
        prices, _ = price.find_tokens([box('44800', 0, 0, 60, 20), box('원', 62, 4, 12, 14)])
        self.assertEqual([c.value for c in prices], [44800])
        self.assertEqual(prices[0].box[2], 74)

    def test_percent_misread(self):
        """EasyOCR이 58%를 '5896'으로 읽는 경우, 바로 오른쪽에 가격이 있으면 할인율로 보정"""
        _, rates = price.find_tokens([box('5896', 0, 8, 32, 16), box('49,600원', 34, 0, 93, 31)])
        self.assertEqual([r.value for r in rates], [58])
        _, rates = price.find_tokens([box('5896', 0, 8, 32, 16)])   # 옆에 가격이 없으면 보정하지 않음
        self.assertEqual(rates, [])


class TestAnalyze(unittest.TestCase):
    def test_verify_with_rate(self):
        """원가 × (1 − 할인율) ≈ 할인가인 조합을 고르고, 맞지 않는 가격은 OCR 오류로 제외"""
        boxes = [
            box('58%', 0, 10, 30, 16),
            box('49,600원', 34, 0, 93, 31),
            box('119,000원', 0, 34, 70, 18),
            box('444366원', 0, 60, 70, 18),        # 화면에 없는 값 (OCR 오류)
        ]
        r = price.analyze(boxes)
        self.assertEqual((r.sale_price, r.original_price, r.discount_rate), (49600, 119000, 58))
        self.assertTrue(r.verified)
        bad = [c for c in r.candidates if c.value == 444366][0]
        self.assertEqual(bad.role, 'excluded')

    def test_rate_tolerance(self):
        """사이트가 반올림한 할인율도 통과 (220,590 / 258,000 → 14.5%, 표시 15%), 크게 다르면 실패"""
        ok = price.analyze([box('15%', 0, 30, 30, 20), box('220,590원', 34, 28, 90, 24), box('258,000원', 0, 0, 80, 18)])
        self.assertTrue(ok.verified)
        ng = price.analyze([box('30%', 0, 30, 30, 20), box('220,590원', 34, 28, 90, 24), box('258,000원', 0, 0, 80, 18)])
        self.assertFalse(ng.verified)

    def test_coupon_rate_is_not_product_rate(self):
        """'첫 구매 20% 쿠폰'의 20%는 상품 할인율이 아님. 그런데 '쿠폰적용가'는 판매가 라벨이므로 기타가 아님"""
        r = price.analyze([box('첫 구매 20% 쿠폰 받으러 가기', 0, 100, 200, 20),
                           box('쿠폰적용가', 0, 0, 60, 18), box('15%', 0, 30, 30, 20), box('220,590원', 34, 28, 90, 24)])
        kinds = {t.value: t.is_product for t in r.rates}
        self.assertEqual(kinds, {20: False, 15: True})
        sale = [c for c in r.candidates if c.value == 220590][0]
        self.assertEqual(sale.features['ctx_other'], 0.0)
        self.assertEqual(sale.features['ctx_sale'], 1.0)

    def test_other_price(self):
        """적립금은 기타"""
        r = price.analyze([box('49,600원', 0, 0, 93, 31), box('최대 2,480원 쿠팡캐시 적립', 0, 300, 180, 20)])
        roles = {c.value: c.role for c in r.candidates}
        self.assertEqual(roles[2480], 'other')
        self.assertEqual(r.sale_price, 49600)

    def test_benefit_amounts_not_verified(self):
        """혜택/적립 금액끼리 할인율 검산을 통과해도 원가/할인가가 아님 (C-2, 무신사 결제 화면 Windows OCR 1배:
        '최대 32,500원 혜택'과 '6,180원 구매 적립'이 80%로 검산 통과해 원가 32,500원, 할인가 6,180원이 됐던 사례)"""
        boxes = [
            box('80%', 0, 10, 30, 16),
            box('79,000원', 34, 0, 93, 31),
            box('최대 32,500원 혜택', 0, 200, 150, 18),
            box('무신사머니 첫 결제 시 6,180원 구매 적립', 0, 240, 260, 18),
        ]
        r = price.analyze(boxes)
        self.assertEqual(r.sale_price, 79000)
        self.assertIsNone(r.original_price)
        self.assertFalse(r.verified)
        roles = {c.value: (c.role, c.reason) for c in r.candidates}
        self.assertEqual(roles[32500], ('other', '혜택/적립 금액 (혜택)'))
        self.assertEqual(roles[6180], ('other', '혜택/적립 금액 (적립)'))

    def test_benefit_label_on_left(self):
        """같은 줄 왼쪽 항목 이름이 혜택이면 ('구매 혜택 … 최대 630원') 꾸밈말을 건너뛰고 혜택 금액으로 본다"""
        r = price.analyze([box('구매 혜택', 0, 0, 60, 18), box('최대', 200, 0, 30, 18), box('630원', 235, 0, 40, 18)])
        self.assertIsNone(r.sale_price)
        self.assertEqual(r.candidates[0].role, 'other')

    def test_sale_labels_are_not_benefit(self):
        """'혜택가', '쿠폰할인가', '쿠폰적용가'는 판매가 라벨이라 혜택 금액으로 빼지 않는다"""
        for label in ('최대혜택가', '쿠폰할인가', '쿠폰적용가'):
            r = price.analyze([box(label, 0, 0, 80, 18), box('44,800원', 90, 0, 90, 18)])
            self.assertEqual(r.sale_price, 44800, label)

    def test_rate_next_to_sale_without_original(self):
        """원가를 못 읽어도 할인가 옆(같은 줄, 또는 바로 위 줄에 가로로 붙음)의 상품 할인율은 쓴다 (C-2)"""
        r = price.analyze([box('58%', 0, 0, 30, 22), box('49,600원', 40, 0, 80, 22)])
        self.assertEqual((r.sale_price, r.original_price, r.discount_rate), (49600, None, 58))
        self.assertTrue(r.rate_shown)
        self.assertFalse(r.verified)
        self.assertLess(r.rate_conf, r.sale_conf + 1e-9)
        # 컬리 장바구니: 할인율이 원가 줄(할인가 바로 위)에 있다
        r = price.analyze([box('49%', 0, 0, 35, 12), box('59,400원', 1, 26, 107, 26)])
        self.assertEqual(r.discount_rate, 49)

    def test_rate_not_next_to_sale(self):
        """할인가에서 먼 퍼센트는 쓰지 않는다"""
        r = price.analyze([box('49,600원', 0, 0, 80, 22), box('58%', 300, 0, 30, 22)])        # 같은 줄이지만 멀다
        self.assertIsNone(r.discount_rate)
        r = price.analyze([box('49,600원', 0, 0, 80, 22), box('58%', 0, 200, 30, 22)])        # 한참 아래
        self.assertIsNone(r.discount_rate)

    def test_rate_in_benefit_context(self):
        """적립·카드·쿠폰·최대·혜택 문맥의 퍼센트는 할인가 옆이어도 할인율이 아님"""
        for text in ('최대 10%', '10% 적립', '카드 7%', '10% 쿠폰', '혜택 5%', '포인트 3%'):
            r = price.analyze([box(text, 0, 0, 60, 22), box('49,600원', 70, 0, 80, 22)])
            self.assertIsNone(r.discount_rate, text)

    def test_rate_with_digit_before(self):
        """'150%'(15% 오인식)에서 50%를 할인율로 읽지 않는다"""
        _, rates = price.find_tokens([box('150%', 0, 0, 40, 18)])
        self.assertEqual(rates, [])

    def test_no_price(self):
        r = price.analyze([box('오늘의 뉴스', 0, 0, 90, 20)])
        self.assertIsNone(r.sale_price)
        self.assertEqual(r.sale_conf, 0.0)

    def test_features_for_learning(self):
        """단서 점수는 학습 특성으로 쓰므로 모든 후보에 같은 이름으로 0~1 값이 있어야 한다"""
        r = price.analyze([box('58%', 0, 10, 30, 16), box('49,600원', 34, 0, 93, 31), box('119,000원', 0, 34, 70, 18)])
        for c in r.candidates:
            self.assertEqual(list(c.features), price.FEATURE_NAMES)
            for v in c.features.values():
                self.assertTrue(0.0 <= v <= 1.0)


# 정답 (할인가, 원가, 할인율). 사용자 확인 완료 (2026-11-11)
EXPECTED = {
    'coupang_product': (49600, 119000, 58),
    'musinsa_product': (220590, 258000, 15),
    'zigzag_product': (44800, 56000, 20),
    'news_page': (None, None, None),
}


class TestImages(unittest.TestCase):
    def test_images(self):
        for name in cache.names():
            if name.startswith('checkout_'):
                continue                                  # 상품 화면의 가격 분석만 본다. 결제 금액은 test_stage.py
            with self.subTest(image=name):
                img, boxes, reread = cache.load(name)
                r = price.analyze(boxes, img, reread=reread)
                self.assertEqual((r.sale_price, r.original_price, r.discount_rate), EXPECTED[name])
                if r.sale_price:
                    self.assertTrue(r.verified)

    def test_strike_and_color_cues(self):
        """취소선과 색 단서: 원가는 취소선+회색, 지그재그 할인가는 빨강"""
        for name in ['coupang_product', 'musinsa_product', 'zigzag_product']:
            with self.subTest(image=name):
                img, boxes, reread = cache.load(name)
                r = price.analyze(boxes, img, reread=reread)
                orig = [c for c in r.candidates if c.role == 'original'][0]
                sale = [c for c in r.candidates if c.role == 'sale'][0]
                self.assertEqual(orig.features['strike'], 1.0)
                self.assertEqual(orig.features['color_gray'], 1.0)
                self.assertEqual(sale.features['strike'], 0.0)
        img, boxes, reread = cache.load('zigzag_product')
        r = price.analyze(boxes, img, reread=reread)
        sale = [c for c in r.candidates if c.role == 'sale'][0]
        self.assertEqual(sale.features['color_red'], 1.0)


if __name__ == '__main__':
    unittest.main()
