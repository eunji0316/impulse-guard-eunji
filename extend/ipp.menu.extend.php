<?php
if (!defined('_GNUBOARD_')) exit;

/*
 * 로그인 회원 메뉴 링크 (7 마무리)
 * 통계, 포인트·리워드, 담아두기, 회원 설정(차단 설정)으로 바로 가는 링크를 기존 메뉴에 넣는다.
 * - 그누보드 기본 파일과 테마 파일은 고치지 않는다. 모든 페이지 끝에서 실행되는 tail_sub 이벤트로 짧은 스크립트를 붙여
 *   이미 있는 메뉴 목록에 항목을 더한다
 *     PC 커뮤니티·쇼핑몰 맨 위 줄(#hd_qnb: FAQ, 1:1문의 등 앞),
 *     모바일 커뮤니티 메뉴(#hd_nb), 쇼핑몰 마이페이지(#smb_my_list 맨 위에 '충동구매 방지' 칸)
 * - 로그인한 회원에게만, 관리자 화면에는 넣지 않는다. 꺼진 기능(IPP_USE_*)의 링크는 넣지 않는다
 * - 넣을 곳이 없는 화면(팝업 창 등)에서는 아무것도 하지 않는다
 */

add_event('tail_sub', 'ipp_member_menu', G5_HOOK_DEFAULT_PRIORITY);

// [이름, 주소, 설명] 기능 스위치가 켜진 것만
function ipp_member_menu_links() {
    $links = array();
    if (IPP_USE_STATS)    $links[] = array('통계', IPP_URL.'/stats.php', '결제 화면 팝업, 차단, 절약 금액');
    if (IPP_USE_GIFTICON) $links[] = array('포인트·리워드', IPP_URL.'/reward.php', '포인트로 기프티콘 교환, 내 쿠폰함');
    if (IPP_USE_COOLDOWN) $links[] = array('담아두기', IPP_URL.'/cooldown.php', '24시간 타임머신 보관함');
    if (IPP_USE_SETTING)  $links[] = array('차단 설정', IPP_URL.'/setting.php', '차단 시간, 키워드, 데스크톱 연결 토큰');
    return $links;
}

function ipp_member_menu() {
    global $is_member;
    if (!$is_member || (defined('G5_IS_ADMIN') && G5_IS_ADMIN)) return;
    $links = ipp_member_menu_links();
    if (!$links) return;
    $data = array();
    foreach ($links as $l) $data[] = array('name' => $l[0], 'url' => $l[1], 'desc' => $l[2]);
    ?>
<style>
.ipp-menu-li a{color:#3730a3 !important;font-weight:bold}
#ipp-mypage{border:1px solid #c7d2fe;background:#f5f7ff;border-radius:6px;padding:14px 16px;margin-bottom:20px}
#ipp-mypage h2{position:static;width:auto;height:auto;overflow:visible;font-size:1.15em;margin:0 0 10px;font-weight:bold}
#ipp-mypage ul{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;margin:0;padding:0;list-style:none}
#ipp-mypage li a{display:block;background:#fff;border:1px solid #dbe1fe;border-radius:6px;padding:10px 12px;color:#1e1b4b}
#ipp-mypage li a strong{display:block;font-size:1.05em;margin-bottom:2px}
#ipp-mypage li a span{color:#666;font-size:0.9em}
</style>
<script>
(function () {
    var links = <?php echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG | JSON_HEX_AMP); ?>;
    function li(l) {
        var e = document.createElement('li'), a = document.createElement('a');
        e.className = 'ipp-menu-li';
        a.href = l.url; a.textContent = l.name; a.title = l.desc;
        e.appendChild(a);
        return e;
    }
    function addTo(sel, prepend) {
        var ul = document.querySelector(sel);
        if (!ul || ul.querySelector('.ipp-menu-li')) return;
        var first = ul.firstChild;
        links.forEach(function (l) { prepend ? ul.insertBefore(li(l), first) : ul.appendChild(li(l)); });
    }
    addTo('#hd_qnb', true);          // PC 커뮤니티·쇼핑몰 맨 위 줄: FAQ 앞

    addTo('#hd_nb', true);           // 모바일 커뮤니티 메뉴
    var my = document.getElementById('smb_my_list');   // 쇼핑몰 마이페이지
    if (my && !document.getElementById('ipp-mypage')) {
        var box = document.createElement('section'), h = document.createElement('h2'), ul = document.createElement('ul');
        box.id = 'ipp-mypage';
        h.textContent = '충동구매 방지';
        links.forEach(function (l) {
            var e = document.createElement('li'), a = document.createElement('a'), s = document.createElement('strong'), d = document.createElement('span');
            a.href = l.url; s.textContent = l.name; d.textContent = l.desc;
            a.appendChild(s); a.appendChild(d); e.appendChild(a); ul.appendChild(e);
        });
        box.appendChild(h); box.appendChild(ul);
        my.insertBefore(box, my.firstChild);
    }
})();
</script>
    <?php
}
