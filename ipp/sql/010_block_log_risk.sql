-- C-2: 결제 화면 감지 기록에 충동구매 위험도 예측을 남긴다
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS)

-- 서버 check가 결제 화면(is_checkout)에서 위험도 모델(ipp/model/risk_model.json)로 계산한 값.
-- 나중에 팝업 결정(bl_decision)과 짝지어 실제 데이터로 다시 평가·학습할 때 쓴다 (ai/risk/README.md)
-- bl_risk:         위험도 0~1. NULL이면 계산하지 않음 (결제 화면이 아님, 모델 꺼짐/실패 → 규칙 이유만)
-- bl_risk_level:   low / mid / high (팝업 문구 단계. 팝업이 결정에 준 영향을 나중에 따로 보려고 남긴다)
-- bl_risk_model:   모델 버전 (risk_model.json의 version)
-- bl_risk_reasons: 이유 group 코드를 큰 순서로 쉼표로 이은 것 (낮음이라 화면에 안 보인 이유도 남긴다)
-- bl_risk_raw:     예측에 쓴 원시 값 JSON. 숫자와 null만 (상품명, 주소, OCR 원문 없음)
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_risk`         DECIMAL(5,4) NULL AFTER `bl_is_checkout`,
  ADD COLUMN IF NOT EXISTS `bl_risk_level`   VARCHAR(4)  NOT NULL DEFAULT '' AFTER `bl_risk`,
  ADD COLUMN IF NOT EXISTS `bl_risk_model`   VARCHAR(40) NOT NULL DEFAULT '' AFTER `bl_risk_level`,
  ADD COLUMN IF NOT EXISTS `bl_risk_reasons` VARCHAR(255) NOT NULL DEFAULT '' AFTER `bl_risk_model`,
  ADD COLUMN IF NOT EXISTS `bl_risk_raw`     TEXT NULL AFTER `bl_risk_reasons`;

-- 과거 기록 특성(최근 결제 빈도, 금액 비율, 과거 선택)을 회원별 기간으로 찾는다
ALTER TABLE `g5_ipp_block_log`
  ADD INDEX IF NOT EXISTS `idx_mb_checkout_dt` (`mb_id`, `bl_is_checkout`, `bl_datetime`);
