<?php
/*
 * 시연용 데모 회원과 최근 2주 기록 넣기·지우기 (7 마무리)
 *
 * 사용 (저장소 루트에서, MariaDB가 켜진 상태):
 *   php scripts/demo_seed.php add      데모 회원(demo)과 최근 2주 결제 화면·차단·담아두기 기록을 넣고,
 *                                      데스크톱용 설정 파일 desktop/local_config.demo.json(토큰 포함, Git 제외)을 만든다
 *   php scripts/demo_seed.php remove   데모 회원과 그 회원의 기록을 모두 지우고 설정 파일도 지운다
 *   php scripts/demo_seed.php status   데모 회원과 기록 수
 *
 * - 데모 회원 아이디는 demo, 비밀번호는 demo1234 (로컬 시연용). admin 등 다른 회원 기록은 건드리지 않는다
 * - 기록은 실행 시각 기준 최근 14일에 만든다 (통계 화면, AI 요약, 위험도의 과거 선택 비율에 쓰임). 상품명은 '데모 상품 N'
 * - 시연 중 데스크톱이 남긴 기록도 회원이 demo이므로 remove로 함께 지워진다
 * - 웹으로는 실행되지 않는다 (php -S가 저장소 전체를 열어 두므로 CLI가 아니면 404)
 */
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

define('G5_IS_CLI', true);   // 그누보드 방문자 기록을 남기지 않는다
$_SERVER += array('HTTP_HOST' => 'localhost:8001', 'REQUEST_URI' => '/', 'SCRIPT_NAME' => '/index.php',
                  'REMOTE_ADDR' => '127.0.0.1', 'SERVER_PORT' => '8001', 'REQUEST_METHOD' => 'GET');
$root = dirname(__DIR__);
chdir($root.'/ipp');
include './_common.php';

const DEMO_ID   = 'demo';
const DEMO_PASS = 'demo1234';
$conf_file = $root.'/desktop/local_config.demo.json';
$cmd = isset($argv[1]) ? $argv[1] : 'status';

function demo_tables() {
    global $g5;
    // [테이블, 설명]. 회원 행은 마지막에 지운다
    return array(
        array($g5['ipp_block_log_table'], '감지·차단 기록'),
        array($g5['ipp_cooldown_table'], '담아두기'),
        array($g5['ipp_setting_table'], '설정·토큰'),
        array($g5['ipp_transaction_table'], 'mock 거래'),
        array($g5['ipp_account_table'], 'mock 계좌'),
        array($g5['ipp_coupon_table'], '쿠폰'),
        array($g5['point_table'], '포인트 내역'),
    );
}

function demo_status() {
    global $g5;
    $mb = sql_fetch(" SELECT mb_id, mb_datetime FROM {$g5['member_table']} WHERE mb_id = '".DEMO_ID."' ");
    echo $mb ? "데모 회원: ".DEMO_ID." (만든 시각 {$mb['mb_datetime']})\n" : "데모 회원 없음\n";
    foreach (demo_tables() as $t) {
        $r = sql_fetch(" SELECT COUNT(*) AS c FROM {$t[0]} WHERE mb_id = '".DEMO_ID."' ");
        echo "  {$t[1]}: {$r['c']}건\n";
    }
    return (bool)$mb;
}

function demo_remove($conf_file) {
    global $g5;
    foreach (demo_tables() as $t) sql_query(" DELETE FROM {$t[0]} WHERE mb_id = '".DEMO_ID."' ");
    sql_query(" DELETE FROM {$g5['member_table']} WHERE mb_id = '".DEMO_ID."' ");
    if (is_file($conf_file)) unlink($conf_file);
    echo "데모 회원과 기록을 지웠습니다.\n";
}

