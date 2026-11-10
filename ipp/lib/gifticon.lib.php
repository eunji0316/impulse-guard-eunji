<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 기프티콘 발급 API
 * 실제 기프티콘 API로 전환할 때는 ipp_gifticon_issue() 내부만 교체한다.
 * 반환 형식은 그대로 유지해야 reward.lib.php를 고치지 않아도 된다.
 */

// 기프티콘 발급 (mock: 임의 쿠폰번호 생성)
// 반환: ok, tr_id(API 거래번호), pin(쿠폰번호), barcode_url, expire_date(Y-m-d), msg
function ipp_gifticon_issue($order_no, $goods_code, $mb_id) {
    $pin = sprintf('%04d-%04d-%04d', mt_rand(0, 9999), mt_rand(0, 9999), mt_rand(0, 9999));

    return array(
        'ok'          => true,
        'tr_id'       => 'MOCK'.date('YmdHis').mt_rand(100, 999),
        'pin'         => $pin,
        'barcode_url' => '',
        'expire_date' => date('Y-m-d', strtotime('+'.(IPP_GIFTICON_EXPIRE_DAYS - 1).' days', G5_SERVER_TIME)),
        'msg'         => ''
    );
}
