<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * C-2 충동구매 위험도 (결제 화면 check)
 * - 모델: ipp/model/risk_model.json (ai/risk/train.py가 내보냄, 형식 risk-logreg/1). 계산 규칙의 기준은 ai/risk/model.py
 * - 원시 값: 서버 시각, check 요청의 숫자(features), 서버 DB의 과거 기록 (ai/risk/schema.py RAW)
 * - 모델 파일이 없거나 형식이 다르거나 계산이 실패하면 null → check는 지금 규칙 이유(reasons)만 쓴다
 * - 포인트와 연결하지 않는다 (위험도를 일부러 올려 포인트를 받는 악용 방지, C-2 결정)
 * - 계산 함수(ipp_risk_transform ~ ipp_risk_reason_text)는 DB를 쓰지 않는다. ipp/tests/risk_test.php가 JSON의 예시로 확인한다
 */

define('IPP_RISK_FORMAT', 'risk-logreg/1');
define('IPP_RISK_LEVELS', array('low', 'mid', 'high'));

// 모델 JSON 읽기 (요청마다 한 번). 실패하면 null
function ipp_risk_model($path = null) {
    static $cache = array();
    $path = $path ?: IPP_RISK_MODEL_FILE;
    if (array_key_exists($path, $cache)) return $cache[$path];
    $model = null;
    if (is_file($path)) {
        $data = json_decode(file_get_contents($path), true);
        if (is_array($data) && isset($data['format'], $data['features'], $data['coef'], $data['intercept'])
            && $data['format'] === IPP_RISK_FORMAT && count($data['features']) === count($data['coef'])) {
            $model = $data;
        }
    }
    return $cache[$path] = $model;
}

// 원시 값 하나를 숫자로. null, '', 숫자가 아니면 null (모름)
function ipp_risk_num($v) {
    if ($v === null || $v === '' || is_bool($v) || !is_numeric($v)) return null;
    $v = (float)$v;
    return is_nan($v) ? null : $v;
}

// 특성 하나의 변환 값. 모름이면 null ('missing' 종류는 0/1). ai/risk/model.py transform_one과 같다
function ipp_risk_transform($spec, $raw) {
    $v    = ipp_risk_num(isset($raw[$spec['raw']]) ? $raw[$spec['raw']] : null);
    $kind = $spec['kind'];
    if ($kind === 'missing') return $v === null ? 1.0 : 0.0;
    if ($v === null) return null;
    switch ($kind) {
        case 'flag_hour': $x = in_array((int)$v, $spec['hours']) ? 1.0 : 0.0; break;
        case 'flag_ge':   $x = $v >= $spec['value'] ? 1.0 : 0.0; break;
        case 'flag_le':   $x = $v <= $spec['value'] ? 1.0 : 0.0; break;
        case 'log':       $x = log(max($v, 1e-9) / $spec['scale']); break;
        case 'log1p':     $x = log1p(max($v, 0.0)); break;
        case 'linear':    $x = $v / $spec['scale']; break;
        default:          throw new Exception('알 수 없는 kind: '.$kind);
    }
    if (isset($spec['clip'])) $x = min(max($x, $spec['clip'][0]), $spec['clip'][1]);
    return $x;
}

// 원시 값 → array('prob' => 0~1, 'reasons' => [[group, 기여], ...] 큰 순서, 'logit' => 로그오즈)
// 이유: 특성별 기여(계수 × 표준화 값)를 group별로 더해 reason_min 이상인 것
function ipp_risk_predict($model, $raw) {
    $logit  = (float)$model['intercept'];
    $groups = array();
    foreach ($model['features'] as $i => $spec) {
        $x = ipp_risk_transform($spec, $raw);
        $z = ($x === null) ? 0.0 : ($x - $spec['mean']) / $spec['std'];
        $c = $model['coef'][$i] * $z;
        $logit += $c;
        if (!empty($spec['group'])) {
            $groups[$spec['group']] = (isset($groups[$spec['group']]) ? $groups[$spec['group']] : 0.0) + $c;
        }
    }
    $reasons = array();
    foreach ($groups as $g => $c) {
        if ($c >= $model['reason_min']) $reasons[] = array($g, $c);
    }
    usort($reasons, function ($a, $b) { return $b[1] <=> $a[1]; });
    return array('prob' => 1 / (1 + exp(-$logit)), 'reasons' => $reasons, 'logit' => $logit);
}

