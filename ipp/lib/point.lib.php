<?php
if (!defined('_GNUBOARD_')) exit;

// 절약 금액으로 포인트 계산
function ipp_calc_point($amount, $multiplier = 1) {
    $point = floor($amount * IPP_POINT_RATE);
    $point = max(IPP_POINT_MIN, min(IPP_POINT_MAX, $point));
    return (int)($point * $multiplier);
}

// 오늘 받은 절약 포인트 합계 (기프티콘 교환 환불은 획득이 아니므로 제외)
function ipp_today_point($mb_id) {
    global $g5;
    $row = sql_fetch(" SELECT IFNULL(SUM(po_point), 0) AS total
                       FROM {$g5['point_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND po_rel_table LIKE 'ipp%'
                         AND po_rel_table <> 'ipp_reward'
                         AND po_point > 0
                         AND po_datetime >= '".G5_TIME_YMD." 00:00:00' ");
    return (int)$row['total'];
}

// 모든 기능은 이 함수로만 포인트를 지급
function ipp_give_point($mb_id, $point, $content, $rel_table, $rel_id) {
    $remain = IPP_DAILY_LIMIT - ipp_today_point($mb_id);
    if ($remain <= 0) return 0;

    $point = min($point, $remain);
    $result = insert_point($mb_id, $point, $content, $rel_table, $rel_id, 'ipp');
    return ($result == 1) ? $point : 0;
}