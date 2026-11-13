<?php
/*
 * C-2 위험도 계산 테스트 (DB 없이 계산 함수만)
 * - ipp/model/risk_model.json의 tests(ai/risk/model.py가 만든 원시 값 → 확률, 이유)와 PHP 계산이 같은지
 * - 단계, 라벨, 월급일, 요청 특성 정리, 문구
 * 실행 (저장소 루트에서): php ipp/tests/risk_test.php
 * 웹으로는 실행하지 않는다
 */
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

define('_GNUBOARD_', true);
define('IPP_USE_RISK_MODEL', true);
define('IPP_RISK_MODEL_FILE', __DIR__.'/../model/risk_model.json');
define('IPP_RISK_LEVEL_MID', 0.3);
define('IPP_RISK_LEVEL_HIGH', 0.55);
define('IPP_RISK_REASON_MAX', 3);
include __DIR__.'/../lib/risk.lib.php';

$pass = 0; $fail = 0;
function check($name, $cond, $detail = '') {
    global $pass, $fail;
    if ($cond) { $pass++; return; }
    $fail++;
    echo "실패: {$name}".($detail !== '' ? " ({$detail})" : '')."\n";
}

// 1. JSON 예시와 같은 계산
$model = ipp_risk_model();
check('모델 읽기', is_array($model));
check('예시 30개 이상', count($model['tests']) >= 30, count($model['tests']));
foreach ($model['tests'] as $i => $t) {
    $p = ipp_risk_predict($model, $t['raw']);
    check("예시 {$i} 확률", abs($p['prob'] - $t['prob']) < 1e-5, $p['prob'].' vs '.$t['prob']);
    $codes = array_map(function ($r) { return $r[0]; }, $p['reasons']);
    check("예시 {$i} 이유", $codes === $t['reasons'], implode(',', $codes).' vs '.implode(',', $t['reasons']));
}
check('없는 파일이면 null', ipp_risk_model(__DIR__.'/없음.json') === null);

// 2. 단계 (기준값 이상이면 그 단계)
check('단계 낮음', ipp_risk_level(0.2999) === 'low');
check('단계 보통', ipp_risk_level(0.30) === 'mid');
check('단계 높음', ipp_risk_level(0.55) === 'high');
check('단계 문구', ipp_risk_message('low') !== '' && ipp_risk_message('high') !== ipp_risk_message('mid'));

// 3. 라벨 (ai/risk/schema.py label_of와 같게)
check('라벨 buy', ipp_risk_label('buy') === 1);
check('라벨 giveup', ipp_risk_label('giveup') === 0);
check('라벨 hold failed', ipp_risk_label('hold', 'failed') === 1);
check('라벨 hold success', ipp_risk_label('hold', 'success') === 0);
check('라벨 hold gaveup', ipp_risk_label('hold', 'gaveup') === 0);
check('라벨 hold waiting', ipp_risk_label('hold', 'waiting') === null);
check('라벨 close', ipp_risk_label('close') === null);

// 4. 월급일 이후 경과일 (25일 가정)
$d = function ($s, $pd = 25) { return ipp_risk_days_since_payday(strtotime($s), $pd); };
check('월급일 당일', $d('2026-11-25 09:00:00') === 0);
check('월급일 전이면 지난달 기준', $d('2026-11-13 23:00:00') === 19, $d('2026-11-13 23:00:00'));
check('해 넘김', $d('2026-01-05 10:00:00') === 11, $d('2026-01-05 10:00:00'));
check('말일 보정 (31일 → 2월 28일)', $d('2026-03-01 10:00:00', 31) === 1, $d('2026-03-01 10:00:00', 31));

// 5. 과거 선택 비율 당기기
check('기록 없으면 prior', ipp_risk_smooth(0, 0, 0.35, 3) == 0.35);
check('기록이 많으면 실제 비율 쪽', ipp_risk_smooth(9, 10, 0.35, 3) > 0.7);

// 6. 요청 특성 정리
$f = ipp_risk_request_features(array('features' => array('discount_rate' => 20, 'pressure' => 1, 'product_views_24h' => 5,
                                                         'same_item_views_24h' => 2, 'browse_sec' => 95)));
check('특성 그대로', $f === array('discount_rate' => 20, 'pressure' => 1, 'product_views_24h' => 5, 'same_item_views_24h' => 2, 'browse_sec' => 95));
$f = ipp_risk_request_features(array('features' => array('discount_rate' => null, 'pressure' => 'x', 'browse_sec' => -5, 'product_views_24h' => 99999)));
check('모름과 범위 밖', $f['discount_rate'] === null && $f['pressure'] === 0 && $f['browse_sec'] === 0 && $f['product_views_24h'] === 1000);
$f = ipp_risk_request_features(array('features' => array('discount_rate' => 0)));
check('할인 없음 0은 0', $f['discount_rate'] === 0);
$f = ipp_risk_request_features(array('discount_rate' => 30));
check('예전 칸 할인율', $f['discount_rate'] === 30 && $f['browse_sec'] === null);
$f = ipp_risk_request_features(array('discount_rate' => 0));
check('예전 칸 0은 모름', $f['discount_rate'] === null);
$f = ipp_risk_request_features(array('features' => array(array('x'))));
check('배열 주입은 모름', $f['discount_rate'] === null && $f['pressure'] === 0);