// 위험도 → low / mid / high (기준: IPP_RISK_LEVEL_MID, IPP_RISK_LEVEL_HIGH)
function ipp_risk_level($prob, $mid = null, $high = null) {
    $mid  = ($mid === null)  ? IPP_RISK_LEVEL_MID  : $mid;
    $high = ($high === null) ? IPP_RISK_LEVEL_HIGH : $high;
    if ($prob >= $high) return 'high';
    if ($prob >= $mid)  return 'mid';
    return 'low';
}

// 단계별 팝업 머리 문구 (문구는 이 함수와 ipp_risk_reason_text 두 곳에서만 정한다)
// 낮음은 이유 없이 가벼운 확인만 (C-2 결정)
function ipp_risk_message($level) {
    switch ($level) {
        case 'high': return '충동구매일 가능성이 높아 보여요. 24시간만 담아 두고 다시 생각해 볼까요?';
        case 'mid':  return '잠깐만요, 이번 결제는 조금 서두르는 것 같아요.';
        case 'low':  return '결제하기 전에 한 번만 확인해요. 꼭 필요한 물건인가요?';
    }
    return '';
}

// 이유 group 코드 → 화면에 보일 문구. $raw는 예측에 쓴 원시 값
function ipp_risk_reason_text($code, $raw) {
    $n = function ($k) use ($raw) { return isset($raw[$k]) ? ipp_risk_num($raw[$k]) : null; };
    switch ($code) {
        case 'night':     return '밤 11시~새벽 4시 사이의 심야 쇼핑이에요.';
        case 'evening':   return '하루를 마무리하는 늦은 저녁 시간이에요.';
        case 'weekend':   return '여유 있는 주말이라 구경하다 사기 쉬워요.';
        case 'payday':    return '월급일 직후예요. 통장이 넉넉해 보일 때 지출이 늘기 쉬워요.';
        case 'amount':    return $n('amount') ? number_format($n('amount')).'원으로 금액이 커요.' : '금액이 커요.';
        case 'amount_ratio':
            $r = $n('amount_ratio');
            return ($r && $r >= 1.5) ? '평소 결제 금액의 '.rtrim(rtrim(number_format($r, 1), '0'), '.').'배예요.' : '평소보다 큰 금액이에요.';
        case 'discount':  return $n('discount_rate') ? (int)$n('discount_rate').'% 할인이라 지금 사야 이득인 것처럼 느껴질 수 있어요.' : '할인 중인 상품이에요.';
        case 'pressure':  return "'오늘만', '품절 임박' 같은 서두르게 하는 문구가 있었어요.";
        case 'views':     return '최근 24시간 동안 이 쇼핑몰 상품을 '.(int)$n('product_views_24h').'번 봤어요.';
        case 'same_item': return '같은 상품을 '.(int)$n('same_item_views_24h').'번 다시 봤어요.';
        case 'browse':
            $sec = $n('browse_sec');
            if ($sec === null) return '상품을 오래 살펴보지 않고 결제하려고 해요.';
            return ($sec < 60) ? '상품을 보고 1분도 안 돼 결제하려고 해요.' : '상품을 보고 '.(int)floor($sec / 60).'분 만에 결제하려고 해요.';
        case 'frequency': return '최근 7일 동안 결제 화면에 '.(int)$n('checkouts_7d').'번 들어갔어요.';
        case 'history':   return "지난 팝업에서 '그래도 구매'를 고른 적이 많아요.";
        case 'cooldown':  return '담아 둔 상품을 기다리지 못하고 산 적이 있어요.';
    }
    return '';
}

// 가장 최근 월급일(오늘 포함) 이후 경과일. 월급일이 그 달에 없으면 그 달 말일 (ai/features.py days_since_payday와 같다)
function ipp_risk_days_since_payday($ts, $payday) {
    $payday_of = function ($y, $m) use ($payday) {
        $last = (int)date('t', mktime(0, 0, 0, $m, 1, $y));
        return mktime(0, 0, 0, $m, min($payday, $last), $y);
    };
    $today = mktime(0, 0, 0, (int)date('n', $ts), (int)date('j', $ts), (int)date('Y', $ts));
    $p = $payday_of((int)date('Y', $ts), (int)date('n', $ts));
    if ($today < $p) {
        $y = (int)date('Y', $ts); $m = (int)date('n', $ts) - 1;
        if ($m < 1) { $m = 12; $y--; }
        $p = $payday_of($y, $m);
    }
    return (int)round(($today - $p) / 86400);
}

