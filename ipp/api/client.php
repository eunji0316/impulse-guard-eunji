<?php
/*
 * 외부 프로그램 공용 API (데스크톱 감지 프로그램, 팀원 프로젝트, 크롬 확장 프로그램)
 * - 로그인 세션 대신 회원별 API 토큰(Authorization: Bearer <토큰>)으로 회원을 식별한다
 * - 요청 본문은 JSON: {"client": "desktop", "action": "...", ...}
 * - client: 어느 프로그램이 부르는지 (IPP_CLIENTS). 기록과 쿨다운의 출처로 저장한다
 *   이 주소로 부를 때는 client가 꼭 있어야 한다. 예전 주소 ext.php는 client가 없으면 extension으로 본다
 * - CORS 헤더는 보내지 않는다 (브라우저 페이지의 JavaScript에서 직접 부르는 용도가 아님)
 * 명세: docs/API.md
 */
include_once(__DIR__.'/../_common.php');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function ipp_api_json($status, $ok, $data = array()) {
    http_response_code($status);
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

// 요청 헤더에서 토큰 꺼내기 (Apache가 Authorization을 지우는 환경을 위해 X-IPP-Token도 받음)
function ipp_api_token() {
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
function ipp_api_str($body, $key) {
    return (isset($body[$key]) && is_scalar($body[$key])) ? trim((string)$body[$key]) : '';
}

function ipp_api_int($body, $key) {
    return (isset($body[$key]) && is_numeric($body[$key])) ? (int)$body[$key] : 0;
}

// true/1/"1"/"true"만 참
function ipp_api_bool($body, $key) {
    return isset($body[$key]) && in_array($body[$key], array(true, 1, '1', 'true'), true);
}

if (!IPP_USE_CLIENT_API)                   ipp_api_json(403, false, array('msg' => '외부 프로그램 연결 기능이 꺼져 있습니다.'));
if ($_SERVER['REQUEST_METHOD'] !== 'POST') ipp_api_json(405, false, array('msg' => 'POST로 요청하세요.'));

$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body)) ipp_api_json(400, false, array('msg' => 'JSON 본문이 필요합니다.'));

// 어느 프로그램인지. ext.php는 IPP_API_DEFAULT_CLIENT = 'extension'을 정하고 이 파일을 include한다
$client = ipp_api_str($body, 'client');
if ($client === '' && defined('IPP_API_DEFAULT_CLIENT')) $client = IPP_API_DEFAULT_CLIENT;
if (!in_array($client, IPP_CLIENTS)) ipp_api_json(400, false, array('msg' => 'client 값이 올바르지 않습니다. ('.implode(', ', IPP_CLIENTS).')'));
if ($client === 'extension' && !IPP_USE_EXTENSION) ipp_api_json(403, false, array('msg' => '확장 프로그램 연결 기능이 꺼져 있습니다.'));

// 세션 로그인은 쓰지 않는다. 토큰으로 찾은 회원으로 덮어쓴다
$member    = ipp_token_member(ipp_api_token());
$is_member = (bool)$member;
if (!$member) ipp_api_json(401, false, array('msg' => '토큰이 올바르지 않습니다.'));

$mb_id  = $member['mb_id'];
$action = ipp_api_str($body, 'action');

// 사이트 코드 확인. 데스크톱은 OCR로 사이트를 모를 수 있어 ''(모름)도 받는다
function ipp_api_site($body, $client) {
    $site = ipp_api_str($body, 'site');
    if (isset(IPP_BLOCK_SITES[$site])) return $site;
    if ($site === '' && $client === 'desktop') return '';
    ipp_api_json(400, false, array('msg' => '알 수 없는 사이트입니다.'));
}

// 데스크톱 감지 정보 (원가, 할인율, 결제 화면 여부). 범위 밖 값은 0으로 정리한다
function ipp_api_detect_info($body) {
    $rate = ipp_api_int($body, 'discount_rate');
    return array(
        'orig_price'    => max(0, ipp_api_int($body, 'orig_price')),
        'discount_rate' => ($rate >= 0 && $rate <= 99) ? $rate : 0,
        'is_checkout'   => ipp_api_bool($body, 'is_checkout')
    );
}

