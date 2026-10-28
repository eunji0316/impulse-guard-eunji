<?php
if (!defined('_GNUBOARD_')) exit;

/* ===== 기능 스위치 (false로 바꾸면 해당 기능이 꺼짐) ===== */
define('IPP_USE_BANK',       true);   // 계좌 연동
define('IPP_USE_COOLDOWN',   true);   // 쿨다운 타임머신
define('IPP_USE_CHARACTER',  false);  // 캐릭터 육성
define('IPP_USE_CHALLENGE',  false);  // 챌린지, 리더보드
define('IPP_USE_SIMULATION', false);  // 미래가치 시뮬레이션
define('IPP_USE_GIFTICON',   true);   // 기프티콘 리워드 교환

/* ===== 포인트 기준 ===== */
define('IPP_POINT_RATE',          0.01);  // 절약 금액의 1%
define('IPP_POINT_MIN',           10);
define('IPP_POINT_MAX',           500);
define('IPP_COOLDOWN_MULTIPLIER', 2);     // 쿨다운 성공 시 배수
define('IPP_DAILY_LIMIT',         1000);  // 하루 획득 상한

/* ===== 쿨다운 기준 ===== */
//define('IPP_COOLDOWN_HOURS', 0.02);   // 약 1분 (테스트용)
define('IPP_COOLDOWN_HOURS', 24); // 24시간 (실제 서비스용)

/* ===== 기프티콘 기준 ===== */
define('IPP_GIFTICON_EXPIRE_DAYS', 30);   // 쿠폰 유효기간(일)

/* ===== 충동구매 감지 기준 ===== */
define('IPP_DETECT_NIGHT_START', 23);     // 23시부터
define('IPP_DETECT_NIGHT_END',   4);      // 새벽 4시 전까지를 심야로 판단
define('IPP_DETECT_AMOUNT',      50000);  // 이 금액 이상이면 고액 결제
define('IPP_DETECT_CATEGORIES',  array('shopping', 'fashion', 'game', 'delivery'));

/* ===== 경로 ===== */
define('IPP_PATH', G5_PATH.'/ipp');
define('IPP_URL',  G5_URL.'/ipp');

/* ===== 테이블 이름 ===== */
$g5['ipp_account_table']     = G5_TABLE_PREFIX.'ipp_account';
$g5['ipp_transaction_table'] = G5_TABLE_PREFIX.'ipp_transaction';
$g5['ipp_cooldown_table']    = G5_TABLE_PREFIX.'ipp_cooldown';
$g5['ipp_reward_table']      = G5_TABLE_PREFIX.'ipp_reward';
$g5['ipp_coupon_table']      = G5_TABLE_PREFIX.'ipp_coupon';

/* ===== ipp/lib 안의 파일 자동 로드 ===== */
foreach (glob(IPP_PATH.'/lib/*.lib.php') as $ipp_lib) {
    include_once($ipp_lib);
}