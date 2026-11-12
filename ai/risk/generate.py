"""C-2 가상 데이터: 결제 화면 팝업 1건 = 1행

가정한 효과(EFFECTS)로 '그래도 구매' 확률을 정하고 그 확률로 결정을 뽑는다.
과거 선택 비율, 쿨다운 실패 비율, 최근 결제 빈도, 금액 비율은 서버와 같은 규칙으로 '그 시점 이전' 행에서 계산한다.
모델은 이 가정을 다시 배우므로, 가상 데이터 성능은 실제 성능의 증거가 아니다 (README '한계').

실행 (ai 폴더에서): .venv\\Scripts\\python.exe -m risk.generate [--n 6000] [--seed 42]
    → data/risk/synthetic.csv (Git 제외)
"""
import argparse
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import schema as S

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import features as F41  # noqa: E402  (4-1의 월급일 계산을 그대로 쓴다)

DATA_DIR = os.path.join(os.path.dirname(HERE), 'data', 'risk')
DEFAULT_OUT = os.path.join(DATA_DIR, 'synthetic.csv')

N_USERS = 300
DAYS = 180
START = datetime(2026, 4, 1)
TARGET_RATE = 0.35       # '그래도 구매' 비율 목표 (결제 직전까지 온 경우라 4-1의 30%보다 조금 높게)
FLIP_RATE = 0.03         # 기록 오류 흉내
CLOSE_RATE = 0.08        # X로 닫아 라벨이 없는 비율
AMOUNT_UNKNOWN = 0.10    # 결제 금액을 끝내 못 읽은 비율
NO_PRODUCT_SCREEN = 0.20 # 상품 화면 없이 결제 화면 (장바구니에서 바로 등). 할인율/압박 문구/머문 시간 모름
DISCOUNT_UNREAD = 0.25   # 상품 화면은 봤지만 할인율을 못 읽은 비율
HAS_DISCOUNT = 0.65      # 할인 중인 상품 비율
PRESSURE_PROB = 0.25

HOUR_WEIGHTS = np.array([
    3, 2, 1.5, 1, .5, .3, .3, .5, 1, 1.5, 2, 3,     # 0~11시
    4, 3, 2.5, 2.5, 2.5, 3, 3.5, 4, 4.5, 5, 5, 4,   # 12~23시
])

# '그래도 구매' 로그오즈에 더하는 가정 효과 (README 특성별 근거와 같은 방향)
EFFECTS = {
    'night': 1.0,
    'late_evening': 0.4,
    'weekend': 0.25,
    'payday': 0.3,
    'log_ratio': 0.8,         # log(평소 대비 금액 비율)
    'discount': 1.5,          # 할인율(0~1). 50% 할인이면 +0.75
    'pressure': 0.6,
    'log_views': 0.3,         # log(1 + 24시간 상품 화면 수)
    'log_same_item': 0.4,     # log(1 + 같은 상품 반복)
    'log_browse': -0.3,       # log(머문 분): 오래 따져 볼수록 덜 충동적
    'log_checkouts': 0.3,     # log(1 + 7일 결제 화면 수)
    'trait_sd': 0.8,          # 회원별 충동 성향 (숨은 변수. 과거 선택 비율을 통해서만 드러난다)
    'noise_sd': 0.5,
}
# 라벨 → 결정 (가정): 그래도 구매 쪽은 대부분 바로 구매, 참은 쪽은 안 살래요와 담아두기가 비슷
BUY_DECISION = {'buy': 0.8, 'hold_failed': 0.2}
KEEP_DECISION = {'giveup': 0.55, 'hold_ok': 0.45}


def make_users(rng):
    return pd.DataFrame({
        'user': ['u%03d' % (i + 1) for i in range(N_USERS)],
        'base': rng.lognormal(math.log(40000), 0.6, N_USERS),   # 평소 결제 금액 수준
        'trait': rng.normal(0, EFFECTS['trait_sd'], N_USERS),
        'browse_rate': rng.gamma(2, 2, N_USERS),                # 하루 평균 상품 화면 수
        'activity': rng.gamma(2, 1, N_USERS),                   # 결제 화면 횟수의 회원별 차이
    })


def smooth(k, n, prior, weight):
    return (k + prior * weight) / (n + weight)


