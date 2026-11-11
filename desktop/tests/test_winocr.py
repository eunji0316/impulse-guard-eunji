"""Windows 내장 OCR 래퍼 테스트 (B-5)

- join_words, split_line: Windows OCR 없이도 도는 순수 함수
- 실제 OCR: 한국어 Windows OCR이 있을 때만 (없으면 건너뜀). tests/images의 결제 화면 금액과 점수
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -p test_winocr.py -v
"""
import unittest
from types import SimpleNamespace
from unittest import mock

import cache
from impulse_guard import config, main, ocr, winocr


def word(text, x, w=40, y=0, h=20):
    return SimpleNamespace(text=text, bounding_rect=SimpleNamespace(x=x, y=y, width=w, height=h))


class TestJoinWords(unittest.TestCase):
    def test_split_number_rejoined_with_comma(self):
        self.assertEqual(winocr.join_words(['224', '910원']), '224,910원')
        self.assertEqual(winocr.join_words(['총', '224', '910원']), '총 224,910원')
        self.assertEqual(winocr.join_words(['최대', '1', '630원']), '최대 1,630원')

    def test_normal_words_joined_with_space(self):
        self.assertEqual(winocr.join_words(['결제', '금액']), '결제 금액')
        self.assertEqual(winocr.join_words(['1회', '본인인증', '후', '결제하기']), '1회 본인인증 후 결제하기')
        self.assertEqual(winocr.join_words(['2026', '11']), '2026 11')     # 뒤가 3자리가 아니면 잇지 않음


class TestSplitLine(unittest.TestCase):
    def test_far_words_become_separate_boxes(self):
        """'상품 금액 ……… 224,910원'처럼 멀리 떨어진 금액은 다른 상자 (라벨 옆 금액 찾기가 EasyOCR과 같게)"""
        groups = winocr.split_line([word('상품', 0), word('금액', 45), word('224,910원', 400, 80)])
        self.assertEqual([[w.text for w in g] for g in groups], [['상품', '금액'], ['224,910원']])

    def test_split_number_kept_together(self):
        """쉼표 자리가 조금 벌어져도 숫자 두 조각은 한 상자"""
        groups = winocr.split_line([word('224', 0, 30), word('910원', 65, 40)])
        self.assertEqual(len(groups), 1)


class TestEngineChoice(unittest.TestCase):
    """main.ocr_engine: 'win'이면 Windows OCR, 쓸 수 없으면 EasyOCR로 바꾼다"""
    def setUp(self):
        self.saved = main._engine
        main._engine = None

    def tearDown(self):
        main._engine = self.saved

    def test_windows_ocr_when_available(self):
        with mock.patch.object(config, 'OCR_ENGINE', 'win'), mock.patch.object(winocr, 'available', return_value=True):
            eng = main.ocr_engine()
        self.assertEqual((eng.name, eng.read, eng.reread, eng.note), ('Windows OCR', winocr.read, winocr.read_struck, ''))

    def test_fallback_to_easyocr(self):
        with mock.patch.object(config, 'OCR_ENGINE', 'win'), mock.patch.object(winocr, 'available', return_value=False):
            eng = main.ocr_engine()
        self.assertEqual((eng.name, eng.read), ('EasyOCR', ocr.read))
        self.assertIn('EasyOCR', eng.note)

    def test_easy_setting(self):
        with mock.patch.object(config, 'OCR_ENGINE', 'easy'), mock.patch.object(winocr, 'available') as avail:
            eng = main.ocr_engine()
        self.assertEqual((eng.name, eng.note), ('EasyOCR', ''))
        avail.assert_not_called()

    def test_engine_name_in_timing(self):
        main._engine = main.OcrEngine('가짜', lambda img: [], lambda img, box: [])
        t = main.timing.Timing('auto')
        with main.timing.active(t):
            main.analyze_image(None)
        self.assertEqual(t.info['엔진'], '가짜')


@unittest.skipUnless(winocr.available(), '한국어 Windows OCR이 없음')
class TestRealWindowsOcr(unittest.TestCase):
    """EasyOCR 기준선보다 결제 키워드 점수가 낮지 않고 금액이 같아야 한다 (B-5 조건)"""
    EASYOCR_SCORE = {'checkout_musinsa': 14, 'checkout_zigzag': 9, 'checkout_zigzag_benefit': 9}
    AMOUNT = {'checkout_musinsa': 79000, 'checkout_zigzag': 224910, 'checkout_zigzag_benefit': 224910}

    def test_checkout_images(self):
        for name, amount in self.AMOUNT.items():
            with self.subTest(name=name):
                img, _, _ = cache.load(name)
                a = main.analyze_boxes(winocr.read(img), img, reread=winocr.read_struck)
                self.assertTrue(a.is_checkout)
                self.assertEqual(a.amount, amount)
                self.assertGreaterEqual(a.stage.score, self.EASYOCR_SCORE[name])


if __name__ == '__main__':
    unittest.main()
