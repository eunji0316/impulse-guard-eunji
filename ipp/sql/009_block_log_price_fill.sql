-- B-5: 데스크톱이 결제 화면의 금액을 나중에 읽어 감지 기록에 채운 시각
-- 다시 실행해도 된다 (ADD COLUMN IF NOT EXISTS)

-- 결제 화면 맨 위처럼 총 결제금액이 안 보이면 데스크톱은 금액 0으로 check(감지 기록)를 하고 '결제 금액 확인 중' 팝업을 띄운다.
-- 그 뒤 화면에서 금액을 읽으면 client.php의 amount action으로 bl_price를 채운다 (금액이 0인 기록만, 한 번만).
-- bl_price_filled_datetime: 나중에 채운 금액이면 채운 시각, NULL이면 check 때 받은 금액(또는 끝내 모름)
--   C단계 위험도 모델 학습에서 '처음부터 읽은 금액'과 '나중에 채운 금액'을 구분할 때 쓴다
ALTER TABLE `g5_ipp_block_log`
  ADD COLUMN IF NOT EXISTS `bl_price_filled_datetime` DATETIME NULL AFTER `bl_price`;
