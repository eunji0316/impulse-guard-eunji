-- 쇼핑몰 전체 차단 설정 추가 (회원 설정 화면 맨 위 토글)
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS)

-- st_block_all: 차단 시간에 어떤 쇼핑 화면을 막을지
--   1 (기본) 쇼핑몰 전체 차단: 사이트 목록과 상관없이 모든 쇼핑 화면을 차단
--   0        켜 둔 사이트만 차단 (st_sites). 사이트를 모르는 데스크톱 감지는 차단 시간인지만 본다
-- 기존 회원도 기본값 1(ON)로 채워진다
ALTER TABLE `g5_ipp_setting`
  ADD COLUMN IF NOT EXISTS `st_block_all` TINYINT NOT NULL DEFAULT 1 AFTER `st_block_until`;
