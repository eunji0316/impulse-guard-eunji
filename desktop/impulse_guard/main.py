"""F4로 화면을 분석하는 진입점 (원본 shopping_detector.py와 같은 동작 + 가격 분석)

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe -m impulse_guard.main
"""
from . import capture, config, ocr
from .detector import price, shopping


def analyze_image(img):
    """이미지 한 장을 분석한다 → (쇼핑 판정, 가격 분석, OCR 상자)"""
    boxes = ocr.read(img)
    shop = shopping.judge(ocr.full_text(boxes))
    prices = price.analyze(boxes, img, reread=ocr.read_struck) if shop.is_mall else None
    return shop, prices, boxes


def _won(v):
    return f'{v:,}원' if v else '찾지 못함'


def print_result(shop, prices):
    print("-" * 40)
    if shop.is_mall:
        print("⭕ [판정 결과] 쇼핑몰 사이트입니다!")
        print(f"  - 감지된 키워드: {shop.found_keywords}")
        print(f"  - 감지된 가격 정보: {shop.price_patterns[:3]}")
        if prices is not None:
            check = '검산 통과' if prices.verified else '검산 못 함'
            rate = f'{prices.discount_rate}%' if prices.discount_rate is not None else '찾지 못함'
            if prices.discount_rate is not None and not prices.rate_shown:
                rate += ' (원가와 할인가로 계산)'
            print(f"  - 할인가: {_won(prices.sale_price)} (확신도 {prices.sale_conf:.2f})")
            print(f"  - 원가:   {_won(prices.original_price)} (확신도 {prices.original_conf:.2f})")
            print(f"  - 할인율: {rate} (확신도 {prices.rate_conf:.2f}, {check})")
            dropped = [c for c in prices.candidates if c.role == 'excluded']
            if dropped:
                print(f"  - 제외한 값: {[f'{c.text} ({c.reason})' for c in dropped]}")
    else:
        print("❌ [판정 결과] 쇼핑몰이 아닙니다.")
        print("  - 쇼핑몰 특유의 구매 버튼이나 가격 정보가 충분히 발견되지 않았습니다.")
    print("-" * 40)


def on_hotkey():
    print(f"\n[{config.HOTKEY.upper()} 감지] 화면 캡처 및 분석을 시작합니다...")
    try:
        img = capture.grab_screen()
        shop, prices, _ = analyze_image(img)
        del img   # 캡처 이미지는 저장하지 않고 바로 버린다
        print_result(shop, prices)
    except Exception as e:
        print(f"!!! 분석 중 오류가 발생했습니다: {e}")


def main():
    import keyboard
    print("화면 분석을 위한 OCR 모델을 로딩 중입니다. 최초 실행 시 약간의 시간이 걸립니다")
    ocr.get_reader()
    print("\n" + "=" * 50)
    print("쇼핑몰 감지 프로그램이 실행되었습니다!")
    print(f"웹서핑 중 쇼핑몰 화면에서 [{config.HOTKEY.upper()}] 키를 누르면 즉시 분석합니다.")
    print("종료하려면 콘솔 창에서 [Ctrl + C]를 누르세요.")
    print("=" * 50 + "\n")
    keyboard.add_hotkey(config.HOTKEY, on_hotkey)
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")


if __name__ == '__main__':
    main()
