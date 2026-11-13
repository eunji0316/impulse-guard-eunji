<?php
/*
 * C-3 예측 서버와 PHP 계산 비교 (예측 서버를 켠 상태에서)
 * - 같은 원시 값을 PHP(ipp_risk_predict)와 예측 서버(/risk/predict)로 계산해 확률·이유가 같은지
 *   대상: 모델 JSON 예시, 가상 데이터(ai/data/risk/synthetic.csv가 있으면 최대 2,000행), 무작위 값 1,000개(모름·경계값 포함)
 * - ipp_risk_result가 서버 값을 쓰고(source=server) 단계·문구·이유가 PHP 계산과 같은지
 * - 자동 전환: 모델 버전이 다르면 PHP, 실패 뒤 60초는 건너뜀, 60초가 지나면 다시 서버
 * - 서버가 받지 않는 입력: 다른 칸(회원 아이디 등), 문자열
 * 실행: 예측 서버를 켠 뒤(ai 폴더에서 .venv\Scripts\python.exe -m serve) 저장소 루트에서
 *       php ipp/tests/risk_server_test.php [http://127.0.0.1:8002]
 * 웹으로는 실행하지 않는다
 */
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$url = isset($argv[1]) ? $argv[1] : 'http://127.0.0.1:8002';
define('_GNUBOARD_', true);
define('IPP_USE_RISK_MODEL', true);
define('IPP_RISK_MODEL_FILE', __DIR__.'/../model/risk_model.json');
define('IPP_RISK_LEVEL_MID', 0.3);
define('IPP_RISK_LEVEL_HIGH', 0.55);
define('IPP_RISK_REASON_MAX', 3);
define('IPP_RISK_SERVER', 'on');
define('IPP_RISK_SERVER_URL', $url);
define('IPP_RISK_SERVER_TIMEOUT', 1.0);   // 비교용이라 넉넉하게 (실제 설정은 0.3)
define('IPP_RISK_SERVER_SKIP_SEC', 60);
define('IPP_RISK_SERVER_DOWN_FILE', sys_get_temp_dir().'/ipp_risk_server_down_cmp.txt');
include __DIR__.'/../lib/risk.lib.php';

$pass = 0; $fail = 0;
function check($name, $cond, $detail = '') {
    global $pass, $fail;
    if ($cond) { $pass++; return; }
    $fail++;
    echo "실패: {$name}".($detail !== '' ? " ({$detail})" : '')."\n";
}

function http($url, $body = null) {
    $ch = curl_init($url);
    $o = array(CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 3, CURLOPT_NOPROXY => '*');
    if ($body !== null) {
        $o += array(CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_HTTPHEADER => array('Content-Type: application/json'));
    }
    curl_setopt_array($ch, $o);
    $text = curl_exec($ch);
    return array((int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE), $text);
}

$model = ipp_risk_model();
$down  = IPP_RISK_SERVER_DOWN_FILE;
@unlink($down);

list($code, $text) = http(rtrim($url, '/').'/health');
$health = json_decode((string)$text, true);
if ($code !== 200 || !isset($health['services']['risk']['model'])) {
    echo "예측 서버에 연결할 수 없거나 위험도 모델이 없습니다 ({$url}, HTTP {$code}).\n";
    echo "ai 폴더에서 .venv\\Scripts\\python.exe -m serve 로 켠 뒤 다시 실행하세요.\n";
    exit(1);
}
check('서버 모델 버전 = PHP 모델 버전', $health['services']['risk']['model'] === $model['version'],
      $health['services']['risk']['model'].' vs '.$model['version']);

// 1. 비교할 원시 값
$rows = array();
foreach ($model['tests'] as $t) $rows[] = array('예시', $t['raw']);

$csv = __DIR__.'/../../ai/data/risk/synthetic.csv';
$n_csv = 0;
if (is_file($csv) && ($fh = fopen($csv, 'r'))) {
    $head = fgetcsv($fh, 0, ',', '"', '');
    while ($n_csv < 2000 && ($line = fgetcsv($fh, 0, ',', '"', '')) !== false) {
        $r = array_combine($head, $line);
        $raw = array();
        foreach ($model['raw_fields'] as $k) $raw[$k] = (isset($r[$k]) && $r[$k] !== '') ? (float)$r[$k] : null;
        $rows[] = array('가상 데이터', $raw);
        $n_csv++;
    }
    fclose($fh);
}

mt_srand(20261113);
$pick = function ($vals) { return $vals[mt_rand(0, count($vals) - 1)]; };
$range = array(
    'hour' => array(0, 23), 'weekday' => array(0, 6), 'days_since_payday' => array(0, 30),
    'amount' => array(0, 5000000), 'discount_rate' => array(0, 99), 'pressure' => array(0, 1),
    'product_views_24h' => array(0, 1000), 'same_item_views_24h' => array(0, 1000), 'browse_sec' => array(0, 86400),
    'amount_ratio' => array(0, 50), 'checkouts_7d' => array(0, 100), 'buy_rate' => array(0, 1), 'cooldown_fail_rate' => array(0, 1)
);
for ($i = 0; $i < 1000; $i++) {
    $raw = array();
    foreach ($model['raw_fields'] as $k) {
        list($lo, $hi) = isset($range[$k]) ? $range[$k] : array(0, 100);
        $u = mt_rand(0, 99);
        if ($u < 20)      $raw[$k] = null;                                   // 모름
        elseif ($u < 30)  $raw[$k] = (float)$pick(array($lo, $hi, 0));        // 경계
        elseif ($u < 35)  $raw[$k] = (float)$pick(array(-1, $hi * 10, 1e-12)); // 범위 밖
        elseif ($u < 70)  $raw[$k] = (float)mt_rand($lo, (int)$hi);           // 정수
        else              $raw[$k] = $lo + ($hi - $lo) * mt_rand() / mt_getrandmax();   // 실수
    }
    $rows[] = array('무작위', $raw);
}

