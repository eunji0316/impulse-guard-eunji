<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_STATS);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

$mb_id = $member['mb_id'];
if (IPP_USE_COOLDOWN) ipp_cooldown_settle($mb_id);   // 만료된 쿨다운을 먼저 정산해야 절약 금액에 잡힌다

$today_blocked  = ipp_stats_today_blocked($mb_id);
$today_attempts = ipp_stats_today_attempts($mb_id);
$saved_7d       = ipp_stats_saved_7d($mb_id);
$avg_sec       = ipp_stats_avg_block_sec($mb_id);
$daily         = ipp_stats_daily_7d($mb_id);
$by_site       = ipp_stats_by_site($mb_id);
// 최근 7일 결제 화면 팝업 (데스크톱이 결제 화면에서 띄운 팝업과 고른 버튼, 위험 단계). 5 AI 요약과 같은 집계
$popup_7d      = ipp_report_week($mb_id, ipp_stats_since(7), G5_TIME_YMDHIS);
$popup_none    = max(0, $popup_7d['checkouts'] - $popup_7d['buy'] - $popup_7d['giveup'] - $popup_7d['hold']);   // 창을 닫았거나 아직 고르지 않음

$g5['title'] = '통계';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">
<p>
    <a href="<?php echo IPP_URL; ?>/cooldown.php">← 타임머신 보관함으로</a>
    <?php if (IPP_USE_SETTING) { ?>
    &nbsp;|&nbsp;
    <a href="<?php echo IPP_URL; ?>/setting.php">⚙️ 차단 설정</a>
    <?php } ?>
</p>

<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:20px;">
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;">
        <div style="color:#888;font-size:13px;">오늘 차단한 상품</div>
        <div style="font-size:22px;font-weight:bold;"><?php echo number_format($today_blocked); ?>개</div>
        <div style="color:#888;font-size:11px;">상품 페이지에서 막은 것</div>
    </div>
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;">
        <div style="color:#888;font-size:13px;">오늘 차단한 쇼핑 시도</div>
        <div style="font-size:22px;font-weight:bold;"><?php echo number_format($today_attempts); ?>회</div>
        <div style="color:#888;font-size:11px;">사이트 홈 차단까지 전부</div>
    </div>
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;">
        <div style="color:#888;font-size:13px;">최근 7일 예상 절약</div>
        <div style="font-size:22px;font-weight:bold;"><?php echo number_format($saved_7d); ?>원</div>
    </div>
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;">
        <div style="color:#888;font-size:13px;">최근 7일 차단</div>
        <div style="font-size:22px;font-weight:bold;"><?php echo number_format(array_sum($daily)); ?>회</div>
    </div>
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;">
        <div style="color:#888;font-size:13px;">평균 차단 시간</div>
        <div style="font-size:22px;font-weight:bold;"><?php echo ipp_format_sec($avg_sec); ?></div>
        <div style="color:#888;font-size:11px;">차단 화면에서 머문 시간</div>
    </div>
</div>

<h3>최근 7일 결제 화면 팝업</h3>
<?php if ($popup_7d['checkouts'] > 0) { ?>
<table style="width:100%;border-collapse:collapse;margin-bottom:8px;" border="1" cellpadding="6">
    <tr><th>결제 화면 감지</th><th>그래도 구매</th><th>안 살래요</th><th>담아두기(24시간)</th><th>닫음·고르지 않음</th></tr>
    <tr style="text-align:center;">
        <td><?php echo number_format($popup_7d['checkouts']); ?>회</td>
        <td><?php echo number_format($popup_7d['buy']); ?>회</td>
        <td><?php echo number_format($popup_7d['giveup']); ?>회</td>
        <td><?php echo number_format($popup_7d['hold']); ?>회</td>
        <td><?php echo number_format($popup_none); ?>회</td>
    </tr>
</table>
<table style="width:100%;border-collapse:collapse;margin-bottom:20px;" border="1" cellpadding="6">
    <tr><th>위험 높음</th><th>위험 보통</th><th>위험 낮음</th><th>심야(23~4시)</th><th>쇼핑몰 수</th></tr>
    <tr style="text-align:center;">
        <td style="color:#c62828;"><?php echo number_format($popup_7d['risk_high']); ?>회</td>
        <td style="color:#b45309;"><?php echo number_format($popup_7d['risk_mid']); ?>회</td>
        <td style="color:#2448c4;"><?php echo number_format($popup_7d['risk_low']); ?>회</td>
        <td><?php echo number_format($popup_7d['night']); ?>회</td>
        <td><?php echo number_format($popup_7d['malls']); ?>곳</td>
    </tr>
</table>
<?php } else { ?>
<p style="color:#888;margin-bottom:20px;">최근 7일 동안 결제 화면 팝업이 없습니다.</p>
<?php } ?>