def base_logit(r):
    """원시 값 한 행의 가정 로그오즈 (회원 성향과 노이즈 제외)"""
    e = EFFECTS
    z = 0.0
    z += e['night'] * (r['hour'] in (23, 0, 1, 2, 3))
    z += e['late_evening'] * (r['hour'] in (21, 22))
    z += e['weekend'] * (r['weekday'] >= 5)
    z += e['payday'] * (r['days_since_payday'] <= 5)
    if r['amount_ratio'] is not None:
        z += e['log_ratio'] * math.log(r['amount_ratio'])
    if r['discount_rate'] is not None:
        z += e['discount'] * r['discount_rate'] / 100
    z += e['pressure'] * r['pressure']
    z += e['log_views'] * math.log1p(r['product_views_24h'])
    z += e['log_same_item'] * math.log1p(r['same_item_views_24h'])
    if r['browse_sec'] is not None:
        z += e['log_browse'] * math.log(r['browse_sec'] / 60)
    z += e['log_checkouts'] * math.log1p(r['checkouts_7d'])
    return z


def make_user_rows(rng, u, n, intercept):
    """회원 한 명의 결제 화면 n건을 시간순으로 만든다. 결정도 차례로 정해 과거 기록 특성에 반영한다"""
    P = S.RAW_PARAMS
    # 첫 결제 화면 전에도 평균이 있도록 90일 앞의 결제 화면 금액
    pre_n = rng.poisson(n * P['ratio_window_days'] / DAYS)
    past_amounts = [(float(d), float(a)) for d, a in
                    zip(rng.uniform(-P['ratio_window_days'], 0, pre_n), np.round(u.base * rng.lognormal(0, 0.6, pre_n), -1))]
    past_times = [d for d, _ in past_amounts]
    decisions = []            # (시각, 결정)
    cooldowns = []            # (끝난 시각, 실패 여부)
    rows = []
    for d in np.sort(rng.uniform(0, DAYS, n)):
        hour = int(rng.choice(24, p=HOUR_WEIGHTS / HOUR_WEIGHTS.sum()))
        dt = START + timedelta(days=int(d), hours=hour, minutes=int(rng.integers(60)))
        t = (dt - START).total_seconds() / 86400

        amount = int(max(1000, round(u.base * rng.lognormal(0.1, 0.7), -1)))
        window = [a for s, a in past_amounts if t - P['ratio_window_days'] <= s < t]
        ratio = F41.amount_ratio(amount, window)
        amount_known = rng.random() >= AMOUNT_UNKNOWN

        seen_product = rng.random() >= NO_PRODUCT_SCREEN
        views = int(rng.poisson(u.browse_rate)) + (1 if seen_product else 0)
        if seen_product:
            same = int(min(views, 1 + rng.poisson(0.7)))
            browse = float(np.clip(rng.lognormal(math.log(240), 1.1), 5, 7200))
            rate = int(np.clip(round(rng.beta(2, 4) * 100), 5, 90)) if rng.random() < HAS_DISCOUNT else 0
            discount = None if rng.random() < DISCOUNT_UNREAD else rate
            pressure = int(rng.random() < PRESSURE_PROB)
        else:
            same, browse, discount, pressure = 0, None, None, 0

        hist = [dc for s, dc in decisions if t - P['history_window_days'] <= s < t]
        buys = sum(1 for dc in hist if S.LABEL_OF[dc] == 1)
        done = [f for s, f in cooldowns if t - P['history_window_days'] <= s < t]
        row = {
            'user': u.user,
            'hour': dt.hour,
            'weekday': dt.weekday(),
            'days_since_payday': F41.days_since_payday(dt, P['payday']),
            'amount': amount if amount_known else None,
            'discount_rate': discount,
            'pressure': pressure,
            'product_views_24h': views,
            'same_item_views_24h': same,
            'browse_sec': None if browse is None else int(browse),
            'amount_ratio': ratio if amount_known else None,
            'checkouts_7d': sum(1 for s in past_times if t - P['checkouts_window_days'] <= s < t),
            'buy_rate': round(smooth(buys, len(hist), P['history_prior'], P['history_weight']), 4),
            'cooldown_fail_rate': round(smooth(sum(done), len(done), P['cooldown_prior'], P['cooldown_weight']), 4),
        }
        # 행동(라벨)은 실제 값으로 정한다. 금액을 못 읽었어도 금액의 영향은 있었다
        truth = dict(row, amount_ratio=ratio, browse_sec=browse,
                     discount_rate=discount if discount is not None else (rate if seen_product else None))
        z = base_logit(truth) + u.trait + rng.normal(0, EFFECTS['noise_sd']) + intercept
        label = int(rng.random() < 1 / (1 + math.exp(-z)))
        if rng.random() < FLIP_RATE:
            label = 1 - label
        probs = BUY_DECISION if label else KEEP_DECISION
        decision = str(rng.choice(list(probs), p=list(probs.values())))
        if rng.random() < CLOSE_RATE:
            decision = 'close'
        row['decision'] = decision
        row['label'] = S.LABEL_OF.get(decision)
        rows.append(row)

        # 다음 행이 볼 기록 (서버에 남는 것과 같게)
        past_times.append(t)
        if amount_known:
            past_amounts.append((t, float(amount)))
        if decision != 'close':
            decisions.append((t, decision))
        if decision in ('hold_failed', 'hold_ok'):
            cooldowns.append((t + 1, 1 if decision == 'hold_failed' else 0))   # 결과는 24시간 뒤에 정해진다
    return rows


