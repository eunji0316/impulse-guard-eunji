"""EasyOCR 래퍼

원본과 같은 설정(Reader(['ko', 'en'], gpu=False), readtext 기본 옵션)으로 글자를 읽고,
글자뿐 아니라 좌표 상자와 확신도까지 OcrBox로 돌려준다.
테스트에서는 OCR이 느리므로 결과를 JSON으로 저장해 두고 다시 쓴다 (save_json, load_json).
"""
import json
from dataclasses import dataclass, asdict

import numpy as np

from . import config, timing

_reader = None


@dataclass
class OcrBox:
    text: str
    conf: float                 # OCR 확신도 0~1
    bbox: list                  # 꼭짓점 4개 [[x, y], ...] (왼쪽 위부터 시계 방향)

    @property
    def x(self):
        return min(p[0] for p in self.bbox)

    @property
    def y(self):
        return min(p[1] for p in self.bbox)

    @property
    def x2(self):
        return max(p[0] for p in self.bbox)

    @property
    def y2(self):
        return max(p[1] for p in self.bbox)

    @property
    def w(self):
        return self.x2 - self.x

    @property
    def h(self):
        return self.y2 - self.y

    @property
    def cy(self):
        return (self.y + self.y2) / 2

    def to_raw(self):
        """원본 readtext 결과와 같은 (bbox, text, conf) 튜플"""
        return (self.bbox, self.text, self.conf)


def get_reader():
    """EasyOCR 모델은 로딩이 느리므로 처음 쓸 때 한 번만 만든다"""
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(config.OCR_LANGS, gpu=config.OCR_GPU)
    return _reader


def read(img):
    """이미지(3채널 배열)에서 글자 상자 목록을 읽는다"""
    with timing.measure('ocr'):
        results = get_reader().readtext(img)
    return [from_raw(r) for r in results]


REREAD_ALLOWLIST = '0123456789,원₩'
REREAD_SCALE = 3


def remove_hline(crop):
    """잘라 낸 이미지에서 가로선(취소선)이 지나가는 줄을 위아래 줄의 평균으로 메운다"""
    out = crop.copy()
    gray = crop.astype(np.int16).mean(axis=2)
    bg = np.median(np.concatenate([gray[0], gray[-1]]))
    line_rows = [r for r in range(gray.shape[0]) if (np.abs(gray[r] - bg) > 40).mean() > 0.5]
    for r in line_rows:
        up, dn = r - 1, r + 1
        while up in line_rows:
            up -= 1
        while dn in line_rows:
            dn += 1
        if up >= 0 and dn < gray.shape[0]:
            out[r] = ((crop[up].astype(np.int16) + crop[dn].astype(np.int16)) // 2).astype(np.uint8)
    return out


def read_struck(img, box, pad=3):
    """취소선이 그어진 가격을 다시 읽는다

    취소선 때문에 첫 OCR이 '#49G68원'처럼 읽는 경우가 많아서, 그 구간만 잘라 선을 지우고
    3배 확대한 뒤 숫자와 '원'만 허용해 다시 읽는다. 반환: [(글자, 확신도), ...]
    """
    import cv2
    x0, y0, x1, y1 = [int(v) for v in box]
    h, w = img.shape[:2]
    crop = img[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
    if crop.size == 0:
        return []
    crop = remove_hline(crop)
    big = cv2.resize(crop, None, fx=REREAD_SCALE, fy=REREAD_SCALE, interpolation=cv2.INTER_CUBIC)
    with timing.measure('reread'):
        results = get_reader().readtext(big, allowlist=REREAD_ALLOWLIST)
    return [(text, float(conf)) for _, text, conf in results]


def from_raw(r):
    bbox, text, conf = r
    return OcrBox(text=text, conf=float(conf), bbox=[[int(v) for v in p] for p in bbox])


def full_text(boxes):
    """원본처럼 상자 글자를 공백으로 이어 붙인다"""
    return " ".join(b.text for b in boxes)


def box_key(box):
    """다시 읽기 결과를 캐시에 저장할 때 쓰는 키 'x0,y0,x1,y1'"""
    return ','.join(str(int(v)) for v in box)


def save_json(path, boxes, meta=None, reread=None):
    """OCR 결과 저장. reread: {box_key: [[글자, 확신도], ...]} 취소선 다시 읽기 결과"""
    data = {'meta': meta or {}, 'boxes': [asdict(b) for b in boxes], 'reread': reread or {}}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_json(path):
    """(상자 목록, meta, reread 사전)"""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return [OcrBox(**b) for b in data['boxes']], data.get('meta', {}), data.get('reread', {})
