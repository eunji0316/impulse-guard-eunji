"""위험도 모델 기준 구현: 원시 값 → 모델 입력 → 위험도와 이유

train.py가 내보낸 JSON 하나로 계산한다 (scikit-learn 없이 math만).
서버 PHP(ipp/lib/risk.lib.php)와 C-3 예측 서버는 이 파일과 같은 결과를 내야 한다.
JSON의 tests(원시 값 → 확률, 이유)로 맞는지 확인한다.

계산
1. 특성마다 원시 값을 변환 (kind). 모름이면 학습 평균을 써서 표준화 값이 0이 된다
2. 표준화: z = (x − mean) / std
3. 로그오즈 = intercept + Σ coef × z, 위험도 = 1 / (1 + e^−로그오즈)
4. 이유: coef × z가 '평균적인 결제보다 위험을 얼마나 올렸나'다. group별로 더해 REASON_MIN 이상인 것을 큰 순서로
"""
import json
import math


def _num(v):
    """None, 빈 문자열, NaN → None"""
    if v is None or v == '':
        return None
    v = float(v)
    return None if math.isnan(v) else v


def transform_one(spec, raw):
    """특성 하나의 변환 값. 모름이면 None (missing 종류는 0/1)"""
    v = _num(raw.get(spec['raw']))
    kind = spec['kind']
    if kind == 'missing':
        return 1.0 if v is None else 0.0
    if v is None:
        return None
    if kind == 'flag_hour':
        x = 1.0 if int(v) in spec['hours'] else 0.0
    elif kind == 'flag_ge':
        x = 1.0 if v >= spec['value'] else 0.0
    elif kind == 'flag_le':
        x = 1.0 if v <= spec['value'] else 0.0
    elif kind == 'log':
        x = math.log(max(v, 1e-9) / spec['scale'])
    elif kind == 'log1p':
        x = math.log1p(max(v, 0.0))
    elif kind == 'linear':
        x = v / spec['scale']
    else:
        raise ValueError(f'알 수 없는 kind: {kind}')
    if 'clip' in spec:
        lo, hi = spec['clip']
        x = min(max(x, lo), hi)
    return x


def transform(features, raw):
    """원시 값 사전 → 변환 값 목록 (모름은 None)"""
    return [transform_one(spec, raw) for spec in features]


class RiskModel:
    def __init__(self, data):
        self.data = data
        self.features = data['features']
        self.coef = data['coef']
        self.intercept = data['intercept']
        self.reason_min = data['reason_min']

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as f:
            return cls(json.load(f))

    def zscores(self, raw):
        z = []
        for spec, x in zip(self.features, transform(self.features, raw)):
            z.append(0.0 if x is None else (x - spec['mean']) / spec['std'])
        return z

    def predict(self, raw):
        """(위험도 0~1, 이유 [(group, 기여)], 로그오즈)"""
        z = self.zscores(raw)
        contrib = [c * v for c, v in zip(self.coef, z)]
        logit = self.intercept + sum(contrib)
        prob = 1 / (1 + math.exp(-logit))
        groups = {}
        for spec, c in zip(self.features, contrib):
            if spec['group']:
                groups[spec['group']] = groups.get(spec['group'], 0.0) + c
        reasons = sorted(((g, round(c, 4)) for g, c in groups.items() if c >= self.reason_min),
                         key=lambda t: -t[1])
        return prob, reasons, logit
