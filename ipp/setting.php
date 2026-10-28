<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_SETTING);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

$st          = ipp_setting_get($member['mb_id']);
$is_blocking = ipp_is_blocking($member['mb_id']);

$g5['title'] = '차단 설정';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">
<p>
    <a href="<?php echo IPP_URL; ?>/cooldown.php">← 타임머신 보관함으로</a>
    <?php if (IPP_USE_STATS) { ?>
    &nbsp;|&nbsp;
    <a href="<?php echo IPP_URL; ?>/stats.php">📊 통계</a>
    <?php } ?>
</p>

<h3>차단 시간</h3>
<p>
    <?php if ($is_blocking) { ?>
        🔒 <b><?php echo $st['st_block_until']; ?></b>까지 차단 중
        <button type="button" onclick="ippPost({ action: 'unblock' })">차단 해제</button>
    <?php } else { ?>
        차단하고 있지 않습니다.
    <?php } ?>
</p>
<p>
    <button type="button" onclick="ippBlock('1h')">지금부터 1시간</button>
    <button type="button" onclick="ippBlock('today')">오늘 하루</button>
    <button type="button" onclick="ippBlock('week')">일주일</button>
    &nbsp;
    <input type="datetime-local" id="ipp_until">
    <button type="button" onclick="ippBlock('custom')">직접 설정</button>
</p>

<form id="ipp_setting_form" onsubmit="return ippSave(this);">
<h3>차단할 사이트</h3>
<p>
    <?php foreach (IPP_BLOCK_SITES as $code => $site) { ?>
    <label style="margin-right:12px;">
        <input type="checkbox" name="sites[]" value="<?php echo $code; ?>" <?php echo in_array($code, $st['st_sites']) ? 'checked' : ''; ?>>
        <?php echo $site['name']; ?>
    </label>
    <?php } ?>
</p>

<h3>추가 차단 키워드</h3>
<p>
    <input type="text" name="keywords" style="width:100%;" value="<?php echo get_text(implode(', ', $st['st_keywords'])); ?>">
    <br><small>쉼표로 구분. 최대 <?php echo IPP_KEYWORD_MAX; ?>개, 하나에 <?php echo IPP_KEYWORD_LEN; ?>자까지</small>
</p>

<h3>알림</h3>
<p>
    <label><input type="checkbox" name="risk_alert" value="1" <?php echo $st['st_risk_alert'] ? 'checked' : ''; ?>> 충동구매 위험도 알림</label>
</p>

<p><button type="submit" style="padding:8px 20px;">저장</button></p>
</form>

<h3>확장 프로그램 연결</h3>
<p>
    토큰 <code><?php echo substr($st['st_api_token'], 0, 8); ?>…</code>
    <button type="button" onclick="if (confirm('토큰을 새로 만들면 기존 확장 프로그램 연결이 끊깁니다.')) ippPost({ action: 'regen_token' })">재발급</button>
</p>
</div>

<script>
function ippPost(data) {
    const fd = data instanceof FormData ? data : new FormData();
    if (!(data instanceof FormData)) for (const k in data) fd.append(k, data[k]);
    fetch('<?php echo IPP_URL; ?>/api/setting.php', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(res => res.ok ? location.reload() : alert(res.msg));
}
function ippBlock(preset) {
    const until = document.getElementById('ipp_until').value;
    if (preset === 'custom' && !until) { alert('종료 시각을 선택하세요.'); return; }
    ippPost({ action: 'block', preset: preset, until: until });
}
function ippSave(form) {
    const fd = new FormData(form);
    fd.append('action', 'save');
    ippPost(fd);
    return false;
}
</script>

<?php include_once(G5_PATH.'/tail.php'); ?>