// 2. 확률·이유 비교
$diff_max = 0.0; $bad = 0; $times = array();
foreach ($rows as $i => $row) {
    list($kind, $raw) = $row;
    $php = ipp_risk_predict($model, $raw);
    $t = microtime(true);
    $srv = ipp_risk_predict_remote($model, $raw);
    $times[] = microtime(true) - $t;
    if ($srv === null) {
        $bad++;
        if ($bad <= 5) echo "실패: {$kind} {$i} 서버 응답 없음 ".json_encode($raw)."\n";
        @unlink($down);
        continue;
    }
    $d = abs($php['prob'] - $srv['prob']);
    $diff_max = max($diff_max, $d);
    $pc = array_map(function ($r) { return $r[0]; }, $php['reasons']);
    $sc = array_map(function ($r) { return $r[0]; }, $srv['reasons']);
    $cd = 0.0;
    if ($pc === $sc) foreach ($php['reasons'] as $j => $r) $cd = max($cd, abs($r[1] - $srv['reasons'][$j][1]));
    if ($d >= 1e-9 || $pc !== $sc || $cd > 1e-4) {
        $bad++;
        if ($bad <= 5) echo "실패: {$kind} {$i} 확률 {$php['prob']} vs {$srv['prob']}, 이유 ".implode(',', $pc).' vs '.implode(',', $sc)."\n";
    }
}
$n = count($rows);
check("확률·이유 일치 {$n}개 (예시 ".count($model['tests'])." / 가상 데이터 {$n_csv} / 무작위 1000)", $bad === 0, "다름 {$bad}개");
sort($times);
printf("  확률 차이 최대 %.2e, 서버 호출 중앙값 %.1fms, p99 %.1fms\n",
       $diff_max, $times[(int)(count($times) / 2)] * 1000, $times[(int)(count($times) * 0.99)] * 1000);

// 3. ipp_risk_result: 서버 값을 쓰고 단계·문구·이유 문장이 PHP와 같다
$same = 0;
foreach ($model['tests'] as $t) {
    $a = ipp_risk_result($model, $t['raw']);
    $p = ipp_risk_predict($model, $t['raw']);
    $level = ipp_risk_level($p['prob']);
    $codes = array_map(function ($r) { return $r[0]; }, $p['reasons']);
    $texts = array();
    foreach (array_slice($codes, 0, IPP_RISK_REASON_MAX) as $c) $texts[] = array('code' => $c, 'text' => ipp_risk_reason_text($c, $t['raw']));
    if ($a['source'] === 'server' && $a['risk'] === round($p['prob'], 4) && $a['level'] === $level
        && $a['message'] === ipp_risk_message($level) && $a['reasons'] === $texts && $a['codes'] === $codes) $same++;
}
check('ipp_risk_result 서버 값 = PHP 값 (단계, 문구, 이유 문장)', $same === count($model['tests']), "{$same}/".count($model['tests']));

// 4. 자동 전환
$t0 = $model['tests'][0]['raw'];
$other = $model; $other['version'] = 'other-version';
check('모델 버전이 다르면 서버 값을 쓰지 않음', ipp_risk_predict_remote($other, $t0) === null);
check('실패 시각 기록', is_file($down));
$t = microtime(true);
$a = ipp_risk_result($model, $t0);
$sec = microtime(true) - $t;
check('60초 안에는 PHP 계산 (서버를 부르지 않음)', $a['source'] === 'php' && $sec < 0.05, $a['source'].' '.round($sec, 3));
check('PHP 계산 값도 같음', $a['risk'] === round(ipp_risk_predict($model, $t0)['prob'], 4));
file_put_contents($down, (string)(time() - 61));
$a = ipp_risk_result($model, $t0);
check('60초가 지나면 다시 서버', $a['source'] === 'server' && !is_file($down));

// 5. 서버가 받지 않는 입력
$raw = (array)ipp_risk_server_body($model, $t0)['raw'];
list($code) = http(rtrim($url, '/').'/risk/predict', json_encode(array('raw' => $raw + array('mb_id' => 'user1'))));
check('다른 칸(회원 아이디)은 422', $code === 422, $code);
list($code) = http(rtrim($url, '/').'/risk/predict', json_encode(array('raw' => array('hour' => '23'))));
check('문자열 값은 422', $code === 422, $code);
list($code, $text) = http(rtrim($url, '/').'/risk/predict', json_encode(array('raw' => $raw)));
check('정상 입력은 200', $code === 200, $code);

@unlink($down);
echo "통과 {$pass}개, 실패 {$fail}개\n";
exit($fail ? 1 : 0);
