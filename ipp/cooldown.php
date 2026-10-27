<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_COOLDOWN);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

ipp_cooldown_settle($member['mb_id']);   // 만료된 쿨다운 정산
$list = ipp_cooldown_list($member['mb_id']);

$status_label = array(
    'waiting' => '⏳ 참는 중',
    'success' => '🎉 성공',
    'gaveup'  => '👍 포기',
    'failed'  => '💸 결제함'
);

$g5['title'] = '타임머신 보관함';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">
<p><a href="<?php echo IPP_URL; ?>/bank.php">← 결제 테스트로</a></p>

<table style="width:100%;border-collapse:collapse;" border="1" cellpadding="6">
    <tr><th>상품</th><th>금액</th><th>상태</th><th>남은 시간 / 종료</th><th>포인트</th></tr>
    <?php foreach ($list as $cd) {
        if ($cd['cd_status'] === 'waiting') {
            $left = strtotime($cd['cd_expire_datetime']) - G5_SERVER_TIME;
            $time = floor($left / 3600).'시간 '.floor(($left % 3600) / 60).'분 남음';
        } else {
            $time = $cd['cd_end_datetime'];
        }
    ?>
    <tr>
        <td><?php echo get_text($cd['cd_item_name']); ?></td>
        <td><?php echo number_format($cd['cd_amount']); ?>원</td>
        <td><?php echo $status_label[$cd['cd_status']]; ?></td>
        <td><?php echo $time; ?></td>
        <td><?php echo $cd['cd_point'] ? '+'.number_format($cd['cd_point']).'P' : '-'; ?></td>
    </tr>
    <?php } ?>
    <?php if (!$list) { ?><tr><td colspan="5" style="text-align:center;">보관 중인 항목이 없습니다.</td></tr><?php } ?>
</table>
</div>

<?php include_once(G5_PATH.'/tail.php'); ?>