"""F4로 화면을 분석하는 진입점

원본 shopping_detector.py와 같은 판정 + 가격 분석(B-1) + 서버 연동(B-2)
- 시작할 때 local_config.json의 토큰으로 회원을 확인한다. 실패하면 오프라인 모드로 감지만 한다.
- 쇼핑 화면이면 서버 check로 위험도를 묻고 감지 기록(detect)을 남긴다. 결과는 콘솔에 출력한다 (팝업은 B-3)

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe -m impulse_guard.main
"""
from dataclasses import dataclass

from . import capture, config, ocr
from .detector import page as page_info, price, shopping
from .server_client import Client


@dataclass
class Analysis:
    shop: shopping.ShoppingResult
    prices: price.PriceResult = None
    page: page_info.PageInfo = None
    boxes: list = None


def analyze_boxes(boxes, img=None, reread=None, site_hints=None):
    """OCR 상자로 쇼핑 판정, 가격 분석, 페이지 정보를 만든다 (테스트는 OCR 캐시로 부른다)"""
    text = ocr.full_text(boxes)
    shop = shopping.judge(text)
    if not shop.is_mall:
        return Analysis(shop, boxes=boxes)
    prices = price.analyze(boxes, img, reread=reread)
    info = page_info.analyze(boxes, text, prices, site_hints)
    return Analysis(shop, prices, info, boxes)


def analyze_image(img, site_hints=None):
    """이미지 한 장을 OCR부터 분석한다"""
    return analyze_boxes(ocr.read(img), img, reread=ocr.read_struck, site_hints=site_hints)


def _won(v):
    return f'{v:,}원' if v else '찾지 못함'


def _hms(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return (f'{h}시간 ' if h else '') + (f'{m}분 ' if h or m else '') + f'{s}초'


def print_result(a):
    """원본과 같은 판정 출력 + 가격 분석"""
    print("-" * 40)
    if a.shop.is_mall:
        print("⭕ [판정 결과] 쇼핑몰 사이트입니다!")
        print(f"  - 감지된 키워드: {a.shop.found_keywords}")
        print(f"  - 감지된 가격 정보: {a.shop.price_patterns[:3]}")
        p = a.prices
        if p is not None:
            check = '검산 통과' if p.verified else '검산 못 함'
            rate = f'{p.discount_rate}%' if p.discount_rate is not None else '찾지 못함'
            if p.discount_rate is not None and not p.rate_shown:
                rate += ' (원가와 할인가로 계산)'
            print(f"  - 할인가: {_won(p.sale_price)} (확신도 {p.sale_conf:.2f})")
            print(f"  - 원가:   {_won(p.original_price)} (확신도 {p.original_conf:.2f})")
            print(f"  - 할인율: {rate} (확신도 {p.rate_conf:.2f}, {check})")
            dropped = [c for c in p.candidates if c.role == 'excluded']
            if dropped:
                print(f"  - 제외한 값: {[f'{c.text} ({c.reason})' for c in dropped]}")
        if a.page is not None:
            print(f"  - 사이트: {a.page.site or '모름'} / 상품명: {a.page.item_name or '찾지 못함'}"
                  f" / 결제 화면: {'예 ' + str(list(a.page.checkout_words)) if a.page.is_checkout else '아니오'}")
    else:
        print("❌ [판정 결과] 쇼핑몰이 아닙니다.")
        print("  - 쇼핑몰 특유의 구매 버튼이나 가격 정보가 충분히 발견되지 않았습니다.")


def send_and_print(client, a):
    """쇼핑 화면이면 서버에 위험도를 묻고 기록을 남긴 뒤 결과를 출력한다. 서버 결과(ApiResult 또는 None)를 돌려준다"""
    if not a.shop.is_mall:
        print("-" * 40)
        return None
    p, info = a.prices, a.page
    r = client.check(site=info.site, item_name=info.item_name, price=p.sale_price or 0,
                     orig_price=p.original_price or 0,
                     discount_rate=p.discount_rate if p.discount_rate is not None else 0,
                     is_checkout=info.is_checkout, page='product', log=True)
    if r.ok:
        d = r.data
        print("  [서버] 위험도 판단")
        if d.get('is_blocking'):
            client.get_setting()
            remain = client.block_remain()
            print(f"    - 차단 시간입니다{f' (남은 시간 {_hms(remain)})' if remain else ''}")
        else:
            print("    - 차단 시간: 아님")
        reason = f" (키워드 '{d['keyword']}')" if d.get('keyword') else ''
        print(f"    - 충동구매 감지: {'예' + reason if d.get('is_impulse') else '아니오'}")
        if p.sale_price:
            print(f"    - 지금 포기하면 {d.get('point', 0)}P, 24시간 참으면 {d.get('point2', 0)}P")
        print(f"    - 감지 기록 저장 (번호 {d.get('bl_id')})")
    elif r.offline:
        print(f"  [서버] 연결 안 됨 ({r.msg}) - 감지만 했습니다")
        remain = client.block_remain()
        if remain:
            print(f"    - (마지막으로 받은 설정 기준) 차단 시간입니다. 남은 시간 {_hms(remain)}")
    else:
        print(f"  [서버] 요청 실패 (HTTP {r.status}): {r.msg}")
    print("-" * 40)
    return r


def print_connection(client):
    if client.online:
        m = client.member
        print(f"[서버] 연결됨: {client.server} / {m.get('nick')}({m.get('mb_id')}) / 포인트 {m.get('point', 0):,}P")
    elif client.auth_failed:
        print(f"[서버] 토큰이 올바르지 않습니다. 웹 설정 화면에서 토큰을 다시 발급해 {config.LOCAL_CONFIG}에 넣으세요.")
        print("       오프라인 모드로 감지만 합니다.")
    else:
        print(f"[서버] 연결 안 됨 ({client.last_error}). 오프라인 모드로 감지만 합니다.")
        if client.token:
            print(f"       F4를 누를 때 {config.RECONNECT_SEC}초 간격으로 다시 연결해 봅니다.")


def make_hotkey_handler(client):
    def on_hotkey():
        print(f"\n[{config.HOTKEY.upper()} 감지] 화면 캡처 및 분석을 시작합니다...")
        try:
            was_online = client.online
            if client.ensure_online() and not was_online:
                print_connection(client)
            client.get_setting()          # 5분 캐시. 사이트 이름을 사이트 찾기에 더한다
            img = capture.grab_screen()
            a = analyze_image(img, client.site_hints())
            del img                       # 캡처 이미지는 저장하지 않고 바로 버린다
            print_result(a)
            send_and_print(client, a)
        except Exception as e:
            print(f"!!! 분석 중 오류가 발생했습니다: {e}")
    return on_hotkey


def main():
    import keyboard
    print("화면 분석을 위한 OCR 모델을 로딩 중입니다. 최초 실행 시 약간의 시간이 걸립니다")
    ocr.get_reader()
    client = Client.from_config()
    client.connect()
    client.get_setting()
    print("\n" + "=" * 50)
    print("쇼핑몰 감지 프로그램이 실행되었습니다!")
    print_connection(client)
    print(f"웹서핑 중 쇼핑몰 화면에서 [{config.HOTKEY.upper()}] 키를 누르면 즉시 분석합니다.")
    print("종료하려면 콘솔 창에서 [Ctrl + C]를 누르세요.")
    print("=" * 50 + "\n")
    keyboard.add_hotkey(config.HOTKEY, make_hotkey_handler(client))
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")


if __name__ == '__main__':
    main()
