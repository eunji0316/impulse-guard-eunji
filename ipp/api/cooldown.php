<?php
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');

function ipp_json($ok, $data = array()) {
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

if (!IPP_USE_COOLDOWN) ipp_json(false, array('msg' => '쿨다운 기능이 꺼져 있습니다.'));
if (!$is_member)       ipp_json(false, array('msg' => '로그인이 필요합니다.'));

$mb_id  = $member['mb_id'];
$action = isset($_POST['action']) ? $_POST['action'] : '';
$item   = isset($_POST['item'])   ? trim($_POST['item']) : '';
$amount = isset($_POST['amount']) ? (int)$_POST['amount'] : 0;

if ($item === '' || $amount <= 0) ipp_json(false, array('msg' => '상품과 금액이 필요합니다.'));

// 24시간 담아두기
if ($action === 'hold') {
    $cd_id = ipp_cooldown_create($mb_id, $item, $amount);
    ipp_json(true, array('cd_id' => $cd_id));
}

// 안 살래요 (즉시 포기)
if ($action === 'giveup') {
    $cd_id = ipp_cooldown_create($mb_id, $item, $amount);
    $point = ipp_cooldown_finish(ipp_cooldown_get($cd_id), 'gaveup');
    ipp_json(true, array('point' => $point));
}

ipp_json(false, array('msg' => '알 수 없는 요청입니다.'));