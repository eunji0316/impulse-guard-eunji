-- 확장 프로그램 토큰을 해시로 저장
-- st_api_token: 이제 SHA-256 해시(64자). NULL이면 발급 안 됨 (UNIQUE 키는 NULL을 여러 개 허용)
ALTER TABLE `g5_ipp_setting`
  MODIFY `st_api_token` VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS `st_token_datetime`      DATETIME NULL AFTER `st_api_token`,      -- 발급 시각
  ADD COLUMN IF NOT EXISTS `st_token_used_datetime` DATETIME NULL AFTER `st_token_datetime`; -- 확장 프로그램 마지막 사용 시각

-- 기존 평문 토큰 무효화. 발급 시각이 없는 행만 바꾸므로 다시 실행해도 새로 발급한 토큰은 그대로 남는다
UPDATE `g5_ipp_setting` SET `st_api_token` = NULL WHERE `st_token_datetime` IS NULL;
