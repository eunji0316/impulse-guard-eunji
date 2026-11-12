"""가상 화면 데이터 만들기 (C-1 쇼핑 화면 분류)

실행 (ai 폴더에서):
    .venv\\Scripts\\python.exe -m screen.generate              # → data/screen/synthetic.jsonl
    .venv\\Scripts\\python.exe -m screen.generate --seed 7 --malls 40

한 줄 = 화면 한 장: {"text": OCR 글자, "label": none/product/checkout, "group": 쇼핑몰/사이트, "kind": 화면 종류, "noise": 노이즈 강도}
group은 평가 때 '처음 보는 쇼핑몰' 기준으로 나누는 데 쓴다 (같은 몰/사이트가 학습과 시험에 함께 들어가지 않게).
글자에 들어가는 이름, 전화번호, 주소는 모두 무작위로 만든 가짜다.
"""
import argparse
import json
import os
import random

from . import noise, pages as P
from . import vocab as V

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), 'data', 'screen', 'synthetic.jsonl')

NOISE_MIX = [('none', 0.1), ('normal', 0.35), ('strong', 0.3), ('heavy', 0.25)]

# 쇼핑몰 하나에서 만드는 화면 수 (분류별)
PER_MALL = {'product': 45, 'checkout': 35, 'none': 14}
PRODUCT_KINDS = [(P.product_detail, 0.6), (P.product_list, 0.25), (P.cart, 0.15)]
DELIVERY_PRODUCT_KINDS = [(P.delivery_menu, 0.75), (P.cart, 0.25)]
MALL_NONE_KINDS = [(P.order_done, 0.4), (P.order_history, 0.3), (P.tracking, 0.15), (P.customer_center, 0.15)]
NON_MALL_COUNT = 2000
SITES_PER_TYPE = 6


def choose(rng, weighted):
    items, weights = zip(*weighted)
    return rng.choices(items, weights=weights, k=1)[0]


def mall_screen(rng, mall, label):
    if label == 'product':
        fn = choose(rng, DELIVERY_PRODUCT_KINDS if mall['cat'] == 'delivery' else PRODUCT_KINDS)
    elif label == 'checkout':
        fn = P.checkout
    else:
        fn = choose(rng, MALL_NONE_KINDS)
    pg = fn(rng, mall)
    minimal = pg['kind'] in ('checkout', 'order_done') and rng.random() < 0.6
    sections = [P.header(rng, mall, minimal=minimal)] + pg['sections'] + [P.footer(rng, mall)]
    chrome = P.browser_bar(rng, mall, pg['path'], pg['title'] if rng.random() < 0.6 else '')
    return sections, chrome, pg['kind']


def make_sites(rng):
    """쇼핑몰이 아닌 화면의 사이트 이름 (종류마다 SITES_PER_TYPE개)"""
    sites = {}
    for kind in P.NON_MALL:
        names = set()
        while len(names) < SITES_PER_TYPE:
            names.add(rng.choice(V.NEWS_SITES) if kind == 'news' and rng.random() < 0.7 else P.fake_mall_name(rng))
        sites[kind] = sorted(names)
    return sites


def generate(seed=42, n_malls=40, noise_mix=None, non_mall_count=NON_MALL_COUNT):
    """noise_mix: [(노이즈 강도, 비율)] (기본 NOISE_MIX)"""
    rng = random.Random(seed)
    noise_mix = noise_mix or NOISE_MIX
    rows = []
    cats = [V.CATEGORIES[i % len(V.CATEGORIES)] for i in range(n_malls)]   # 분야를 고르게
    malls = [P.make_mall(rng, i, cat) for i, cat in enumerate(cats)]
    for mall in malls:
        for label, count in PER_MALL.items():
            for _ in range(count):
                level = choose(rng, noise_mix)
                sections, chrome, kind = mall_screen(rng, mall, label)
                rows.append({'text': noise.apply(sections, rng, level, chrome), 'label': label, 'group': mall['id'],
                             'kind': kind, 'noise': level, 'cat': mall['cat']})
    sites = make_sites(rng)
    kinds = [(k, w) for k, (_, w) in P.NON_MALL.items()]
    for _ in range(non_mall_count):
        kind = choose(rng, kinds)
        site = rng.choice(sites[kind])
        sections, url = P.NON_MALL[kind][0](rng, site)
        chrome = [P.fill(rng, url)] if url and rng.random() < 0.7 else []
        level = choose(rng, noise_mix)
        rows.append({'text': noise.apply(sections, rng, level, chrome), 'label': 'none', 'group': f'{kind}:{site}',
                     'kind': kind, 'noise': level, 'cat': ''})
    rng.shuffle(rows)
    return rows


def save(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def load(path=DEFAULT_OUT):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser(description='C-1 가상 화면 데이터 만들기')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--malls', type=int, default=40)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    rows = generate(args.seed, args.malls)
    save(rows, args.out)
    counts = {}
    for r in rows:
        counts[r['label']] = counts.get(r['label'], 0) + 1
    print(f'{len(rows)}건 → {args.out}')
    print('분류별: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))


if __name__ == '__main__':
    main()
