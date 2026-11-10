-- B-3: 데스크톱 차단 팝업에서 회원이 고른 결정을 감지 기록에 남긴다
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS)

-- bl_decision: 감지 기록(detect)에 대해 팝업에서 무엇을 골랐나
--   ''      아직 결정 없음 (팝업을 띄우지 않았거나, 006 이전 기록)
--   hold    조금 더 생각하기 (24시간 담아두기, 쿨다운 시작)
--   giveup  안 살래요 (쿨다운을 바로 포기로 끝내고 포인트 지급. 가격을 모르면 기록만)
--   buy     그래도 구매할래요 (기록만)
--   close   창의 X로 닫음 (기록만, 포인트 없음)
-- bl_cd_id: hold/giveup으로 만든 쿨다운 번호 (g5_ipp_cooldown.cd_id, 없으면 0)
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_decision`          VARCHAR(10) NOT NULL DEFAULT '' AFTER `bl_event`,
  ADD COLUMN IF NOT EXISTS `bl_decision_datetime` DATETIME NULL AFTER `bl_decision`,
  ADD COLUMN IF NOT EXISTS `bl_cd_id`             INT NOT NULL DEFAULT 0 AFTER `bl_decision_datetime`;

-- bl_event: 데스크톱이 차단 시간에 쇼핑 화면을 감지하면 detect가 아니라 blocked로 저장한다 (B-3부터)
