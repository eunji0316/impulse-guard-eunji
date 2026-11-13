"""C-2 위험도 모델 학습과 내보내기

실행 (ai 폴더에서, 먼저 risk.generate로 데이터를 만든다):
    .venv\\Scripts\\python.exe -m risk.train [--data data/risk/synthetic.csv]
    → ipp/model/risk_model.json

모델: 표준화한 특성 + 로지스틱 회귀 (class_weight 없음: 위험도를 확률로 보여 주므로 보정을 지킨다).
내보낸 JSON은 서버 PHP가 계산한다. 내보낸 뒤 기준 구현(model.py)과 sklearn 확률이 같은지 확인하고,
서버 테스트용으로 원시 값 → 확률/이유 예시(tests)를 함께 넣는다.
"""
import argparse
import datetime
import json
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from . import generate, schema as S
from .model import RiskModel, transform

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MODEL_OUT = os.path.join(ROOT, 'ipp', 'model', 'risk_model.json')
FORMAT = 'risk-logreg/1'
C = 1.0
N_TESTS = 30


def raw_rows(df):
    """DataFrame → 원시 값 사전 목록 (빈 값은 None)"""
    return [{k: (None if pd.isna(v) else float(v)) for k, v in rec.items()}
            for rec in df[S.RAW_FIELDS].to_dict('records')]


def labeled(df):
    lab = df[df['label'].notna()].reset_index(drop=True)
    return lab, lab['label'].astype(int).to_numpy()


class Scaler:
    """변환 값 → 표준화. 모름(None)은 평균으로 채운다 (표준화 값 0)"""

    def fit(self, rows):
        T = [transform(S.FEATURES, r) for r in rows]
        self.mean, self.std = [], []
        for j in range(len(S.FEATURES)):
            col = np.array([t[j] for t in T if t[j] is not None], dtype=float)
            m = float(col.mean()) if len(col) else 0.0
            s = float(col.std()) if len(col) else 1.0
            self.mean.append(m)
            self.std.append(s if s > 1e-9 else 1.0)
        return self

    def matrix(self, rows):
        X = np.zeros((len(rows), len(S.FEATURES)))
        for i, r in enumerate(rows):
            for j, x in enumerate(transform(S.FEATURES, r)):
                X[i, j] = 0.0 if x is None else (x - self.mean[j]) / self.std[j]
        return X


def fit(rows, y, feature_mask=None, c=C):
    """(scaler, sklearn 모델). feature_mask: 쓰지 않을 특성을 False로 (비교 실험용, 해당 열을 0으로)"""
    sc = Scaler().fit(rows)
    X = sc.matrix(rows)
    if feature_mask is not None:
        X = X * np.asarray(feature_mask, dtype=float)
    clf = LogisticRegression(C=c, max_iter=2000)
    clf.fit(X, y)
    return sc, clf


def to_json(sc, clf, n_rows, data_name):
    feats = []
    for spec, m, s in zip(S.FEATURES, sc.mean, sc.std):
        f = dict(spec)
        f['mean'], f['std'] = round(m, 6), round(s, 6)
        feats.append(f)
    return {
        'format': FORMAT,
        'version': datetime.date.today().strftime('%Y%m%d') + '-synthetic',
        'meta': {'trained': datetime.date.today().isoformat(), 'rows': n_rows, 'C': C, 'data': data_name,
                 'note': '가상 데이터로 학습. 실제 사용자 성능의 증거가 아님 (ai/risk/README.md)'},
        'raw_fields': S.RAW_FIELDS,
        'raw_params': S.RAW_PARAMS,
        'features': feats,
        'coef': [round(float(v), 6) for v in clf.coef_[0]],
        'intercept': round(float(clf.intercept_[0]), 6),
        'reason_min': S.REASON_MIN,
    }


def golden_cases(model, rows, n=N_TESTS, seed=0):
    """서버 테스트용 예시: 데이터에서 고른 행 + 모름이 많은 행 + 극단값"""
    rng = np.random.default_rng(seed)
    picks = [rows[i] for i in rng.choice(len(rows), size=min(n, len(rows)), replace=False)]
    picks.append({k: None for k in S.RAW_FIELDS})                                 # 모두 모름
    picks.append(dict(picks[0], hour=2, amount=900000, amount_ratio=30, discount_rate=95, pressure=1,
                      product_views_24h=500, same_item_views_24h=99, browse_sec=1, checkouts_7d=80,
                      buy_rate=1, cooldown_fail_rate=1))                            # 범위 밖 (clip 확인)
    cases = []
    for r in picks:
        prob, reasons, _ = model.predict(r)
        raw = {k: (None if v is None else (int(v) if float(v).is_integer() else v)) for k, v in r.items()}
        cases.append({'raw': raw, 'prob': round(prob, 6), 'reasons': [g for g, _ in reasons]})
    return cases


def export(sc, clf, path, rows, data_name):
    data = to_json(sc, clf, len(rows), data_name)
    model = RiskModel(data)
    data['tests'] = golden_cases(model, rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def check_export(path, sc, clf, rows):
    """JSON(model.py 계산)과 sklearn 확률의 최대 차이"""
    model = RiskModel.load(path)
    sk = clf.predict_proba(sc.matrix(rows))[:, 1]
    mine = np.array([model.predict(r)[0] for r in rows])
    return float(np.abs(sk - mine).max())


def main():
    ap = argparse.ArgumentParser(description='C-2 위험도 모델 학습')
    ap.add_argument('--data', default=generate.DEFAULT_OUT)
    ap.add_argument('--out', default=MODEL_OUT)
    args = ap.parse_args()
    df = generate.load(args.data)
    lab, y = labeled(df)
    rows = raw_rows(lab)
    sc, clf = fit(rows, y)
    name = os.path.relpath(args.data, ROOT).replace('\\', '/')
    export(sc, clf, args.out, rows, name)
    diff = check_export(args.out, sc, clf, rows)
    print(f'학습 {len(rows):,}건 (그래도 구매 {y.mean():.1%}) → {args.out}')
    print('계수 (표준화 1단위당 로그오즈):')
    for spec, c in sorted(zip(S.FEATURES, clf.coef_[0]), key=lambda t: -abs(t[1])):
        print(f"  {spec['name']:18} {c:+.3f}")
    print(f'절편 {clf.intercept_[0]:+.3f}')
    print(f'sklearn과 확률 차이 최대 {diff:.2e} (계수를 소수 6자리로 반올림해 생기는 차이)')
    if diff > 1e-4:
        raise SystemExit('내보낸 모델이 sklearn과 다름')


if __name__ == '__main__':
    main()
