<?php
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');

function ipp_json($ok, $data = array()) {
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

if (!IPP_USE_BANK) ipp_json(false, array('msg' => '계좌 연동 기능이 꺼져 있습니다.'));
if (!$is_member)   ipp_json(false, array('msg' => '로그인이 필요합니다.'));

$mb_id  = $member['mb_id'];
$action = isset($_POST['action']) ? $_POST['action'] : '';

// 계좌 연결
if ($action === 'link') {
    $bank = isset($_POST['bank']) ? trim($_POST['bank']) : '';
    if ($bank === '') ipp_json(false, array('msg' => '은행을 선택하세요.'));
    $ac_id = ipp_bank_link($mb_id, $bank);
    ipp_json(true, array('ac_id' => $ac_id));
}

// 가짜 결제 발생
if ($action === 'pay') {
    $account = ipp_bank_get_account($mb_id);
    if (!$account) ipp_json(false, array('msg' => '연결된 계좌가 없습니다.'));

    $amount   = isset($_POST['amount'])   ? (int)$_POST['amount'] : 0;
    $merchant = isset($_POST['merchant']) ? trim($_POST['merchant']) : '';
    $category = isset($_POST['category']) ? trim($_POST['category']) : '';
    $datetime = !empty($_POST['datetime'])
              ? date('Y-m-d H:i:s', strtotime($_POST['datetime']))
              : G5_TIME_YMDHIS;

    if ($amount <= 0 || $merchant === '') ipp_json(false, array('msg' => '금액과 가맹점을 입력하세요.'));

    $result = ipp_bank_save_transaction($mb_id, $account['ac_id'], 'pay', $amount, $merchant, $category, $datetime);
    ipp_json(true, $result);
}

ipp_json(false, array('msg' => '알 수 없는 요청입니다.'));