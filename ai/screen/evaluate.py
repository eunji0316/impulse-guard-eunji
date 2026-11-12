"""쇼핑 화면 분류 평가 (C-1)

실행 (ai 폴더에서, generate → train 다음에):
    .venv\\Scripts\\python.exe -m screen.evaluate            # 전체 → 화면 출력 + data/screen/report.md
    .venv\\Scripts\\python.exe -m screen.evaluate --quick    # 실측과 속도만

1. 가상 데이터, 처음 보는 쇼핑몰 기준: 쇼핑몰/사이트 단위 5겹 교차검증 (GroupKFold)
   키워드 방식, 문자 n-gram 로지스틱 회귀(메인), 단어 n-gram 로지스틱 회귀, 문자 n-gram 나이브 베이즈,
   메인 + 저신뢰 시 키워드 (실제 데스크톱 동작) 비교
2. 새 시드 가상 데이터: 학습에 없던 몰 구성으로 노이즈 강도별 성능
3. 실측: desktop/tests의 OCR 캐시 (EasyOCR, Windows OCR). 이미지별 정답 여부
4. 판정 시간: 데스크톱 추론 코드 (numpy)

지표
- macro F1: 세 분류 F1의 평균
- 결제 재현율: 실제 결제 화면 중 결제 화면으로 맞힌 비율 (놓치면 개입하지 못한다)
- 쇼핑 아님 오탐률: 실제 쇼핑 아님 중 상품/결제 화면으로 판정한 비율 (높으면 일반 화면에 알림이 뜬다)
"""
import argparse
import os
import statistics
import sys
import time

import numpy as np
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

from . import generate, train

sys.path.insert(0, os.path.join(train.DESKTOP, 'tests'))
from impulse_guard import config as dconfig  # noqa: E402
from impulse_guard.detector import classifier, shopping, stage  # noqa: E402
import make_screen_cache  # noqa: E402

LABELS = train.LABELS
REPORT = os.path.join(os.path.dirname(generate.DEFAULT_OUT), 'report.md')
THRESHOLDS = [0.4, 0.5, 0.6, 0.7, 0.8]


def keyword(text):
    return stage.classify(text, shopping.judge(text).is_mall).stage


def hybrid(pred, prob, text, thr):
    return pred if prob >= thr else keyword(text)


def metrics(y, p):
    y, p = np.asarray(y), np.asarray(p)
    co = y == 'checkout'
    no = y == 'none'
    return {
        'macro F1': f1_score(y, p, labels=LABELS, average='macro', zero_division=0),
        '결제 재현율': float((p[co] == 'checkout').mean()) if co.any() else float('nan'),
        '쇼핑 아님 오탐률': float((p[no] != 'none').mean()) if no.any() else float('nan'),
        '정확도': float((y == p).mean()),
    }


def table(rows, cols):
    out = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    for r in rows:
        out.append('| ' + ' | '.join(f'{v:.3f}' if isinstance(v, float) else str(v) for v in r) + ' |')
    return '\n'.join(out)


