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
