<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_GIFTICON);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

$list     = ipp_reward_list();
$my_point = (int)$member['mb_point'];

// 이 페이지에서 보내는 교환 요청의 주문번호. 같은 번호는 한 번만 처리되므로 중복 클릭을 막는다.
$order_no = 'IPP'.date('YmdHis').substr(md5($member['mb_id'].uniqid('', true)), 0, 8);

$g5['title'] = '기프티콘 교환';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">
<p>
    보유 포인트 <b><?php echo number_format($my_point); ?>P</b>
    &nbsp;|&nbsp;
    <a href="<?php echo IPP_URL; ?>/coupon.php">🎟️ 내 쿠폰함</a>
</p>

<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;">
    <?php foreach ($list as $rw) {
        $soldout = ((int)$rw['rw_stock'] === 0);
        $lack    = ($my_point < (int)$rw['rw_point']);
    ?>
    <div style="border:1px solid #ddd;border-radius:8px;padding:14px;text-align:center;">
        <?php if ($rw['rw_image']) { ?>
            <img src="<?php echo get_text($rw['rw_image']); ?>" alt="" style="width:100%;height:120px;object-fit:contain;">
        <?php } else { ?>
            <div style="font-size:48px;line-height:120px;">🎁</div>
        <?php } ?>
        <div style="color:#888;font-size:13px;"><?php echo get_text($rw['rw_brand']); ?></div>
        <div style="margin:4px 0;"><?php echo get_text($rw['rw_name']); ?></div>
        <div style="font-weight:bold;"><?php echo number_format($rw['rw_point']); ?>P</div>
        <?php if ((int)$rw['rw_stock'] > 0) { ?>
            <div style="color:#888;font-size:12px;">남은 수량 <?php echo (int)$rw['rw_stock']; ?>개</div>
        <?php } ?>
        <button type="button" class="ipp-exchange" style="width:100%;padding:8px;margin-top:8px;"
                data-id="<?php echo (int)$rw['rw_id']; ?>"
                data-name="<?php echo get_text($rw['rw_name']); ?>"
                data-point="<?php echo (int)$rw['rw_point']; ?>"
                <?php echo ($soldout || $lack) ? 'disabled' : ''; ?>>
            <?php echo $soldout ? '품절' : ($lack ? '포인트 부족' : '교환하기'); ?>
        </button>
    </div>
    <?php } ?>
</div>
<?php if (!$list) { ?><p style="text-align:center;">교환할 수 있는 상품이 없습니다.</p><?php } ?>
</div>

<script>
const IPP_REWARD_API = '<?php echo IPP_URL; ?>/api/reward.php';
const IPP_ORDER_NO   = '<?php echo $order_no; ?>';

document.querySelectorAll('.ipp-exchange').forEach(btn => {
    btn.addEventListener('click', () => {
        const point = Number(btn.dataset.point).toLocaleString();
        if (!confirm(btn.dataset.name + '을(를) ' + point + 'P로 교환할까요?')) return;

        // 응답이 올 때까지 모든 버튼을 막는다
        const buttons = document.querySelectorAll('.ipp-exchange');
        const prev    = Array.from(buttons).map(b => b.disabled);
        buttons.forEach(b => b.disabled = true);

        const fd = new FormData();
        fd.append('action', 'exchange');
        fd.append('rw_id', btn.dataset.id);
        fd.append('order_no', IPP_ORDER_NO);

        fetch(IPP_REWARD_API, { method: 'POST', body: fd })
            .then(r => r.json())
            .then(res => {
                if (!res.ok) {
                    alert(res.msg);
                    return location.reload();   // 새 주문번호와 최신 잔액으로 다시 그림
                }
                alert('교환이 완료되었습니다. 쿠폰함에서 확인하세요.');
                location.href = '<?php echo IPP_URL; ?>/coupon.php';
            })
            .catch(() => {
                alert('네트워크 오류가 발생했습니다.');
                buttons.forEach((b, i) => b.disabled = prev[i]);
            });
    });
});
</script>

<?php include_once(G5_PATH.'/tail.php'); ?>
