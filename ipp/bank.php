<?php
include_once('./_common.php');
ipp_require_feature(IPP_USE_BANK);
if (!$is_member) alert('로그인이 필요합니다.', G5_BBS_URL.'/login.php');

$account = ipp_bank_get_account($member['mb_id']);
$list    = ipp_bank_get_transactions($member['mb_id']);

$g5['title'] = '계좌 연동 테스트';
include_once(G5_PATH.'/head.php');
?>

<div style="max-width:720px;margin:30px auto;padding:0 15px;">

<h2>계좌</h2>
<?php if ($account) { ?>
    <p><?php echo $account['ac_bank_name']; ?> <?php echo $account['ac_number_masked']; ?> (연결됨)</p>
<?php } else { ?>
    <select id="bank">
        <option value="">은행 선택</option>
        <option>국민은행</option>
        <option>신한은행</option>
        <option>카카오뱅크</option>
        <option>토스뱅크</option>
    </select>
    <button type="button" onclick="ippLink()">계좌 연결</button>
<?php } ?>

<?php if ($account) { ?>
<h2 style="margin-top:30px;">가짜 결제 발생</h2>
<p>
    <input type="text" id="merchant" placeholder="가맹점 (예: 무신사)">
    <input type="number" id="amount" placeholder="금액">
    <select id="category">
        <option value="shopping">쇼핑</option>
        <option value="fashion">패션</option>
        <option value="game">게임</option>
        <option value="delivery">배달</option>
        <option value="food">식비</option>
        <option value="transport">교통</option>
    </select>
    <input type="datetime-local" id="datetime">
    <button type="button" onclick="ippPay()">결제</button>
</p>
<p style="color:#888;font-size:13px;">시간을 비워 두면 현재 시각으로 결제됩니다. 심야 테스트를 하려면 23시 이후로 지정하세요.</p>
<?php } ?>

<h2 style="margin-top:30px;">거래 내역</h2>
<table style="width:100%;border-collapse:collapse;" border="1" cellpadding="6">
    <tr><th>일시</th><th>가맹점</th><th>업종</th><th>금액</th><th>감지</th></tr>
    <?php foreach ($list as $row) { ?>
    <tr>
        <td><?php echo $row['tr_datetime']; ?></td>
        <td><?php echo get_text($row['tr_merchant']); ?></td>
        <td><?php echo $row['tr_category']; ?></td>
        <td><?php echo number_format($row['tr_amount']); ?>원</td>
        <td><?php echo $row['tr_is_impulse'] ? '⚠️ 충동' : ''; ?></td>
    </tr>
    <?php } ?>
    <?php if (!$list) { ?><tr><td colspan="5" style="text-align:center;">거래 내역이 없습니다.</td></tr><?php } ?>
</table>

</div>

<div id="ipp-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;align-items:center;justify-content:center;">
    <div style="background:#fff;width:90%;max-width:360px;padding:28px;border-radius:12px;text-align:center;">
        <div style="font-size:42px;">⏳</div>
        <h3 style="margin:10px 0;">정말 필요한 것인가요?</h3>
        <p id="ipp-modal-desc" style="color:#555;"></p>
        <button type="button" onclick="ippHold()" style="display:block;width:100%;padding:12px;margin-top:14px;background:#4a5af0;color:#fff;border:0;border-radius:8px;">
            24시간 담아두기 (성공 시 <span id="ipp-p2"></span>P)
        </button>
        <button type="button" onclick="ippGiveup()" style="display:block;width:100%;padding:12px;margin-top:8px;background:#eee;border:0;border-radius:8px;">
            안 살래요 (<span id="ipp-p1"></span>P)
        </button>
        <button type="button" onclick="ippDoPay(ippPending)" style="margin-top:12px;background:none;border:0;color:#999;text-decoration:underline;">
            그래도 결제할래요
        </button>
    </div>
</div>

<script>
const IPP_BANK_API     = '<?php echo IPP_URL; ?>/api/mock_bank.php';
const IPP_CD_API       = '<?php echo IPP_URL; ?>/api/cooldown.php';
const IPP_USE_COOLDOWN = <?php echo IPP_USE_COOLDOWN ? 'true' : 'false'; ?>;
let ippPending = null;

function ippPost(url, data) {
    const fd = new FormData();
    for (const k in data) fd.append(k, data[k]);
    return fetch(url, { method: 'POST', body: fd }).then(r => r.json());
}

function ippLink() {
    ippPost(IPP_BANK_API, { action: 'link', bank: document.getElementById('bank').value })
        .then(res => res.ok ? location.reload() : alert(res.msg));
}

function ippForm() {
    return {
        merchant: document.getElementById('merchant').value,
        amount:   document.getElementById('amount').value,
        category: document.getElementById('category').value,
        datetime: document.getElementById('datetime').value
    };
}

// 결제 버튼: 감지 먼저, 감지되면 팝업
function ippPay() {
    const f = ippForm();
    if (!IPP_USE_COOLDOWN) return ippDoPay(f);

    ippPost(IPP_BANK_API, Object.assign({ action: 'check' }, f)).then(res => {
        if (!res.ok) return alert(res.msg);
        if (!res.is_impulse) return ippDoPay(f);

        ippPending = f;
        document.getElementById('ipp-modal-desc').textContent =
            f.merchant + ' ' + Number(f.amount).toLocaleString() + '원 결제를 앞두고 있어요.';
        document.getElementById('ipp-p1').textContent = res.point;
        document.getElementById('ipp-p2').textContent = res.point2;
        document.getElementById('ipp-modal').style.display = 'flex';
    });
}

function ippDoPay(f) {
    ippPost(IPP_BANK_API, Object.assign({ action: 'pay' }, f))
        .then(res => res.ok ? location.reload() : alert(res.msg));
}

function ippHold() {
    ippPost(IPP_CD_API, { action: 'hold', item: ippPending.merchant, amount: ippPending.amount })
        .then(res => {
            if (!res.ok) return alert(res.msg);
            alert('24시간 동안 보관합니다. 참아내면 더블 포인트!');
            location.href = '<?php echo IPP_URL; ?>/cooldown.php';
        });
}

function ippGiveup() {
    ippPost(IPP_CD_API, { action: 'giveup', item: ippPending.merchant, amount: ippPending.amount })
        .then(res => {
            if (!res.ok) return alert(res.msg);
            alert(res.point > 0 ? res.point + 'P 적립! 잘 참았어요.' : '오늘 받을 수 있는 포인트를 모두 받았어요.');
            location.reload();
        });
}
</script>