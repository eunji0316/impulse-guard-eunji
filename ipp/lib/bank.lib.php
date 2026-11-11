<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 은행 연동 함수 모음
 * 실제 오픈뱅킹으로 전환할 때는 이 파일의 함수 내부만 교체한다.
 */

// 계좌 연결 (mock: 가짜 계좌번호 생성)
function ipp_bank_link($mb_id, $bank_name) {
    global $g5;
    $mb_id     = sql_real_escape_string($mb_id);
    $bank_name = sql_real_escape_string($bank_name);
    $masked    = sprintf('%03d-****-%04d', rand(100, 999), rand(0, 9999));
    $fintech   = 'MOCK'.date('YmdHis').rand(100, 999);

    sql_query(" INSERT INTO {$g5['ipp_account_table']}
                SET mb_id            = '{$mb_id}',
                    ac_bank_name     = '{$bank_name}',
                    ac_number_masked = '{$masked}',
                    ac_fintech_num   = '{$fintech}',
                    ac_status        = 'active',
                    ac_datetime      = '".G5_TIME_YMDHIS."' ");
    return sql_insert_id();
}

// 현재 연결된 계좌
function ipp_bank_get_account($mb_id) {
    global $g5;
    $mb_id = sql_real_escape_string($mb_id);
    return sql_fetch(" SELECT * FROM {$g5['ipp_account_table']}
                       WHERE mb_id = '{$mb_id}' AND ac_status = 'active'
                       ORDER BY ac_id DESC LIMIT 1 ");
}

// 충동구매 여부 판단 (1: 감지, 0: 정상)
// $text(가맹점명/상품명)와 $mb_id를 주면 회원 키워드도 검사한다.
// 키워드는 카테고리와 상관없이 적용한다 (확장 프로그램에서 온 상품은 카테고리를 모름)
function ipp_detect_impulse($amount, $category, $datetime, $text = '', $mb_id = '') {
    if (IPP_USE_SETTING && $text !== '' && $mb_id) {
        $st = ipp_setting_get($mb_id);
        if (ipp_keyword_match($text, $st['st_keywords']) !== '') return 1;
    }

    if (!in_array($category, IPP_DETECT_CATEGORIES)) return 0;

    $hour     = (int)date('G', strtotime($datetime));
    $is_night = ($hour >= IPP_DETECT_NIGHT_START || $hour < IPP_DETECT_NIGHT_END);
    $is_big   = ($amount >= IPP_DETECT_AMOUNT);

    return ($is_night || $is_big) ? 1 : 0;
}

// 충동구매로 본 이유 목록 [{code, text}] (B-3, 데스크톱 팝업과 콘솔에 보여 줌)
// 판단(어떤 code인지)과 문구(ipp_reason_text)를 나눠 두었다. 위험도 모델이 붙으면 code를 더하거나
// 문구 함수만 바꾸고, 응답 모양은 그대로 둔다. 목록이 비어 있지 않으면 is_impulse가 1이다
// code: checkout(결제 화면, B-4), keyword(회원 키워드), big(고액), night(심야). 중요한 것부터 담는다
// $ctx: is_checkout(데스크톱이 결제 화면을 감지함)
function ipp_impulse_reasons($amount, $category, $datetime, $text = '', $mb_id = '', $ctx = array()) {
    $found = array();   // code => 문구에 쓸 값
    if (!empty($ctx['is_checkout'])) $found['checkout'] = array();
    if (IPP_USE_SETTING && $text !== '' && $mb_id) {
        $st = ipp_setting_get($mb_id);
        $kw = ipp_keyword_match($text, $st['st_keywords']);
        if ($kw !== '') $found['keyword'] = array('keyword' => $kw);
    }
    if (in_array($category, IPP_DETECT_CATEGORIES)) {
        if ($amount >= IPP_DETECT_AMOUNT) $found['big'] = array('amount' => IPP_DETECT_AMOUNT);
        $hour = (int)date('G', strtotime($datetime));
        if ($hour >= IPP_DETECT_NIGHT_START || $hour < IPP_DETECT_NIGHT_END) {
            $found['night'] = array('start' => IPP_DETECT_NIGHT_START, 'end' => IPP_DETECT_NIGHT_END);
        }
    }
    $reasons = array();
    foreach ($found as $code => $p) $reasons[] = array('code' => $code, 'text' => ipp_reason_text($code, $p));
    return $reasons;
}

// 이유 코드 → 화면에 보일 문구 (문구는 이 함수 한 곳에서만 정한다)
function ipp_reason_text($code, $p = array()) {
    switch ($code) {
        case 'checkout': return '결제 직전이에요. 정말 지금 필요한 물건인지 한 번만 더 생각해 봐요.';
        case 'keyword':  return "'{$p['keyword']}' 키워드가 들어 있어요.";
        case 'big':      return number_format($p['amount']).'원 이상의 큰 금액이에요.';
        case 'night':    return ipp_hour_label($p['start']).'~'.ipp_hour_label($p['end']).' 사이의 심야 쇼핑이에요.';
    }
    return '';
}

// 23 → '밤 11시', 4 → '새벽 4시', 19 → '저녁 7시'
function ipp_hour_label($hour) {
    $hour = (int)$hour % 24;
    if ($hour < 6)  return '새벽 '.($hour === 0 ? 12 : $hour).'시';
    if ($hour < 12) return '오전 '.$hour.'시';
    if ($hour < 18) return '오후 '.($hour === 12 ? 12 : $hour - 12).'시';
    if ($hour < 21) return '저녁 '.($hour - 12).'시';
    return '밤 '.($hour - 12).'시';
}

// 거래 저장 후 [거래 ID, 감지 여부] 반환
function ipp_bank_save_transaction($mb_id, $ac_id, $type, $amount, $merchant, $category, $datetime) {
    global $g5;
    $is_impulse = ($type === 'pay') ? ipp_detect_impulse($amount, $category, $datetime, $merchant, $mb_id) : 0;

    sql_query(" INSERT INTO {$g5['ipp_transaction_table']}
                SET mb_id           = '".sql_real_escape_string($mb_id)."',
                    ac_id           = '".(int)$ac_id."',
                    tr_type         = '".sql_real_escape_string($type)."',
                    tr_amount       = '".(int)$amount."',
                    tr_merchant     = '".sql_real_escape_string($merchant)."',
                    tr_category     = '".sql_real_escape_string($category)."',
                    tr_datetime     = '".sql_real_escape_string($datetime)."',
                    tr_is_impulse   = '{$is_impulse}',
                    tr_reg_datetime = '".G5_TIME_YMDHIS."' ");

    return array('tr_id' => sql_insert_id(), 'is_impulse' => $is_impulse);
}

// 최근 거래 목록
function ipp_bank_get_transactions($mb_id, $limit = 20) {
    global $g5;
    $mb_id = sql_real_escape_string($mb_id);
    $list  = array();
    $res   = sql_query(" SELECT * FROM {$g5['ipp_transaction_table']}
                         WHERE mb_id = '{$mb_id}'
                         ORDER BY tr_datetime DESC LIMIT ".(int)$limit);
    while ($row = sql_fetch_array($res)) $list[] = $row;
    return $list;
}