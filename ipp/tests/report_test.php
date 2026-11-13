<?php
/*
 * 5 LLM 주간 리포트 요약 테스트 (서버 PHP 쪽)
 * - 계산 함수: 이유 횟수, 칸 정리, 금액 반올림, 기록 있음 판단, 예측 서버 응답 확인
 * - 꺼짐/기록 없음/다른 주소/닫힌 포트 → null, 실패 시각 기록과 60초 건너뛰기
 * - DB 집계: 테스트 전용 아이디(ipptest_report)로 임시 기록을 넣고 집계를 확인한 뒤 지운다 (그누보드를 CLI로 불러옴)
 * - 예측 서버(127.0.0.1:8002)가 켜져 있고 API 키가 없으면: 503 → null, 실패 시각 기록 (켜져 있지 않으면 이 부분은 건너뜀)
 * 실행 (저장소 루트에서, MariaDB가 켜진 상태): php ipp/tests/report_test.php [예측 서버 주소, 기본 http://127.0.0.1:8002]
 * 실제 Claude API는 부르지 않는다. 웹으로는 실행하지 않는다
 */
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

define('G5_IS_CLI', true);   // 그누보드 방문자 기록을 남기지 않는다
$_SERVER += array('HTTP_HOST' => 'localhost:8001', 'REQUEST_URI' => '/', 'SCRIPT_NAME' => '/index.php',
                  'REMOTE_ADDR' => '127.0.0.1', 'SERVER_PORT' => '8001', 'REQUEST_METHOD' => 'GET');
chdir(__DIR__.'/..');
include './_common.php';

$pass = 0; $fail = 0;
function check($name, $cond, $detail = '') {
    global $pass, $fail;
    if ($cond) { $pass++; return; }
    $fail++;
    echo "실패: {$name}".($detail !== '' ? " ({$detail})" : '')."\n";
}

// 1. 계산 함수
$known = ipp_report_known_reasons();
check('이유 코드 목록 (모델 group)', in_array('night', $known, true) && in_array('cooldown', $known, true) && count($known) === 14, implode(',', $known));
$top = ipp_report_top_reasons(array('night,amount_ratio', 'night', 'discount', 'night,discount,night', 'x,<b>', ''), $known);
check('이유 횟수 상위', $top === array(array('code' => 'night', 'count' => 3), array('code' => 'discount', 'count' => 2),
                                     array('code' => 'amount_ratio', 'count' => 1)), json_encode($top));
$many = ipp_report_top_reasons(array(implode(',', $known)), $known);
check('이유는 최대 5개', count($many) === 5);
check('금액 반올림', ipp_report_round_amount(42400) === 42000 && ipp_report_round_amount(15600) === 16000 && ipp_report_round_amount(-5) === 0);
$w = ipp_report_week_clean(array('checkouts' => '3', 'mb_id' => 'admin', 'blocked' => -2));
check('칸 정리: 정해진 칸만, 0 이상 정수', array_keys($w) === IPP_REPORT_FIELDS && $w['checkouts'] === 3 && $w['blocked'] === 0 && !isset($w['mb_id']));
$zero = ipp_report_week_clean(array());
check('기록 없음', !ipp_report_has_data(array('this_week' => $zero, 'last_week' => $zero, 'top_reasons' => array())));
check('지난주 차단만 있어도 있음', ipp_report_has_data(array('this_week' => $zero, 'last_week' => array('blocked' => 1) + $zero)));

$ok = json_encode(array('headline' => '이번 주 2번 참았어요', 'summary' => '잘했어요.', 'tip' => '내일 다시 봐요.', 'model' => 'm', 'cached' => false));
check('응답 확인', ipp_report_parse(200, $ok) === array('headline' => '이번 주 2번 참았어요', 'summary' => '잘했어요.', 'tip' => '내일 다시 봐요.'));
foreach (array(
    '502'        => array(502, $ok),
    'JSON 아님'  => array(200, '<html>'),
    '칸 빠짐'    => array(200, json_encode(array('headline' => 'a', 'summary' => 'b'))),
    '빈 칸'      => array(200, json_encode(array('headline' => 'a', 'summary' => ' ', 'tip' => 'c'))),
    '너무 김'    => array(200, json_encode(array('headline' => str_repeat('가', 41), 'summary' => 'b', 'tip' => 'c'))),
    '문자열 아님' => array(200, json_encode(array('headline' => 1, 'summary' => 'b', 'tip' => 'c'))),
) as $name => $c) check("응답 거부: {$name}", ipp_report_parse($c[0], $c[1]) === null);

