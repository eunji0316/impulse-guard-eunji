"""페이지 정보(사이트, 상품명, 결제 화면)와 main의 서버 출력 테스트"""
import contextlib
import io
import unittest

import cache
from impulse_guard import main, ocr
from impulse_guard.detector import page
from impulse_guard.ocr import OcrBox
from impulse_guard.server_client import ApiResult

# 상품명은 OCR이 읽은 글자 그대로다 (OCR 오류 포함: 맨즈'실'렉터, 볼'룹' 등)
EXPECTED = {
    'coupang_product': ('coupang', '맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩'),
    'musinsa_product': ('musinsa', 'FLUFFY TOGGLE HOODED JACKET IVORY'),
    'zigzag_product':  ('zigzag', '[made]뒤디움기모델스'),
}


def box(text, x=0, y=0, w=100, h=20):
    return OcrBox(text=text, conf=0.9, bbox=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


class TestPage(unittest.TestCase):
    def test_images(self):
        for name in cache.names():
            with self.subTest(image=name):
                img, boxes, reread = cache.load(name)
                a = main.analyze_boxes(boxes, img, reread)
                if name == 'news_page':
                    self.assertIsNone(a.page)
                    self.assertEqual(page.find_site(ocr.full_text(boxes)), '')
                    continue
                self.assertEqual((a.page.site, a.page.item_name), EXPECTED[name])
                self.assertFalse(a.page.is_checkout)

    def test_site_hints(self):
        self.assertEqual(page.find_site('오늘의 특가 쿠팡 로켓배송'), 'coupang')
        self.assertEqual(page.find_site('MUSINSA BEAUTY'), 'musinsa')
        self.assertEqual(page.find_site('아무 사이트'), '')
        self.assertEqual(page.find_site('오늘의집 특가', {'ohou': ['오늘의집']}), 'ohou')   # 서버에서 받은 이름

    def test_checkout(self):
        self.assertEqual(page.find_checkout('주문서 작성 배송지 변경 결제하기')[0], True)
        self.assertEqual(page.find_checkout('바로구매 결제하기')[0], False)              # 1개뿐

    def test_item_name_skips_price_and_review(self):
        boxes = [box('나이키 에어맥스 운동화', 0, 0, 200, 24), box('리뷰 1,234개 만족해요', 0, 30, 150, 26),
                 box('58%', 0, 70, 30, 16), box('49,600원', 0, 90, 90, 30)]
        a = main.analyze_boxes(boxes)
        self.assertEqual(a.page.item_name, '나이키 에어맥스 운동화')


class FakeClient:
    def __init__(self, result, remain=0):
        self.result, self.remain, self.sent = result, remain, None

    def check(self, **kw):
        self.sent = kw
        return self.result

    def get_setting(self):
        return {}

    def block_remain(self):
        return self.remain


class TestSendAndPrint(unittest.TestCase):
    def run_main(self, result, remain=0):
        img, boxes, reread = cache.load('coupang_product')
        a = main.analyze_boxes(boxes, img, reread)
        client = FakeClient(result, remain)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.send_and_print(client, a)
        return client.sent, out.getvalue()

    def test_online(self):
        sent, out = self.run_main(ApiResult(True, {'is_blocking': True, 'is_impulse': 1, 'keyword': '특가',
                                                   'point': 496, 'point2': 992, 'bl_id': 7}), remain=3725)
        self.assertEqual(sent, {'site': 'coupang', 'item_name': '맨즈실렉터 대박 남자 오버핏 볼룹 겨울 패딩', 'price': 49600,
                                'orig_price': 119000, 'discount_rate': 58, 'is_checkout': False, 'page': 'product', 'log': True})
        self.assertIn('차단 시간입니다 (남은 시간 1시간 2분 5초)', out)
        self.assertIn("충동구매 감지: 예 (키워드 '특가')", out)
        self.assertIn('지금 포기하면 496P, 24시간 참으면 992P', out)
        self.assertIn('감지 기록 저장 (번호 7)', out)

    def test_offline(self):
        _, out = self.run_main(ApiResult(False, msg='응답 시간 초과', offline=True), remain=60)
        self.assertIn('연결 안 됨 (응답 시간 초과) - 감지만 했습니다', out)
        self.assertIn('(마지막으로 받은 설정 기준) 차단 시간입니다. 남은 시간 1분 0초', out)

    def test_not_shopping_sends_nothing(self):
        img, boxes, reread = cache.load('news_page')
        a = main.analyze_boxes(boxes, img, reread)
        client = FakeClient(None)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(main.send_and_print(client, a))
        self.assertIsNone(client.sent)


if __name__ == '__main__':
    unittest.main()
