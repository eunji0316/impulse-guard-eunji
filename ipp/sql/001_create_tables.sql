-- 연동 계좌 (mock)
CREATE TABLE IF NOT EXISTS `g5_ipp_account` (
  `ac_id`              INT NOT NULL AUTO_INCREMENT,
  `mb_id`              VARCHAR(20) NOT NULL,
  `ac_bank_name`       VARCHAR(50) NOT NULL DEFAULT '',
  `ac_number_masked`   VARCHAR(30) NOT NULL DEFAULT '',  -- 예: 123-****-5678
  `ac_fintech_num`     VARCHAR(50) NOT NULL DEFAULT '',  -- 오픈뱅킹 핀테크이용번호
  `ac_status`          VARCHAR(10) NOT NULL DEFAULT 'active', -- active, revoked
  `ac_datetime`        DATETIME NOT NULL,
  PRIMARY KEY (`ac_id`),
  KEY `idx_mb_id` (`mb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 계좌 거래 내역
CREATE TABLE IF NOT EXISTS `g5_ipp_transaction` (
  `tr_id`              INT NOT NULL AUTO_INCREMENT,
  `mb_id`              VARCHAR(20) NOT NULL,
  `ac_id`              INT NOT NULL,
  `tr_type`            VARCHAR(10) NOT NULL DEFAULT 'pay',  -- pay, cancel
  `tr_amount`          INT NOT NULL DEFAULT 0,
  `tr_merchant`        VARCHAR(100) NOT NULL DEFAULT '',
  `tr_category`        VARCHAR(30) NOT NULL DEFAULT '',
  `tr_datetime`        DATETIME NOT NULL,                  -- 실제 거래 시각
  `tr_is_impulse`      TINYINT NOT NULL DEFAULT 0,         -- 충동구매로 감지됐는지
  `tr_reg_datetime`    DATETIME NOT NULL,                  -- 우리 DB에 저장된 시각
  PRIMARY KEY (`tr_id`),
  KEY `idx_mb_datetime` (`mb_id`, `tr_datetime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 쿨다운 기록 (참은 기록 겸용)
CREATE TABLE IF NOT EXISTS `g5_ipp_cooldown` (
  `cd_id`              INT NOT NULL AUTO_INCREMENT,
  `mb_id`              VARCHAR(20) NOT NULL,
  `cd_source`          VARCHAR(10) NOT NULL DEFAULT 'manual', -- manual(사전 등록), detect(사후 감지)
  `tr_id`              INT NULL,                              -- detect일 때 연결된 거래
  `cd_item_name`       VARCHAR(255) NOT NULL DEFAULT '',
  `cd_amount`          INT NOT NULL DEFAULT 0,
  `cd_status`          VARCHAR(10) NOT NULL DEFAULT 'waiting',
                       -- waiting(진행중), gaveup(바로 포기), success(24시간 성공), failed(결제함)
  `cd_start_datetime`  DATETIME NOT NULL,
  `cd_expire_datetime` DATETIME NOT NULL,
  `cd_end_datetime`    DATETIME NULL,
  `cd_point`           INT NOT NULL DEFAULT 0,               -- 지급된 포인트 (화면 표시용)
  PRIMARY KEY (`cd_id`),
  KEY `idx_mb_status` (`mb_id`, `cd_status`),
  KEY `idx_expire` (`cd_status`, `cd_expire_datetime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;