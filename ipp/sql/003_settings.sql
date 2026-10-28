-- 회원별 설정 (회원당 1행, 처음 조회할 때 기본값으로 생성)
CREATE TABLE IF NOT EXISTS `g5_ipp_setting` (
  `mb_id`              VARCHAR(20) NOT NULL,
  `st_block_start`     DATETIME NULL,                       -- 이번 차단을 시작한 시각
  `st_block_until`     DATETIME NULL,                       -- 차단 종료 시각 (NULL이거나 지났으면 차단 안 함)
  `st_sites`           TEXT NOT NULL,                       -- 차단할 사이트 코드 JSON 배열, 예: ["coupang","musinsa"]
  `st_keywords`        TEXT NOT NULL,                       -- 추가 차단 키워드 JSON 배열, 예: ["세일","특가"]
  `st_risk_alert`      TINYINT NOT NULL DEFAULT 1,          -- 충동구매 위험도 알림 (1: 켬, 0: 끔)
  `st_api_token`       VARCHAR(64) NOT NULL,                -- 크롬 확장 프로그램 인증 토큰
  `st_datetime`        DATETIME NOT NULL,
  `st_update_datetime` DATETIME NOT NULL,
  PRIMARY KEY (`mb_id`),
  UNIQUE KEY `uk_api_token` (`st_api_token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 쇼핑 사이트 방문/차단 기록 (크롬 확장 프로그램이 보냄)
CREATE TABLE IF NOT EXISTS `g5_ipp_block_log` (
  `bl_id`              INT NOT NULL AUTO_INCREMENT,
  `mb_id`              VARCHAR(20) NOT NULL,
  `bl_site`            VARCHAR(20) NOT NULL DEFAULT '',     -- IPP_BLOCK_SITES의 코드
  `bl_url`             VARCHAR(500) NOT NULL DEFAULT '',
  `bl_item_name`       VARCHAR(255) NOT NULL DEFAULT '',
  `bl_price`           INT NOT NULL DEFAULT 0,
  `bl_event`           VARCHAR(10) NOT NULL DEFAULT 'visit',
                       -- visit(방문), blocked(차단 화면 표시), checkout(결제 단계 진입)
  `bl_stay_sec`        INT NOT NULL DEFAULT 0,              -- 체류 시간(초)
  `bl_datetime`        DATETIME NOT NULL,
  PRIMARY KEY (`bl_id`),
  KEY `idx_mb_event_datetime` (`mb_id`, `bl_event`, `bl_datetime`),
  KEY `idx_mb_datetime` (`mb_id`, `bl_datetime`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
