"""쇼핑 화면 분류 모델 학습과 내보내기 (C-1)

실행 (ai 폴더에서, 먼저 screen.generate로 데이터를 만든다):
    .venv\\Scripts\\python.exe -m screen.train
    → desktop/impulse_guard/models/screen_classifier.json

모델: 문자 2~4-gram TF-IDF + 로지스틱 회귀. 전처리는 데스크톱 classifier.preprocess를 그대로 쓴다.
내보낸 JSON은 데스크톱이 numpy로만 계산한다 (scikit-learn, pickle 없이). 내보낸 뒤 sklearn과 확률이 같은지 확인한다.
"""
import argparse
import datetime
import json
import os
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline

from . import generate

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DESKTOP = os.path.join(ROOT, 'desktop')
sys.path.insert(0, DESKTOP)

from impulse_guard import config as desktop_config  # noqa: E402
from impulse_guard.detector import classifier  # noqa: E402

MODEL_OUT = os.path.join(DESKTOP, 'impulse_guard', desktop_config.SCREEN_MODEL_PATH)
LABELS = ['none', 'product', 'checkout']          # 데스크톱 stage.NONE / PRODUCT / CHECKOUT
OCR_FIXES = dict(desktop_config.CHECKOUT_OCR_FIXES)

# 메인 모델 설정
NGRAM = (2, 4)
MAX_FEATURES = 20000
MIN_DF = 3
C = 4.0


def prep(text):
    return classifier.preprocess(text, OCR_FIXES)


def word_prep(text):
    """단어 n-gram 비교용: 띄어쓰기는 남기고 나머지 전처리는 같게"""
    text = (text or '').lower()
    for wrong, right in OCR_FIXES.items():
        text = text.replace(wrong, right)
    return classifier.DIGIT_RE.sub('0', text)


def build(kind='char_lr'):
    """비교할 모델들. char_lr이 메인"""
    if kind == 'char_lr':
        vec = TfidfVectorizer(analyzer='char', ngram_range=NGRAM, preprocessor=prep, lowercase=False,
                              sublinear_tf=True, min_df=MIN_DF, max_features=MAX_FEATURES)
        clf = LogisticRegression(C=C, max_iter=3000, class_weight='balanced')
    elif kind == 'word_lr':
        vec = TfidfVectorizer(analyzer='word', ngram_range=(1, 2), preprocessor=word_prep, lowercase=False,
                              token_pattern=r'\S+', sublinear_tf=True, min_df=2, max_features=MAX_FEATURES)
        clf = LogisticRegression(C=C, max_iter=3000, class_weight='balanced')
    elif kind == 'char_nb':
        vec = TfidfVectorizer(analyzer='char', ngram_range=NGRAM, preprocessor=prep, lowercase=False,
                              sublinear_tf=True, min_df=MIN_DF, max_features=MAX_FEATURES)
        clf = ComplementNB(alpha=0.3)
    else:
        raise ValueError(kind)
    return Pipeline([('tfidf', vec), ('clf', clf)])


def fit(rows, kind='char_lr'):
    model = build(kind)
    model.fit([r['text'] for r in rows], [r['label'] for r in rows])
    return model


def export(model, path, n_rows):
    """sklearn 파이프라인 → 데스크톱 JSON (어휘 순서 = 특성 번호)"""
    vec, clf = model.named_steps['tfidf'], model.named_steps['clf']
    vocab = [None] * len(vec.vocabulary_)
    for gram, i in vec.vocabulary_.items():
        vocab[i] = gram
    order = [list(clf.classes_).index(lab) for lab in LABELS]     # 분류 순서를 LABELS로 맞춘다
    data = {
        'format': 'tfidf-char-logreg/1',
        'labels': LABELS,
        'ngram_range': list(vec.ngram_range),
        'sublinear_tf': bool(vec.sublinear_tf),
        'ocr_fixes': OCR_FIXES,
        'meta': {'trained': datetime.date.today().isoformat(), 'rows': n_rows, 'C': C, 'min_df': MIN_DF,
                 'max_features': MAX_FEATURES, 'data': 'ai/screen/generate.py (가상 데이터)'},
        'vocab': vocab,
        'idf': [round(float(v), 6) for v in vec.idf_],
        'coef': [[round(float(v), 6) for v in clf.coef_[k]] for k in order],
        'intercept': [round(float(clf.intercept_[k]), 6) for k in order],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    return data


def check_export(model, path, texts):
    """내보낸 JSON(numpy 계산)과 sklearn 확률의 최대 차이"""
    sm = classifier.ScreenModel.load(path)
    sk = model.predict_proba(texts)
    order = [list(model.classes_).index(lab) for lab in LABELS]
    diff = 0.0
    for t, p in zip(texts, sk):
        q = sm.predict_proba(t)
        if q is None:
            continue
        diff = max(diff, float(np.abs(q - p[order]).max()))
    return diff


def main():
    ap = argparse.ArgumentParser(description='C-1 쇼핑 화면 분류 모델 학습')
    ap.add_argument('--data', default=generate.DEFAULT_OUT)
    ap.add_argument('--out', default=MODEL_OUT)
    args = ap.parse_args()
    rows = generate.load(args.data)
    model = fit(rows)
    export(model, args.out, len(rows))
    size = os.path.getsize(args.out)
    diff = check_export(model, args.out, [r['text'] for r in rows[:500]])
    print(f'학습 {len(rows)}건 → {args.out} ({size / 1024:.0f}KB, 특성 {len(model.named_steps["tfidf"].vocabulary_):,}개)')
    print(f'sklearn과 확률 차이 최대 {diff:.2e} (가중치를 소수 6자리로 반올림해 생기는 차이)')
    if diff > 1e-3:
        raise SystemExit('내보낸 모델이 sklearn과 다름')


if __name__ == '__main__':
    main()