// 7. 이유 문구: 모든 group에 문구가 있다
$raw = array('amount' => 89000, 'amount_ratio' => 3.2, 'discount_rate' => 40, 'product_views_24h' => 6,
             'same_item_views_24h' => 3, 'browse_sec' => 150, 'checkouts_7d' => 4);
$groups = array_unique(array_filter(array_map(function ($s) { return $s['group']; }, $model['features'])));
foreach ($groups as $g) check("문구 {$g}", ipp_risk_reason_text($g, $raw) !== '');
check('금액 비율 문구', ipp_risk_reason_text('amount_ratio', $raw) === '평소 결제 금액의 3.2배예요.', ipp_risk_reason_text('amount_ratio', $raw));
check('머문 시간 문구', ipp_risk_reason_text('browse', $raw) === '상품을 보고 2분 만에 결제하려고 해요.');
check('할인 문구', strpos(ipp_risk_reason_text('discount', $raw), '40%') === 0);

// 8. C-3 예측 서버 자동 전환 (서버 없이 되는 부분. 서버와 결과 비교는 risk_server_test.php)
$t0  = $model['tests'][0];
$res = ipp_risk_result($model, $t0['raw']);
check('예측 서버 상수 없으면 꺼짐', !ipp_risk_server_on() && $res['source'] === 'php');
check('응답에 risk_source', ipp_risk_response($res)['risk_source'] === 'php' && ipp_risk_response(null)['risk_source'] === '');

$ok = json_encode(array('prob' => 0.42, 'reasons' => array(array('night', 0.3)), 'model' => $model['version']));
check('정상 응답', ipp_risk_server_parse($model, 200, $ok)['prob'] === 0.42);
$bad = array(
    '모델 버전 다름'  => array(200, json_encode(array('prob' => 0.42, 'reasons' => array(), 'model' => 'other'))),
    '확률 범위 밖'    => array(200, json_encode(array('prob' => 1.5, 'reasons' => array(), 'model' => $model['version']))),
    '확률 문자열'     => array(200, json_encode(array('prob' => '0.4', 'reasons' => array(), 'model' => $model['version']))),
    '모르는 이유 코드' => array(200, json_encode(array('prob' => 0.4, 'reasons' => array(array('<b>x</b>', 0.3)), 'model' => $model['version']))),
    '이유 모양 틀림'  => array(200, json_encode(array('prob' => 0.4, 'reasons' => array('night'), 'model' => $model['version']))),
    '이유 없음'       => array(200, json_encode(array('prob' => 0.4, 'model' => $model['version']))),
    'JSON 아님'       => array(200, '<html>'),
    '503'             => array(503, $ok),
);
foreach ($bad as $name => $b) check("응답 거부: {$name}", ipp_risk_server_parse($model, $b[0], $b[1]) === null);

check('주소 127.0.0.1', ipp_risk_server_local_url('http://127.0.0.1:8002'));
check('주소 localhost', ipp_risk_server_local_url('http://localhost:8002/'));
foreach (array('http://example.com:8002', 'http://10.0.0.5:8002', 'https://127.0.0.1:8002', 'http://u:p@127.0.0.1:8002',
               'http://127.0.0.1.example.com', '', 'file:///etc/passwd') as $u) {
    check("다른 주소 거부 {$u}", !ipp_risk_server_local_url($u));
}

$down = sys_get_temp_dir().'/ipp_risk_server_down_test.txt';
@unlink($down);
$opts = array('url' => 'http://example.com', 'timeout' => 0.3, 'skip_sec' => 60, 'down_file' => $down);
check('다른 주소는 부르지 않음', ipp_risk_predict_remote($model, $t0['raw'], $opts) === null && !is_file($down));

$opts['url'] = 'http://127.0.0.1:9';   // 닫힌 포트
$t = microtime(true);
$r = ipp_risk_predict_remote($model, $t0['raw'], $opts);
$sec = microtime(true) - $t;
check('닫힌 포트면 null', $r === null);
check('닫힌 포트도 시간 제한 안에', $sec < 0.6, round($sec, 3));
check('실패 시각 기록', is_file($down) && abs((int)file_get_contents($down) - time()) <= 2);
$t = microtime(true);
ipp_risk_predict_remote($model, $t0['raw'], $opts);
$sec = microtime(true) - $t;
check('60초 안에는 부르지 않음', $sec < 0.05, round($sec, 3));
@unlink($down);

$body = ipp_risk_server_body($model, array_merge($t0['raw'], array('mb_id' => 'user1', 'item_name' => '상품', 'amount' => '89000')));
$keys = array_keys((array)$body['raw']);
check('보내는 칸은 원시 값만', $keys === $model['raw_fields'], implode(',', $keys));
check('보내는 값은 숫자 또는 null', count(array_filter((array)$body['raw'], function ($v) { return $v !== null && !is_float($v); })) === 0);

echo "통과 {$pass}개, 실패 {$fail}개\n";
exit($fail ? 1 : 0);