// (구매 수 + prior×weight) / (결정 수 + weight). 기록이 적으면 prior 쪽으로 당긴다
function ipp_risk_smooth($k, $n, $prior, $weight) {
    return round(($k + $prior * $weight) / ($n + $weight), 4);
}

// check 요청의 데스크톱 숫자 특성 정리. features가 없으면(예전 데스크톱) 할인율만 예전 칸에서
function ipp_risk_request_features($body) {
    $f   = (isset($body['features']) && is_array($body['features'])) ? $body['features'] : array();
    $int = function ($k, $lo, $hi) use ($f) {
        $v = isset($f[$k]) ? ipp_risk_num($f[$k]) : null;
        return ($v === null) ? null : (int)max($lo, min($hi, round($v)));
    };
    if (array_key_exists('discount_rate', $f)) {
        $rate = $int('discount_rate', 0, 99);
    } else {
        $old  = isset($body['discount_rate']) ? ipp_risk_num($body['discount_rate']) : null;
        $rate = ($old !== null && $old > 0 && $old <= 99) ? (int)$old : null;   // 예전 칸의 0은 '모름'과 '할인 없음'을 구분 못 함
    }
    return array(
        'discount_rate'       => $rate,
        'pressure'            => (int)($int('pressure', 0, 1) ?: 0),
        'product_views_24h'   => (int)($int('product_views_24h', 0, 1000) ?: 0),
        'same_item_views_24h' => (int)($int('same_item_views_24h', 0, 1000) ?: 0),
        'browse_sec'          => $int('browse_sec', 0, 86400)
    );
}

