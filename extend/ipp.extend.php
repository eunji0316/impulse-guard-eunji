<?php
if (!defined('_GNUBOARD_')) exit;

/* ===== 기능 스위치 (false로 바꾸면 해당 기능이 꺼짐) ===== */
define('IPP_USE_BANK',       true);   // 계좌 연동
define('IPP_USE_COOLDOWN',   true);   // 쿨다운 타임머신
define('IPP_USE_CHARACTER',  false);  // 캐릭터 육성
define('IPP_USE_CHALLENGE',  false);  // 챌린지, 리더보드
define('IPP_USE_SIMULATION', false);  // 미래가치 시뮬레이션
define('IPP_USE_GIFTICON',   true);   // 기프티콘 리워드 교환
define('IPP_USE_SETTING',    true);   // 회원별 차단 설정, 차단 기록
define('IPP_USE_STATS',      true);   // 통계 화면
define('IPP_USE_CLIENT_API', true);   // 외부 프로그램 API (토큰 인증, ipp/api/client.php). 데스크톱, 팀원 프로젝트, 확장 프로그램 공용
define('IPP_USE_EXTENSION',  false);  // 그중 크롬 확장 프로그램의 호출 (보류 중이라 꺼 둠, extension/README.md)

/* ===== 포인트 기준 ===== */
define('IPP_POINT_RATE',          0.01);  // 절약 금액의 1%
define('IPP_POINT_MIN',           10);
define('IPP_POINT_MAX',           500);
define('IPP_COOLDOWN_MULTIPLIER', 2);     // 쿨다운 성공 시 배수
define('IPP_DAILY_LIMIT',         1000);  // 하루 획득 상한

/* ===== 쿨다운 기준 ===== */
//define('IPP_COOLDOWN_HOURS', 0.02);   // 약 1분 (테스트용)
define('IPP_COOLDOWN_HOURS', 24); // 24시간 (실제 서비스용)

/* ===== 기프티콘 기준 ===== */
define('IPP_GIFTICON_EXPIRE_DAYS', 30);   // 쿠폰 유효기간(일)

/* ===== 충동구매 감지 기준 ===== */
define('IPP_DETECT_NIGHT_START', 23);     // 23시부터
define('IPP_DETECT_NIGHT_END',   4);      // 새벽 4시 전까지를 심야로 판단
define('IPP_DETECT_AMOUNT',      50000);  // 이 금액 이상이면 고액 결제
define('IPP_DETECT_CATEGORIES',  array('shopping', 'fashion', 'game', 'delivery'));

/* ===== 차단 설정 기준 ===== */
// 차단할 수 있는 사이트 (코드 => 이름, 도메인). 크롬 확장 프로그램도 이 목록을 쓴다.
define('IPP_BLOCK_SITES', array(
    'naver'   => array('name' => '네이버쇼핑', 'domain' => 'shopping.naver.com'),
    'coupang' => array('name' => '쿠팡',       'domain' => 'coupang.com'),
    'gmarket' => array('name' => 'G마켓',      'domain' => 'gmarket.co.kr'),
    '11st'    => array('name' => '11번가',     'domain' => '11st.co.kr'),
    'zigzag'  => array('name' => '지그재그',   'domain' => 'zigzag.kr'),
    'musinsa' => array('name' => '무신사',     'domain' => 'musinsa.com')
));
define('IPP_DEFAULT_KEYWORDS',      array('세일', '할인', '특가'));  // 새 회원의 기본 차단 키워드
define('IPP_KEYWORD_MAX',           20);  // 키워드 최대 개수
define('IPP_KEYWORD_LEN',           20);  // 키워드 하나의 최대 글자 수
define('IPP_BLOCK_CUSTOM_MAX_DAYS', 30);  // 직접 설정할 수 있는 최대 차단 기간(일)

/* ===== 외부 프로그램 API 기준 ===== */
define('IPP_TOKEN_TOUCH_SEC', 60);  // 토큰 마지막 사용 시각은 이 간격(초)마다 한 번만 갱신
define('IPP_CLIENTS', array('extension', 'desktop'));  // API를 부를 수 있는 프로그램 (요청의 client 값)

/* ===== 경로 ===== */
define('IPP_PATH', G5_PATH.'/ipp');
define('IPP_URL',  G5_URL.'/ipp');