def cross_validate(rows, out):
    texts = [r['text'] for r in rows]
    y = np.array([r['label'] for r in rows])
    groups = [r['group'] for r in rows]
    preds = {k: np.empty(len(rows), dtype=object) for k in ('키워드', 'char_lr', 'word_lr', 'char_nb')}
    probs = np.zeros(len(rows))
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=5).split(texts, y, groups)):
        tr_rows = [rows[i] for i in tr]
        te_texts = [texts[i] for i in te]
        for kind in ('char_lr', 'word_lr', 'char_nb'):
            m = train.fit(tr_rows, kind)
            p = m.predict_proba(te_texts)
            preds[kind][te] = m.classes_[p.argmax(1)]
            if kind == 'char_lr':
                probs[te] = p.max(1)
        print(f'  교차검증 {fold + 1}/5', flush=True)
    preds['키워드'] = np.array([keyword(t) for t in texts], dtype=object)
    lines = []
    for name, p in preds.items():
        m = metrics(y, p)
        lines.append([name, m['macro F1'], m['결제 재현율'], m['쇼핑 아님 오탐률'], m['정확도'], '-'])
    for thr in THRESHOLDS:
        p = np.array([hybrid(a, b, t, thr) for a, b, t in zip(preds['char_lr'], probs, texts)], dtype=object)
        m = metrics(y, p)
        lines.append([f'char_lr + 키워드 (확률 < {thr})', m['macro F1'], m['결제 재현율'], m['쇼핑 아님 오탐률'], m['정확도'],
                      f'{(probs < thr).mean():.1%}'])
    out.append('## 1. 가상 데이터, 처음 보는 쇼핑몰 기준 (쇼핑몰/사이트 단위 5겹 교차검증)\n')
    out.append(f'{len(rows)}건. 시험 데이터의 쇼핑몰/사이트는 그 겹의 학습 데이터에 없다.\n')
    out.append(table(lines, ['방법', 'macro F1', '결제 재현율', '쇼핑 아님 오탐률', '정확도', '키워드로 넘긴 비율']))
    # 화면 종류별 오답률 (메인 모델)
    kinds = sorted({r['kind'] for r in rows})
    kl = []
    for k in kinds:
        idx = [i for i, r in enumerate(rows) if r['kind'] == k]
        wrong = [preds['char_lr'][i] for i in idx if preds['char_lr'][i] != y[i]]
        kwrong = sum(preds['키워드'][i] != y[i] for i in idx)
        kl.append([k, rows[idx[0]]['label'], len(idx), f'{len(wrong) / len(idx):.1%}', f'{kwrong / len(idx):.1%}',
                   ', '.join(f'{w} {wrong.count(w)}' for w in sorted(set(wrong)))])
    out.append('\n화면 종류별 오답률 (교차검증)\n')
    out.append(table(kl, ['화면 종류', '정답', '건수', 'char_lr 오답', '키워드 오답', 'char_lr 오답 내용']))
    return preds, probs


def fresh_test(model_json, out):
    """새 시드(몰 구성이 다름)로 노이즈 강도별"""
    sm = classifier.ScreenModel.load(model_json)
    lines = []
    for level in ('none', 'normal', 'strong', 'heavy'):
        if level not in generate.noise.LEVELS:
            continue
        rows = generate.generate(seed=2026, n_malls=16, noise_mix=[(level, 1.0)], non_mall_count=800)
        y = [r['label'] for r in rows]
        res = [sm.predict(r['text']) for r in rows]
        pm = [r[0] if r else 'none' for r in res]
        ph = [hybrid(r[0], r[1], row['text'], dconfig.SCREEN_MODEL_MIN_PROB) if r else keyword(row['text'])
              for r, row in zip(res, rows)]
        pk = [keyword(r['text']) for r in rows]
        for name, p in (('키워드', pk), ('모델', pm), ('모델 + 키워드', ph)):
            m = metrics(y, p)
            lines.append([level, name, m['macro F1'], m['결제 재현율'], m['쇼핑 아님 오탐률']])
    out.append('\n## 2. 새 시드 가상 데이터 (몰 16곳 + 일반 화면 800장, 노이즈 강도별)\n')
    out.append(table(lines, ['노이즈', '방법', 'macro F1', '결제 재현율', '쇼핑 아님 오탐률']))


def real_sets():
    """{엔진: [(이름, 정답, 글자)]}. EasyOCR은 tests/ocr_cache(7장)와 screen_cache/easy를 합친다"""
    import json
    easy = {}
    cache_dir = os.path.join(train.DESKTOP, 'tests', 'ocr_cache')
    for fn in sorted(os.listdir(cache_dir)):
        if fn.endswith('.json'):
            with open(os.path.join(cache_dir, fn), encoding='utf-8') as f:
                data = json.load(f)
            name = fn[:-5]
            easy[name] = (name, make_screen_cache.screen_label(name), ' '.join(b['text'] for b in data['boxes']))
    for item in make_screen_cache.load_all('easy'):
        easy[item[0]] = item
    return {'EasyOCR': sorted(easy.values()), 'Windows OCR': make_screen_cache.load_all('win')}


