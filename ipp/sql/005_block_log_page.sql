-- 차단 기록에 페이지 종류 추가 (통계에서 상품 차단과 사이트 전체 차단을 나눈다)
-- bl_page: product(상품 상세), cart(장바구니), ''(사이트 홈 등 그 밖의 페이지, 또는 0.3.0 이전 확장 프로그램)
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_page` VARCHAR(10) NOT NULL DEFAULT '' AFTER `bl_url`;

-- 기존 기록 채우기. 3-2까지는 쿠팡 상품 상세와 장바구니에서만 기록했으므로 주소로 구분한다
-- 빈 값만 바꾸므로 다시 실행해도 된다
UPDATE `g5_ipp_block_log` SET `bl_page` = 'product'
 WHERE `bl_page` = '' AND (`bl_url` LIKE 'https://www.coupang.com/vp/products/%' OR `bl_url` LIKE 'https://zigzag.kr/catalog/products/%');
UPDATE `g5_ipp_block_log` SET `bl_page` = 'cart'
 WHERE `bl_page` = '' AND `bl_url` LIKE 'https://cart.coupang.com/cartView.pang%';