/* ===== 충동구매 위험도 모델 (C-2, ipp/lib/risk.lib.php) ===== */
// 결제 화면 check에서 위험도(0~1), 단계, 이유를 계산한다. 끄거나 모델 파일이 없으면 지금 규칙 이유(reasons)만
// 위험도는 팝업 문구에만 쓰고 포인트와는 연결하지 않는다
define('IPP_USE_RISK_MODEL',  true);
define('IPP_RISK_MODEL_FILE', IPP_PATH.'/model/risk_model.json');   // ai/risk/train.py가 만든다
define('IPP_RISK_LEVEL_MID',  0.3);    // 이 이상이면 보통 (이유 문장을 보임)
define('IPP_RISK_LEVEL_HIGH', 0.55);   // 이 이상이면 높음
define('IPP_RISK_REASON_MAX', 3);      // 응답에 담는 이유 수 (기록에는 모두)

/* ===== 예측 서버 (C-3, ai/serve, ipp/lib/risk.lib.php) ===== */
// 'on'이면 위험도 확률과 이유를 예측 서버(FastAPI)에서 받는다. 'off'면 지금처럼 PHP가 계산한다
// 예측 서버가 꺼져 있거나 실패하면 자동으로 PHP 계산을 쓰고, IPP_RISK_SERVER_SKIP_SEC 동안 다시 부르지 않는다
// 시연 모드: 환경변수 IPP_RISK_SERVER=on으로 서버를 켜면 'on' (scripts/start.ps1 -Demo). 환경변수가 없으면 'off'
define('IPP_RISK_SERVER',           getenv('IPP_RISK_SERVER') === 'on' ? 'on' : 'off');
define('IPP_RISK_SERVER_URL',       'http://127.0.0.1:8002');   // 127.0.0.1, localhost, [::1]만 허용
define('IPP_RISK_SERVER_TIMEOUT',   0.3);   // 초. check가 이보다 더 늦어지지 않는다
define('IPP_RISK_SERVER_SKIP_SEC',  60);
define('IPP_RISK_SERVER_DOWN_FILE', G5_DATA_PATH.'/ipp_risk_server_down.txt');   // 마지막 실패 시각 (data/는 Git 제외)

/* ===== LLM 주간 리포트 요약 (5, 선택, ai/serve/message_api.py, ipp/lib/report.lib.php) ===== */
// true면 통계 화면에 'AI 요약 보기' 버튼이 생긴다. 누르면 이번 주·지난주 집계 숫자를 예측 서버로 보내 Claude API 요약을 받는다
// 보내는 값: 숫자와 위험도 이유 코드만 (회원 아이디, 쇼핑몰 이름, 상품명 없음). 요약은 저장하지 않는다
// API 키는 예측 서버의 환경변수(ANTHROPIC_API_KEY)에만 둔다. 꺼져 있거나 실패하면 통계 화면은 지금 그대로
// 시연 모드: 환경변수 IPP_USE_LLM=1로 서버를 켜면 true (scripts/start.ps1 -Demo -Llm). 환경변수가 없으면 false
define('IPP_USE_LLM',        getenv('IPP_USE_LLM') === '1');
define('IPP_LLM_SERVER_URL', 'http://127.0.0.1:8002');   // 예측 서버. 127.0.0.1, localhost, [::1]만 허용
define('IPP_LLM_TIMEOUT',    10);    // 초. 버튼을 누른 뒤 최대로 기다리는 시간
define('IPP_LLM_SKIP_SEC',   60);    // 예측 서버가 없거나 키가 없으면 이 시간 동안 다시 부르지 않음
define('IPP_LLM_DOWN_FILE',  G5_DATA_PATH.'/ipp_llm_server_down.txt');

/* ===== 테이블 이름 ===== */
$g5['ipp_account_table']     = G5_TABLE_PREFIX.'ipp_account';
$g5['ipp_transaction_table'] = G5_TABLE_PREFIX.'ipp_transaction';
$g5['ipp_cooldown_table']    = G5_TABLE_PREFIX.'ipp_cooldown';
$g5['ipp_reward_table']      = G5_TABLE_PREFIX.'ipp_reward';
$g5['ipp_coupon_table']      = G5_TABLE_PREFIX.'ipp_coupon';
$g5['ipp_setting_table']     = G5_TABLE_PREFIX.'ipp_setting';
$g5['ipp_block_log_table']   = G5_TABLE_PREFIX.'ipp_block_log';

/* ===== ipp/lib 안의 파일 자동 로드 ===== */
foreach (glob(IPP_PATH.'/lib/*.lib.php') as $ipp_lib) {
    include_once($ipp_lib);
}