// 연결 확인
if ($action === 'me') {
    ipp_api_json(200, true, array(
        'mb_id'       => $mb_id,
        'nick'        => $member['mb_nick'],
        'point'       => (int)get_point_sum($mb_id),
        'client'      => $client,
        'server_time' => G5_TIME_YMDHIS,
        'features'    => array(
            'setting'  => IPP_USE_SETTING,
            'cooldown' => IPP_USE_COOLDOWN,
            'gifticon' => IPP_USE_GIFTICON
        )
    ));
}

// 차단 설정 조회
if ($action === 'setting') {
    if (!IPP_USE_SETTING) ipp_api_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
    $st    = ipp_setting_get($mb_id);
    $sites = array();
    foreach (IPP_BLOCK_SITES as $code => $site) {
        $sites[] = array('code' => $code, 'name' => $site['name'], 'domain' => $site['domain'], 'on' => in_array($code, $st['st_sites']));
    }
    $blocking = ipp_is_blocking($mb_id);
    ipp_api_json(200, true, array(
        'is_blocking'  => $blocking,
        'block_until'  => $blocking ? $st['st_block_until'] : null,
        'block_remain' => $blocking ? max(0, strtotime($st['st_block_until']) - G5_SERVER_TIME) : 0,   // 남은 초. PC 시계와 상관없이 이 값으로 종료 시각을 계산한다
        'sites'        => $sites,
        'keywords'     => $st['st_keywords'],
        'risk_alert'   => (bool)$st['st_risk_alert']
    ));
}

// 상품 하나에 대한 차단/충동구매 판단
// log가 true면 기록 1건도 저장한다 (데스크톱이 요청 한 번으로 판단과 기록을 함께 하도록)
//   차단 시간이면 blocked(통계의 차단 횟수에 들어감), 아니면 detect. 저장한 이벤트는 event로 돌려준다
// reasons: 충동구매로 본 이유 [{code, text}]. 비어 있지 않으면 is_impulse가 1이다
// orig_price, discount_rate, is_checkout은 지금은 저장만 한다. 위험도 반영은 C단계
if ($action === 'check') {
    $site      = ipp_api_site($body, $client);
    $item_name = ipp_api_str($body, 'item_name');
    $price     = max(0, ipp_api_int($body, 'price'));
    $info      = ipp_api_detect_info($body);

    $st       = ipp_setting_get($mb_id);
    $reasons  = ipp_impulse_reasons($price, 'shopping', G5_TIME_YMDHIS, $item_name, $mb_id);   // 차단 사이트는 모두 쇼핑몰
    $blocking = ipp_is_blocking($mb_id, $site);   // site가 ''면 사이트 목록과 상관없이 차단 시간인지만 본다
    $result   = array(
        'is_blocking' => $blocking,
        'is_impulse'  => $reasons ? 1 : 0,
        'reasons'     => $reasons,
        'keyword'     => IPP_USE_SETTING ? ipp_keyword_match($item_name, $st['st_keywords']) : '',
        'point'       => ipp_calc_point($price),
        'point2'      => ipp_calc_point($price, IPP_COOLDOWN_MULTIPLIER),
        'received'    => $info
    );
    if (ipp_api_bool($body, 'log')) {
        if (!IPP_USE_SETTING) ipp_api_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
        $info['client']  = $client;
        $result['event'] = $blocking ? 'blocked' : 'detect';
        $result['bl_id'] = ipp_block_log_add($mb_id, $site, ipp_api_str($body, 'url'), $item_name, $price,
            $result['event'], 0, ipp_api_str($body, 'page'), $info);
        if (!$result['bl_id']) ipp_api_json(400, false, array('msg' => '페이지 값이 올바르지 않습니다.'));
    }
    ipp_api_json(200, true, $result);
}

// 방문/차단/결제 진입/감지 기록
if ($action === 'log') {
    if (!IPP_USE_SETTING) ipp_api_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
    $extra = ipp_api_detect_info($body);
    $extra['client'] = $client;
    $bl_id = ipp_block_log_add($mb_id,
        ipp_api_str($body, 'site'), ipp_api_str($body, 'url'), ipp_api_str($body, 'item_name'),
        ipp_api_int($body, 'price'), ipp_api_str($body, 'event'), ipp_api_int($body, 'stay_sec'),
        ipp_api_str($body, 'page'), $extra);
    if (!$bl_id) ipp_api_json(400, false, array('msg' => '사이트, 이벤트, 페이지 값이 올바르지 않습니다.'));
    ipp_api_json(200, true, array('bl_id' => $bl_id));
}

