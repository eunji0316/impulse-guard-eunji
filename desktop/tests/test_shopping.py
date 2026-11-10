"""원본(desktop/original/shopping_detector.py)과 새 코드의 쇼핑 판정이 같은지 비교한다

같은 OCR 캐시를 원본과 새 코드에 넣고 판정, 감지된 키워드, 가격 정보(원본이 출력하는 앞 3개)를 비교한다.
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import unittest

import cache
import run_original
from impulse_guard import ocr
from impulse_guard.detector import shopping

# 사람이 이미지를 보고 정한 정답 (원본과 새 코드 모두 이렇게 나와야 한다)
EXPECTED_MALL = {
    'coupang_product': True,
    'musinsa_product': True,
    'zigzag_product': True,
    'news_page': False,
}


class TestShoppingSameAsOriginal(unittest.TestCase):
    def test_cache_covers_all_images(self):
        self.assertEqual(sorted(EXPECTED_MALL), cache.names())

    def test_same_as_original(self):
        for name in cache.names():
            with self.subTest(image=name):
                img, boxes, _ = cache.load(name)
                orig = run_original.run([b.to_raw() for b in boxes], img)
                new = shopping.judge(ocr.full_text(boxes))

                self.assertEqual(orig['is_mall'], new.is_mall)
                self.assertEqual(new.is_mall, EXPECTED_MALL[name])
                if new.is_mall:
                    self.assertEqual(orig['found_keywords'], new.found_keywords)
                    self.assertEqual(orig['price_patterns_top3'], new.price_patterns[:3])

    def test_rules_same_as_original_on_samples(self):
        """캐시 말고도 경계 사례로 원본과 비교 (키워드 1개/2개, 가격만, ',원' 같은 원본 정규식 버릇)"""
        samples = [
            '장바구니',                       # 키워드 1개 → 아님
            '장바구니 구매하기',               # 키워드 2개 → 쇼핑
            '오늘 날씨 15,000원',              # 가격만 → 쇼핑
            '₩35,000',                        # ₩ 가격
            '뉴스 기사 ,원 입니다',            # 원본 정규식은 ',원'도 가격으로 잡는다
            '',
        ]
        import numpy as np
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        for text in samples:
            with self.subTest(text=text):
                raw = [([[0, 0], [1, 0], [1, 1], [0, 1]], text, 0.9)] if text else []
                orig = run_original.run(raw, img)
                new = shopping.judge(text)
                self.assertEqual(orig['is_mall'], new.is_mall)
                if new.is_mall:
                    self.assertEqual(orig['found_keywords'], new.found_keywords)
                    self.assertEqual(orig['price_patterns_top3'], new.price_patterns[:3])


if __name__ == '__main__':
    unittest.main()