def real_test(model_json, out):
    sm = classifier.ScreenModel.load(model_json)
    thr = dconfig.SCREEN_MODEL_MIN_PROB
    out.append(f'\n## 3. 실측 (desktop/tests/images, 저신뢰 기준 {thr})\n')
    summary = []
    for engine, items in real_sets().items():
        if not items:
            continue
        lines, y, pk, pm, ph = [], [], [], [], []
        for name, label, text in items:
            r = sm.predict(text)
            kw = keyword(text)
            hy = hybrid(r[0], r[1], text, thr) if r else kw
            y.append(label), pk.append(kw), pm.append(r[0] if r else 'none'), ph.append(hy)
            mark = lambda v: v if v == label else f'**{v}** ✗'     # noqa: E731
            lines.append([name, label, mark(kw), f'{mark(r[0])} {r[1]:.2f}' if r else '-', mark(hy)])
        out.append(f'\n### {engine} ({len(items)}장)\n')
        out.append(table(lines, ['이미지', '정답', '키워드', '모델 (확률)', '모델 + 키워드 (실제 동작)']))
        for name, p in (('키워드', pk), ('모델', pm), ('모델 + 키워드', ph)):
            m = metrics(y, p)
            summary.append([engine, name, f'{sum(a == b for a, b in zip(y, p))}/{len(y)}', m['결제 재현율'],
                            m['쇼핑 아님 오탐률']])
    out.append('\n### 요약\n')
    out.append(table(summary, ['엔진', '방법', '정답', '결제 재현율', '쇼핑 아님 오탐률']))


def speed_test(model_json, out):
    classifier.reset()
    t0 = time.perf_counter()
    sm = classifier.ScreenModel.load(model_json)
    load_sec = time.perf_counter() - t0
    texts = [t for items in real_sets().values() for _, _, t in items] or ['테스트']
    times = []
    for i in range(1000):
        t = texts[i % len(texts)]
        s = time.perf_counter()
        sm.predict(t)
        times.append(time.perf_counter() - s)
    times.sort()
    out.append('\n## 4. 판정 시간 (데스크톱 numpy 추론, 실측 글자 1,000회)\n')
    out.append(f'- 모델 파일 읽기 (프로그램 시작 때 한 번): {load_sec * 1000:.0f}ms, 파일 {os.path.getsize(model_json) / 1024:.0f}KB')
    out.append(f'- 판정 한 번: 중앙값 {statistics.median(times) * 1000:.2f}ms, p99 {times[int(len(times) * 0.99)] * 1000:.2f}ms, '
               f'최대 {times[-1] * 1000:.2f}ms (목표 100ms 미만)')
    out.append(f'- 글자 수: 최대 {max(len(t) for t in texts)}자')


def main():
    ap = argparse.ArgumentParser(description='C-1 쇼핑 화면 분류 평가')
    ap.add_argument('--data', default=generate.DEFAULT_OUT)
    ap.add_argument('--model', default=train.MODEL_OUT)
    ap.add_argument('--quick', action='store_true', help='실측과 속도만')
    args = ap.parse_args()
    out = ['# C-1 쇼핑 화면 분류 평가 결과', '',
           f'생성: {time.strftime("%Y-%m-%d %H:%M")}, 모델: {os.path.relpath(args.model, train.ROOT)}', '']
    if not args.quick:
        rows = generate.load(args.data)
        print('교차검증...', flush=True)
        cross_validate(rows, out)
        print('새 시드...', flush=True)
        fresh_test(args.model, out)
    real_test(args.model, out)
    speed_test(args.model, out)
    text = '\n'.join(out) + '\n'
    print(text)
    if not args.quick:
        with open(REPORT, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'→ {REPORT}')


if __name__ == '__main__':
    main()
