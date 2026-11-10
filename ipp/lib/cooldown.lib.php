<?php
if (!defined('_GNUBOARD_')) exit;

// 쿨다운 시작 (상태: waiting)
// $client: 어디서 만들었나. web(웹 화면), extension(크롬 확장 프로그램), desktop(데스크톱 감지 프로그램)
function ipp_cooldown_create($mb_id, $item_name, $amount, $client = 'web') {
    global $g5;
    $now    = G5_TIME_YMDHIS;
    $expire = date('Y-m-d H:i:s', G5_SERVER_TIME + (int)(IPP_COOLDOWN_HOURS * 3600));
    if (!in_array($client, array('web', 'extension', 'desktop'))) $client = 'web';

    sql_query(" INSERT INTO {$g5['ipp_cooldown_table']}
                SET mb_id              = '".sql_real_escape_string($mb_id)."',
                    cd_source          = 'manual',
                    cd_client          = '{$client}',
                    cd_item_name       = '".sql_real_escape_string($item_name)."',
                    cd_amount          = '".(int)$amount."',
                    cd_status          = 'waiting',
                    cd_start_datetime  = '{$now}',
                    cd_expire_datetime = '{$expire}' ");
    return sql_insert_id();
}

function ipp_cooldown_get($cd_id) {
    global $g5;
    return sql_fetch(" SELECT * FROM {$g5['ipp_cooldown_table']} WHERE cd_id = '".(int)$cd_id."' ");
}

// 쿨다운 종료 처리 + 포인트 지급. 지급된 포인트 반환
function ipp_cooldown_finish($cd, $status) {
    global $g5;
    if ($cd['cd_status'] !== 'waiting') return 0;

    $point = 0;
    if ($status === 'gaveup')  $point = ipp_calc_point($cd['cd_amount']);
    if ($status === 'success') $point = ipp_calc_point($cd['cd_amount'], IPP_COOLDOWN_MULTIPLIER);

    if ($point > 0) {
        $label = ($status === 'success') ? '쿨다운 성공' : '충동구매 포기';
        $point = ipp_give_point($cd['mb_id'], $point, $label.': '.$cd['cd_item_name'], 'ipp_cooldown', $cd['cd_id']);
    }

    sql_query(" UPDATE {$g5['ipp_cooldown_table']}
                SET cd_status       = '".sql_real_escape_string($status)."',
                    cd_end_datetime = '".G5_TIME_YMDHIS."',
                    cd_point        = '".(int)$point."'
                WHERE cd_id = '".(int)$cd['cd_id']."' AND cd_status = 'waiting' ");
    return $point;
}

// 만료된 쿨다운 정산: 기간 내 같은 가맹점 결제가 있으면 실패, 없으면 성공
function ipp_cooldown_settle($mb_id) {
    global $g5;
    $mb  = sql_real_escape_string($mb_id);
    $res = sql_query(" SELECT * FROM {$g5['ipp_cooldown_table']}
                       WHERE mb_id = '{$mb}' AND cd_status = 'waiting'
                         AND cd_expire_datetime <= '".G5_TIME_YMDHIS."' ");

    while ($cd = sql_fetch_array($res)) {
        $row = sql_fetch(" SELECT COUNT(*) AS cnt FROM {$g5['ipp_transaction_table']}
                           WHERE mb_id = '{$mb}' AND tr_type = 'pay'
                             AND tr_merchant = '".sql_real_escape_string($cd['cd_item_name'])."'
                             AND tr_datetime BETWEEN '{$cd['cd_start_datetime']}' AND '{$cd['cd_expire_datetime']}' ");
        ipp_cooldown_finish($cd, ($row['cnt'] > 0) ? 'failed' : 'success');
    }
}

function ipp_cooldown_list($mb_id, $limit = 30) {
    global $g5;
    $list = array();
    $res  = sql_query(" SELECT * FROM {$g5['ipp_cooldown_table']}
                        WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                        ORDER BY cd_id DESC LIMIT ".(int)$limit);
    while ($row = sql_fetch_array($res)) $list[] = $row;
    return $list;
}