"""테스트 이미지의 OCR 결과를 JSON으로 저장한다

OCR은 한 장에 수 초~수십 초가 걸리므로, 테스트는 여기서 만든 tests/ocr_cache/*.json을 다시 쓴다.
JSON에는 두 가지가 들어 있다.
- boxes: 화면 전체 OCR 결과 (원본과 같은 설정)
- reread: 가격 분석이 취소선 구간을 다시 읽은 결과 {'x0,y0,x1,y1': [[글자, 확신도], ...]}
이미지를 바꾸거나 OCR 설정(config.OCR_*, ocr.read_struck)이나 취소선 판정을 바꿨을 때 다시 실행한다.

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe tests\\make_ocr_cache.py                  # 전체
    .venv\\Scripts\\python.exe tests\\make_ocr_cache.py coupang          # 이름에 coupang이 들어간 것만
    .venv\\Scripts\\python.exe tests\\make_ocr_cache.py --reread-only    # 전체 OCR은 캐시를 쓰고 다시 읽기만 새로
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from impulse_guard import capture, ocr, config  # noqa: E402
from impulse_guard.detector import price  # noqa: E402

IMAGE_DIR = os.path.join(HERE, 'images')
CACHE_DIR = os.path.join(HERE, 'ocr_cache')


def main(args):
    import easyocr
    reread_only = '--reread-only' in args
    filters = [a for a in args if not a.startswith('--')]
    os.makedirs(CACHE_DIR, exist_ok=True)

    for name in sorted(os.listdir(IMAGE_DIR)):
        if not name.lower().endswith('.png'):
            continue
        if filters and not any(f in name for f in filters):
            continue
        img = capture.load_image(os.path.join(IMAGE_DIR, name))
        out = os.path.join(CACHE_DIR, os.path.splitext(name)[0] + '.json')

        start = time.time()
        if reread_only and os.path.exists(out):
            boxes, meta, _ = ocr.load_json(out)
        else:
            boxes = ocr.read(img)
            meta = {
                'image': name,
                'width': int(img.shape[1]),
                'height': int(img.shape[0]),
                'easyocr': easyocr.__version__,
                'langs': config.OCR_LANGS,
                'seconds': round(time.time() - start, 1),
            }

        # 가격 분석을 실제로 돌리면서 다시 읽기 결과를 기록한다
        reread = {}

        def recorder(image, box):
            result = ocr.read_struck(image, box)
            reread[ocr.box_key(box)] = [[t, round(c, 4)] for t, c in result]
            return result

        price.analyze(boxes, img, reread=recorder)
        ocr.save_json(out, boxes, meta, reread)
        print(f'{name}: 상자 {len(boxes)}개, 다시 읽기 {len(reread)}건, {time.time() - start:.1f}초', flush=True)
        for key, result in reread.items():
            print(f'    [{key}] → {result}', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
