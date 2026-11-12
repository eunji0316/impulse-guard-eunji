"""C-2 위험도 기준 구현 테스트

실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m unittest risk.test_risk
"""
import math
import os
import unittest

from . import schema as S, train
from .model import RiskModel, transform_one


def spec(name):
    return next(f for f in S.FEATURES if f['name'] == name)


class TestLabel(unittest.TestCase):
    def test_label_of(self):
        self.assertEqual(S.label_of('buy'), 1)
        self.assertEqual(S.label_of('giveup'), 0)
        self.assertEqual(S.label_of('hold', 'failed'), 1)
        self.assertEqual(S.label_of('hold', 'success'), 0)
        self.assertEqual(S.label_of('hold', 'gaveup'), 0)
        self.assertIsNone(S.label_of('hold', 'waiting'))
        self.assertIsNone(S.label_of('close'))
        self.assertIsNone(S.label_of(''))


class TestTransform(unittest.TestCase):
    def test_hour_flags(self):
        self.assertEqual(transform_one(spec('night'), {'hour': 23}), 1.0)
        self.assertEqual(transform_one(spec('night'), {'hour': 3}), 1.0)
        self.assertEqual(transform_one(spec('night'), {'hour': 4}), 0.0)
        self.assertEqual(transform_one(spec('late_evening'), {'hour': 22}), 1.0)

    def test_missing(self):
        """모름은 None, 모름 표시 특성은 1"""
        self.assertIsNone(transform_one(spec('discount'), {'discount_rate': None}))
        self.assertIsNone(transform_one(spec('discount'), {'discount_rate': float('nan')}))
        self.assertEqual(transform_one(spec('discount_unknown'), {'discount_rate': None}), 1.0)
        self.assertEqual(transform_one(spec('discount_unknown'), {'discount_rate': 0}), 0.0)   # 할인 없음은 모름이 아님
        self.assertEqual(transform_one(spec('discount'), {'discount_rate': 0}), 0.0)

    def test_log_and_clip(self):
        self.assertAlmostEqual(transform_one(spec('log_browse'), {'browse_sec': 60}), 0.0)
        self.assertEqual(transform_one(spec('log_browse'), {'browse_sec': 1}), -3)            # clip
        self.assertAlmostEqual(transform_one(spec('log_views'), {'product_views_24h': 3}), math.log(4))
        self.assertEqual(transform_one(spec('log_views'), {'product_views_24h': 10 ** 6}), 4)
        self.assertEqual(transform_one(spec('discount'), {'discount_rate': 150}), 0.99)


@unittest.skipUnless(os.path.exists(train.MODEL_OUT), '모델 JSON이 없음 (risk.train 먼저)')
class TestExportedModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = RiskModel.load(train.MODEL_OUT)

    def test_golden_cases(self):
        """JSON의 예시가 기준 구현과 같다 (서버 PHP도 같은 예시로 확인)"""
        tests = self.model.data['tests']
        self.assertGreaterEqual(len(tests), 30)
        for t in tests:
            prob, reasons, _ = self.model.predict(t['raw'])
            self.assertAlmostEqual(prob, t['prob'], places=5)
            self.assertEqual([g for g, _ in reasons], t['reasons'])

    def test_all_unknown_is_baseline(self):
        """모두 모름이면 연속 특성 기여가 0이고 이유는 '모름 표시'로 생기지 않는다"""
        prob, reasons, _ = self.model.predict({k: None for k in S.RAW_FIELDS})
        self.assertTrue(0 < prob < 1)
        groups = {f['group'] for f in S.FEATURES}
        self.assertTrue(all(g in groups and g is not None for g, _ in reasons))

    def test_directions(self):
        """가정한 방향과 같은 부호 (가상 데이터 기준)"""
        coef = dict(zip([f['name'] for f in self.model.features], self.model.coef))
        for name in ('night', 'log_ratio', 'discount', 'pressure', 'log_same_item', 'buy_rate'):
            self.assertGreater(coef[name], 0, name)
        self.assertLess(coef['log_browse'], 0)

    def test_reasons_sorted_and_above_min(self):
        prob, reasons, _ = self.model.predict({'hour': 1, 'amount': 300000, 'amount_ratio': 6, 'discount_rate': 60,
                                               'pressure': 1, 'buy_rate': 0.8})
        self.assertGreater(prob, 0.6)
        vals = [c for _, c in reasons]
        self.assertEqual(vals, sorted(vals, reverse=True))
        self.assertTrue(all(c >= self.model.reason_min for c in vals))
        self.assertIn('night', [g for g, _ in reasons])


if __name__ == '__main__':
    unittest.main()
