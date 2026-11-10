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
// ipp_detect_impulse()와 같은 기준이다. 목록이 비어 있지 않으면 is_impulse가 1이다
// code: keyword(회원 키워드), big(고액), night(심야). 중요한 것부터 담는다
function ipp_impulse_reasons($amount, $category, $datetime, $text = '', $mb_id = '') {
    $reasons = array();
    if (IPP_USE_SETTING && $text !== '' && $mb_id) {
        $st = ipp_setting_get($mb_id);
        $kw = ipp_keyword_match($text, $st['st_keywords']);
        if ($kw !== '') $reasons[] = array('code' => 'keyword', 'text' => "'{$kw}' 키워드가 들어 있어요.");
    }
    if (!in_array($category, IPP_DETECT_CATEGORIES)) return $reasons;

    if ($amount >= IPP_DETECT_AMOUNT) {
        $reasons[] = array('code' => 'big', 'text' => number_format(IPP_DETECT_AMOUNT).'원 이상의 큰 금액이에요.');
    }
    $hour = (int)date('G', strtotime($datetime));
    if ($hour >= IPP_DETECT_NIGHT_START || $hour < IPP_DETECT_NIGHT_END) {
        $reasons[] = array('code' => 'night', 'text' => ipp_hour_label(IPP_DETECT_NIGHT_START).'~'
            .ipp_hour_label(IPP_DETECT_NIGHT_END).' 사이의 심야 쇼핑이에요.');
    }
    return $reasons;
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