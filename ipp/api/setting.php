<?php
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');

function ipp_json($ok, $data = array()) {
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

if (!IPP_USE_SETTING)                      ipp_json(false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
if (!$is_member)                           ipp_json(false, array('msg' => '로그인이 필요합니다.'));
if ($_SERVER['REQUEST_METHOD'] !== 'POST') ipp_json(false, array('msg' => '잘못된 요청입니다.'));

$mb_id  = $member['mb_id'];
$action = isset($_POST['action']) ? $_POST['action'] : '';

// 사이트, 키워드, 위험도 알림 저장 (키워드는 쉼표로 구분)
if ($action === 'save') {
    $sites    = isset($_POST['sites']) ? (array)$_POST['sites'] : array();
    $keywords = isset($_POST['keywords']) ? explode(',', $_POST['keywords']) : array();
    $alert    = !empty($_POST['risk_alert']);

    ipp_setting_save($mb_id, $sites, $keywords, $alert);
    $st = ipp_setting_get($mb_id);
    ipp_json(true, array('sites' => $st['st_sites'], 'keywords' => $st['st_keywords']));
}

// 차단 시작
if ($action === 'block') {
    $preset = isset($_POST['preset']) ? $_POST['preset'] : '';
    $custom = isset($_POST['until'])  ? trim($_POST['until']) : '';

    $until = ipp_block_start($mb_id, $preset, $custom);
    if (!$until) ipp_json(false, array('msg' => '차단 종료 시각은 지금 이후, '.IPP_BLOCK_CUSTOM_MAX_DAYS.'일 이내로 정해 주세요.'));
    ipp_json(true, array('until' => $until));
}

// 차단 해제
if ($action === 'unblock') {
    ipp_block_stop($mb_id);
    ipp_json(true);
}

// 확장 프로그램 토큰 발급/재발급. 평문 토큰은 이 응답에서 한 번만 내려간다
if ($action === 'regen_token') {
    if (!IPP_USE_EXTENSION) ipp_json(false, array('msg' => '확장 프로그램 연결 기능이 꺼져 있습니다.'));
    $token = ipp_setting_regen_token($mb_id);
    ipp_json(true, array('token' => $token, 'server' => G5_URL));
}

// 확장 프로그램 연결 해제
if ($action === 'revoke_token') {
    ipp_setting_revoke_token($mb_id);
    ipp_json(true);
}

ipp_json(false, array('msg' => '알 수 없는 요청입니다.'));