def generate(n, seed, intercept=None):
    rng = np.random.default_rng(seed)
    users = make_users(rng)
    counts = rng.multinomial(n, users.activity / users.activity.sum())
    if intercept is None:
        intercept = fit_intercept(n, seed)
    rows = []
    for u, c in zip(users.itertuples(), counts):
        rows += make_user_rows(rng, u, c, intercept)
    df = pd.DataFrame(rows)[S.COLUMNS]
    for col in ('amount', 'discount_rate', 'browse_sec'):
        df[col] = df[col].astype('Int64')
    df['label'] = df['label'].astype('Int64')
    return df


def fit_intercept(n, seed):
    """'그래도 구매' 비율이 TARGET_RATE가 되는 절편. 과거 기록 특성이 결정에 따라 달라지므로 생성을 반복해 맞춘다"""
    lo, hi = -6.0, 2.0
    for _ in range(14):
        mid = (lo + hi) / 2
        rate = generate(n, seed, intercept=mid)['label'].mean()
        if rate < TARGET_RATE:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def summary(df):
    lab = df[df.label.notna()].copy()
    lab['label'] = lab.label.astype(int)
    print(f'{len(df):,}건 (라벨 있음 {len(lab):,}건, X 닫기 제외 {int((df.decision == "close").sum())}건), '
          f'그래도 구매 {lab.label.mean():.1%}, 회원 {df.user.nunique()}명')
    print('결정:', df.decision.value_counts().to_dict())
    conds = [
        ('낮 4~18시', lab.hour.between(4, 18)), ('심야 23~4시', lab.hour.isin([23, 0, 1, 2, 3])),
        ('평소 대비 0.7배 미만', lab.amount_ratio < 0.7), ('평소 대비 2배 이상', lab.amount_ratio >= 2),
        ('할인 없음', lab.discount_rate == 0), ('할인 40% 이상', lab.discount_rate >= 40), ('할인율 모름', lab.discount_rate.isna()),
        ('압박 문구 없음', lab.pressure == 0), ('압박 문구 있음', lab.pressure == 1),
        ('같은 상품 1번', lab.same_item_views_24h <= 1), ('같은 상품 3번 이상', lab.same_item_views_24h >= 3),
        ('머문 시간 1분 미만', lab.browse_sec < 60), ('머문 시간 20분 이상', lab.browse_sec >= 1200),
        ('과거 구매 비율 0.3 미만', lab.buy_rate < 0.3), ('과거 구매 비율 0.5 이상', lab.buy_rate >= 0.5),
    ]
    print('| 조건 | 건수 | 그래도 구매 |')
    print('|---|---|---|')
    for name, m in conds:
        print(f'| {name} | {int(m.sum()):,} | {lab.label[m].mean():.0%} |')


def load(path=DEFAULT_OUT):
    return pd.read_csv(path)


def main():
    ap = argparse.ArgumentParser(description='C-2 위험도 가상 데이터 생성')
    ap.add_argument('--n', type=int, default=6000)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    df = generate(args.n, args.seed)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_csv(args.out, index=False, encoding='utf-8')
    print('저장:', args.out)
    summary(df)


if __name__ == '__main__':
    main()