// 파생 값 (지난주 대비 차이·배수, 참은 비율)
$a = array('checkouts' => 5, 'night' => 3, 'blocked' => 4, 'buy' => 1, 'giveup' => 2, 'hold' => 1, 'hold_success' => 1, 'hold_failed' => 0, 'saved_amount' => 32000) + $zero;
$b = array('checkouts' => 3, 'night' => 0, 'blocked' => 4, 'buy' => 1, 'giveup' => 1, 'hold' => 1, 'hold_success' => 1, 'hold_failed' => 0, 'saved_amount' => 10000) + $zero;
$d = ipp_report_derived($a, $b);
check('파생: 차이', $d['checkouts_diff'] === 2 && $d['night_diff'] === 3 && $d['blocked_diff'] === 0 && $d['saved_amount_diff'] === 22000);
check('파생: 배수 소수 한 자리', $d['checkouts_ratio'] === 1.7 && $d['blocked_ratio'] === 1.0, var_export($d['checkouts_ratio'], true));
check('파생: 지난주 0이면 배수 null', $d['night_ratio'] === null);
check('파생: 참은 비율 정수 %', $d['resist_rate_this'] === 75 && $d['resist_rate_last'] === 67 && $d['hold_success_rate_this'] === 100);
$d0 = ipp_report_derived($zero, $zero);
check('파생: 결정이 없으면 비율 null', $d0['resist_rate_this'] === null && $d0['hold_success_rate_last'] === null && $d0['checkouts_diff'] === 0);
check('파생: 칸 13개', count($d) === 13);
check('파생: 줄면 음수 차이', ipp_report_derived($b, $a)['checkouts_diff'] === -2);

// 2. 꺼짐, 기록 없음, 주소, 닫힌 포트, 건너뛰기
$has  = array('this_week' => array('checkouts' => 2) + $zero, 'last_week' => $zero, 'top_reasons' => array());
$down = sys_get_temp_dir().'/ipp_llm_down_test.txt';
@unlink($down);
check('기본값 꺼짐', IPP_USE_LLM === false && ipp_report_summary($has) === null);
$opts = array('on' => true, 'url' => 'http://127.0.0.1:9', 'timeout' => 1, 'skip_sec' => 60, 'down_file' => $down);
check('기록 없으면 부르지 않음', ipp_report_summary(array('this_week' => $zero, 'last_week' => $zero, 'top_reasons' => array()), $opts) === null && !is_file($down));
check('다른 주소는 부르지 않음', ipp_report_summary($has, array('url' => 'http://example.com:8002') + $opts) === null && !is_file($down));
$t = microtime(true);
check('닫힌 포트면 null', ipp_report_summary($has, $opts) === null);
check('닫힌 포트도 시간 제한 안에', microtime(true) - $t < 1.5, round(microtime(true) - $t, 2));
check('실패 시각 기록', is_file($down));
$t = microtime(true);
ipp_report_summary($has, $opts);
check('60초 안에는 부르지 않음', microtime(true) - $t < 0.05);
@unlink($down);

