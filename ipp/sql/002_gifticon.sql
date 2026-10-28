-- 기프티콘 리워드 상품 (교환 가능한 상품 목록)
CREATE TABLE IF NOT EXISTS `g5_ipp_reward` (
  `rw_id`              INT NOT NULL AUTO_INCREMENT,
  `rw_name`            VARCHAR(255) NOT NULL DEFAULT '',
  `rw_brand`           VARCHAR(50) NOT NULL DEFAULT '',     -- 예: 스타벅스, CU
  `rw_image`           VARCHAR(255) NOT NULL DEFAULT '',
  `rw_point`           INT NOT NULL DEFAULT 0,              -- 교환에 필요한 포인트
  `rw_goods_code`      VARCHAR(50) NOT NULL DEFAULT '',     -- 기프티콘 API 상품 코드 (mock)
  `rw_stock`           INT NOT NULL DEFAULT -1,             -- -1이면 재고 무제한
  `rw_use`             TINYINT NOT NULL DEFAULT 1,          -- 1: 노출, 0: 숨김
  `rw_order`           INT NOT NULL DEFAULT 0,              -- 정렬 순서 (작을수록 앞)
  `rw_datetime`        DATETIME NOT NULL,
  PRIMARY KEY (`rw_id`),
  KEY `idx_use_order` (`rw_use`, `rw_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 발급된 쿠폰 (회원이 포인트로 교환한 기프티콘)
CREATE TABLE IF NOT EXISTS `g5_ipp_coupon` (
  `cp_id`              INT NOT NULL AUTO_INCREMENT,
  `mb_id`              VARCHAR(20) NOT NULL,
  `rw_id`              INT NOT NULL,
  `cp_name`            VARCHAR(255) NOT NULL DEFAULT '',    -- 교환 당시 상품명 (상품이 바뀌어도 유지)
  `cp_point`           INT NOT NULL DEFAULT 0,              -- 차감된 포인트
  `cp_order_no`        VARCHAR(50) NOT NULL,                -- 우리가 만든 주문번호 (중복 발급 방지)
  `cp_tr_id`           VARCHAR(50) NOT NULL DEFAULT '',     -- 기프티콘 API 거래번호
  `cp_pin`             VARCHAR(100) NOT NULL DEFAULT '',    -- 쿠폰 번호
  `cp_barcode_url`     VARCHAR(255) NOT NULL DEFAULT '',
  `cp_status`          VARCHAR(10) NOT NULL DEFAULT 'pending',
                       -- pending(발급 요청중), issued(발급 완료), used(사용), expired(만료),
                       -- failed(발급 실패, 포인트 환불), cancelled(취소, 포인트 환불)
  `cp_expire_date`     DATE NULL,                           -- 쿠폰 유효기간
  `cp_datetime`        DATETIME NOT NULL,                   -- 교환 신청 시각
  `cp_issue_datetime`  DATETIME NULL,                       -- 발급 완료 시각
  `cp_end_datetime`    DATETIME NULL,                       -- 사용/만료/실패/취소 처리 시각
  PRIMARY KEY (`cp_id`),
  UNIQUE KEY `uk_order_no` (`cp_order_no`),
  KEY `idx_mb_status` (`mb_id`, `cp_status`),
  KEY `idx_expire` (`cp_status`, `cp_expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 시연용 리워드 (재고 -1: 무제한)
INSERT INTO `g5_ipp_reward` (`rw_name`, `rw_brand`, `rw_image`, `rw_point`, `rw_goods_code`, `rw_stock`, `rw_use`, `rw_order`, `rw_datetime`) VALUES
('바나나맛 우유',              'CU',         '', 1500,  'MOCK-001', -1, 1, 1, NOW()),
('카페 아메리카노 T',          '스타벅스',   '', 3000,  'MOCK-002', -1, 1, 2, NOW()),
('문화상품권 5,000원',         '컬쳐랜드',   '', 5000,  'MOCK-003', -1, 1, 3, NOW()),
('파인트 아이스크림',          '배스킨라빈스', '', 9000,  'MOCK-004',  3, 1, 4, NOW()),
('황금올리브치킨 + 콜라 1.25L', 'BBQ',        '', 18000, 'MOCK-005', -1, 1, 5, NOW());
