<?php
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');

function ipp_json($ok, $data = array()) {
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

if (!IPP_USE_GIFTICON)                     ipp_json(false, array('msg' => '기프티콘 교환 기능이 꺼져 있습니다.'));
if (!$is_member)                           ipp_json(false, array('msg' => '로그인이 필요합니다.'));
if ($_SERVER['REQUEST_METHOD'] !== 'POST') ipp_json(false, array('msg' => '잘못된 요청입니다.'));

$mb_id  = $member['mb_id'];
$action = isset($_POST['action']) ? $_POST['action'] : '';

// 포인트로 기프티콘 교환
if ($action === 'exchange') {
    $rw_id    = isset($_POST['rw_id'])    ? (int)$_POST['rw_id'] : 0;
    $order_no = isset($_POST['order_no']) ? trim($_POST['order_no']) : '';
    if (!$rw_id || !preg_match('/^[A-Za-z0-9]{10,40}$/', $order_no)) {
        ipp_json(false, array('msg' => '잘못된 요청입니다.'));
    }

    $result = ipp_reward_exchange($mb_id, $rw_id, $order_no);
    if (!$result['ok']) ipp_json(false, array('msg' => $result['msg']));
    ipp_json(true, array('cp_id' => $result['cp_id'], 'point' => get_point_sum($mb_id)));
}

// 쿠폰 사용 완료 표시
if ($action === 'use') {
    $cp_id = isset($_POST['cp_id']) ? (int)$_POST['cp_id'] : 0;
    if (!ipp_coupon_use($mb_id, $cp_id)) ipp_json(false, array('msg' => '사용 처리할 수 없는 쿠폰입니다.'));
    ipp_json(true);
}

ipp_json(false, array('msg' => '알 수 없는 요청입니다.'));