<?php if (defined('IPP_USE_LLM') && IPP_USE_LLM) { // 5 LLM 주간 리포트 요약: 버튼을 눌렀을 때만 부른다 (php -S가 요청을 하나씩 처리해 기다리는 동안 다른 요청도 멈추므로) ?>
<div id="ipp-ai-report" style="border:1px solid #c7d2fe;background:#f5f7ff;border-radius:8px;padding:14px;margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <strong>이번 주 AI 요약</strong>
        <button type="button" id="ipp-ai-report-btn" class="btn btn_02">AI 요약 보기</button>
    </div>
    <div id="ipp-ai-report-body" style="margin-top:8px;display:none;">
        <div id="ipp-ai-headline" style="font-weight:bold;font-size:16px;"></div>
        <p id="ipp-ai-summary" style="margin:6px 0;"></p>
        <p id="ipp-ai-tip" style="margin:0;color:#3730a3;"></p>
    </div>
    <div id="ipp-ai-report-msg" style="margin-top:8px;color:#888;font-size:13px;"></div>
    <div style="margin-top:6px;color:#999;font-size:11px;">최근 2주 집계 숫자만 Claude API로 보내 요약해요. 쇼핑몰 이름, 상품명, 아이디는 보내지 않고 요약은 저장하지 않아요.</div>
</div>
<script>
(function () {
    var btn = document.getElementById('ipp-ai-report-btn');
    var msg = document.getElementById('ipp-ai-report-msg');
    btn.addEventListener('click', function () {
        btn.disabled = true;
        msg.textContent = '요약을 만드는 중이에요...';
        fetch('<?php echo IPP_URL; ?>/api/report.php', {method: 'POST', credentials: 'same-origin'})
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.ok && d.summary) {
                    document.getElementById('ipp-ai-headline').textContent = d.summary.headline;
                    document.getElementById('ipp-ai-summary').textContent = d.summary.summary;
                    document.getElementById('ipp-ai-tip').textContent = '💡 ' + d.summary.tip;
                    document.getElementById('ipp-ai-report-body').style.display = '';
                    msg.textContent = '';
                } else {
                    msg.textContent = d.msg || '지금은 요약을 만들 수 없어요.';
                }
            })
            .catch(function () { msg.textContent = '지금은 요약을 만들 수 없어요.'; })
            .then(function () { btn.disabled = false; });
    });
})();
</script>
<?php } ?>

<h3>일별 차단 횟수</h3>
<table style="width:100%;border-collapse:collapse;" border="1" cellpadding="6">
    <tr><th>날짜</th><th>차단</th></tr>
    <?php foreach ($daily as $d => $cnt) { ?>
    <tr><td><?php echo $d; ?></td><td><?php echo number_format($cnt); ?>회</td></tr>
    <?php } ?>
</table>

<h3>사이트별 차단 횟수 (최근 7일)</h3>
<table style="width:100%;border-collapse:collapse;" border="1" cellpadding="6">
    <tr><th>사이트</th><th>차단</th></tr>
    <?php foreach ($by_site as $row) { ?>
    <tr><td><?php echo get_text($row['name']); ?></td><td><?php echo number_format($row['cnt']); ?>회</td></tr>
    <?php } ?>
    <?php if (!$by_site) { ?><tr><td colspan="2" style="text-align:center;">차단 기록이 없습니다.</td></tr><?php } ?>
</table>
</div>

<?php include_once(G5_PATH.'/tail.php'); ?>
