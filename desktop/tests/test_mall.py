"""팝업의 쇼핑몰 이름 테스트 (mall.py)

- 창 제목의 도메인/이름 → 주소창 도메인 → 화면 글자의 쇼핑몰 이름 → 모르는 도메인 → '쇼핑몰' 순서
- OCR로 읽은 상품명은 쓰지 않는다
- 자동 감지 팝업에 쇼핑몰 이름, 로그에 근거
실행 (desktop 폴더에서): .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import dataclasses
import os
import shutil
import tempfile
import unittest

import checkout_samples as cs
from impulse_guard import config, main, mall, server_client
from impulse_guard.detect_log import DetectLog
from impulse_guard.ocr import OcrBox
from test_auto import CHECKOUT_RESULT, NOT_BLOCKING, Clock
from test_popup import TkCase, quiet
from test_server_client import FakeServer, make


def box(text, x, y, w=200, h=20):
    return OcrBox(text=text, conf=0.9, bbox=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


class TestIdentify(unittest.TestCase):
    def test_title_domain(self):
        m = mall.identify('zigzag.kr/checkout/order-sheets/abc123 - Chrome')
        self.assertEqual((m.name, m.code, m.basis), ('지그재그', 'zigzag', '창 제목 주소 zigzag.kr'))
        m = mall.identify('https://order.pay.naver.com/orderSheet/abc')
        self.assertEqual((m.name, m.basis), ('네이버쇼핑', '창 제목 주소 naver.com'))

    def test_title_word(self):
        """창 제목에 상품명과 쇼핑몰 이름이 같이 있어도 쇼핑몰 이름만"""
        m = mall.identify('[특가] 무선 이어폰 블루투스 5.3 - 쿠팡! - Chrome')
        self.assertEqual((m.name, m.basis), ('쿠팡', "창 제목 '쿠팡'"))
        m = mall.identify('주문/결제 : 네이버페이 - Chrome')
        self.assertEqual(m.name, '네이버쇼핑')

    def test_address_bar(self):
        """창 제목에 근거가 없으면 화면 맨 위(주소창) 글자의 도메인. 아래쪽 본문의 도메인은 주소창이 아님"""
        boxes = [box('www.oliveyoung.co.kr/store/goods/getGoodsDetail.do', 150, 10), box('상품 설명', 100, 300)]
        m = mall.identify('[올영단독] 라이브오랄스 화이트닝 - Chrome', boxes)
        self.assertEqual((m.name, m.basis), ('올리브영', '주소창 oliveyoung.co.kr'))
        body = [box('탭', 0, 0), box('공식 판매처 musinsa.com', 100, 400)]
        self.assertEqual(mall.identify('', body).name, mall.UNKNOWN_NAME)

    def test_address_bar_ocr_misreads(self):
        """실제 Windows OCR 주소창 오인식 (tests/images 캡처): 0/o, 1/l, i/l, '•', 빠진 마침표, 끼어든 공백, 글자 바뀜"""
        cases = {
            '수 수 0hveyoung•c0.kr/store/order/getOrderForm.d0?t-page=상품상세': '올리브영',
            '수 수 C !; 01iveyoung•c0.kr/store/g00ds/getG00dsDetail.d0': '올리브영',
            '주문/결제 - 11 번가 - Chrome 2; buy.11stc0.kr/pay/Orderlnf0Action.tmall': '11번가',
            '수 수 muslnsa.com/order/order-form I MUSINSA': '무신사',
            '수 수 ku rly.com/order/checkout 카테고리': '컬리',
            '수 수 zigzagkr. 51.000킨': '지그재그',
        }
        for text, name in cases.items():
            self.assertEqual(mall.identify('', [box(text, 100, 10)]).name, name, text)

    def test_fuzzy_needs_long_name(self):
        """짧은 도메인 이름은 비슷해도 알려진 쇼핑몰로 보지 않는다 (모르는 쇼핑몰 도메인)"""
        self.assertEqual(mall.identify('', [box('abc.com/order', 100, 10)]).name, 'abc.com')

    def test_page_site_hint(self):
        m = mall.identify('', [box('상품', 0, 0)], 'coupang')
        self.assertEqual((m.name, m.basis), ('쿠팡', '화면 글자의 쇼핑몰 이름'))

    def test_priority(self):
        """창 제목 도메인 > 창 제목 이름 > 주소창 > 화면 글자"""
        boxes = [box('coupang.com/vp/products/1', 150, 10)]
        self.assertEqual(mall.identify('musinsa.com/order - 쿠팡', boxes, 'zigzag').name, '무신사')
        self.assertEqual(mall.identify('11번가 주문', boxes, 'zigzag').name, '11번가')
        self.assertEqual(mall.identify('주문서', boxes, 'zigzag').name, '쿠팡')

    def test_unknown_mall_domain(self):
        m = mall.identify('shop.example.co.kr/order/123 - Chrome')
        self.assertEqual((m.name, m.code, m.basis), ('example.co.kr', '', '모르는 쇼핑몰, 창 제목 도메인'))
        m = mall.identify('주문서', [box('https://www.mystore.com/checkout', 150, 10)])
        self.assertEqual((m.name, m.basis), ('mystore.com', '모르는 쇼핑몰, 주소창 도메인'))

    def test_nothing_known(self):
        """상품명만 있으면 상품명을 쓰지 않고 '쇼핑몰'"""
        m = mall.identify('맨즈실렉터 오버핏 패딩 - Chrome', [box('맨즈실렉터 오버핏 패딩', 100, 200)])
        self.assertEqual((m.name, m.basis), ('쇼핑몰', '근거 없음'))

    def test_not_a_domain(self):
        self.assertEqual(mall.domains_in('가격 3.5만원, 버전 1.2.3, file.txt'), [])
        self.assertEqual(mall.base_domain('order.pay.naver.com'), 'naver.com')
        self.assertEqual(mall.base_domain('a.b.example.co.kr'), 'example.co.kr')

    def test_codes_match_server_sites(self):
        """서버 차단 사이트 코드와 같은 코드를 쓴다"""
        for code in ('naver', 'coupang', 'gmarket', '11st', 'zigzag', 'musinsa'):
            self.assertIn(code, config.MALLS)
            self.assertIn(code, config.SITE_HINTS)


class TestPopupMall(TkCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = DetectLog(self.dir, console=False)

    def tearDown(self):
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_auto_popup_shows_mall_from_title(self):
        """자동 감지: 창 제목으로 쇼핑몰 이름을 정해 팝업에 보이고, 로그에 근거. 서버에는 상품명(쿨다운 이름)"""
        fake = FakeServer(setting=(200, NOT_BLOCKING), check=(200, CHECKOUT_RESULT))
        client, _ = make(fake)
        client.connect()
        client.get_setting()
        app = main.App(client, self.host, settings=server_client.auto_settings(), log=self.log, clock=Clock())
        a = main.analyze_boxes(cs.COUPANG_CHECKOUT)
        a = dataclasses.replace(a, page=dataclasses.replace(a.page, item_name='브랜드명만 잡힌 상품'))
        app.analyze_frame = lambda img: dataclasses.replace(a)
        self.assertTrue(app.try_begin())
        self.assertTrue(app.run_auto(object(), 1, 'checkout.coupang.com/ssr/desktop/order/abc - Chrome'))
        self.assertTrue(self.pump(lambda: app.window is not None))
        self.assertEqual(app.window.view.item_name, '쿠팡')
        self.assertEqual(app.window.name_label['text'], '쿠팡')
        self.assertEqual([b for b in fake.calls if b['action'] == 'check'][-1]['item_name'], '브랜드명만 잡힌 상품')
        with open(os.path.join(self.dir, config.LOG_FILE), encoding='utf-8') as f:
            log = f.read()
        self.assertIn('쇼핑몰 이름 쿠팡 (창 제목 주소 coupang.com)', log)
        self.assertNotIn('ssr/desktop/order/abc', log)                       # 창 제목 원문은 남기지 않는다
        with quiet():
            app.window.destroy()
            self.pump(lambda: app.window is None)


if __name__ == '__main__':
    unittest.main()