// 원시 값 전체 (ai/risk/schema.py RAW 순서). DB에서는 지금 시각 이전 기록만 본다 (이번 기록은 아직 저장 전)
function ipp_risk_raw($mb_id, $price, $req, $p, $now = null) {
    global $g5;
    $now = $now ?: G5_TIME_YMDHIS;
    $ts  = strtotime($now);
    $mb  = sql_real_escape_string($mb_id);
    $bl  = $g5['ipp_block_log_table'];
    $since = function ($days) use ($ts) { return date('Y-m-d H:i:s', $ts - (int)$days * 86400); };
    $amount = ($price > 0) ? (int)$price : null;

    $ratio  = ipp_risk_amount_ratio($mb_id, $amount, $p, $now);

    $row = sql_fetch(" SELECT COUNT(*) AS cnt FROM {$bl}
                       WHERE mb_id = '{$mb}' AND bl_is_checkout = 1
                         AND bl_datetime >= '".$since($p['checkouts_window_days'])."' AND bl_datetime < '{$now}' ");
    $checkouts = (int)$row['cnt'];

    // 과거 선택: buy·hold→failed = 구매, giveup·hold→success/gaveup = 참음. close, 결과 모르는 hold는 뺀다
    $buy = $n = $cd_fail = $cd_n = 0;
    $res = sql_query(" SELECT b.bl_decision, c.cd_status FROM {$bl} b
                       LEFT JOIN {$g5['ipp_cooldown_table']} c ON c.cd_id = b.bl_cd_id
                       WHERE b.mb_id = '{$mb}' AND b.bl_is_checkout = 1 AND b.bl_decision IN ('buy', 'giveup', 'hold')
                         AND b.bl_datetime >= '".$since($p['history_window_days'])."' AND b.bl_datetime < '{$now}' ");
    while ($r = sql_fetch_array($res)) {
        $label = ipp_risk_label($r['bl_decision'], (string)$r['cd_status']);
        if ($label === null) continue;
        $n++; $buy += $label;
        if ($r['bl_decision'] === 'hold') { $cd_n++; $cd_fail += $label; }
    }

    $f = $req;
    return array(
        'hour'                => (int)date('G', $ts),
        'weekday'             => (int)date('N', $ts) - 1,
        'days_since_payday'   => ipp_risk_days_since_payday($ts, $p['payday']),
        'amount'              => $amount,
        'discount_rate'       => $f['discount_rate'],
        'pressure'            => $f['pressure'],
        'product_views_24h'   => $f['product_views_24h'],
        'same_item_views_24h' => $f['same_item_views_24h'],
        'browse_sec'          => $f['browse_sec'],
        'amount_ratio'        => $ratio,
        'checkouts_7d'        => $checkouts,
        'buy_rate'            => ipp_risk_smooth($buy, $n, $p['history_prior'], $p['history_weight']),
        'cooldown_fail_rate'  => ipp_risk_smooth($cd_fail, $cd_n, $p['cooldown_prior'], $p['cooldown_weight'])
    );
}

// 금액 비율: $now 이전 90일 결제 화면 금액 평균 대비 (금액을 읽은 기록만). 금액 모름이면 null, 이전 금액이 적으면 1.0
function ipp_risk_amount_ratio($mb_id, $amount, $p, $now) {
    global $g5;
    if (!$amount) return null;
    $since = date('Y-m-d H:i:s', strtotime($now) - (int)$p['ratio_window_days'] * 86400);
    $row = sql_fetch(" SELECT COUNT(*) AS cnt, AVG(bl_price) AS avg FROM {$g5['ipp_block_log_table']}
                       WHERE mb_id = '".sql_real_escape_string($mb_id)."' AND bl_is_checkout = 1 AND bl_price > 0
                         AND bl_datetime >= '{$since}' AND bl_datetime < '".sql_real_escape_string($now)."' ");
    return ((int)$row['cnt'] >= $p['ratio_min_count'] && $row['avg'] > 0) ? round($amount / $row['avg'], 4) : 1.0;
}

// 팝업 결정 → 라벨 1/0, 학습에서 뺄 것은 null (ai/risk/schema.py label_of)
function ipp_risk_label($decision, $cd_status = '') {
    if ($decision === 'buy')    return 1;
    if ($decision === 'giveup') return 0;
    if ($decision === 'hold') {
        if ($cd_status === 'failed') return 1;
        if ($cd_status === 'success' || $cd_status === 'gaveup') return 0;
    }
    return null;
}

// 결제 화면 check의 위험도. 모델이 꺼졌거나 없거나 실패하면 null
// 돌려주는 값: risk, level, message, reasons [{code, text}] (낮음이어도 채움, 최대 IPP_RISK_REASON_MAX개),
//   codes(모든 이유 코드, 기록용), show_reasons(보통 이상만 true: 낮음은 이유 없이 확인 문구만), model, raw
function ipp_risk_assess($mb_id, $price, $req) {
    if (!IPP_USE_RISK_MODEL) return null;
    $model = ipp_risk_model();
    if (!$model) return null;
    try {
        $raw = ipp_risk_raw($mb_id, $price, $req, $model['raw_params']);
        return ipp_risk_result($model, $raw);
    } catch (Throwable $e) {
        return null;
    }
}

// 원시 값 → 위험도 결과 (ipp_risk_assess, ipp_risk_reassess 공용)
function ipp_risk_result($model, $raw) {
    $pred    = ipp_risk_predict($model, $raw);
    $level   = ipp_risk_level($pred['prob']);
    $reasons = array();
    foreach (array_slice($pred['reasons'], 0, IPP_RISK_REASON_MAX) as $r) {
        $reasons[] = array('code' => $r[0], 'text' => ipp_risk_reason_text($r[0], $raw));
    }
    return array(
        'risk'         => round($pred['prob'], 4),
        'level'        => $level,
        'message'      => ipp_risk_message($level),
        'reasons'      => $reasons,
        'codes'        => array_map(function ($r) { return $r[0]; }, $pred['reasons']),   // 기록용: 개수 제한 없이 모두
        'show_reasons' => $level !== 'low',
        'model'        => (string)$model['version'],
        'raw'          => $raw
    );
}

// 감지 기록에 위험도 예측을 적는다 (010_block_log_risk.sql). 원시 값은 숫자만 JSON으로
function ipp_block_log_set_risk($bl_id, $assess) {
    global $g5;
    if ((int)$bl_id <= 0 || !$assess) return;
    $codes = implode(',', $assess['codes']);
    $raw   = json_encode($assess['raw']);
    sql_query(" UPDATE {$g5['ipp_block_log_table']}
                SET bl_risk         = '".sprintf('%.4f', $assess['risk'])."',
                    bl_risk_level   = '".sql_real_escape_string($assess['level'])."',
                    bl_risk_model   = '".sql_real_escape_string(mb_substr($assess['model'], 0, 40))."',
                    bl_risk_reasons = '".sql_real_escape_string(mb_substr($codes, 0, 255))."',
                    bl_risk_raw     = '".sql_real_escape_string($raw)."'
                WHERE bl_id = '".(int)$bl_id."' ");
}

// 결제 금액을 나중에 채운 감지 기록의 위험도를 다시 계산한다 (amount action, 011_block_log_risk_update.sql)
// check 때 저장한 원시 값(bl_risk_raw)에서 금액과 금액 비율만 바꾼다. 금액 비율은 check 시각(bl_datetime) 이전 기록으로 계산하고,
// 시각·상품 화면 숫자·과거 기록 특성은 check 때 값 그대로 쓴다 (그 사이 생긴 기록이 섞이지 않게).
// check 때 위험도를 계산하지 않았거나(모델 꺼짐/없음) 모델이 지금 없으면 null
function ipp_risk_reassess($mb_id, $bl_id, $price) {
    global $g5;
    if (!IPP_USE_RISK_MODEL) return null;
    $model = ipp_risk_model();
    if (!$model) return null;
    $row = sql_fetch(" SELECT bl_datetime, bl_risk_raw FROM {$g5['ipp_block_log_table']}
                       WHERE bl_id = '".(int)$bl_id."' AND mb_id = '".sql_real_escape_string($mb_id)."' ");
    $raw = ($row && $row['bl_risk_raw']) ? json_decode($row['bl_risk_raw'], true) : null;
    if (!is_array($raw)) return null;
    try {
        $raw['amount']       = (int)$price;
        $raw['amount_ratio'] = ipp_risk_amount_ratio($mb_id, (int)$price, $model['raw_params'], $row['bl_datetime']);
        return ipp_risk_result($model, $raw);
    } catch (Throwable $e) {
        return null;
    }
}

// 다시 계산한 위험도를 기록한다. 처음(check 때) 값은 *_first로 옮긴다 (처음 한 번만. 이미 다시 계산했으면 처음 값을 덮지 않는다)
function ipp_block_log_update_risk($bl_id, $assess) {
    global $g5;
    if ((int)$bl_id <= 0 || !$assess) return;
    $codes = implode(',', $assess['codes']);
    sql_query(" UPDATE {$g5['ipp_block_log_table']}
                SET bl_risk_first         = IF(bl_risk_updated_datetime IS NULL, bl_risk, bl_risk_first),
                    bl_risk_level_first   = IF(bl_risk_updated_datetime IS NULL, bl_risk_level, bl_risk_level_first),
                    bl_risk_reasons_first = IF(bl_risk_updated_datetime IS NULL, bl_risk_reasons, bl_risk_reasons_first),
                    bl_risk                  = '".sprintf('%.4f', $assess['risk'])."',
                    bl_risk_level            = '".sql_real_escape_string($assess['level'])."',
                    bl_risk_model            = '".sql_real_escape_string(mb_substr($assess['model'], 0, 40))."',
                    bl_risk_reasons          = '".sql_real_escape_string(mb_substr($codes, 0, 255))."',
                    bl_risk_raw              = '".sql_real_escape_string(json_encode($assess['raw']))."',
                    bl_risk_updated_datetime = '".G5_TIME_YMDHIS."'
                WHERE bl_id = '".(int)$bl_id."' ");
}

// 응답에 넣을 위험도 칸 (check와 amount 공용). 계산하지 않았으면 null/빈 값
function ipp_risk_response($assess) {
    return array(
        'risk'              => $assess ? $assess['risk'] : null,
        'risk_level'        => $assess ? $assess['level'] : '',
        'risk_message'      => $assess ? $assess['message'] : '',
        'risk_reasons'      => $assess ? $assess['reasons'] : array(),
        'risk_show_reasons' => $assess ? $assess['show_reasons'] : false,
        'risk_model'        => $assess ? $assess['model'] : ''
    );
}
