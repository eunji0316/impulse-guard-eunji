/*
 * 사이트별 선택자 설정
 * 쇼핑 사이트 구조가 바뀌면 이 파일만 고친다. (새 사이트를 추가할 때는 manifest.json의 content_scripts.matches도 추가)
 *
 * - hosts: 이 사이트의 도메인. 차단 시간에는 페이지 종류와 상관없이 이 도메인 전체에 차단 화면을 띄운다.
 *   (manifest.json의 matches도 도메인 전체 "https://<host>/*"로 등록한다)
 * - pages: 상품 정보 추출과 결제 버튼 가로채기를 할 페이지. 여기 없는 페이지에서는 차단 화면만 띄운다.
 * - 선택자 배열은 앞에서부터 차례로 찾고, 처음 찾은 요소를 쓴다. 맞는 것을 앞에 둔다.
 * - name, image는 선택자로 못 찾으면 <meta property="og:title|og:image">를 대신 쓴다.
 *   price는 <meta property="product:price:amount">가 있으면 대신 쓴다.
 * - buttons.texts: 선택자로 못 찾을 때를 대비해 버튼 글자로도 찾는다. 공백을 뺀 글자가 이 값으로 시작하면 결제 버튼으로 본다.
 * - 실제 페이지에서 확인 전인 선택자는 '확인 필요'로 표시했다. 확인 방법은 README.md의 "선택자 찾기"를 본다.
 */

const IPP_SITES = {
  coupang: {
    hosts: ['www.coupang.com', 'cart.coupang.com'],   // IPP_BLOCK_SITES의 코드와 같은 키를 쓴다
    pages: {
      // 상품 상세: https://www.coupang.com/vp/products/1234567?itemId=...
      product: {
        path: /^\/vp\/products\/\d+/,
        logVisit: true,          // 방문과 체류 시간을 기록
        urlParams: [],           // 기록할 URL에 남길 쿼리 (나머지 검색어/추적값은 버림)
        name: [
          'h1.product-title',                // 2026-10-28 확인
          'h2.prod-buy-header__title'        // 예전 구조
        ],
        price: [
          // 2026-10-28 확인: 화면에 크게 보이는 빨간 가격 (예: 로켓와우회원가 53,530)
          // <div class="twc-text-red-700 ..."><span class="twc-text-[24px] ...">53,530</span>
          // Tailwind 클래스뿐이라 색과 글자 크기를 같이 걸어 할인율 같은 다른 빨간 글자를 피한다. [ ]는 \\[ \\]로 이스케이프
          '.twc-text-red-700 > .twc-text-\\[24px\\]',
          '.final-price-amount',             // 확인 필요
          '.prod-coupon-price .total-price strong',
          '.prod-sale-price .total-price strong',
          '.total-price strong'              // 예전 구조
        ],
        image: [
          '.product-image img',              // 2026-10-28 확인
          'img.prod-image__detail'           // 예전 구조
        ],
        buttons: {
          selectors: [
            'button.prod-buy-btn'            // 2026-10-28 확인
          ],
          texts: ['바로구매', '구매하기']
        }
      },
      // 장바구니: https://cart.coupang.com/cartView.pang
      cart: {
        path: /^\/cartView\.pang/,
        logVisit: false,
        urlParams: [],
        multiName: true,          // 상품이 여러 개면 "첫 상품명 외 N건"
        name: [
          '.cart-deal-item .product-name'    // 확인 필요
        ],
        price: [
          '#totalPrice',                     // 확인 필요 (전체 결제 예정 금액)
          '.total-order-price'               // 확인 필요
        ],
        image: [
          '.cart-deal-item img'              // 확인 필요
        ],
        buttons: {
          selectors: [
            '#btnPay'                        // 확인 필요
          ],
          texts: ['구매하기', '주문하기']
        }
      }
    }
  },

  // 지그재그는 페이지를 새로 불러오지 않고 주소만 바꾸는 SPA다 (content.js가 주소 변경을 따로 감지한다)
  // class 이름이 배포마다 바뀌는 구조라 선택자보다 og 메타와 버튼 글자 대체값에 기대는 편이다
  zigzag: {
    hosts: ['zigzag.kr', 'www.zigzag.kr'],
    pages: {
      // 상품 상세: https://zigzag.kr/catalog/products/123456789
      product: {
        path: /^\/catalog\/products\/\d+/,
        logVisit: true,
        urlParams: [],
        name: [],                            // 확인 필요 (지금은 og:title로 읽음)
        price: [
          '[class*="FinalPrice"]',           // 확인 필요
          '[class*="final-price"]'           // 확인 필요
        ],
        image: [
          'img[alt*="상품"]'                 // 확인 필요
        ],
        buttons: {
          selectors: [],
          texts: ['바로구매', '구매하기']
        }
      },
      // 장바구니: https://zigzag.kr/cart
      cart: {
        path: /^\/cart/,                     // 확인 필요
        logVisit: false,
        urlParams: [],
        multiName: true,
        name: [
          '[class*="product-name"]'          // 확인 필요
        ],
        price: [
          '[class*="total-price"]'           // 확인 필요
        ],
        image: [
          '[class*="product"] img'           // 확인 필요
        ],
        buttons: {
          selectors: [],
          texts: ['구매하기', '주문하기']
        }
      }
    }
  }
};