// 3. DB 집계 (임시 기록, 끝나면 지움)
$mb = 'ipptest_report';
$bl = $g5['ipp_block_log_table']; $cdt = $g5['ipp_cooldown_table'];
$cleanup = function () use ($mb, $bl, $cdt) {
    sql_query(" DELETE FROM {$bl} WHERE mb_id = '{$mb}' ");
    sql_query(" DELETE FROM {$cdt} WHERE mb_id = '{$mb}' ");
};
$cleanup();
$ins = function ($dt, $site, $checkout, $event, $decision = '', $level = '', $reasons = '') use ($mb, $bl) {
    sql_query(" INSERT INTO {$bl} SET mb_id = '{$mb}', bl_client = 'desktop', bl_site = '{$site}', bl_is_checkout = {$checkout},
                bl_event = '{$event}', bl_decision = '{$decision}', bl_risk_level = '{$level}', bl_risk_reasons = '{$reasons}',
                bl_datetime = '{$dt}' ");
};
$cd = function ($status, $end, $amount) use ($mb, $cdt) {
    $e = $end ? "'{$end}'" : 'NULL';
    sql_query(" INSERT INTO {$cdt} SET mb_id = '{$mb}', cd_source = 'detect', cd_item_name = '', cd_amount = {$amount},
                cd_status = '{$status}', cd_start_datetime = '2026-10-01 00:00:00', cd_expire_datetime = '2026-10-02 00:00:00',
                cd_end_datetime = {$e} ");
};
try {
    // 이번 주 = 2026-11-07 00:00 ~ 2026-11-13 12:00, 지난주 = 2026-10-31 00:00 ~ 11-07 00:00
    $ins('2026-11-12 23:30:00', 'coupang', 1, 'detect', 'buy', 'high', 'night,amount_ratio');
    $ins('2026-11-12 01:00:00', 'coupang', 1, 'detect', 'giveup', 'mid', 'night');
    $ins('2026-11-10 14:00:00', 'musinsa', 1, 'detect', 'hold', 'low', 'discount');
    $ins('2026-11-09 15:00:00', '', 1, 'detect', 'close', 'mid', 'night,discount');
    $ins('2026-11-13 12:30:00', 'coupang', 1, 'detect', 'buy', 'high', 'night');   // 기준 시각 뒤: 빠짐
    $ins('2026-11-11 10:00:00', 'coupang', 0, 'blocked');
    $ins('2026-11-11 10:05:00', 'zigzag', 0, 'blocked');
    $ins('2026-11-08 10:00:00', 'coupang', 0, 'detect');                              // 상품 화면 감지: 결제·차단 아님
    $ins('2026-11-05 23:10:00', 'coupang', 1, 'detect', 'buy', 'high', 'night');
    $ins('2026-11-01 10:00:00', 'coupang', 1, 'detect', 'giveup', 'low', '');
    $ins('2026-11-02 10:00:00', 'coupang', 0, 'blocked');
    $ins('2026-10-30 10:00:00', 'coupang', 1, 'detect', 'buy', 'high', 'night');   // 2주 전: 빠짐
    $cd('success', '2026-11-11 09:00:00', 32400);
    $cd('gaveup',  '2026-11-08 09:00:00', 10000);
    $cd('failed',  '2026-11-12 09:00:00', 50000);
    $cd('waiting', null, 70000);
    $cd('success', '2026-11-03 09:00:00', 15600);

    $in = ipp_report_input($mb, '2026-11-13 12:00:00');
    $want_this = array('checkouts' => 4, 'buy' => 1, 'giveup' => 1, 'hold' => 1, 'hold_success' => 2, 'hold_failed' => 1,
                       'saved_amount' => 42000, 'risk_high' => 1, 'risk_mid' => 2, 'risk_low' => 1, 'night' => 2, 'malls' => 2, 'blocked' => 2);
    $want_last = array('checkouts' => 2, 'buy' => 1, 'giveup' => 1, 'hold' => 0, 'hold_success' => 1, 'hold_failed' => 0,
                       'saved_amount' => 16000, 'risk_high' => 1, 'risk_mid' => 0, 'risk_low' => 1, 'night' => 1, 'malls' => 1, 'blocked' => 1);
    check('이번 주 집계', $in['this_week'] === $want_this, json_encode($in['this_week']));
    check('지난주 집계', $in['last_week'] === $want_last, json_encode($in['last_week']));
    check('이번 주 이유', $in['top_reasons'] === array(array('code' => 'night', 'count' => 3), array('code' => 'discount', 'count' => 2),
                                                      array('code' => 'amount_ratio', 'count' => 1)), json_encode($in['top_reasons']));
    $json = json_encode($in);
    check('입력에 아이디·쇼핑몰 이름 없음', strpos($json, $mb) === false && strpos($json, 'coupang') === false && strpos($json, 'musinsa') === false);
    check('파생 값 (DB 집계)', $in['derived'] === ipp_report_derived($want_this, $want_last)
          && $in['derived']['checkouts_ratio'] === 2.0 && $in['derived']['resist_rate_this'] === 67 && $in['derived']['resist_rate_last'] === 50
          && $in['derived']['hold_success_rate_this'] === 67 && $in['derived']['saved_amount_diff'] === 26000, json_encode($in['derived']));
    check('기록 없는 회원', !ipp_report_has_data(ipp_report_input('ipptest_nobody', '2026-11-13 12:00:00')));
} finally {
    $cleanup();
}
$left = sql_fetch(" SELECT (SELECT COUNT(*) FROM {$bl} WHERE mb_id = '{$mb}') + (SELECT COUNT(*) FROM {$cdt} WHERE mb_id = '{$mb}') AS c ");
check('임시 기록 지움', (int)$left['c'] === 0);

// 4. 예측 서버가 켜져 있으면: 키가 없을 때 503 → null, 실패 시각 기록
$srv = isset($argv[1]) ? rtrim($argv[1], '/') : 'http://127.0.0.1:8002';   // 예측 서버 주소 (선택)
$ch = curl_init($srv.'/health');
curl_setopt_array($ch, array(CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 2, CURLOPT_NOPROXY => '*'));
$h = json_decode((string)curl_exec($ch), true);
if (is_array($h) && array_key_exists('message', $h['services'] ?? array())) {
    if ($h['services']['message'] === null) {
        $o = array('on' => true, 'url' => $srv, 'timeout' => 3, 'skip_sec' => 60, 'down_file' => $down);
        check('예측 서버 키 없음 → null', ipp_report_summary($in, $o) === null);
        // 서버가 PHP 파생 값을 받아들이는지 (두 주와 안 맞으면 422, 맞으면 키 없음 503). 무작위 두 주 200쌍
        mt_srand(5);
        $post = function ($body) use ($srv) {
            $c = curl_init($srv.'/message/weekly');
            curl_setopt_array($c, array(CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($body), CURLOPT_RETURNTRANSFER => true,
                CURLOPT_HTTPHEADER => array('Content-Type: application/json'), CURLOPT_TIMEOUT => 3, CURLOPT_NOPROXY => '*'));
            curl_exec($c);
            return (int)curl_getinfo($c, CURLINFO_RESPONSE_CODE);
        };
        $bad = 0;
        for ($i = 0; $i < 200; $i++) {
            $w = array(); $v = array();
            foreach (IPP_REPORT_FIELDS as $k) {
                $hi = ($k === 'saved_amount') ? 300 : 12;
                $w[$k] = mt_rand(0, $hi) * ($k === 'saved_amount' ? 1000 : 1);
                $v[$k] = (mt_rand(0, 3) === 0) ? 0 : mt_rand(0, $hi) * ($k === 'saved_amount' ? 1000 : 1);
            }
            $code = $post(array('this_week' => (object)$w, 'last_week' => (object)$v, 'top_reasons' => array(),
                                'derived' => (object)ipp_report_derived($w, $v)));
            if ($code !== 503) { $bad++; if ($bad <= 3) echo "  파생 값 거부 HTTP {$code}: ".json_encode(ipp_report_derived($w, $v))."
"; }
        }
        check('서버가 PHP 파생 값을 받아들임 (200쌍)', $bad === 0, "거부 {$bad}개");
        $wrong = ipp_report_derived($a, $b); $wrong['checkouts_ratio'] = 9.9;
        check('틀린 파생 값은 서버가 422', $post(array('this_week' => (object)$a, 'last_week' => (object)$b, 'top_reasons' => array(), 'derived' => (object)$wrong)) === 422);
        check('키 없음(503)도 실패 시각 기록', is_file($down));
        @unlink($down);
    } else {
        echo "  예측 서버에 API 키가 있어 503 확인은 건너뜀 (실제 API를 부르지 않으려고)\n";
    }
} else {
    echo "  예측 서버({$srv})가 꺼져 있거나 요약 서비스가 없어 서버 확인은 건너뜀\n";
}

echo "통과 {$pass}개, 실패 {$fail}개\n";
exit($fail ? 1 : 0);
