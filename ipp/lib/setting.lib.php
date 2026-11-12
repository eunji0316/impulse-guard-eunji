<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 회원별 차단 설정과 차단 기록
 * 설정은 회원당 1행이며, 처음 조회할 때 기본값으로 만든다.
 */

// 회원 설정 조회 (없으면 기본값으로 생성). st_sites, st_keywords는 배열로 반환
// $reset이 true면 캐시를 비우기만 한다 (저장 직후 호출)
function ipp_setting_get($mb_id, $reset = false) {
    global $g5;
    static $cache = array();

    if ($reset) { unset($cache[$mb_id]); return null; }
    if (isset($cache[$mb_id])) return $cache[$mb_id];

    $mb = sql_real_escape_string($mb_id);
    $st = sql_fetch(" SELECT * FROM {$g5['ipp_setting_table']} WHERE mb_id = '{$mb}' ");

    if (!$st) {
        // 동시에 처음 열어도 PK 때문에 1행만 들어간다
        $now = G5_TIME_YMDHIS;
        sql_query(" INSERT IGNORE INTO {$g5['ipp_setting_table']}
                    SET mb_id              = '{$mb}',
                        st_sites           = '".sql_real_escape_string(ipp_json_encode(array_keys(IPP_BLOCK_SITES)))."',
                        st_keywords        = '".sql_real_escape_string(ipp_json_encode(IPP_DEFAULT_KEYWORDS))."',
                        st_risk_alert      = 1,
                        st_datetime        = '{$now}',
                        st_update_datetime = '{$now}' ");
        $st = sql_fetch(" SELECT * FROM {$g5['ipp_setting_table']} WHERE mb_id = '{$mb}' ");
    }

    $st['st_sites']    = ipp_json_list($st['st_sites']);
    $st['st_block_all'] = isset($st['st_block_all']) ? (int)$st['st_block_all'] : 1;   // 008 실행 전 DB면 기본값 ON
    $st['st_keywords'] = ipp_json_list($st['st_keywords']);
    return $cache[$mb_id] = $st;
}

// 설정 저장 (차단할 사이트, 키워드, 위험도 알림). 정리된 값으로 저장한다
function ipp_setting_save($mb_id, $sites, $keywords, $risk_alert) {
    global $g5;
    ipp_setting_get($mb_id);   // 행이 없으면 먼저 만든다

    $sites    = array_values(array_intersect(array_keys(IPP_BLOCK_SITES), (array)$sites));
    $keywords = ipp_keyword_clean($keywords);

    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_sites           = '".sql_real_escape_string(ipp_json_encode($sites))."',
                    st_keywords        = '".sql_real_escape_string(ipp_json_encode($keywords))."',
                    st_risk_alert      = '".($risk_alert ? 1 : 0)."',
                    st_update_datetime = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."' ");
    ipp_setting_get($mb_id, true);
}

// 키워드 정리: 앞뒤 공백 제거, 빈 값과 중복 제거, 개수와 길이 제한
function ipp_keyword_clean($keywords) {
    $list = array();
    foreach ((array)$keywords as $kw) {
        $kw = trim(preg_replace('/\s+/u', ' ', (string)$kw));
        if ($kw === '') continue;
        $kw = mb_substr($kw, 0, IPP_KEYWORD_LEN, 'UTF-8');
        if (!in_array($kw, $list)) $list[] = $kw;
        if (count($list) >= IPP_KEYWORD_MAX) break;
    }
    return $list;
}

// 차단 시작. $preset: 1h(1시간), today(오늘 하루), week(일주일), custom(직접 설정)
// 성공하면 종료 시각, 잘못된 값이면 false 반환
function ipp_block_start($mb_id, $preset, $custom_until = '') {
    global $g5;
    $now = G5_SERVER_TIME;

    if ($preset === '1h')         $until = $now + 3600;
    else if ($preset === 'today') $until = strtotime(G5_TIME_YMD.' 23:59:59');
    else if ($preset === 'week')  $until = $now + 7 * 86400;
    else if ($preset === 'custom') {
        $until = strtotime($custom_until);
        if (!$until || $until <= $now || $until > $now + IPP_BLOCK_CUSTOM_MAX_DAYS * 86400) return false;
    }
    else return false;

    ipp_setting_get($mb_id);
    $until = date('Y-m-d H:i:s', $until);
    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_block_start     = '".G5_TIME_YMDHIS."',
                    st_block_until     = '{$until}',
                    st_update_datetime = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."' ");
    ipp_setting_get($mb_id, true);
    return $until;
}

// 차단 해제 (종료 시각을 지금으로 당긴다)
function ipp_block_stop($mb_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_block_until     = '".G5_TIME_YMDHIS."',
                    st_update_datetime = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."'
                  AND st_block_until > '".G5_TIME_YMDHIS."' ");
    ipp_setting_get($mb_id, true);
}

