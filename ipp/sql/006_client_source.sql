-- B-2: 기록과 쿨다운에 출처(어느 프로그램에서 왔는지) 구분 추가, 데스크톱 감지 정보 저장
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS, 빈 값만 채움)

-- 기록 (g5_ipp_block_log)
-- bl_client: extension(크롬 확장 프로그램), desktop(데스크톱 감지 프로그램)
-- 006 이전 기록은 모두 확장 프로그램에서 왔으므로 기본값 extension으로 채워진다
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_client`        VARCHAR(10) NOT NULL DEFAULT 'extension' AFTER `mb_id`,
  ADD COLUMN IF NOT EXISTS `bl_orig_price`    INT NOT NULL DEFAULT 0 AFTER `bl_price`,        -- 원가 (0 = 모름)
  ADD COLUMN IF NOT EXISTS `bl_discount_rate` TINYINT NOT NULL DEFAULT 0 AFTER `bl_orig_price`, -- 할인율 % (0 = 모름/할인 없음)
  ADD COLUMN IF NOT EXISTS `bl_is_checkout`   TINYINT NOT NULL DEFAULT 0 AFTER `bl_discount_rate`; -- 결제 화면 여부 (1: 결제 화면)
-- bl_event에 detect(데스크톱이 쇼핑 화면을 감지함)가 추가된다. 통계는 blocked만 세므로 영향 없음

-- 쿨다운 (g5_ipp_cooldown)
-- cd_client: web(웹 화면), extension, desktop, ''(006 이전. 웹과 확장 프로그램을 구분할 수 없음)
-- cd_source(manual 사전 등록 / detect 사후 감지)는 '어떻게 시작됐나'이고, cd_client는 '어디서 왔나'다
ALTER TABLE `g5_ipp_cooldown`
  ADD COLUMN IF NOT EXISTS `cd_client` VARCHAR(10) NOT NULL DEFAULT '' AFTER `cd_source`;
