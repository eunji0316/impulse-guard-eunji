"""테스트 공용: 이미지와 OCR 캐시 불러오기"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from impulse_guard import capture, ocr  # noqa: E402

IMAGE_DIR = os.path.join(HERE, 'images')
CACHE_DIR = os.path.join(HERE, 'ocr_cache')


def names():
    """캐시가 있는 테스트 이미지 이름 (확장자 없이)"""
    return sorted(os.path.splitext(n)[0] for n in os.listdir(CACHE_DIR) if n.endswith('.json'))


def load(name):
    """(이미지 BGR, OCR 상자 목록, reread 함수)

    reread 함수는 캐시에 저장된 다시 읽기 결과를 돌려준다. 캐시에 없는 구간이면 빈 목록과 함께 경고를 남긴다.
    (취소선 판정을 바꿔 구간이 달라졌으면 make_ocr_cache.py --reread-only를 다시 실행)
    """
    img = capture.load_image(os.path.join(IMAGE_DIR, name + '.png'))
    boxes, _, reread_cache = ocr.load_json(os.path.join(CACHE_DIR, name + '.json'))

    def reread(_img, box):
        key = ocr.box_key(box)
        if key not in reread_cache:
            print(f'[경고] {name}: 다시 읽기 캐시 없음 {key} → make_ocr_cache.py --reread-only 실행 필요', file=sys.stderr)
            return []
        return [tuple(r) for r in reread_cache[key]]

    return img, boxes, reread
