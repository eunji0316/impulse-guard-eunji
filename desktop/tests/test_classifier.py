"""쇼핑 화면 분류 모델 테스트 (C-1)

- 추론 계산: 작은 모델로 TF-IDF + softmax를 직접 계산한 값과 비교
- 키워드 판정으로 바꾸기: 모델 파일 없음, 파일 깨짐, 저신뢰, 판정 오류, 모델 꺼짐
- 함께 배포하는 모델: 실측 캐시 정답, 주문 완료 화면은 쇼핑 아님, 판정 시간 0.1초 미만

실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest tests.test_classifier -v
"""
import json
import math
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import cache
import make_screen_cache
from impulse_guard import config, main
from impulse_guard.detector import classifier, stage

TINY = {
    'labels': ['none', 'product', 'checkout'], 'ngram_range': [2, 2], 'sublinear_tf': True,
    'ocr_fixes': {'금억': '금액'},
    'vocab': ['결제', '금액', '상품'], 'idf': [2.0, 1.5, 1.0],
    'coef': [[-1.0, -1.0, 0.0], [0.0, 0.0, 2.0], [3.0, 2.0, -1.0]], 'intercept': [0.5, 0.0, -0.5],
}


class FakeModel:
    """predict(text) → (분류, 확률, {분류: 확률})를 정해 둔 모델"""

    def __init__(self, label='checkout', prob=0.9, error=None):
        self.label, self.prob, self.error = label, prob, error
        self.calls = 0

    def predict(self, text):
        self.calls += 1
        if self.error:
            raise self.error
        return self.label, self.prob, {self.label: self.prob}


class TestPreprocess(unittest.TestCase):
    def test_spaces_case_digits(self):
        self.assertEqual(classifier.preprocess(' 총 결제 금액\n224,910원 SALE '), '총결제금액000,000원sale')

    def test_ocr_fixes_after_removing_spaces(self):
        self.assertEqual(classifier.preprocess('좀 결제 금억', {'금억': '금액', '좀결제': '총결제'}), '총결제금액')

    def test_empty(self):
        self.assertEqual(classifier.preprocess(None), '')


class TestScreenModel(unittest.TestCase):
    def setUp(self):
        self.m = classifier.ScreenModel(TINY)

    def test_probability_matches_manual(self):
        """'결제 금억 결제' → 결제 2번, 금액 1번 (오타 고침), 제금 등은 어휘에 없음"""
        tf = {0: 1 + math.log(2), 1: 1.0}
        v = {i: tf[i] * TINY['idf'][i] for i in tf}
        norm = math.sqrt(sum(x * x for x in v.values()))
        logits = [sum(TINY['coef'][k][i] * v[i] / norm for i in v) + TINY['intercept'][k] for k in range(3)]
        exp = [math.exp(x) for x in logits]
        want = [e / sum(exp) for e in exp]
        got = self.m.predict_proba('결제 금억 결제')
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=9)
        label, prob, probs = self.m.predict('결제 금억 결제')
        self.assertEqual(label, 'checkout')
        self.assertAlmostEqual(prob, max(want))
        self.assertAlmostEqual(sum(probs.values()), 1.0)

    def test_no_known_ngram(self):
        self.assertIsNone(self.m.predict_proba('뉴스 기사'))
        self.assertIsNone(self.m.predict(''))

    def test_size_mismatch(self):
        bad = dict(TINY, idf=[1.0])
        with self.assertRaises(ValueError):
            classifier.ScreenModel(bad)


class TestDecide(unittest.TestCase):
    """stage.decide: 모델을 못 쓰거나 확신이 낮으면 키워드 판정"""
    PRODUCT_TEXT = '장바구니 구매하기 49,600원'                       # 키워드: 상품 화면

    def tearDown(self):
        classifier.reset()

    def test_confident_model_wins(self):
        classifier.set_model(FakeModel('checkout', 0.9))
        r = stage.decide(self.PRODUCT_TEXT, True)
        self.assertEqual((r.stage, r.source, r.model_stage), (stage.CHECKOUT, 'model', stage.CHECKOUT))
        self.assertTrue(r.evidence().endswith('| 모델 결제 화면 0.90'))

    def test_model_can_say_none(self):
        classifier.set_model(FakeModel('none', 0.95))
        self.assertEqual(stage.decide(self.PRODUCT_TEXT, True).stage, stage.NONE)

    def test_low_confidence_uses_keyword(self):
        classifier.set_model(FakeModel('none', config.SCREEN_MODEL_MIN_PROB - 0.01))
        r = stage.decide(self.PRODUCT_TEXT, True)
        self.assertEqual((r.stage, r.source, r.fallback), (stage.PRODUCT, 'keyword', '저신뢰'))
        self.assertIn(f'| 키워드 판정 (저신뢰: 모델 쇼핑 아님 {config.SCREEN_MODEL_MIN_PROB - 0.01:.2f})', r.evidence())

    def test_threshold_is_inclusive(self):
        classifier.set_model(FakeModel('none', config.SCREEN_MODEL_MIN_PROB))
        self.assertEqual(stage.decide(self.PRODUCT_TEXT, True).source, 'model')

    def test_no_model_uses_keyword(self):
        classifier.set_model(None)
        r = stage.decide(self.PRODUCT_TEXT, True)
        kw = stage.classify(self.PRODUCT_TEXT, True)
        self.assertEqual((r.stage, r.score, r.source), (kw.stage, kw.score, 'keyword'))
        self.assertEqual(r.evidence(), kw.evidence())          # 모델이 없을 때는 근거 문구가 예전과 같다

    def test_model_error_uses_keyword(self):
        classifier.set_model(FakeModel(error=RuntimeError('boom')))
        r = stage.decide(self.PRODUCT_TEXT, True)
        self.assertEqual((r.stage, r.source), (stage.PRODUCT, 'keyword'))
        self.assertIn('모델 판정 오류', classifier.last_error())

    def test_disabled(self):
        fake = FakeModel('checkout', 0.99)
        classifier.set_model(fake)
        with mock.patch.object(config, 'SCREEN_MODEL_ENABLED', False):
            self.assertEqual(stage.decide(self.PRODUCT_TEXT, True).stage, stage.PRODUCT)
        self.assertEqual(fake.calls, 0)

    def test_analyze_boxes_uses_model(self):
        """main.analyze_boxes가 모델 판정을 쓴다: 모델이 쇼핑 아님이면 가격 분석을 하지 않는다"""
        classifier.set_model(FakeModel('none', 0.99))
        img, boxes, reread = cache.load('coupang_product')
        a = main.analyze_boxes(boxes, img, reread)
        self.assertEqual(a.stage.stage, stage.NONE)
        self.assertFalse(a.is_shopping)
        self.assertIsNone(a.prices)


class TestModelFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        classifier.reset()
        shutil.rmtree(self.dir, ignore_errors=True)

    def load_from(self, path):
        classifier.reset()
        with mock.patch.object(config, 'SCREEN_MODEL_PATH', path):
            return classifier.get_model()

    def test_missing_file(self):
        self.assertIsNone(self.load_from(os.path.join(self.dir, 'none.json')))
        self.assertEqual(classifier.last_error(), '모델 파일 없음')
        self.assertIsNone(classifier.predict('주문/결제 결제수단'))

    def test_broken_file(self):
        path = os.path.join(self.dir, 'broken.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{"labels": ')
        self.assertIsNone(self.load_from(path))
        self.assertIn('모델 읽기 실패', classifier.last_error())

    def test_load_once(self):
        path = os.path.join(self.dir, 'tiny.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(TINY, f)
        m = self.load_from(path)
        self.assertIsNotNone(m)
        os.remove(path)
        with mock.patch.object(config, 'SCREEN_MODEL_PATH', path):
            self.assertIs(classifier.get_model(), m)            # 다시 읽지 않는다

    def test_status_text(self):
        classifier.reset()
        with mock.patch.object(config, 'SCREEN_MODEL_PATH', os.path.join(self.dir, 'none.json')):
            self.assertIn('키워드 판정 (모델 파일 없음', main.screen_model_status())


class TestShippedModel(unittest.TestCase):
    """함께 배포하는 models/screen_classifier.json"""

    @classmethod
    def setUpClass(cls):
        classifier.reset()
        cls.model = classifier.get_model()

    @classmethod
    def tearDownClass(cls):
        classifier.reset()

    def test_loads(self):
        self.assertIsNotNone(self.model, classifier.last_error())
        self.assertEqual(self.model.labels, [stage.NONE, stage.PRODUCT, stage.CHECKOUT])

    def real_texts(self):
        """[(엔진, 이름, 정답, 글자)] EasyOCR 캐시 7장 + 분류 평가 캐시"""
        out = []
        for name in cache.names():
            _, boxes, _ = cache.load(name)
            out.append(('easy', name, make_screen_cache.screen_label(name), ' '.join(b.text for b in boxes)))
        for engine in make_screen_cache.ENGINES:
            out += [(engine, n, label, t) for n, label, t in make_screen_cache.load_all(engine)]
        return out

    def test_real_images(self):
        """실측 캐시: 실제 동작(모델 + 저신뢰 시 키워드)은 모두 정답"""
        for engine, name, label, text in self.real_texts():
            with self.subTest(engine=engine, name=name):
                self.assertEqual(stage.decide(text, True).stage, label)

    def test_order_complete_is_none(self):
        """주문 완료/주문 내역은 쇼핑 아님 (이미 산 뒤라 개입하지 않고, 배송 조회 중 차단 창이 뜨면 안 된다)"""
        texts = [
            '주문이 완료되었습니다 주문해 주셔서 감사합니다 주문번호 202611130012345 결제 금액 39,000원 결제수단 신용카드 '
            '배송지 김*연 서울특별시 마포구 월드컵로 12 주문 상세보기 쇼핑 계속하기',
            '주문/배송 조회 1개월 3개월 6개월 2026.11.02 배송중 오버핏 후드 집업 49,000원 배송조회 구매확정 '
            '2026.10.28 배송완료 무선 이어폰 89,000원 리뷰 작성 반품 신청',
        ]
        for text in texts:
            with self.subTest(text=text[:12]):
                label, prob, _ = self.model.predict(text)
                self.assertEqual(label, stage.NONE)
                self.assertGreaterEqual(prob, config.SCREEN_MODEL_MIN_PROB)

    def test_speed(self):
        """판정 0.1초 미만 (가장 긴 실측 글자를 3배로 늘려도)"""
        text = max((t for *_, t in self.real_texts()), key=len) * 3
        start = time.perf_counter()
        for _ in range(20):
            stage.decide(text, True)
        self.assertLess((time.perf_counter() - start) / 20, 0.1)


if __name__ == '__main__':
    unittest.main()
