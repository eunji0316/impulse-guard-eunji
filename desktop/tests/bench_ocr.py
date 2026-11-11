"""OCR 속도 벤치마크 (B-5)

tests/images/의 캡처를 실제 자동 감지와 같은 분석(main.analyze_boxes)으로 돌려
단계별 시간(OCR, 취소선 다시 읽기, 판정)과 결과(화면 단계, 결제 키워드 점수, 금액)를 표로 보여 준다.
개선 전후를 같은 이미지로 비교하는 기준이다. 이미지를 새로 저장하지 않는다.
정답(EXPECTED)과 다르면 줄 끝에 NG를 붙인다.

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe tests\\bench_ocr.py                       # EasyOCR, 전체, 이미지마다 1번
    .venv\\Scripts\\python.exe tests\\bench_ocr.py checkout --repeat 3   # 이름에 checkout이 들어간 것만 3번 (중앙값)
    .venv\\Scripts\\python.exe tests\\bench_ocr.py --engine win          # Windows 내장 OCR (winocr.py)
    .venv\\Scripts\\python.exe tests\\bench_ocr.py --engine win --win-scale 1.5
    .venv\\Scripts\\python.exe tests\\bench_ocr.py --scale 0.75          # OCR 전에 이미지를 줄여서
"""
import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from impulse_guard import capture, main as app_main, ocr, timing  # noqa: E402

IMAGE_DIR = os.path.join(HERE, 'images')

# 사람이 이미지를 보고 정한 정답: (단계, 금액). 결제 화면은 결제 금액, 상품 화면은 할인가
EXPECTED = {
    'checkout_musinsa': ('checkout', 79000),
    'checkout_zigzag': ('checkout', 224910),
    'checkout_zigzag_benefit': ('checkout', 224910),
    'coupang_product': ('product', 49600),
    'musinsa_product': ('product', 220590),
    'zigzag_product': ('product', 44800),
    'news_page': ('none', 0),
}


def engine_fns(name, win_scale):
    """(읽기 함수, 다시 읽기 함수)"""
    if name == 'win':
        from impulse_guard import winocr
        return (lambda img: winocr.read(img, win_scale)), winocr.read_struck
    return ocr.read, ocr.read_struck


def run_once(img, read, reread):
    t = timing.Timing('bench')
    with timing.active(t):
        a, total = app_main.timed_analysis(lambda: app_main.analyze_boxes(read(img), img, reread=reread))
    return a, total, t


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('names', nargs='*', help='이미지 이름 일부 (없으면 전체)')
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--scale', type=float, default=1.0, help='OCR 전에 이미지를 이 배율로 줄인다')
    p.add_argument('--engine', choices=['easy', 'win'], default='easy')
    p.add_argument('--win-scale', type=float, default=None, help='Windows OCR이 키워서 읽는 배율 (기본 config)')
    args = p.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    read, reread = engine_fns(args.engine, args.win_scale)
    t0 = timing.now()
    if args.engine == 'win':
        from impulse_guard import config, winocr
        winocr.get_engine()
        print(f'엔진 Windows OCR (키우는 배율 {args.win_scale or config.WINOCR_SCALE}), 축소 {args.scale}')
    else:
        import torch
        ocr.get_reader()
        print(f'엔진 EasyOCR (torch {torch.__version__}, 스레드 {torch.get_num_threads()}), 축소 {args.scale}')
    print(f'엔진 준비 {timing.now() - t0:.1f}초 (프로그램 시작 때 한 번)\n')

    files = sorted(f for f in os.listdir(IMAGE_DIR) if f.endswith('.png'))
    if args.names:
        files = [f for f in files if any(n in f for n in args.names)]
    print(f"{'이미지':<26}{'크기':>11}{'OCR':>7}{'다시읽기':>10}{'판정':>7}{'합계':>7}  단계 / 점수 / 금액 / 키워드")
    bad = 0
    for name in files:
        key = os.path.splitext(name)[0]
        img = capture.load_image(os.path.join(IMAGE_DIR, name))
        if args.scale != 1.0:
            import cv2
            img = cv2.resize(img, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
        runs = [run_once(img, read, reread) for _ in range(args.repeat)]
        med = lambda k: statistics.median(t.sec.get(k, 0.0) for _, _, t in runs)  # noqa: E731
        total = statistics.median(s for _, s, _ in runs)
        a, _, t = runs[-1]
        st = a.stage
        amount = a.amount if a.is_shopping else 0
        verdict = ''
        if key in EXPECTED:
            ok = (st.stage, amount) == EXPECTED[key]
            bad += not ok
            verdict = '  OK' if ok else f'  NG (정답 {EXPECTED[key][0]} {EXPECTED[key][1]:,}원)'
        rr = f"{med('reread'):.2f}({t.counts.get('reread', 0)})"
        print(f"{name:<26}{img.shape[1]:>5}x{img.shape[0]:<5}{med('ocr'):>7.2f}{rr:>10}{med('judge'):>7.2f}{total:>7.2f}  "
              f"{st.label} / {st.score} / {amount:,}원 / {','.join(st.words)} (상자 {len(a.boxes)}개){verdict}")
        del img
    print(f'\n정답과 다른 이미지: {bad}개')


if __name__ == '__main__':
    main(sys.argv[1:])
