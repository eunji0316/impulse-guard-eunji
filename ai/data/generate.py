"""
가상 데이터 생성: 쿨다운 1건(구매를 고민한 순간) = 1행

현실적인 패턴을 가정해 충동구매 확률을 정하고, 그 확률로 정답을 뽑는다.
가정한 효과(EFFECTS)는 README.md의 특성별 근거와 같은 방향이다. 모델은 이 가정을 다시 배우므로,
가상 데이터 성능은 실제 성능의 증거가 아니다 (README "한계" 참고).

사용: python data/generate.py [--n 5000] [--seed 42] [--out data/synthetic.csv]
"""
import argparse
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import features as F  # noqa: E402
from describe import summary  # noqa: E402

N_USERS     = 300
DAYS        = 180
START       = datetime(2026, 4, 1)
TARGET_RATE = 0.30    # 전체 충동구매 비율 목표
FLIP_RATE   = 0.03    # 기록 오류 흉내: 정답을 뒤집는 비율
MISSING_STAY = 0.15   # 체류 시간을 모르는 비율 (확장 프로그램 밖에서 만든 쿨다운)

# 고민이 시작되는 시각의 분포: 점심, 저녁, 심야에 봉우리
HOUR_WEIGHTS = np.array([
    3, 2, 1.5, 1, .5, .3, .3, .5, 1, 1.5, 2, 3,     # 0~11시
    4, 3, 2.5, 2.5, 2.5, 3, 3.5, 4, 4.5, 5, 5, 4,   # 12~23시
])

CATEGORY_PROB = {'shopping': .30, 'fashion': .25, 'game': .08, 'delivery': .12, 'food': .14, 'transport': .05, 'etc': .06}
PRESSURE_PROB = {'shopping': .45, 'fashion': .45, 'game': .35, 'delivery': .30, 'food': .25, 'transport': .05, 'etc': .20}

# 충동구매 로그오즈에 더하는 가정 효과
EFFECTS = {
    'night':        1.2,    # 심야 23~4시
    'late_evening': 0.5,    # 21~23시
    'weekend':      0.3,
    'log_ratio':    0.9,    # log(회원 평균 대비 금액 비율)
    'pressure':     0.8,    # 할인/압박 문구
    'log_stay':    -0.4,    # log(체류 초 / 60): 오래 볼수록 덜 충동적
    'log_visits':   0.25,   # log(1 + 24시간 방문 수)
    'payday':       0.5,    # 월급일 후 5일 이내
    'category': {'shopping': .3, 'fashion': .4, 'game': .4, 'delivery': .1, 'food': -.4, 'transport': -.8, 'etc': 0},
    'trait_sd':     0.7,    # 회원별 충동 성향 (CSV에 넣지 않는 숨은 변수)
    'noise_sd':     0.5,
}


def make_users(rng):
    return pd.DataFrame({
        'user':       ['u%03d' % (i + 1) for i in range(N_USERS)],
        'base':       rng.lognormal(math.log(30000), 0.6, N_USERS),   # 평소 결제 수준, 중앙값 약 3만 원
        'trait':      rng.normal(0, EFFECTS['trait_sd'], N_USERS),
        'visit_rate': rng.gamma(2, 1.5, N_USERS),                     # 하루 평균 쇼핑 사이트 방문 수
        'activity':   rng.gamma(2, 1, N_USERS),                       # 고민 횟수의 회원별 차이
        'pay_rate':   rng.uniform(0.2, 0.8, N_USERS),                 # 하루 평균 일반 결제 수
    })


# 회원의 평소 결제 내역 (g5_ipp_transaction 흉내). 첫 고민 전에도 평균이 있도록 90일 앞부터 만든다
def make_payments(rng, u):
    n = rng.poisson(u.pay_rate * (DAYS + F.RATIO_WINDOW_DAYS))
    days = np.sort(rng.uniform(-F.RATIO_WINDOW_DAYS, DAYS, n))
    amounts = np.round(u.base * rng.lognormal(0, 0.5, n), -1)
    return days, amounts


def make_events(rng, u, n):
    pay_days, pay_amounts = make_payments(rng, u)
    day  = np.sort(rng.uniform(0, DAYS, n))
    rows = []
    for d in day:
        hour = int(rng.choice(24, p=HOUR_WEIGHTS / HOUR_WEIGHTS.sum()))
        dt   = START + timedelta(days=int(d), hours=hour, minutes=int(rng.integers(60)))
        t    = (dt - START).total_seconds() / 86400
        past = pay_amounts[(pay_days < t) & (pay_days >= t - F.RATIO_WINDOW_DAYS)]

        category = rng.choice(list(CATEGORY_PROB), p=list(CATEGORY_PROB.values()))
        amount   = int(max(1000, round(u.base * rng.lognormal(0.2, 0.7), -1)))   # 고민하는 물건은 평소보다 약간 비싸다
        rows.append({
            'user':              u.user,
            'hour':              dt.hour,
            'weekday':           dt.weekday(),
            'amount':            amount,
            'amount_ratio':      F.amount_ratio(amount, past.tolist()),
            'category':          category,
            'has_pressure':      int(rng.random() < PRESSURE_PROB[category]),
            'stay_sec':          int(np.clip(rng.lognormal(math.log(90), 0.9), 3, 3600)),
            'visits_24h':        int(rng.poisson(u.visit_rate)),
            'days_since_payday': F.days_since_payday(dt),
            'trait':             u.trait,
        })
    return rows


def logit(df, rng):
    e = EFFECTS
    night = (df.hour >= 23) | (df.hour < 4)
    return (e['night'] * night
            + e['late_evening'] * df.hour.between(21, 22)
            + e['weekend'] * (df.weekday >= 5)
            + e['log_ratio'] * np.log(df.amount_ratio)
            + e['pressure'] * df.has_pressure
            + df.category.map(e['category'])
            + e['log_stay'] * np.log(df.stay_sec / 60)
            + e['log_visits'] * np.log1p(df.visits_24h)
            + e['payday'] * (df.days_since_payday <= 5)
            + df.trait
            + rng.normal(0, e['noise_sd'], len(df)))


# 평균 확률이 TARGET_RATE가 되는 절편 (이분 탐색)
def fit_intercept(z):
    lo, hi = -10.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if (1 / (1 + np.exp(-(z + mid)))).mean() < TARGET_RATE:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def generate(n, seed):
    rng   = np.random.default_rng(seed)
    users = make_users(rng)
    counts = rng.multinomial(n, users.activity / users.activity.sum())

    rows = []
    for u, c in zip(users.itertuples(), counts):
        rows += make_events(rng, u, c)
    df = pd.DataFrame(rows)

    z = logit(df, rng)
    p = 1 / (1 + np.exp(-(z + fit_intercept(z))))
    label = (rng.random(len(df)) < p).astype(int)
    flip  = rng.random(len(df)) < FLIP_RATE
    df['label'] = np.where(flip, 1 - label, label)

    # 체류 시간은 정답을 정한 뒤에 가린다 (모르는 값이 생겨도 실제 행동은 있었으므로)
    df['stay_sec'] = df.stay_sec.astype('Int64').mask(rng.random(len(df)) < MISSING_STAY)
    return df[F.COLUMNS]


def main():
    ap = argparse.ArgumentParser(description='충동구매 가상 데이터 생성')
    ap.add_argument('--n', type=int, default=5000)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'synthetic.csv'))
    args = ap.parse_args()

    df = generate(args.n, args.seed)
    df.to_csv(args.out, index=False, encoding='utf-8')
    print('저장:', args.out)
    summary(df)


if __name__ == '__main__':
    main()