function demo_add($conf_file) {
    global $g5;
    $now = G5_SERVER_TIME;
    $at  = function ($days_ago, $hm) use ($now) { return date('Y-m-d', $now - $days_ago * 86400).' '.$hm.':00'; };

    sql_query(" INSERT INTO {$g5['member_table']}
                SET mb_id = '".DEMO_ID."', mb_password = '".get_encrypt_string(DEMO_PASS)."',
                    mb_name = '시연', mb_nick = '시연회원', mb_nick_date = '".G5_TIME_YMD."', mb_email = 'demo@example.com',
                    mb_homepage = '', mb_tel = '', mb_hp = '', mb_zip1 = '', mb_zip2 = '', mb_addr1 = '', mb_addr2 = '', mb_addr3 = '',
                    mb_addr_jibeon = '', mb_signature = '', mb_profile = '', mb_memo = '', mb_lost_certify = '',
                    mb_today_login = '".G5_TIME_YMDHIS."', mb_datetime = '".G5_TIME_YMDHIS."', mb_ip = '127.0.0.1',
                    mb_level = 2, mb_recommend = '', mb_login_ip = '127.0.0.1', mb_mailling = 0, mb_sms = 0, mb_open = 0,
                    mb_open_date = '".G5_TIME_YMD."', mb_email_certify = '".G5_TIME_YMDHIS."',
                    mb_1 = '', mb_2 = '', mb_3 = '', mb_4 = '', mb_5 = '', mb_6 = '', mb_7 = '', mb_8 = '', mb_9 = '', mb_10 = '' ");

    ipp_setting_get(DEMO_ID);                 // 기본 설정 행 (사이트, 키워드)
    $token = ipp_setting_regen_token(DEMO_ID);

    // 결제 화면: [며칠 전, 시각, 쇼핑몰, 금액, 할인율, 결정, 위험 단계, 위험도, 이유 코드]
    $checkouts = array(
        // 이번 주 (최근 7일): 참은 결정이 늘어난 주
        array(0, '00:40', 'musinsa', 129000, 30, 'hold',   'high', 0.6120, 'night,amount_ratio,discount'),
        array(1, '21:30', 'coupang',  45900, 20, 'giveup', 'mid',  0.4210, 'evening,discount'),
        array(2, '23:50', 'coupang',  89000,  0, 'giveup', 'high', 0.5810, 'night,amount_ratio'),
        array(3, '13:10', '11st',     32000,  0, 'buy',    'low',  0.2210, ''),
        array(4, '20:05', 'musinsa',  76000, 40, 'hold',   'mid',  0.4630, 'discount,same_item'),
        array(5, '22:15', 'zigzag',   28000, 15, 'close',  'mid',  0.3320, 'evening'),
        // 지난주 (그 전 7일): 그래도 구매가 많던 주
        array(7,  '01:20', 'coupang',  99000, 25, 'buy',    'high', 0.6630, 'night,amount_ratio,discount'),
        array(8,  '23:30', 'musinsa', 158000,  0, 'buy',    'high', 0.7010, 'night,amount_ratio,history'),
        array(9,  '12:40', 'coupang',  23000,  0, 'buy',    'low',  0.1980, ''),
        array(10, '22:10', '11st',     54000, 10, 'giveup', 'mid',  0.3870, 'evening'),
        array(11, '00:15', 'zigzag',   41000, 35, 'buy',    'mid',  0.5120, 'night,discount'),
        array(12, '19:00', 'coupang',  67000,  0, 'hold',   'mid',  0.3540, 'history'),
        array(13, '15:30', 'musinsa',  35000, 20, 'giveup', 'low',  0.2650, 'discount'),
    );
    $n = 0;
    foreach ($checkouts as $c) {
        $n++;
        list($ago, $hm, $site, $price, $rate, $dec, $level, $risk, $reasons) = $c;
        $dt = $at($ago, $hm);
        sql_query(" INSERT INTO {$g5['ipp_block_log_table']}
                    SET mb_id = '".DEMO_ID."', bl_client = 'desktop', bl_site = '{$site}', bl_url = '', bl_page = 'checkout',
                        bl_item_name = '데모 상품 {$n}', bl_price = {$price}, bl_discount_rate = {$rate}, bl_is_checkout = 1,
                        bl_event = 'detect', bl_decision = '{$dec}', bl_decision_datetime = '{$dt}',
                        bl_risk = {$risk}, bl_risk_level = '{$level}', bl_risk_model = 'demo-seed', bl_risk_reasons = '{$reasons}',
                        bl_datetime = '{$dt}' ");
        if ($dec === 'hold') {
            // 담아두기: 이번 주 2건은 참음(success), 지난주 1건은 참지 못하고 삼(failed)
            $status = ($ago < 7) ? 'success' : 'failed';
            $end = date('Y-m-d H:i:s', strtotime($dt) + ($status === 'success' ? 86400 : 6 * 3600));
            if (strtotime($end) > $now) $end = date('Y-m-d H:i:s', $now - 60);
            sql_query(" INSERT INTO {$g5['ipp_cooldown_table']}
                        SET mb_id = '".DEMO_ID."', cd_source = 'detect', cd_client = 'desktop', cd_item_name = '데모 상품 {$n}',
                            cd_amount = {$price}, cd_status = '{$status}', cd_start_datetime = '{$dt}',
                            cd_expire_datetime = '".date('Y-m-d H:i:s', strtotime($dt) + 86400)."', cd_end_datetime = '{$end}' ");
            sql_query(" UPDATE {$g5['ipp_block_log_table']} SET bl_cd_id = '".sql_insert_id()."'
                        WHERE mb_id = '".DEMO_ID."' AND bl_item_name = '데모 상품 {$n}' ");
        }
    }
    // 차단 시간에 막은 기록: 이번 주 4건, 지난주 1건
    foreach (array(array(1, '10:00', 'coupang'), array(2, '10:20', 'musinsa'), array(3, '22:00', 'coupang'),
                   array(5, '09:30', '11st'), array(9, '11:00', 'coupang')) as $b) {
        sql_query(" INSERT INTO {$g5['ipp_block_log_table']}
                    SET mb_id = '".DEMO_ID."', bl_client = 'desktop', bl_site = '{$b[2]}', bl_url = '', bl_page = 'product',
                        bl_event = 'blocked', bl_datetime = '".$at($b[0], $b[1])."' ");
    }

    $conf = array('server' => 'http://localhost:8001', 'token' => $token, 'timeout_sec' => 2);
    $example = $GLOBALS['root'].'/desktop/local_config.json';
    if (is_file($example)) {   // 지금 쓰는 설정의 자동 감지 설정을 이어받는다 (토큰만 데모 회원 것으로)
        $cur = json_decode(file_get_contents($example), true);
        if (is_array($cur)) $conf = array_merge($cur, $conf);
    }
    file_put_contents($conf_file, json_encode($conf, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)."\n");

    echo "데모 회원을 만들었습니다. 아이디 ".DEMO_ID.", 비밀번호 ".DEMO_PASS."\n";
    echo "데스크톱 설정: desktop/local_config.demo.json (scripts/start.ps1 -Demo가 이 파일을 씁니다)\n";
}

if ($cmd === 'status') {
    demo_status();
} elseif ($cmd === 'remove') {
    demo_remove($conf_file);
} elseif ($cmd === 'add') {
    $exists = sql_fetch(" SELECT mb_id FROM {$g5['member_table']} WHERE mb_id = '".DEMO_ID."' ");
    if ($exists) { echo "데모 회원이 이미 있습니다. 다시 만들려면 먼저 remove를 실행하세요.\n"; exit(1); }
    demo_add($conf_file);
    demo_status();
} else {
    echo "사용: php scripts/demo_seed.php add | remove | status\n";
    exit(1);
}