// 팝업 결정을 감지 기록에 먼저 적는다 (bl_id가 있을 때만). 이미 결정했거나 내 detect 기록이 아니면 409
// 포인트를 주기 전에 적어야 같은 기록으로 두 번 요청해도 포인트가 한 번만 나간다
function ipp_api_claim_decision($mb_id, $bl_id, $decision) {
    if ($bl_id <= 0) return;
    if (!ipp_block_log_decide($mb_id, $bl_id, $decision)) {
        ipp_api_json(409, false, array('msg' => '이미 처리했거나 찾을 수 없는 감지 기록입니다.'));
    }
}

// 쿨다운 시작 (사고 싶은 상품을 타임머신에 보관)
// bl_id(선택): 데스크톱 팝업의 '조금 더 생각하기'. 그 감지 기록에 hold와 쿨다운 번호를 적는다
if ($action === 'cooldown') {
    if (!IPP_USE_COOLDOWN) ipp_api_json(403, false, array('msg' => '쿨다운 기능이 꺼져 있습니다.'));
    $item_name = ipp_api_str($body, 'item_name');
    $price     = ipp_api_int($body, 'price');
    $bl_id     = ipp_api_int($body, 'bl_id');
    if ($item_name === '' || $price <= 0) ipp_api_json(400, false, array('msg' => '상품명과 가격을 보내 주세요.'));
    ipp_api_claim_decision($mb_id, $bl_id, 'hold');

    $cd_id = ipp_cooldown_create($mb_id, mb_substr($item_name, 0, 255, 'UTF-8'), $price, $client);
    if ($bl_id > 0) ipp_block_log_set_cooldown($bl_id, $cd_id);
    $cd    = ipp_cooldown_get($cd_id);
    ipp_api_json(200, true, array('cd_id' => $cd_id, 'expire' => $cd['cd_expire_datetime'],
        'point2' => ipp_calc_point($price, IPP_COOLDOWN_MULTIPLIER)));
}

// 안 살래요 (즉시 포기, 포인트 바로 지급. 웹의 ipp/api/cooldown.php giveup과 같은 처리)
// bl_id(선택): 데스크톱 팝업의 '안 살래요'. 그 감지 기록에 giveup과 쿨다운 번호를 적는다
if ($action === 'giveup') {
    if (!IPP_USE_COOLDOWN) ipp_api_json(403, false, array('msg' => '쿨다운 기능이 꺼져 있습니다.'));
    $item_name = ipp_api_str($body, 'item_name');
    $price     = ipp_api_int($body, 'price');
    $bl_id     = ipp_api_int($body, 'bl_id');
    if ($item_name === '' || $price <= 0) ipp_api_json(400, false, array('msg' => '상품명과 가격을 보내 주세요.'));
    ipp_api_claim_decision($mb_id, $bl_id, 'giveup');

    $cd_id = ipp_cooldown_create($mb_id, mb_substr($item_name, 0, 255, 'UTF-8'), $price, $client);
    if ($bl_id > 0) ipp_block_log_set_cooldown($bl_id, $cd_id);
    $point = ipp_cooldown_finish(ipp_cooldown_get($cd_id), 'gaveup');
    ipp_api_json(200, true, array('cd_id' => $cd_id, 'point' => $point));
}

// 팝업 결정을 기록만 한다 (쿨다운, 포인트 없음)
// buy(그래도 구매할래요), close(창의 X로 닫음), giveup(가격을 몰라 포인트 없이 '안 살래요')
if ($action === 'decide') {
    if (!IPP_USE_SETTING) ipp_api_json(403, false, array('msg' => '차단 설정 기능이 꺼져 있습니다.'));
    $bl_id    = ipp_api_int($body, 'bl_id');
    $decision = ipp_api_str($body, 'decision');
    if ($bl_id <= 0) ipp_api_json(400, false, array('msg' => 'bl_id를 보내 주세요.'));
    if (!in_array($decision, array('buy', 'close', 'giveup'), true)) {
        ipp_api_json(400, false, array('msg' => 'decision 값이 올바르지 않습니다. (buy, close, giveup)'));
    }
    ipp_api_claim_decision($mb_id, $bl_id, $decision);
    ipp_api_json(200, true, array('bl_id' => $bl_id, 'decision' => $decision));
}

ipp_api_json(400, false, array('msg' => '알 수 없는 요청입니다.'));
