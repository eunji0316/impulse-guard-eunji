-- C-2: 결제 금액을 나중에 채울 때(amount action) 다시 계산한 위험도와 처음 위험도를 구분해 남긴다
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS)

-- 데스크톱이 금액을 못 읽은 채 check를 하면 위험도는 '금액 모름'으로 계산된다. 나중에 amount로 금액을 채우면
-- 서버가 금액과 금액 비율만 바꿔 다시 계산하고 bl_risk, bl_risk_level, bl_risk_reasons, bl_risk_raw를 새 값으로 바꾼다.
-- bl_risk_updated_datetime: 다시 계산한 시각. NULL이면 bl_risk*는 check 때 값 그대로
-- bl_risk_first, bl_risk_level_first, bl_risk_reasons_first: 다시 계산하기 전(check 때) 값. 다시 계산하지 않았으면 NULL/빈 값
--   check 때의 원시 값은 지금 bl_risk_raw에서 amount와 amount_ratio를 null로 바꾼 것과 같다 (나머지는 그대로 둔다)
-- 팝업 결정이 다시 계산 전인지 후인지는 bl_decision_datetime과 bl_risk_updated_datetime을 비교해서 안다
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_risk_first`            DECIMAL(5,4) NULL AFTER `bl_risk_raw`,
  ADD COLUMN IF NOT EXISTS `bl_risk_level_first`      VARCHAR(4)  NOT NULL DEFAULT '' AFTER `bl_risk_first`,
  ADD COLUMN IF NOT EXISTS `bl_risk_reasons_first`    VARCHAR(255) NOT NULL DEFAULT '' AFTER `bl_risk_level_first`,
  ADD COLUMN IF NOT EXISTS `bl_risk_updated_datetime` DATETIME NULL AFTER `bl_risk_reasons_first`;