// 지금 차단 중인지
// - 쇼핑몰 전체 차단(st_block_all = 1, 기본)이면 차단 시간에는 사이트와 상관없이 true
// - 끄면 $site가 차단 목록(st_sites)에 있어야 true. $site가 ''(사이트 모름, 데스크톱)면 차단 시간인지만 본다
function ipp_is_blocking($mb_id, $site = '') {
    if (!IPP_USE_SETTING || !$mb_id) return false;

    $st = ipp_setting_get($mb_id);
    if (!$st['st_block_until'] || $st['st_block_until'] <= G5_TIME_YMDHIS) return false;
    if (!$st['st_block_all'] && $site !== '' && !in_array($site, $st['st_sites'])) return false;
    return true;
}

// 쇼핑몰 전체 차단 켜기/끄기 (설정 화면 맨 위 토글. 바꾸면 바로 저장)
function ipp_setting_set_block_all($mb_id, $on) {
    global $g5;
    ipp_setting_get($mb_id);   // 행이 없으면 먼저 만든다
    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_block_all       = '".($on ? 1 : 0)."',
                    st_update_datetime = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."' ");
    ipp_setting_get($mb_id, true);
}

// $text에 들어 있는 첫 키워드 반환 (대소문자 무시). 없으면 ''
function ipp_keyword_match($text, $keywords) {
    if ($text === '') return '';
    foreach ($keywords as $kw) {
        if ($kw !== '' && mb_stripos($text, $kw, 0, 'UTF-8') !== false) return $kw;
    }
    return '';
}

