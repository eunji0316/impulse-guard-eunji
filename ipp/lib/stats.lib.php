<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 통계 지표
 * - 기간은 서버 날짜 기준. "최근 N일"은 오늘을 포함해 (N-1)일 전 00:00부터
 * - 차단 지표는 bl_event = 'blocked'만 센다
 */

// 최근 N일의 시작 시각
function ipp_stats_since($days) {
    return date('Y-m-d', G5_SERVER_TIME - ($days - 1) * 86400).' 00:00:00';
}

// 오늘 차단된 상품 수: 상품 상세 페이지에서 막은 것만 (같은 URL은 1개로 셈)
function ipp_stats_today_blocked($mb_id) {
    global $g5;
    $row = sql_fetch(" SELECT COUNT(DISTINCT bl_url) AS cnt FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND bl_event = 'blocked'
                         AND bl_page = 'product'
                         AND bl_datetime >= '".G5_TIME_YMD." 00:00:00' ");
    return (int)$row['cnt'];
}

// 오늘 차단한 쇼핑 시도 횟수: 상품, 장바구니, 사이트 홈 등 차단 기록 전부 (같은 URL도 매번 셈)
function ipp_stats_today_attempts($mb_id) {
    global $g5;
    $row = sql_fetch(" SELECT COUNT(*) AS cnt FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND bl_event = 'blocked'
                         AND bl_datetime >= '".G5_TIME_YMD." 00:00:00' ");
    return (int)$row['cnt'];
}

// 최근 7일 예상 절약 금액: 쿨다운을 포기(gaveup)하거나 끝까지 참은(success) 금액의 합 (종료 시각 기준)
function ipp_stats_saved_7d($mb_id) {
    global $g5;
    $row = sql_fetch(" SELECT IFNULL(SUM(cd_amount), 0) AS total FROM {$g5['ipp_cooldown_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND cd_status IN ('gaveup', 'success')
                         AND cd_end_datetime >= '".ipp_stats_since(7)."' ");
    return (int)$row['total'];
}

// 최근 7일 일별 차단 횟수 (기록이 없는 날은 0). array('Y-m-d' => 횟수), 오래된 날부터
function ipp_stats_daily_7d($mb_id) {
    global $g5;
    $daily = array();
    for ($i = 6; $i >= 0; $i--) $daily[date('Y-m-d', G5_SERVER_TIME - $i * 86400)] = 0;

    $res = sql_query(" SELECT DATE(bl_datetime) AS d, COUNT(*) AS cnt FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND bl_event = 'blocked'
                         AND bl_datetime >= '".ipp_stats_since(7)."'
                       GROUP BY DATE(bl_datetime) ");
    while ($row = sql_fetch_array($res)) {
        if (isset($daily[$row['d']])) $daily[$row['d']] = (int)$row['cnt'];
    }
    return $daily;
}

// 최근 N일 사이트별 차단 횟수, 많은 순. array(array(site, name, cnt), ...)
function ipp_stats_by_site($mb_id, $days = 7) {
    global $g5;
    $list = array();
    $res  = sql_query(" SELECT bl_site, COUNT(*) AS cnt FROM {$g5['ipp_block_log_table']}
                        WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                          AND bl_event = 'blocked'
                          AND bl_datetime >= '".ipp_stats_since($days)."'
                        GROUP BY bl_site
                        ORDER BY cnt DESC, bl_site ");
    while ($row = sql_fetch_array($res)) {
        $name = isset(IPP_BLOCK_SITES[$row['bl_site']]) ? IPP_BLOCK_SITES[$row['bl_site']]['name'] : $row['bl_site'];
        $list[] = array('site' => $row['bl_site'], 'name' => $name, 'cnt' => (int)$row['cnt']);
    }
    return $list;
}

// 최근 N일 평균 차단 시간(초): 차단 화면이 뜬 뒤 페이지를 떠나기까지 머문 시간의 평균
// 체류 시간이 기록되지 않은(0) 건은 뺀다. 기록이 없으면 0
function ipp_stats_avg_block_sec($mb_id, $days = 7) {
    global $g5;
    $row = sql_fetch(" SELECT IFNULL(ROUND(AVG(bl_stay_sec)), 0) AS sec FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                         AND bl_event = 'blocked'
                         AND bl_stay_sec > 0
                         AND bl_datetime >= '".ipp_stats_since($days)."' ");
    return (int)$row['sec'];
}

// 초를 "1분 30초" 형식으로
function ipp_format_sec($sec) {
    $sec = (int)$sec;
    if ($sec < 60) return $sec.'초';
    $text = floor($sec / 60).'분';
    if ($sec % 60) $text .= ' '.($sec % 60).'초';
    return $text;
}
