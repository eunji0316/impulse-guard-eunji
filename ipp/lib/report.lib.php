<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 5 LLM 주간 리포트 요약 (선택 기능, IPP_USE_LLM)
 * - 집계: 회원 한 명의 이번 주(오늘 포함 최근 7일)와 지난주(그 전 7일) 숫자, 이번 주 위험도 이유 코드 횟수 상위 5개
 * - 예측 서버(ai/serve, POST /message/weekly)가 Claude API로 요약을 만든다. 서버 PHP는 API 키를 모른다
 * - 보내는 값은 숫자와 이유 코드뿐이다. 회원 아이디, 쇼핑몰 이름(개수만), 상품명, 주소, 시각은 보내지 않는다
 * - 요약은 저장하지 않는다 (예측 서버의 메모리 캐시만). 꺼져 있거나 실패하면 null → 통계 화면은 지금 그대로
 * - 실패(연결 실패, 시간 초과, 503) 뒤 IPP_LLM_SKIP_SEC 동안은 부르지 않는다 (ipp_risk_predict_remote와 같은 방식)
 */

define('IPP_REPORT_FIELDS', array('checkouts', 'buy', 'giveup', 'hold', 'hold_success', 'hold_failed', 'saved_amount',
                                  'risk_high', 'risk_mid', 'risk_low', 'night', 'malls', 'blocked'));
define('IPP_REPORT_TEXT_MAX', array('headline' => 40, 'summary' => 220, 'tip' => 100));

