"""C-2 위험도 모델 평가 (회원 단위 5겹 교차검증)

실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m risk.evaluate [--data data/risk/synthetic.csv]
    → 화면 출력 + data/risk/report.md (Git 제외)

비교
- 지금 규칙: 결제 화면은 항상 팝업이라 규칙이 말할 수 있는 것은 심야/고액뿐 (심야 + 고액 개수를 점수로)
- 로지스틱 회귀: 서버 특성만 / 데스크톱 특성 추가 / 과거 기록 제외 / 전체(배포)
- 참고: 그래디언트 부스팅 (배포하지 않음. 해석 가능한 모델이 얼마나 손해 보는지 보기 위함)
지표: AUC(순서), Brier·log loss(확률이 맞는지), 구간별 예측 평균과 실제 비율(보정), 위험 단계별 실제 비율
"""
import argparse
import os

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from . import generate, schema as S, train
from .model import RiskModel

REPORT = os.path.join(generate.DATA_DIR, 'report.md')
DESKTOP_FEATURES = {'discount', 'discount_unknown', 'pressure', 'log_views', 'log_same_item', 'log_browse', 'browse_unknown'}
HISTORY_FEATURES = {'buy_rate', 'cooldown_fail'}
LEVELS = [(0.0, '낮음'), (0.3, '보통'), (0.55, '높음')]   # 서버 IPP_RISK_LEVEL_* 후보 (위험도 이상이면 그 단계)


def mask(exclude):
    return [0.0 if f['name'] in exclude else 1.0 for f in S.FEATURES]


def rule_score(rows):
    """지금 규칙 흉내: 심야(23~4시) + 고액(5만 원 이상). 금액 모름은 고액 아님"""
    out = []
    for r in rows:
        night = r['hour'] is not None and int(r['hour']) in (23, 0, 1, 2, 3)
        big = r['amount'] is not None and r['amount'] >= 50000
        out.append(int(night) + int(big))
    return np.array(out, dtype=float)


def cross_val(rows, y, groups, kind, exclude=()):
    pred = np.zeros(len(rows))
    for tr, te in GroupKFold(n_splits=5).split(rows, y, groups):
        r_tr, r_te = [rows[i] for i in tr], [rows[i] for i in te]
        if kind == 'rule':
            pred[te] = rule_score(r_te)
        elif kind == 'lr':
            m = mask(exclude)
            sc, clf = train.fit(r_tr, y[tr], m)
            pred[te] = clf.predict_proba(sc.matrix(r_te) * np.asarray(m))[:, 1]
        elif kind == 'gbm':
            sc = train.Scaler().fit(r_tr)
            clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=0)
            clf.fit(sc.matrix(r_tr), y[tr])
            pred[te] = clf.predict_proba(sc.matrix(r_te))[:, 1]
    return pred


def metrics(y, p, prob=True):
    out = {'AUC': roc_auc_score(y, p)}
    if prob:
        out['Brier'] = brier_score_loss(y, p)
        out['log loss'] = log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))
    return out


def level_of(p):
    name = LEVELS[0][1]
    for cut, n in LEVELS:
        if p >= cut:
            name = n
    return name


