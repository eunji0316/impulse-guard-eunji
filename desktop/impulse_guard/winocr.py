"""Windows 내장 OCR (Windows.Media.Ocr) 래퍼 (B-5, 기본 엔진. config.OCR_ENGINE / main.ocr_engine)

ocr.read와 같은 형식(OcrBox 목록)으로 돌려줘서 판정/가격 분석을 그대로 쓸 수 있다.
- Windows 10 이상 + 한국어 OCR 언어팩이 필요하다 (설정 → 언어에 한국어). 패키지: winrt-Windows.Media.Ocr 등
- 결과는 줄 단위이고 단어 사이가 멀면(줄 높이의 WINOCR_SPLIT_GAP배 이상) 다른 상자로 나눈다.
  EasyOCR처럼 '상품 금액'과 오른쪽 끝 '224,910원'이 다른 상자가 되게 (같은 줄 판단과 라벨 옆 금액 찾기가 그대로 동작)
- 작은 글자에서 쉼표를 빠뜨리므로('224910원') WINOCR_SCALE배로 키워서 읽고 좌표를 원래 크기로 돌린다
- 쉼표를 공백으로 읽어 금액이 두 단어로 나뉘면('224 | 910원') 쉼표로 다시 잇는다 (join_words)
- 확신도를 주지 않으므로 conf는 1.0
- 이미지는 메모리에서만 넘기고 파일로 저장하지 않는다
"""
import asyncio
import re

import numpy as np

from . import config, timing
from .ocr import OcrBox, REREAD_ALLOWLIST, REREAD_SCALE, remove_hline

_engine = None


def available():
    """한국어 Windows OCR을 쓸 수 있으면 True"""
    try:
        return get_engine() is not None
    except Exception:
        return False


def get_engine():
    global _engine
    if _engine is None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        _engine = OcrEngine.try_create_from_language(Language(config.WINOCR_LANG))
    return _engine


def _bitmap(img):
    import cv2
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    bgra = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA if img.ndim == 2 else cv2.COLOR_BGR2BGRA)
    writer = DataWriter()
    writer.write_bytes(np.ascontiguousarray(bgra).tobytes())
    return SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                  bgra.shape[1], bgra.shape[0], BitmapAlphaMode.PREMULTIPLIED)


def _recognize(img):
    async def run():
        return await get_engine().recognize_async(_bitmap(img))
    return asyncio.run(run())


def _resize(img, scale):
    if scale == 1:
        return img
    import cv2
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)


_HEAD_DIGITS = re.compile(r'(?:.*\D)?\d{1,3}(?:,\d{3})*')     # 끝이 '224', '1,224', '총224'
_TAIL_DIGITS = re.compile(r'\d{3}(?:,\d{3})*(?:원.*)?')         # '910원', '910', '910원~'


def join_words(texts):
    """단어를 공백으로 잇되, 숫자 1~3자리 뒤에 숫자 3자리로 시작하는 단어가 오면 쉼표로 잇는다
    (Windows OCR이 '224,910원'의 쉼표를 빠뜨리고 '224', '910원' 두 단어로 주는 경우)"""
    out = ''
    for t in texts:
        if out and _HEAD_DIGITS.fullmatch(out.rsplit(' ', 1)[-1]) and _TAIL_DIGITS.fullmatch(t):
            out += ',' + t
        else:
            out = f'{out} {t}' if out else t
    return out


def _box(words, scale):
    x0 = min(w.bounding_rect.x for w in words)
    y0 = min(w.bounding_rect.y for w in words)
    x1 = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
    y1 = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
    x0, y0, x1, y1 = (int(round(v / scale)) for v in (x0, y0, x1, y1))
    return OcrBox(text=join_words([w.text for w in words]), conf=1.0, bbox=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def split_line(words, gap_ratio=None):
    """한 줄의 단어를 사이가 먼 곳에서 나눈다 → [[단어, ...], ...]"""
    gap_ratio = gap_ratio or config.WINOCR_SPLIT_GAP
    groups = []
    for w in words:
        r = w.bounding_rect
        if groups:
            prev = groups[-1][-1].bounding_rect
            h = max(prev.height, r.height, 1)
            close = r.x - (prev.x + prev.width) <= h * gap_ratio
            if close or (r.x - (prev.x + prev.width) <= h * 3 and _is_split_number(groups[-1][-1].text, w.text)):
                groups[-1].append(w)
                continue
        groups.append([w])
    return groups


def _is_split_number(a, b):
    return bool(_HEAD_DIGITS.fullmatch(a) and _TAIL_DIGITS.fullmatch(b))


def read(img, scale=None):
    """이미지(3채널 BGR)에서 글자 상자 목록 (ocr.read와 같은 형식)"""
    scale = scale or config.WINOCR_SCALE
    with timing.measure('ocr'):
        result = _recognize(_resize(img, scale))
    boxes = []
    for line in result.lines:
        for group in split_line(list(line.words)):
            boxes.append(_box(group, scale))
    return boxes


def read_struck(img, box, pad=3):
    """ocr.read_struck과 같은 일 (취소선을 지우고 키워서 다시 읽기). 허용 글자는 읽은 뒤 거른다"""
    x0, y0, x1, y1 = [int(v) for v in box]
    h, w = img.shape[:2]
    crop = img[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
    if crop.size == 0:
        return []
    crop = remove_hline(crop)
    with timing.measure('reread'):
        result = _recognize(_resize(crop, REREAD_SCALE))
    out = []
    for line in result.lines:
        text = ''.join(ch for ch in line.text if ch in REREAD_ALLOWLIST)
        if text:
            out.append((text, 1.0))
    return out