// 한 기간 [$from, $to)의 숫자
function ipp_report_week($mb_id, $from, $to) {
    global $g5;
    $mb = sql_real_escape_string($mb_id);
    $range = "bl_datetime >= '".sql_real_escape_string($from)."' AND bl_datetime < '".sql_real_escape_string($to)."'";
    $row = sql_fetch(" SELECT COUNT(*) AS checkouts,
                              IFNULL(SUM(bl_decision = 'buy'), 0) AS buy,
                              IFNULL(SUM(bl_decision = 'giveup'), 0) AS giveup,
                              IFNULL(SUM(bl_decision = 'hold'), 0) AS hold,
                              IFNULL(SUM(bl_risk_level = 'high'), 0) AS risk_high,
                              IFNULL(SUM(bl_risk_level = 'mid'), 0) AS risk_mid,
                              IFNULL(SUM(bl_risk_level = 'low'), 0) AS risk_low,
                              IFNULL(SUM(HOUR(bl_datetime) IN (23, 0, 1, 2, 3)), 0) AS night,
                              COUNT(DISTINCT NULLIF(bl_site, '')) AS malls
                       FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '{$mb}' AND bl_is_checkout = 1 AND {$range} ");
    $blk = sql_fetch(" SELECT COUNT(*) AS cnt FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '{$mb}' AND bl_event = 'blocked' AND {$range} ");
    // 담아두기: 이 기간에 끝난 것. 참음 = success(24시간 참음)·gaveup(포기), 삼 = failed. 절약 금액은 통계 화면과 같은 기준
    $cd = sql_fetch(" SELECT IFNULL(SUM(cd_status IN ('success', 'gaveup')), 0) AS ok,
                             IFNULL(SUM(cd_status = 'failed'), 0) AS failed,
                             IFNULL(SUM(IF(cd_status IN ('success', 'gaveup'), cd_amount, 0)), 0) AS saved
                      FROM {$g5['ipp_cooldown_table']}
                      WHERE mb_id = '{$mb}' AND cd_end_datetime >= '".sql_real_escape_string($from)."'
                        AND cd_end_datetime < '".sql_real_escape_string($to)."' ");
    $w = array();
    foreach (array('checkouts', 'buy', 'giveup', 'hold', 'risk_high', 'risk_mid', 'risk_low', 'night', 'malls') as $k) $w[$k] = (int)$row[$k];
    $w['hold_success'] = (int)$cd['ok'];
    $w['hold_failed']  = (int)$cd['failed'];
    $w['saved_amount'] = ipp_report_round_amount($cd['saved']);
    $w['blocked']      = (int)$blk['cnt'];
    return ipp_report_week_clean($w);
}

// 금액은 1,000원 단위로 반올림해서 보낸다
function ipp_report_round_amount($v) {
    return (int)(round(max(0, (float)$v) / 1000) * 1000);
}

// 정해진 칸만, 0 이상 정수로 (예측 서버가 다른 칸을 받지 않으므로 순서와 칸을 맞춘다)
function ipp_report_week_clean($w) {
    $out = array();
    foreach (IPP_REPORT_FIELDS as $k) $out[$k] = max(0, (int)(isset($w[$k]) ? $w[$k] : 0));
    return $out;
}

// 파생 값: 지난주 대비 차이·배수, 참은 비율. LLM이 직접 계산하지 않도록 미리 계산해서 보낸다
// (예측 서버 message_api.expected_derived가 두 주 숫자와 맞는지 다시 확인한다. 반올림: 배수 소수 한 자리, 비율 정수 %)
function ipp_report_derived($a, $b) {
    $d = array();
    foreach (array('checkouts', 'night', 'blocked', 'buy', 'giveup', 'saved_amount') as $k) $d[$k.'_diff'] = $a[$k] - $b[$k];
    foreach (array('checkouts', 'night', 'blocked') as $k) $d[$k.'_ratio'] = ($b[$k] > 0) ? round($a[$k] / $b[$k], 1) : null;
    $rate = function ($num, $den) { return ($den > 0) ? (int)round(100 * $num / $den) : null; };
    foreach (array('this' => $a, 'last' => $b) as $s => $w) {
        $d['resist_rate_'.$s]       = $rate($w['giveup'] + $w['hold'], $w['buy'] + $w['giveup'] + $w['hold']);   // 안 살래요·담아두기 ÷ 팝업 결정
        $d['hold_success_rate_'.$s] = $rate($w['hold_success'], $w['hold_success'] + $w['hold_failed']);         // 담아두기 참음 ÷ 끝난 담아두기
    }
    return $d;
}

// 이유 코드 문자열 목록(bl_risk_reasons, 쉼표 구분) → 횟수 상위 5개 [{code, count}]. 모델에 있는 이유 코드만
function ipp_report_top_reasons($code_lists, $known) {
    $cnt = array();
    foreach ($code_lists as $s) {
        foreach (array_unique(array_filter(explode(',', (string)$s))) as $c) {
            if (in_array($c, $known, true)) $cnt[$c] = (isset($cnt[$c]) ? $cnt[$c] : 0) + 1;
        }
    }
    uksort($cnt, function ($a, $b) use ($cnt) { return ($cnt[$b] <=> $cnt[$a]) ?: strcmp($a, $b); });
    $out = array();
    foreach (array_slice($cnt, 0, 5, true) as $c => $n) $out[] = array('code' => $c, 'count' => $n);
    return $out;
}

// 위험도 이유 코드 목록 (모델 JSON의 group). 모델이 없으면 빈 배열
function ipp_report_known_reasons() {
    $model = function_exists('ipp_risk_model') ? ipp_risk_model() : null;
    if (!$model) return array();
    $g = array();
    foreach ($model['features'] as $spec) if (!empty($spec['group'])) $g[$spec['group']] = true;
    return array_keys($g);
}

// 예측 서버에 보낼 입력 전체. $now는 테스트용
function ipp_report_input($mb_id, $now = null) {
    global $g5;
    $ts   = $now ? strtotime($now) : G5_SERVER_TIME;
    $to   = date('Y-m-d H:i:s', $ts);
    $from = date('Y-m-d', $ts - 6 * 86400).' 00:00:00';                 // 오늘 포함 7일 (ipp_stats_since(7)과 같은 기준)
    $prev = date('Y-m-d H:i:s', strtotime($from) - 7 * 86400);

    $lists = array();
    $res = sql_query(" SELECT bl_risk_reasons FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."' AND bl_is_checkout = 1 AND bl_risk_reasons <> ''
                         AND bl_datetime >= '{$from}' AND bl_datetime < '{$to}' ");
    while ($r = sql_fetch_array($res)) $lists[] = $r['bl_risk_reasons'];

    $this_week = ipp_report_week($mb_id, $from, $to);
    $last_week = ipp_report_week($mb_id, $prev, $from);
    return array(
        'this_week'   => $this_week,
        'last_week'   => $last_week,
        'top_reasons' => ipp_report_top_reasons($lists, ipp_report_known_reasons()),
        'derived'     => ipp_report_derived($this_week, $last_week)
    );
}

// 요약할 기록이 있는지 (두 주 모두 결제 화면·차단이 0이면 부르지 않는다)
function ipp_report_has_data($input) {
    foreach (array('this_week', 'last_week') as $w) {
        if ($input[$w]['checkouts'] > 0 || $input[$w]['blocked'] > 0) return true;
    }
    return false;
}

// 예측 서버 응답 확인. 맞으면 array(headline, summary, tip), 아니면 null
function ipp_report_parse($code, $text) {
    if ($code !== 200 || !is_string($text)) return null;
    $d = json_decode($text, true);
    if (!is_array($d)) return null;
    $out = array();
    foreach (IPP_REPORT_TEXT_MAX as $k => $max) {
        if (!isset($d[$k]) || !is_string($d[$k])) return null;
        $v = trim($d[$k]);
        if ($v === '' || mb_strlen($v, 'UTF-8') > $max) return null;
        $out[$k] = $v;
    }
    return $out;
}

// 주간 요약. 기능이 꺼졌거나, 기록이 없거나, 실패하면 null
// $opts: url, timeout, skip_sec, down_file (테스트용)
function ipp_report_summary($input, $opts = array()) {
    $o = array_merge(array(
        'on'        => defined('IPP_USE_LLM') && IPP_USE_LLM,
        'url'       => defined('IPP_LLM_SERVER_URL') ? IPP_LLM_SERVER_URL : '',
        'timeout'   => defined('IPP_LLM_TIMEOUT') ? IPP_LLM_TIMEOUT : 10,
        'skip_sec'  => defined('IPP_LLM_SKIP_SEC') ? IPP_LLM_SKIP_SEC : 60,
        'down_file' => defined('IPP_LLM_DOWN_FILE') ? IPP_LLM_DOWN_FILE : ''
    ), $opts);
    if (!$o['on'] || !ipp_report_has_data($input)) return null;
    if (!ipp_risk_server_local_url($o['url']) || !function_exists('curl_init')) return null;

    $down = (string)$o['down_file'];
    if ($down !== '' && is_file($down) && time() - (int)@file_get_contents($down) < (int)$o['skip_sec']) return null;

    $a = ipp_report_week_clean($input['this_week']);
    $b = ipp_report_week_clean($input['last_week']);
    $body = array('this_week' => (object)$a, 'last_week' => (object)$b,
                  'top_reasons' => array_values($input['top_reasons']),
                  'derived' => (object)ipp_report_derived($a, $b));   // 정리한 두 주 숫자로 다시 계산 (서버 확인과 맞게)
    $ms = max(100, (int)round($o['timeout'] * 1000));
    $ch = curl_init(rtrim($o['url'], '/').'/message/weekly');
    curl_setopt_array($ch, array(
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($body),
        CURLOPT_HTTPHEADER => array('Content-Type: application/json'), CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT_MS => min($ms, 1000), CURLOPT_TIMEOUT_MS => $ms,
        CURLOPT_NOSIGNAL => true, CURLOPT_FOLLOWLOCATION => false, CURLOPT_NOPROXY => '*'
    ));
    $text = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $out  = ($text === false) ? null : ipp_report_parse($code, $text);

    if ($down !== '') {
        // 서버가 없거나(연결 실패, 시간 초과) 쓸 수 없으면(503: 키 없음, 하루 상한) 잠시 부르지 않는다. 502(요약이 이상함)는 다음에 다시
        if ($text === false || $code === 503) @file_put_contents($down, (string)time());
        elseif ($out !== null && is_file($down)) @unlink($down);
    }
    return $out;
}
