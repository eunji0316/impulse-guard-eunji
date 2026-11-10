"""
데이터 요약: 조건별 충동구매 비율 표와 그래프

가상 데이터가 의도한 패턴을 갖는지, 실제 데이터가 어떤 모양인지 확인하는 데 쓴다.
사용: python data/describe.py data/synthetic.csv [--plot data/synthetic.png]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import features as F  # noqa: E402


# 특성마다 (제목, 행 → 구간 이름 함수, 구간 순서)
def _hour(h):
    if h >= 23 or h < 4: return '심야 23~4시'
    if h < 18:           return '낮 4~18시'
    if h < 21:           return '저녁 18~21시'
    return '늦은 저녁 21~23시'


def _ratio(r):
    if r < 0.7: return '0.7배 미만'
    if r < 1.5: return '0.7~1.5배'
    if r < 3:   return '1.5~3배'
    return '3배 이상'


def _stay(s):
    if pd.isna(s): return '모름'
    if s < 30:     return '30초 미만'
    if s < 120:    return '30초~2분'
    if s < 600:    return '2~10분'
    return '10분 이상'


def _visits(v):
    if v == 0: return '0회'
    if v <= 2: return '1~2회'
    if v <= 5: return '3~5회'
    return '6회 이상'


GROUPS = [
    ('시각',            'hour',              _hour,   ['낮 4~18시', '저녁 18~21시', '늦은 저녁 21~23시', '심야 23~4시']),
    ('요일',            'weekday',           lambda w: '주말' if w >= 5 else '평일', ['평일', '주말']),
    ('회원 평균 대비 금액', 'amount_ratio',   _ratio,  ['0.7배 미만', '0.7~1.5배', '1.5~3배', '3배 이상']),
    ('할인/압박 문구',    'has_pressure',      lambda p: '있음' if p else '없음', ['없음', '있음']),
    ('업종',            'category',          str,     F.CATEGORIES),
    ('체류 시간',        'stay_sec',          _stay,   ['30초 미만', '30초~2분', '2~10분', '10분 이상', '모름']),
    ('24시간 방문 수',    'visits_24h',        _visits, ['0회', '1~2회', '3~5회', '6회 이상']),
    ('월급일 이후',       'days_since_payday', lambda d: '5일 이내' if d <= 5 else '6일 이후', ['5일 이내', '6일 이후']),
]


def rates(df):
    """특성별 구간마다 건수와 충동 비율. [(제목, DataFrame(구간, 건수, 충동 비율))]"""
    out = []
    for title, col, fn, order in GROUPS:
        g = df.groupby(df[col].map(fn))['label'].agg(['count', 'mean'])
        g = g.reindex([o for o in order if o in g.index])
        out.append((title, g.rename(columns={'count': '건수', 'mean': '충동 비율'})))
    return out


def summary(df):
    print('행 수: %d, 회원 수: %d, 충동구매 비율: %.1f%%' % (len(df), df.user.nunique(), df.label.mean() * 100 if len(df) else 0))
    print('체류 시간 모름: %d건' % df.stay_sec.isna().sum())
    if not len(df):
        return
    rule = df.apply(F.is_rule_impulse, axis=1)
    print('지금 규칙으로 감지: %.1f%% (규칙과 정답 일치율 %.1f%%)' % (rule.mean() * 100, (rule == df.label).mean() * 100))
    for title, g in rates(df):
        print('\n[%s]' % title)
        print(g.to_string(formatters={'충동 비율': '{:.1%}'.format}))


def plot(df, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 설치된 한글 글꼴 하나만 고른다 (없는 글꼴을 목록에 넣으면 경고가 많이 나온다)
    installed = {f.name for f in font_manager.fontManager.ttflist}
    korean = [f for f in ('Malgun Gothic', 'AppleGothic', 'NanumGothic') if f in installed]
    if korean:
        plt.rcParams['font.family'] = korean[0]
    else:
        print('한글 글꼴을 찾지 못해 그래프 글자가 깨질 수 있습니다.')
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    base = df.label.mean()
    for ax, (title, g) in zip(axes.flat, rates(df)):
        ax.bar(range(len(g)), g['충동 비율'], color='#3b6cf6')
        ax.axhline(base, color='#888', linestyle='--', linewidth=1)
        ax.set_xticks(range(len(g)), [str(i) for i in g.index], rotation=20, fontsize=9)
        ax.set_ylim(0, 1)
        ax.set_title(title)
        for i, (r, c) in enumerate(zip(g['충동 비율'], g['건수'])):
            ax.text(i, r + 0.02, '%.0f%%\n(%d)' % (r * 100, c), ha='center', fontsize=8)
    fig.suptitle('조건별 충동구매 비율 (점선: 전체 평균 %.0f%%, 괄호: 건수)' % (base * 100))
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print('그래프 저장:', path)


def main():
    ap = argparse.ArgumentParser(description='충동구매 데이터 요약')
    ap.add_argument('csv')
    ap.add_argument('--plot', help='그래프를 저장할 png 경로')
    args = ap.parse_args()

    df = pd.read_csv(args.csv, dtype={'stay_sec': 'Int64'})
    missing = [c for c in F.COLUMNS if c not in df.columns]
    if missing:
        sys.exit('열이 없습니다: ' + ', '.join(missing))
    summary(df)
    if args.plot and len(df):
        plot(df, args.plot)


if __name__ == '__main__':
    main()
