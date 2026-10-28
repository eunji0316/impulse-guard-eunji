<?php
/*
 * 크롬 확장 프로그램 전용 API
 * - 로그인 세션 대신 회원별 API 토큰(Authorization: Bearer <토큰>)으로 회원을 식별한다
 * - 요청 본문은 JSON: {"action": "...", ...}
 * - 확장 프로그램의 background service worker가 host_permissions로 호출하므로 CORS 헤더는 보내지 않는다
 */
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function ipp_ext_json($status, $ok, $data = array()) {
    http_response_code($status);
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

// 요청 헤더에서 토큰 꺼내기 (Apache가 Authorization을 지우는 환경을 위해 X-IPP-Token도 받음)
function ipp_ext_token() {
    $auth = isset($_SERVER['HTTP_AUTHORIZATION']) ? $_SERVER['HTTP_AUTHORIZATION'] : '';
    if ($auth === '' && function_exists('getallheaders')) {
        foreach (getallheaders() as $k => $v) {
            if (strtolower($k) === 'authorization') $auth = $v;
        }
    }
    if (preg_match('/^Bearer\s+(\S+)$/i', trim($auth), $m)) return $m[1];
    return isset($_SERVER['HTTP_X_IPP_TOKEN']) ? trim($_SERVER['HTTP_X_IPP_TOKEN']) : '';
}

// JSON 본문의 문자열 값 (배열 등 다른 타입은 빈 문자열)
function ipp_ext_str($body, $key) {
    return (isset($body[$key]) && is_scalar($body[$key])) ? trim((string)$body[$key]) : '';
}

function ipp_ext_int($body, $key) {
    return (isset($body[$key]) && is_numeric($body[$key])) ? (int)$body[$key] : 0;
}

if (!IPP_USE_EXTENSION)                    ipp_ext_json(403, false, array('msg' => '확장 프로그램 연결 기능이 꺼져 있습니다.'));
if ($_SERVER['REQUEST_METHOD'] !== 'POST') ipp_ext_json(405, false, array('msg' => 'POST로 요청하세요.'));

// 세션 로그인은 쓰지 않는다. 토큰으로 찾은 회원으로 덮어쓴다
$member    = ipp_token_member(ipp_ext_token());
$is_member = (bool)$member;
if (!$member) ipp_ext_json(401, false, array('msg' => '토큰이 올바르지 않습니다.'));

$mb_id  = $member['mb_id'];
$body   = json_decode(file_get_contents('php://input'), true);
if (!is_array($body)) ipp_ext_json(400, false, array('msg' => 'JSON 본문이 필요합니다.'));
$action = ipp_ext_str($body, 'action');

// 연결 확인 (팝업의 연결 테스트)
if ($action === 'me') {
    ipp_ext_json(200, true, array(
        'mb_id'    => $mb_id,
        'nick'     => $member['mb_nick'],
        'point'    => (int)get_point_sum($mb_id),
        'features' => array(
            'setting'  => IPP_USE_SETTING,
            'cooldown' => IPP_USE_COOLDOWN,
            'gifticon' => IPP_USE_GIFTICON
        )
    ));
}

// 차단 설정 조회
if ($action === 'setting') {
    if (!IPP_USE_SETTING) ipp_ext_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
    $st    = ipp_setting_get($mb_id);
    $sites = array();
    foreach (IPP_BLOCK_SITES as $code => $site) {
        $sites[] = array('code' => $code, 'name' => $site['name'], 'domain' => $site['domain'], 'on' => in_array($code, $st['st_sites']));
    }
    $blocking = ipp_is_blocking($mb_id);
    ipp_ext_json(200, true, array(
        'is_blocking'  => $blocking,
        'block_until'  => $blocking ? $st['st_block_until'] : null,
        'block_remain' => $blocking ? max(0, strtotime($st['st_block_until']) - G5_SERVER_TIME) : 0,   // 남은 초. 확장 프로그램은 PC 시계와 상관없이 이 값으로 종료 시각을 계산한다
        'sites'        => $sites,
        'keywords'     => $st['st_keywords'],
        'risk_alert'   => (bool)$st['st_risk_alert']
    ));
}

// 상품 하나에 대한 차단/충동구매 판단 (저장하지 않음)
if ($action === 'check') {
    $site      = ipp_ext_str($body, 'site');
    $item_name = ipp_ext_str($body, 'item_name');
    $price     = max(0, ipp_ext_int($body, 'price'));
    if (!isset(IPP_BLOCK_SITES[$site])) ipp_ext_json(400, false, array('msg' => '알 수 없는 사이트입니다.'));

    $st = ipp_setting_get($mb_id);
    ipp_ext_json(200, true, array(
        'is_blocking' => ipp_is_blocking($mb_id, $site),
        'is_impulse'  => ipp_detect_impulse($price, 'shopping', G5_TIME_YMDHIS, $item_name, $mb_id),   // 차단 사이트는 모두 쇼핑몰
        'keyword'     => IPP_USE_SETTING ? ipp_keyword_match($item_name, $st['st_keywords']) : '',
        'point'       => ipp_calc_point($price),
        'point2'      => ipp_calc_point($price, IPP_COOLDOWN_MULTIPLIER)
    ));
}

// 방문/차단/결제 진입 기록
if ($action === 'log') {
    if (!IPP_USE_SETTING) ipp_ext_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
    $bl_id = ipp_block_log_add($mb_id,
        ipp_ext_str($body, 'site'), ipp_ext_str($body, 'url'), ipp_ext_str($body, 'item_name'),
        ipp_ext_int($body, 'price'), ipp_ext_str($body, 'event'), ipp_ext_int($body, 'stay_sec'),
        ipp_ext_str($body, 'page'));
    if (!$bl_id) ipp_ext_json(400, false, array('msg' => '사이트, 이벤트, 페이지 값이 올바르지 않습니다.'));
    ipp_ext_json(200, true, array('bl_id' => $bl_id));
}

// 쿨다운 시작 (사고 싶은 상품을 타임머신에 보관)
if ($action === 'cooldown') {
    if (!IPP_USE_COOLDOWN) ipp_ext_json(403, false, array('msg' => '쿨다운 기능이 꺼져 있습니다.'));
    $item_name = ipp_ext_str($body, 'item_name');
    $price     = ipp_ext_int($body, 'price');
    if ($item_name === '' || $price <= 0) ipp_ext_json(400, false, array('msg' => '상품명과 가격을 보내 주세요.'));

    $cd_id = ipp_cooldown_create($mb_id, mb_substr($item_name, 0, 255, 'UTF-8'), $price);
    $cd    = ipp_cooldown_get($cd_id);
    ipp_ext_json(200, true, array('cd_id' => $cd_id, 'expire' => $cd['cd_expire_datetime']));
}

// 안 살래요 (즉시 포기, 포인트 바로 지급. 웹의 ipp/api/cooldown.php giveup과 같은 처리)
if ($action === 'giveup') {
    if (!IPP_USE_COOLDOWN) ipp_ext_json(403, false, array('msg' => '쿨다운 기능이 꺼져 있습니다.'));
    $item_name = ipp_ext_str($body, 'item_name');
    $price     = ipp_ext_int($body, 'price');
    if ($item_name === '' || $price <= 0) ipp_ext_json(400, false, array('msg' => '상품명과 가격을 보내 주세요.'));

    $cd_id = ipp_cooldown_create($mb_id, mb_substr($item_name, 0, 255, 'UTF-8'), $price);
    $point = ipp_cooldown_finish(ipp_cooldown_get($cd_id), 'gaveup');
    ipp_ext_json(200, true, array('cd_id' => $cd_id, 'point' => $point));
}

ipp_ext_json(400, false, array('msg' => '알 수 없는 요청입니다.'));
