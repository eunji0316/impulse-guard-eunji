import time #시간 관련 기능 제공하는 모듈
import re #정규표현식 관련 기능 제공하는 모듈
import keyboard #키보드 입력 관련 기능 제공하는 모듈
import mss #화면 캡쳐 모듈
import numpy as np #numpy 모듈
import easyocr #OCR 모듈

print("화면 분석을 위한 OCR 모델을 로딩 중입니다. 최초 실행 시 약간의 시간이 걸립니다")
reader = easyocr.Reader(['ko', 'en'], gpu=False) # 한국어와 영어 인식 설정, gpu 가속 사용하지 않고 CPU 모드로 동작함, 처음 실행 시 약간의 딜레이 발생

print("\n" + "="*50)
print("쇼핑몰 감지 프로그램이 실행되었습니다!")
print("웹서핑 중 쇼핑몰 화면에서 [F4] 키를 누르면 즉시 분석합니다.")
print("종료하려면 콘솔 창에서 [Ctrl + C]를 누르세요.")
print("="*50 + "\n")

def check_shopping_mall():
    print("\n[F4 감지] 화면 캡처 및 분석을 시작합니다...")
   
    try:
        # 1. 화면 캡처 (mss 라이브러리로 메인 모니터 캡처)
        with mss.mss() as sct:
            # monitors[1]은 주 모니터를 의미합니다.
            screenshot = sct.grab(sct.monitors[1])
            img = np.array(screenshot)
           
        # 2. 알파 채널(투명도) 제거 및 RGB 변환
        img_rgb = img[:, :, :3]
       
        # 3. OCR을 통해 화면 내 텍스트 추출
        results = reader.readtext(img_rgb)
        extracted_text = " ".join([text[1] for text in results])
       
        # 4. 쇼핑몰 특징 분석 (키워드 및 가격 패턴 매칭)
        shopping_keywords = [
            '장바구니', '구매하기', '바로구매', '결제하기', '주문하기',
            '옵션선택', '수량', '배송비', '상품상세', '찜하기', '쿠폰'
        ]
       
        found_keywords = [kw for kw in shopping_keywords if kw in extracted_text]
       
        # 가격 패턴 검출 (예: 15,000원, ₩35,000 등)
        price_patterns = re.findall(r'[\d,]+원|₩[\d,]+', extracted_text)
       
        # 5. 판정 로직 (키워드가 2개 이상이거나 가격 패턴이 존재하면 쇼핑몰로 판정)
        is_mall = False
        if len(found_keywords) >= 2 or len(price_patterns) > 0:
            is_mall = True
           
        # 6. 결과 출력
        print("-" * 40)
        if is_mall:
            print("⭕ [판정 결과] 쇼핑몰 사이트입니다!")
            print(f"  - 감지된 키워드: {found_keywords}")
            print(f"  - 감지된 가격 정보: {price_patterns[:3]}")
        else:
            print("❌ [판정 결과] 쇼핑몰이 아닙니다.")
            print("  - 쇼핑몰 특유의 구매 버튼이나 가격 정보가 충분히 발견되지 않았습니다.")
        print("-" * 40)
       
    except Exception as e:
        print(f"!!! 분석 중 오류가 발생했습니다: {e}")

# F4 키 단축키 등록
keyboard.add_hotkey('f4', check_shopping_mall)

# 프로그램이 종료되지 않도록 대기
try:
    keyboard.wait()
except KeyboardInterrupt:
    print("\n프로그램을 종료합니다.")