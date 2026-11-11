"""OCR 속도 벤치마크 (B-5)

tests/images/의 캡처를 실제 자동 감지와 같은 분석(main.analyze_image)으로 돌려
단계별 시간(OCR, 취소선 다시 읽기, 판정)과 결과(화면 단계, 결제 키워드 점수, 결제 금액)를 표로 보여 준다.
개선 전후를 같은 이미지로 비교하는 기준이다. 이미지를 새로 저장하지 않는다.

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe tests\\bench_ocr.py                     # 전체, 이미지마다 1번
    .venv\\Scripts\\python.exe tests\\bench_ocr.py checkout --repeat 3 # 이름에 checkout이 들어간 것만 3번 (중앙값)
    .venv\\Scripts\\python.exe tests\\bench_ocr.py --scale 0.75        # OCR 전에 0.75배로 줄여서 (2단계 후보 미리 보기)
"""
import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from impulse_guard import capture, main as app_main, ocr, timing  # noqa: E402

IMAGE_DIR = os.path.join(HERE, 'images')


def prepare(img, scale):
    if scale == 1.0:
        return img
    import cv2
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def run_once(img):
    t = timing.Timing('bench')
    with timing.active(t):
        a, total = app_main.timed_analysis(app_main.analyze_image, img)
    return a, total, t


def summary(a):
    st = a.stage
    amount = a.amount if a.is_shopping else 0
    return st.label, st.score, ','.join(st.words), amount


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('names', nargs='*', help='이미지 이름 일부 (없으면 전체)')
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--scale', type=float, default=1.0)
    args = p.parse_args(argv)

    import torch
    print(f'torch {torch.__version__}, 스레드 {torch.get_num_threads()}, 축소 {args.scale}')
    t0 = timing.now()
    ocr.get_reader()
    print(f'Reader 만들기 {timing.now() - t0:.1f}초 (프로그램 시작 때 한 번)\n')

    files = sorted(f for f in os.listdir(IMAGE_DIR) if f.endswith('.png'))
    if args.names:
        files = [f for f in files if any(n in f for n in args.names)]
    print(f"{'이미지':<22}{'크기':>11}{'OCR':>7}{'다시읽기':>10}{'판정':>7}{'합계':>7}  단계 / 점수 / 금액 / 키워드")
    for name in files:
        img = prepare(capture.load_image(os.path.join(IMAGE_DIR, name)), args.scale)
        runs = [run_once(img) for _ in range(args.repeat)]
        med = lambda key: statistics.median(t.sec.get(key, 0.0) for _, _, t in runs)  # noqa: E731
        total = statistics.median(s for _, s, _ in runs)
        a, _, t = runs[-1]
        label, score, words, amount = summary(a)
        rr = f"{med('reread'):.2f}({t.counts.get('reread', 0)})"
        size = f'{img.shape[1]}x{img.shape[0]}'
        print(f"{name:<22}{size:>11}{med('ocr'):>7.2f}{rr:>10}{med('judge'):>7.2f}{total:>7.2f}  "
              f"{label} / {score} / {amount:,}원 / {words} (상자 {len(a.boxes)}개)")
        del img


if __name__ == '__main__':
    main(sys.argv[1:])