// 차단 기록 저장. 잘못된 사이트 코드, 이벤트, 페이지 종류면 0, 성공하면 bl_id 반환
// $page: product(상품 상세), cart(장바구니), ''(사이트의 그 밖의 페이지)
// $extra: client(extension/desktop, 기본 extension), orig_price(원가), discount_rate(할인율 %), is_checkout(결제 화면 여부)
// 사이트를 모르는 데스크톱 감지는 $site = ''로 저장할 수 있다 (OCR로 사이트를 알아내지 못한 경우)
function ipp_block_log_add($mb_id, $site, $url, $item_name, $price, $event, $stay_sec = 0, $page = '', $extra = array()) {
    global $g5;
    if (!IPP_USE_SETTING) return 0;

    $client = isset($extra['client']) ? $extra['client'] : 'extension';
    if (!in_array($client, IPP_CLIENTS)) return 0;
    if (!isset(IPP_BLOCK_SITES[$site]) && !($site === '' && $client === 'desktop')) return 0;
    if (!in_array($event, array('visit', 'blocked', 'checkout', 'detect'))) return 0;
    if (!in_array($page, array('product', 'cart', ''))) return 0;

    $orig_price    = isset($extra['orig_price'])    ? max(0, (int)$extra['orig_price']) : 0;
    $discount_rate = isset($extra['discount_rate']) ? max(0, min(99, (int)$extra['discount_rate'])) : 0;
    $is_checkout   = !empty($extra['is_checkout']) ? 1 : 0;

    sql_query(" INSERT INTO {$g5['ipp_block_log_table']}
                SET mb_id            = '".sql_real_escape_string($mb_id)."',
                    bl_client        = '{$client}',
                    bl_site          = '".sql_real_escape_string($site)."',
                    bl_url           = '".sql_real_escape_string(mb_substr($url, 0, 500, 'UTF-8'))."',
                    bl_page          = '{$page}',
                    bl_item_name     = '".sql_real_escape_string(mb_substr($item_name, 0, 255, 'UTF-8'))."',
                    bl_price         = '".max(0, (int)$price)."',
                    bl_orig_price    = '{$orig_price}',
                    bl_discount_rate = '{$discount_rate}',
                    bl_is_checkout   = '{$is_checkout}',
                    bl_event         = '{$event}',
                    bl_stay_sec      = '".max(0, (int)$stay_sec)."',
                    bl_datetime      = '".G5_TIME_YMDHIS."' ");
    return sql_insert_id();
}

// 팝업 결정 (B-3, 007_popup_decision.sql)
// hold(담아두기), giveup(안 살래요), buy(그래도 구매), close(창 닫기)
define('IPP_DECISIONS', array('hold', 'giveup', 'buy', 'close'));

// 감지 기록 하나에 팝업 결정을 적는다. 본인의 detect 기록이고 아직 결정이 없을 때만 적고 true
// 쿨다운/포인트보다 먼저 부른다. 같은 기록으로 두 번 요청해도 한 번만 성공하므로 포인트가 두 번 나가지 않는다
function ipp_block_log_decide($mb_id, $bl_id, $decision) {
    global $g5;
    if (!IPP_USE_SETTING || !in_array($decision, IPP_DECISIONS, true) || (int)$bl_id <= 0) return false;
    sql_query(" UPDATE {$g5['ipp_block_log_table']}
                SET bl_decision          = '{$decision}',
                    bl_decision_datetime = '".G5_TIME_YMDHIS."'
                WHERE bl_id = '".(int)$bl_id."'
                  AND mb_id = '".sql_real_escape_string($mb_id)."'
                  AND bl_event = 'detect'
                  AND bl_decision = '' ");
    return ipp_affected_rows() > 0;
}

// 결제 화면 감지 기록에 나중에 읽은 금액을 채운다 (B-5, 009_block_log_price_fill.sql)
// 본인의 데스크톱 결제 화면 detect 기록이고 금액이 아직 0일 때만 채우고 true (이미 금액이 있으면 바꾸지 않는다)
function ipp_block_log_fill_price($mb_id, $bl_id, $price) {
    global $g5;
    if (!IPP_USE_SETTING || (int)$bl_id <= 0 || (int)$price <= 0) return false;
    sql_query(" UPDATE {$g5['ipp_block_log_table']}
                SET bl_price                 = '".(int)$price."',
                    bl_price_filled_datetime = '".G5_TIME_YMDHIS."'
                WHERE bl_id = '".(int)$bl_id."'
                  AND mb_id = '".sql_real_escape_string($mb_id)."'
                  AND bl_client = 'desktop'
                  AND bl_event = 'detect'
                  AND bl_is_checkout = 1
                  AND bl_price = 0 ");
    return ipp_affected_rows() > 0;
}

// 결정으로 만든 쿨다운 번호를 감지 기록에 잇는다
function ipp_block_log_set_cooldown($bl_id, $cd_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_block_log_table']}
                SET bl_cd_id = '".(int)$cd_id."'
                WHERE bl_id = '".(int)$bl_id."' ");
}

// 외부 프로그램(데스크톱 등) 토큰 발급/재발급. DB에는 해시만 저장하고 평문 토큰을 반환한다 (화면에 한 번만 보여 줌)
function ipp_setting_regen_token($mb_id) {
    global $g5;
    ipp_setting_get($mb_id);
    $token = ipp_new_token();
    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_api_token           = '".ipp_token_hash($token)."',
                    st_token_datetime      = '".G5_TIME_YMDHIS."',
                    st_token_used_datetime = NULL,
                    st_update_datetime     = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."' ");
    ipp_setting_get($mb_id, true);
    return $token;
}

// 외부 프로그램 연결 해제 (토큰 삭제)
function ipp_setting_revoke_token($mb_id) {
    global $g5;
    sql_query(" UPDATE {$g5['ipp_setting_table']}
                SET st_api_token           = NULL,
                    st_token_datetime      = NULL,
                    st_token_used_datetime = NULL,
                    st_update_datetime     = '".G5_TIME_YMDHIS."'
                WHERE mb_id = '".sql_real_escape_string($mb_id)."' ");
    ipp_setting_get($mb_id, true);
}

// 토큰으로 회원 찾기. 탈퇴/차단 회원이거나 토큰이 틀리면 null
function ipp_token_member($token) {
    global $g5;
    if (!preg_match('/^[0-9a-f]{64}$/', (string)$token)) return null;

    $st = sql_fetch(" SELECT mb_id, st_token_used_datetime FROM {$g5['ipp_setting_table']}
                      WHERE st_api_token = '".ipp_token_hash($token)."' ");
    if (!$st) return null;

    $mb = get_member($st['mb_id']);
    if (!$mb || !$mb['mb_id'] || $mb['mb_leave_date'] || $mb['mb_intercept_date']) return null;

    // 마지막 사용 시각은 IPP_TOKEN_TOUCH_SEC마다 한 번만 갱신
    $used = $st['st_token_used_datetime'] ? strtotime($st['st_token_used_datetime']) : 0;
    if (G5_SERVER_TIME - $used >= IPP_TOKEN_TOUCH_SEC) {
        sql_query(" UPDATE {$g5['ipp_setting_table']}
                    SET st_token_used_datetime = '".G5_TIME_YMDHIS."'
                    WHERE mb_id = '".sql_real_escape_string($mb['mb_id'])."' ");
    }
    return $mb;
}

function ipp_new_token() {
    return bin2hex(random_bytes(32));
}

function ipp_token_hash($token) {
    return hash('sha256', $token);
}

function ipp_json_encode($list) {
    return json_encode(array_values($list), JSON_UNESCAPED_UNICODE);
}

// JSON 배열 문자열을 PHP 배열로. 깨진 값이면 빈 배열
function ipp_json_list($json) {
    $list = json_decode((string)$json, true);
    return is_array($list) ? $list : array();
}
