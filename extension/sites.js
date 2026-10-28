/*
 * 사이트별 선택자 설정
 * 쇼핑 사이트 구조가 바뀌면 이 파일만 고친다. (새 사이트를 추가할 때는 manifest.json의 content_scripts.matches도 추가)
 *
 * - 선택자 배열은 앞에서부터 차례로 찾고, 처음 찾은 요소를 쓴다. 맞는 것을 앞에 둔다.
 * - name, image는 선택자로 못 찾으면 <meta property="og:title|og:image">를 대신 쓴다.
 * - buttons.texts: 선택자로 못 찾을 때를 대비해 버튼 글자로도 찾는다. 공백을 뺀 글자가 이 값으로 시작하면 결제 버튼으로 본다.
 * - 쿠팡 페이지에서 확인 전인 선택자는 '확인 필요'로 표시했다. 확인 방법은 README.md의 "선택자 찾기"를 본다.
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
          'h1.product-title',                // 확인 필요
          'h2.prod-buy-header__title'        // 확인 필요 (예전 구조)
        ],
        price: [
          '.final-price-amount',             // 확인 필요
          '.prod-coupon-price .total-price strong',
          '.prod-sale-price .total-price strong',
          '.total-price strong'              // 확인 필요 (예전 구조)
        ],
        image: [
          '.product-image img',              // 확인 필요
          'img.prod-image__detail'           // 확인 필요 (예전 구조)
        ],
        buttons: {
          selectors: [
            'button.prod-buy-btn'            // 확인 필요
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
  }
};