def main():
    ap = argparse.ArgumentParser(description='C-2 위험도 모델 평가')
    ap.add_argument('--data', default=generate.DEFAULT_OUT)
    ap.add_argument('--model', default=train.MODEL_OUT)
    args = ap.parse_args()
    df = generate.load(args.data)
    lab, y = train.labeled(df)
    rows = train.raw_rows(lab)
    groups = lab['user'].to_numpy()
    lines = [f'# C-2 위험도 모델 평가', '',
             f'데이터: `{os.path.basename(args.data)}` 라벨 있는 {len(rows):,}건, 회원 {len(set(groups))}명, '
             f'그래도 구매 {y.mean():.1%}. 회원 단위 5겹 교차검증 (시험 회원은 학습에 없음)', '']

    runs = [
        ('지금 규칙 (심야 + 고액)', 'rule', ()),
        ('LR 서버 특성만 (시각, 금액, 빈도, 과거 기록)', 'lr', DESKTOP_FEATURES),
        ('LR 과거 기록 제외', 'lr', HISTORY_FEATURES),
        ('**LR 전체 (배포)**', 'lr', ()),
        ('참고: 그래디언트 부스팅', 'gbm', ()),
    ]
    lines += ['| 방법 | AUC | Brier | log loss |', '|---|---|---|---|']
    preds = {}
    for name, kind, ex in runs:
        p = cross_val(rows, y, groups, kind, ex)
        preds[name] = p
        m = metrics(y, p, prob=(kind != 'rule'))
        fmt = lambda k: f'{m[k]:.3f}' if k in m else '-'   # noqa: E731
        lines.append(f"| {name} | {fmt('AUC')} | {fmt('Brier')} | {fmt('log loss')} |")
    base = y.mean()
    lines.append(f'| (기준) 모두 평균 {base:.2f}로 예측 | 0.500 | {brier_score_loss(y, np.full(len(y), base)):.3f} | '
                 f'{log_loss(y, np.full(len(y), base)):.3f} |')

    p = preds['**LR 전체 (배포)**']
    lines += ['', '## 보정 (LR 전체, 교차검증 예측을 10구간으로)', '', '| 예측 구간 | 건수 | 예측 평균 | 실제 비율 |', '|---|---|---|---|']
    order = np.argsort(p)
    for chunk in np.array_split(order, 10):
        lines.append(f'| {p[chunk].min():.2f}~{p[chunk].max():.2f} | {len(chunk)} | {p[chunk].mean():.2f} | {y[chunk].mean():.2f} |')

    lines += ['', f'## 위험 단계 (후보 기준 {", ".join(f"{n} ≥ {c}" for c, n in LEVELS[1:])})', '',
              '| 단계 | 건수 | 비율 | 실제 그래도 구매 |', '|---|---|---|---|']
    lv = np.array([level_of(v) for v in p])
    for _, n in LEVELS:
        m = lv == n
        lines.append(f'| {n} | {int(m.sum()):,} | {m.mean():.0%} | {y[m].mean():.0%} |')

    model = RiskModel.load(args.model)
    counts, firsts = [], {}
    for r in rows:
        _, reasons, _ = model.predict(r)
        counts.append(len(reasons))
        if reasons:
            firsts[reasons[0][0]] = firsts.get(reasons[0][0], 0) + 1
    counts = np.array(counts)
    lines += ['', f'## 이유 (배포 모델, 기여 ≥ {model.reason_min})', '',
              f'- 이유 개수: 0개 {np.mean(counts == 0):.0%}, 1개 {np.mean(counts == 1):.0%}, 2개 {np.mean(counts == 2):.0%}, '
              f'3개 이상 {np.mean(counts >= 3):.0%}',
              '- 첫 번째 이유: ' + ', '.join(f'{g} {c:,}' for g, c in sorted(firsts.items(), key=lambda t: -t[1]))]
    for name in ('높음', '낮음'):
        i = int(np.where(lv == name)[0][0])
        prob, reasons, _ = model.predict(rows[i])
        lines.append(f'- 예시 ({name}, {prob:.2f}): ' + ', '.join(f'{g} +{c:.2f}' for g, c in reasons)
                     + f"  ← {', '.join(f'{k}={v:g}' for k, v in rows[i].items() if v is not None)}")

    lines += ['', '**읽을 때 주의**: 가상 데이터는 우리가 정한 효과(generate.EFFECTS)로 만들었다. 점수는 "파이프라인이 동작하고 '
              '그런 패턴이 있으면 잡는다"까지만 말한다.']
    text = '\n'.join(lines)
    print(text)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write(text + '\n')


if __name__ == '__main__':
    main()
