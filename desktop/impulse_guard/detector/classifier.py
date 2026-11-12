"""쇼핑 화면 분류 모델 추론 (C-1): OCR 글자 → 쇼핑 아님 / 상품 화면 / 결제 화면

학습은 ai/screen/train.py(scikit-learn)에서 하고, 결과(어휘, idf, 가중치)를 JSON으로 내보낸다.
데스크톱은 그 JSON을 읽어 numpy로만 계산한다. scikit-learn을 설치할 필요가 없고, pickle을 읽지 않는다.

모델: 문자 n-gram TF-IDF + 로지스틱 회귀 (다항, softmax)
- 전처리(preprocess): 공백 삭제 → 소문자 → OCR 오타 고치기 → 숫자를 모두 0으로 (가격을 외우지 않게)
  학습도 이 함수를 그대로 쓴다. OCR 오타 표는 학습할 때 쓴 것을 모델 파일에 넣어 두고 그것을 쓴다
- 특성: n-gram 개수 → 1 + log(개수) → × idf → L2 정규화 (TfidfVectorizer(sublinear_tf=True)와 같다)
- 확률: softmax(특성 · 가중치 + 절편)

모델 파일이 없거나 읽지 못하면 predict()가 None을 돌려준다. 그때는 키워드 판정을 쓴다 (stage.decide).
"""
import json
import os
import re
import threading

import numpy as np

from .. import config

DIGIT_RE = re.compile(r'\d')

_lock = threading.Lock()
_model = None          # ScreenModel, 읽기 실패면 False
_error = ''            # 읽기 실패 이유 (로그용)


def preprocess(text, ocr_fixes=None):
    """모델 입력용 글자. ocr_fixes: {틀린 글자: 고친 글자} (공백을 뺀 뒤 바꾼다)"""
    text = ''.join((text or '').split()).lower()
    for wrong, right in (ocr_fixes or {}).items():
        text = text.replace(wrong, right)
    return DIGIT_RE.sub('0', text)


class ScreenModel:
    def __init__(self, data):
        self.labels = list(data['labels'])
        self.ngram_min, self.ngram_max = data['ngram_range']
        self.sublinear_tf = bool(data.get('sublinear_tf', True))
        self.ocr_fixes = dict(data.get('ocr_fixes', {}))
        self.meta = data.get('meta', {})
        vocab = data['vocab']
        self.index = {g: i for i, g in enumerate(vocab)}
        self.idf = np.asarray(data['idf'], dtype=np.float64)
        self.coef_t = np.asarray(data['coef'], dtype=np.float64).T     # (특성 수, 분류 수)
        self.intercept = np.asarray(data['intercept'], dtype=np.float64)
        if not (len(vocab) == len(self.idf) == self.coef_t.shape[0] and self.coef_t.shape[1] == len(self.labels)
                == len(self.intercept)):
            raise ValueError('모델 파일의 크기가 서로 맞지 않음')

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as f:
            return cls(json.load(f))

    def features(self, text):
        """(특성 번호 배열, 값 배열). 아는 n-gram이 하나도 없으면 빈 배열"""
        s = preprocess(text, self.ocr_fixes)
        counts = {}
        index = self.index
        for n in range(self.ngram_min, self.ngram_max + 1):
            for i in range(len(s) - n + 1):
                j = index.get(s[i:i + n])
                if j is not None:
                    counts[j] = counts.get(j, 0) + 1
        if not counts:
            return np.zeros(0, dtype=np.int64), np.zeros(0)
        idx = np.fromiter(counts.keys(), dtype=np.int64, count=len(counts))
        val = np.fromiter(counts.values(), dtype=np.float64, count=len(counts))
        if self.sublinear_tf:
            val = 1.0 + np.log(val)
        val *= self.idf[idx]
        norm = np.sqrt(np.dot(val, val))
        return idx, (val / norm if norm > 0 else val)

    def predict_proba(self, text):
        """분류별 확률 배열 (self.labels 순서). 아는 n-gram이 없으면 None"""
        idx, val = self.features(text)
        if len(idx) == 0:
            return None
        logits = val @ self.coef_t[idx] + self.intercept
        logits -= logits.max()
        p = np.exp(logits)
        return p / p.sum()

    def predict(self, text):
        """(분류, 확률, {분류: 확률}) 또는 None"""
        p = self.predict_proba(text)
        if p is None:
            return None
        k = int(np.argmax(p))
        return self.labels[k], float(p[k]), {lab: float(v) for lab, v in zip(self.labels, p)}


def model_path():
    path = config.SCREEN_MODEL_PATH
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_model():
    """한 번만 읽는다. 없거나 읽지 못하면 None (이유는 last_error())"""
    global _model, _error
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    _model = ScreenModel.load(model_path())
                    _error = ''
                except FileNotFoundError:
                    _model, _error = False, '모델 파일 없음'
                except Exception as e:      # 파일이 깨졌거나 형식이 다름 → 키워드 판정으로
                    _model, _error = False, f'모델 읽기 실패: {type(e).__name__}'
    return _model or None


def last_error():
    return _error


def reset():
    """다음 get_model()에서 다시 읽는다 (테스트, 모델 교체용)"""
    global _model, _error
    with _lock:
        _model, _error = None, ''


def set_model(model):
    """테스트용: 모델을 직접 넣는다 (None이면 '모델 없음' 상태)"""
    global _model, _error
    with _lock:
        _model, _error = (model if model is not None else False), ('' if model is not None else '모델 없음(테스트)')


def predict(text):
    """(분류, 확률, {분류: 확률}) 또는 None (모델 없음, 아는 글자 없음, 계산 오류)"""
    global _error
    model = get_model()
    if model is None:
        return None
    try:
        return model.predict(text)
    except Exception as e:
        _error = f'모델 판정 오류: {type(e).__name__}'
        return None
