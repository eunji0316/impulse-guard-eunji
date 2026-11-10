<?php
if (!defined('_GNUBOARD_')) exit;

// 교환 가능한 리워드 목록
function ipp_reward_list() {
    global $g5;
    $list = array();
    $res  = sql_query(" SELECT * FROM {$g5['ipp_reward_table']}
                        WHERE rw_use = 1
                        ORDER BY rw_order, rw_id ");
    while ($row = sql_fetch_array($res)) $list[] = $row;
    return $list;
}

function ipp_reward_get($rw_id) {
    global $g5;
    return sql_fetch(" SELECT * FROM {$g5['ipp_reward_table']} WHERE rw_id = '".(int)$rw_id."' ");
}

// 직전 UPDATE로 바뀐 행 수
function ipp_affected_rows() {
    global $g5;
    return G5_MYSQLI_USE ? mysqli_affected_rows($g5['connect_db']) : mysql_affected_rows($g5['connect_db']);
}

// 포인트로 기프티콘 교환. 결과 배열(ok, cp_id, msg) 반환
// 같은 회원의 교환은 named lock으로 한 번에 하나씩만 처리해 잔액 검사와 차감 사이에 끼어들지 못하게 한다.
function ipp_reward_exchange($mb_id, $rw_id, $order_no) {
    $lock = 'ipp_reward_'.md5($mb_id);
    $row  = sql_fetch(" SELECT GET_LOCK('{$lock}', 5) AS got ");
    if (!$row['got']) return array('ok' => false, 'msg' => '다른 교환을 처리 중입니다. 잠시 후 다시 시도해 주세요.');

    $result = ipp_reward_exchange_locked($mb_id, $rw_id, $order_no);

    sql_query(" DO RELEASE_LOCK('{$lock}') ");
    return $result;
}

// 락을 잡은 상태에서만 호출한다
function ipp_reward_exchange_locked($mb_id, $rw_id, $order_no) {
    global $g5;
    $mb    = sql_real_escape_string($mb_id);
    $order = sql_real_escape_string($order_no);
    $now   = G5_TIME_YMDHIS;

    // 같은 주문번호가 이미 있으면 중복 클릭
    $dup = sql_fetch(" SELECT cp_id FROM {$g5['ipp_coupon_table']} WHERE cp_order_no = '{$order}' ");
    if ($dup) return array('ok' => false, 'msg' => '이미 처리된 요청입니다.');

    $rw = ipp_reward_get($rw_id);
    if (!$rw || !$rw['rw_use']) return array('ok' => false, 'msg' => '교환할 수 없는 상품입니다.');

    $point = (int)$rw['rw_point'];
    if (get_point_sum($mb_id) < $point) return array('ok' => false, 'msg' => '포인트가 부족합니다.');

    // 재고 차감. -1은 무제한이라 UPDATE하지 않는다
    // (예전에는 무제한도 rw_stock = -1로 다시 썼는데, 값이 그대로면 바뀐 행 수가 0이라 품절로 처리되는 버그가 있었다)
    if ((int)$rw['rw_stock'] !== -1) {
        sql_query(" UPDATE {$g5['ipp_reward_table']}
                    SET rw_stock = rw_stock - 1
                    WHERE rw_id = '{$rw['rw_id']}' AND rw_use = 1 AND rw_stock > 0 ");
        if (ipp_affected_rows() < 1) return array('ok' => false, 'msg' => '품절된 상품입니다.');
    }

    sql_query(" INSERT INTO {$g5['ipp_coupon_table']}
                SET mb_id       = '{$mb}',
                    rw_id       = '{$rw['rw_id']}',
                    cp_name     = '".sql_real_escape_string($rw['rw_name'])."',
                    cp_point    = '{$point}',
                    cp_order_no = '{$order}',
                    cp_status   = 'pending',
                    cp_datetime = '{$now}' ");
    $cp_id = sql_insert_id();

    // 포인트 차감 (음수라 ipp_today_point 합계에는 들어가지 않는다)
    if (insert_point($mb_id, -$point, '기프티콘 교환: '.$rw['rw_name'], 'ipp_reward', $cp_id, 'exchange') != 1) {
        ipp_reward_fail($cp_id, $rw['rw_id']);
        return array('ok' => false, 'msg' => '포인트 차감에 실패했습니다.');
    }

    $res = ipp_gifticon_issue($order_no, $rw['rw_goods_code'], $mb_id);

    if (!$res['ok']) {
        insert_point($mb_id, $point, '기프티콘 발급 실패 환불: '.$rw['rw_name'], 'ipp_reward', $cp_id, 'refund');
        ipp_reward_fail($cp_id, $rw['rw_id']);
        return array('ok' => false, 'msg' => '기프티콘 발급에 실패해 포인트를 돌려드렸습니다. '.$res['msg']);
    }

    sql_query(" UPDATE {$g5['ipp_coupon_table']}
                SET cp_status         = 'issued',
                    cp_tr_id          = '".sql_real_escape_string($res['tr_id'])."',
                    cp_pin            = '".sql_real_escape_string($res['pin'])."',
                    cp_barcode_url    = '".sql_real_escape_string($res['barcode_url'])."',
                    cp_expire_date    = '".sql_real_escape_string($res['expire_date'])."',
                    cp_issue_datetime = '{$now}'
                WHERE cp_id = '{$cp_id}' ");

    return array('ok' => true, 'cp_id' => $cp_id);
}

// 발급 실패 처리: 쿠폰 failed, 재고 복구
function ipp_reward_fail($cp_id, $rw_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_coupon_table']}
                SET cp_status = 'failed', cp_end_datetime = '".G5_TIME_YMDHIS."'
                WHERE cp_id = '".(int)$cp_id."' ");
    sql_query(" UPDATE {$g5['ipp_reward_table']}
                SET rw_stock = rw_stock + 1
                WHERE rw_id = '".(int)$rw_id."' AND rw_stock <> -1 ");
}

// 유효기간이 지난 쿠폰을 만료 처리
function ipp_coupon_settle($mb_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_coupon_table']}
                SET cp_status = 'expired', cp_end_datetime = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                  AND cp_status = 'issued'
                  AND cp_expire_date < '".G5_TIME_YMD."' ");
}

// 사용 완료 처리 (시연용. 실제 API에서는 사용 여부를 조회해 반영)
function ipp_coupon_use($mb_id, $cp_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_coupon_table']}
                SET cp_status = 'used', cp_end_datetime = '".G5_TIME_YMDHIS."'
                WHERE cp_id = '".(int)$cp_id."'
                  AND mb_id = '".sql_real_escape_string($mb_id)."'
                  AND cp_status = 'issued' ");
    return ipp_affected_rows() > 0;
}

function ipp_coupon_list($mb_id, $limit = 50) {
    global $g5;
    $list = array();
    $res  = sql_query(" SELECT * FROM {$g5['ipp_coupon_table']}
                        WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                          AND cp_status <> 'pending'
                        ORDER BY cp_id DESC LIMIT ".(int)$limit);
    while ($row = sql_fetch_array($res)) $list[] = $row;
    return $list;
}
