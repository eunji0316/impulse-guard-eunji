<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_GIFTICON);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

ipp_coupon_settle($member['mb_id']);   // 유효기간 지난 쿠폰 만료 처리
$list = ipp_coupon_list($member['mb_id']);

$status_label = array(
    'issued'    => '사용 전',
    'used'      => '사용 완료',
    'expired'   => '만료',
    'failed'    => '발급 실패 (환불)',
    'cancelled' => '취소 (환불)'
);

$g5['title'] = '내 쿠폰함';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">
<p>
    <a href="<?php echo IPP_URL; ?>/reward.php">← 기프티콘 교환으로</a>
    &nbsp;|&nbsp;
    보유 <?php echo number_format($member['mb_point']); ?>P
</p>

<table style="width:100%;border-collapse:collapse;" border="1" cellpadding="6">
    <tr><th>상품</th><th>쿠폰번호</th><th>상태</th><th>유효기간</th><th>발급일</th></tr>
    <?php foreach ($list as $cp) { ?>
    <tr>
        <td><?php echo get_text($cp['cp_name']); ?></td>
        <td><?php echo $cp['cp_status'] === 'issued' ? get_text($cp['cp_pin']) : '-'; ?></td>
        <td>
            <?php echo $status_label[$cp['cp_status']]; ?>
            <?php if ($cp['cp_status'] === 'issued') { ?>
                <button type="button" onclick="ippUse(<?php echo (int)$cp['cp_id']; ?>)">사용 완료로 표시</button>
            <?php } ?>
        </td>
        <td><?php echo $cp['cp_expire_date'] ? $cp['cp_expire_date'] : '-'; ?></td>
        <td><?php echo $cp['cp_issue_datetime'] ? substr($cp['cp_issue_datetime'], 0, 10) : '-'; ?></td>
    </tr>
    <?php } ?>
    <?php if (!$list) { ?><tr><td colspan="5" style="text-align:center;">교환한 쿠폰이 없습니다.</td></tr><?php } ?>
</table>
</div>

<script>
function ippUse(cp_id) {
    if (!confirm('이 쿠폰을 사용 완료로 표시할까요?')) return;
    const fd = new FormData();
    fd.append('action', 'use');
    fd.append('cp_id', cp_id);
    fetch('<?php echo IPP_URL; ?>/api/reward.php', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(res => res.ok ? location.reload() : alert(res.msg));
}
</script>

<?php include_once(G5_PATH.'/tail.php'); ?>
