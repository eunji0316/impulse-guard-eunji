<?php
// 5 LLM 주간 리포트 요약 (통계 화면의 'AI 요약 보기' 버튼, 로그인 세션)
// 응답: {"ok": true, "summary": {headline, summary, tip}} / 요약이 없으면 {"ok": true, "summary": null}
// 요약은 저장하지 않는다. 꺼져 있거나 실패하면 summary가 null이고 화면은 지금 그대로
include_once('../_common.php');
header('Content-Type: application/json; charset=utf-8');

function ipp_report_json($ok, $data = array()) {
    echo json_encode(array_merge(array('ok' => $ok), $data), JSON_UNESCAPED_UNICODE);
    exit;
}

if (!IPP_USE_STATS || !defined('IPP_USE_LLM') || !IPP_USE_LLM) ipp_report_json(false, array('msg' => 'AI 요약 기능이 꺼져 있습니다.'));
if (!$is_member)                           ipp_report_json(false, array('msg' => '로그인이 필요합니다.'));
if ($_SERVER['REQUEST_METHOD'] !== 'POST') ipp_report_json(false, array('msg' => '잘못된 요청입니다.'));

$mb_id = $member['mb_id'];
if (IPP_USE_COOLDOWN) ipp_cooldown_settle($mb_id);   // 통계 화면과 같은 절약 금액이 되도록

$input = ipp_report_input($mb_id);
if (!ipp_report_has_data($input)) ipp_report_json(true, array('summary' => null, 'msg' => '최근 2주 동안 쇼핑 기록이 없어요.'));

$summary = ipp_report_summary($input);
ipp_report_json(true, array('summary' => $summary, 'msg' => $summary ? '' : '지금은 요약을 만들 수 없어요.'));
