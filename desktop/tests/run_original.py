"""팀원 원본(desktop/original/shopping_detector.py)을 수정하지 않고 테스트 이미지로 실행한다

원본은 import하는 순간 OCR 모델을 로딩하고 keyboard.wait()에서 멈추므로,
easyocr, mss, keyboard 세 모듈을 가짜로 바꿔 끼운 뒤 원본 소스를 그대로 실행한다.
- 가짜 easyocr: readtext()가 OCR 캐시 JSON을 원본 형식 (bbox, text, conf)으로 돌려준다
- 가짜 mss: grab()이 테스트 이미지를 BGRA로 돌려준다
- 가짜 keyboard: 핫키 함수만 받아 두고 wait()는 바로 끝난다
그다음 원본의 check_shopping_mall()을 직접 부르고, 콘솔 출력을 읽어 판정 결과를 꺼낸다.
"""
import ast
import contextlib
import io
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL = os.path.join(os.path.dirname(HERE), 'original', 'shopping_detector.py')


def _fake_modules(raw_results, img_bgr):
    easyocr = types.ModuleType('easyocr')

    class Reader:
        def __init__(self, *args, **kwargs):
            pass

        def readtext(self, img):
            return list(raw_results)

    easyocr.Reader = Reader

    mss = types.ModuleType('mss')
    bgra = np.dstack([img_bgr, np.full(img_bgr.shape[:2], 255, dtype=np.uint8)])

    class _Sct:
        monitors = [None, {'left': 0, 'top': 0, 'width': img_bgr.shape[1], 'height': img_bgr.shape[0]}]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def grab(self, monitor):
            return bgra

    mss.mss = _Sct

    keyboard = types.ModuleType('keyboard')
    keyboard.hotkeys = {}
    keyboard.add_hotkey = lambda key, fn: keyboard.hotkeys.__setitem__(key, fn)
    keyboard.wait = lambda *a, **k: None
    return {'easyocr': easyocr, 'mss': mss, 'keyboard': keyboard}


def run(raw_results, img_bgr):
    """원본을 실행하고 {'is_mall', 'found_keywords', 'price_patterns_top3', 'output'}를 돌려준다

    원본은 가격 패턴을 앞 3개만 출력하므로 price_patterns_top3만 비교할 수 있다.
    """
    with open(ORIGINAL, encoding='utf-8') as f:
        source = f.read()

    fakes = _fake_modules(raw_results, img_bgr)
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    buf = io.StringIO()
    try:
        namespace = {'__name__': 'shopping_detector_original'}
        with contextlib.redirect_stdout(buf):
            exec(compile(source, ORIGINAL, 'exec'), namespace)   # 모델 로딩 문구 출력, 핫키 등록, wait() 즉시 종료
            start = len(buf.getvalue())
            fakes['keyboard'].hotkeys['f4']()                     # = check_shopping_mall()
        output = buf.getvalue()[start:]
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    return _parse(output)


def _parse(output):
    if '분석 중 오류가 발생했습니다' in output:
        raise RuntimeError('원본 실행 중 오류:\n' + output)
    result = {'is_mall': '⭕' in output, 'found_keywords': None, 'price_patterns_top3': None, 'output': output}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('- 감지된 키워드:'):
            result['found_keywords'] = ast.literal_eval(line.split(':', 1)[1].strip())
        elif line.startswith('- 감지된 가격 정보:'):
            result['price_patterns_top3'] = ast.literal_eval(line.split(':', 1)[1].strip())
    return result
