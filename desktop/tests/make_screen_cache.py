"""화면 분류(C-1) 실측 평가용 OCR 글자 캐시

tests/images/의 모든 이미지를 OCR로 읽어 tests/screen_cache/<엔진>/<이름>.json에 글자 상자만 저장한다.
- win: Windows OCR (지금 기본 엔진), easy: EasyOCR (tests/ocr_cache와 같은 엔진)
- tests/ocr_cache/는 가격/페이지 테스트 정답이 있는 7장 전용이다. 새 이미지를 거기에 넣으면
  test_shopping/test_page/test_price가 정답 없음으로 실패하므로 분류 평가 캐시는 여기에 따로 둔다.

정답(분류)은 파일 이름으로 정한다 (screen_label):
    이름에 checkout → 결제 화면, product 또는 cart → 상품 화면, 그 밖 → 쇼핑 아님
    예: news_naver.png, youtube_home.png, vscode.png → 쇼핑 아님 / order_done_xxx.png → 쇼핑 아님

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe tests\\make_screen_cache.py              # 두 엔진 모두, 캐시 없는 이미지만
    .venv\\Scripts\\python.exe tests\\make_screen_cache.py win --all    # Windows OCR만, 전부 다시
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from impulse_guard import capture  # noqa: E402

IMAGE_DIR = os.path.join(HERE, 'images')
CACHE_DIR = os.path.join(HERE, 'screen_cache')
ENGINES = ('win', 'easy')


def screen_label(name):
    """파일 이름 → 정답 분류 (none / product / checkout)"""
    n = name.lower()
    if 'checkout' in n:
        return 'checkout'
    if 'product' in n or 'cart' in n:
        return 'product'
    return 'none'


def load_all(engine):
    """[(이름, 정답, OCR 전체 글자)] — 캐시가 있는 것만"""
    folder = os.path.join(CACHE_DIR, engine)
    out = []
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if fn.endswith('.json'):
            with open(os.path.join(folder, fn), encoding='utf-8') as f:
                data = json.load(f)
            name = os.path.splitext(fn)[0]
            out.append((name, screen_label(name), ' '.join(data['texts'])))
    return out


def reader(engine):
    if engine == 'win':
        from impulse_guard import winocr
        if not winocr.available():
            raise SystemExit('Windows 한국어 OCR을 쓸 수 없음')
        return winocr.read
    from impulse_guard import ocr
    ocr.get_reader()
    return ocr.read


def main(args):
    engines = [a for a in args if a in ENGINES] or list(ENGINES)
    redo = '--all' in args
    for engine in engines:
        folder = os.path.join(CACHE_DIR, engine)
        os.makedirs(folder, exist_ok=True)
        read = None
        for name in sorted(os.listdir(IMAGE_DIR)):
            if not name.lower().endswith('.png'):
                continue
            out = os.path.join(folder, os.path.splitext(name)[0] + '.json')
            if os.path.exists(out) and not redo:
                continue
            read = read or reader(engine)
            img = capture.load_image(os.path.join(IMAGE_DIR, name))
            start = time.time()
            boxes = read(img)
            data = {'meta': {'image': name, 'engine': engine, 'width': int(img.shape[1]), 'height': int(img.shape[0]),
                             'seconds': round(time.time() - start, 1)},
                    'texts': [b.text for b in boxes]}
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            print(f'[{engine}] {name}: 상자 {len(boxes)}개, {time.time() - start:.1f}초 → {screen_label(name)}', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
