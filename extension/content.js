/*
 * content script: 쇼핑 페이지에서 상품 정보 추출, 방문 기록, 결제 버튼 가로채기, 차단 팝업, 차단 모드
 * - 선택자는 sites.js의 IPP_SITES에 있다. 이 파일에는 사이트별 값을 두지 않는다.
 * - 서버 호출은 background.js에 메시지로 맡긴다.
 * - document_start에 실행해서 페이지 스크립트보다 먼저 클릭 리스너를 단다.
 * - 서버에 연결되지 않으면(토큰 없음, 서버 꺼짐) 구매를 막지 않는다.
 * - 차단 모드: 회원이 정한 차단 시간 중이고 이 사이트가 차단 목록에 있으면 사이트 전체를 전체 화면 안내로 가린다.
 */
(() => {
  const CLICKABLE = 'button, a, input[type="submit"], input[type="button"], [role="button"]';

  // 크롬에 로드된 버전 확인용 (확장 프로그램을 고친 뒤 새로고침이 반영됐는지 페이지 콘솔에서 바로 보인다)
  try { console.info('[impulse-guard] content script', chrome.runtime.getManifest().version); } catch (e) { /* 연결 끊김 */ }

  let visit  = null;    // { match, url, item, start, sent } 상품 페이지 방문
  let modal  = null;    // { match, item, start, logged, host } 떠 있는 차단 팝업
  let wall   = null;    // { match, url, until, start, logged, host, timer } 떠 있는 차단 모드 화면
  let busy   = false;   // 서버 확인 중이거나 팝업이 떠 있음
  let bypass = false;   // '그래도 구매하기'로 원래 클릭을 다시 보내는 중

  /* ===== 사이트 설정과 상품 정보 ===== */

  // 현재 주소에 맞는 사이트 코드와 페이지 설정. 없으면 null
  function matchPage() {
    for (const [code, site] of Object.entries(IPP_SITES)) {
      if (!site.hosts.includes(location.hostname)) continue;
      for (const [type, page] of Object.entries(site.pages)) {
        if (page.path.test(location.pathname)) return { code, type, page };
      }
    }
    return null;
  }

  // 현재 주소의 사이트 코드. 차단 모드는 페이지 종류와 상관없이 사이트 전체에 적용한다. 없으면 ''
  function matchSite() {
    for (const [code, site] of Object.entries(IPP_SITES)) {
      if (site.hosts.includes(location.hostname)) return code;
    }
    return '';
  }

  // 선택자 배열에서 처음으로 요소가 있는 선택자의 요소 목록
  function findAll(selectors) {
    for (const sel of selectors || []) {
      try {
        const list = document.querySelectorAll(sel);
        if (list.length) return list;
      } catch (e) {
        console.warn('[impulse-guard] 잘못된 선택자:', sel);
      }
    }
    return [];
  }

  const textOf  = (el) => (el ? el.textContent : '').replace(/\s+/g, ' ').trim();
  const metaOf  = (prop) => (document.querySelector('meta[property="' + prop + '"]') || {}).content || '';
  const secFrom = (start) => Math.round((Date.now() - start) / 1000);

  // "29,900원" → 29900. '원' 앞 숫자를 먼저 보고, 없으면 첫 숫자
  function parsePrice(text) {
    const m = text.match(/(\d[\d,]*)\s*원/) || text.match(/\d[\d,]*/);
    return m ? parseInt((m[1] || m[0]).replace(/,/g, ''), 10) || 0 : 0;
  }

  // http(s) 절대 주소만 받는다
  function absUrl(src) {
    try {
      const url = new URL(src, location.href);
      return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '';
    } catch (e) {
      return '';
    }
  }

  // 상품명, 가격, 대표 이미지. 클릭 시점의 화면에서 읽는다 (옵션을 바꾸면 가격이 바뀌므로)
  function extract(page) {
    const names = findAll(page.name);
    let name = textOf(names[0]) || metaOf('og:title') || document.title;
    if (page.multiName && names.length > 1) name += ' 외 ' + (names.length - 1) + '건';

    const img = findAll(page.image)[0];
    const src = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';

    return {
      name:  name.slice(0, 255),
      price: parsePrice(textOf(findAll(page.price)[0]) || metaOf('product:price:amount')),
      image: absUrl(src || metaOf('og:image'))
    };
  }

  // 기록용 주소: 검색어나 추적값이 붙은 쿼리는 버리고 urlParams만 남긴다
  function cleanUrl(page) {
    const url  = new URL(location.href);
    const keep = new URLSearchParams();
    for (const key of page.urlParams || []) {
      if (url.searchParams.has(key)) keep.set(key, url.searchParams.get(key));
    }
    const qs = keep.toString();
    return url.origin + url.pathname + (qs ? '?' + qs : '');
  }

  // 클릭한 요소가 결제 버튼이면 그 버튼, 아니면 null
  function matchButton(target, page) {
    if (!(target instanceof Element)) return null;
    for (const sel of page.buttons.selectors || []) {
      try {
        const el = target.closest(sel);
        if (el) return el;
      } catch (e) { /* 잘못된 선택자는 findAll에서 경고한다 */ }
    }
    const el = target.closest(CLICKABLE);
    return (el && isBuyText(el, page)) ? el : null;
  }

  function isBuyText(el, page) {
    const text = (el.tagName === 'INPUT' ? el.value : el.textContent).replace(/\s+/g, '');
    if (!text || text.length > 20) return false;   // 긴 글자는 버튼이 아니라 상품 설명 등이다
    return (page.buttons.texts || []).some((t) => text.startsWith(t.replace(/\s+/g, '')));
  }

  // 원래 버튼이 화면에서 사라졌을 때 다시 찾기
  function findButton(page) {
    const el = findAll(page.buttons.selectors)[0];
    if (el) return el;
    return [...document.querySelectorAll(CLICKABLE)].find((b) => isBuyText(b, page)) || null;
  }

  /* ===== 서버 호출 (background.js) ===== */

  function send(msg) {
    try {
      return chrome.runtime.sendMessage(msg)
        .catch(() => ({ ok: false, status: 0, msg: '확장 프로그램에 연결할 수 없습니다.' }));
    } catch (e) {
      // 확장 프로그램을 새로고침하면 이미 열린 페이지의 content script는 연결이 끊긴다
      return Promise.resolve({ ok: false, status: 0, msg: '확장 프로그램이 새로고침되었습니다. 페이지를 새로고침하세요.' });
    }
  }

  const api        = (action, data) => send({ type: 'ipp:api', action, data });
  const getSetting = (force) => send({ type: 'ipp:setting', force: !!force });   // 5분 캐시 (background.js)

  // url: SPA에서 주소가 이미 바뀐 뒤 기록할 때는 이전 주소를 넘긴다
  // page: 페이지 종류(product, cart). sites.js에 없는 페이지(사이트 홈 등)는 ''. 통계에서 상품 차단과 사이트 차단을 나눈다
  function log(match, event, item, staySec, url) {
    return api('log', {
      site: match.code, page: match.type || '', url: url || cleanUrl(match.page || {}), item_name: item.name,
      price: item.price, event, stay_sec: staySec
    });
  }

  /* ===== 방문 기록 (페이지를 떠날 때 체류 시간과 함께 한 번) ===== */

  function startVisit() {
    const match = matchPage();
    visit = (match && match.page.logVisit && !wall)
      ? { match, url: cleanUrl(match.page), item: null, start: Date.now(), sent: false }
      : null;
  }

  // snapshot: SPA 주소 변경처럼 화면이 이미 다음 페이지로 바뀌었으면, 마지막으로 읽어 둔 상품 정보를 쓴다
  function endVisit(snapshot) {
    if (!visit || visit.sent) return;
    visit.sent = true;
    const item = snapshot ? visit.item : extract(visit.match.page);
    if (item) log(visit.match, 'visit', item, secFrom(visit.start), visit.url);
  }

  // 차단 팝업을 본 시간과 함께 blocked 기록 (선택했거나 페이지를 떠날 때 한 번)
  function endBlocked() {
    if (!modal || modal.logged) return;
    modal.logged = true;
    log(modal.match, 'blocked', modal.item, secFrom(modal.start));
  }

  addEventListener('pagehide', () => { endBlocked(); endWall(); endVisit(); });
  addEventListener('pageshow', (e) => {
    if (!e.persisted) return;   // 뒤로 가기 캐시에서 돌아옴
    if (wall) {
      wall.start  = Date.now();   // 다시 보게 된 차단 화면은 새 차단으로 기록
      wall.logged = false;
    } else {
      startVisit();
      checkWall();
    }
  });
  startVisit();
  checkWall();

  // SPA(지그재그 등)는 페이지를 새로 불러오지 않고 주소만 바꾼다. 1초마다 주소를 확인해 방문 기록을 나누고 차단 여부를 다시 본다
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href === lastUrl) {
      if (visit && !visit.sent) visit.item = extract(visit.match.page);   // 주소가 바뀌기 전 마지막 화면의 상품 정보
      return;
    }
    lastUrl = location.href;
    endVisit(true);
    if (!wall) {
      startVisit();
      checkWall();
    }
  }, 1000);

  /* ===== 결제 버튼 가로채기 ===== */

  addEventListener('click', async (e) => {
    if (bypass) return;
    const match = matchPage();
    if (!match) return;
    const btn = matchButton(e.target, match.page);
    if (!btn) return;

    e.preventDefault();
    e.stopImmediatePropagation();
    if (busy || wall) return;   // 확인 중에 다시 누른 클릭, 차단 화면 뒤에서 키보드로 누른 클릭은 버린다
    busy = true;

    const item = extract(match.page);
    if (item.price <= 0) console.warn('[impulse-guard] 가격을 읽지 못했습니다. sites.js의 price 선택자를 확인하세요 (ippInspect()).');
    const res  = await api('check', { site: match.code, item_name: item.name, price: item.price });
    if (!res.ok) {
      console.warn('[impulse-guard] 확인하지 못해 그대로 진행합니다:', res.msg);
      return proceed(match, btn, item);
    }
    // 가격을 못 읽으면 고액인지 알 수 없으므로 안전으로 보지 않고 팝업을 띄운다 (선택자가 깨져도 조용히 꺼지지 않게)
    if (!res.data.is_blocking && !res.data.is_impulse && item.price > 0) return proceed(match, btn, item);
    showModal(match, btn, item, res.data);
  }, true);

  // 원래 클릭 동작을 그대로 진행
  function proceed(match, btn, item) {
    busy = false;
    log(match, 'checkout', item, 0);
    const el = btn.isConnected ? btn : findButton(match.page);
    if (!el) return console.warn('[impulse-guard] 결제 버튼을 다시 찾지 못했습니다.');
    bypass = true;
    try {
      el.click();
    } finally {
      bypass = false;
    }
  }

  /* ===== 차단 팝업 ===== */

  const MODAL_HTML = `
<style>
  .back { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; padding: 16px;
          font: 14px/1.5 -apple-system, 'Malgun Gothic', sans-serif; color: #222; }
  .box { width: 100%; max-width: 380px; background: #fff; border-radius: 12px; padding: 22px; box-shadow: 0 10px 40px rgba(0,0,0,.3); }
  h2 { margin: 0 0 14px; font-size: 18px; }
  .item { display: flex; gap: 12px; align-items: center; padding: 10px; background: #f6f7f9; border-radius: 8px; }
  .item img { width: 72px; height: 72px; object-fit: cover; border-radius: 6px; background: #e5e7eb; flex: none; }
  .item img[hidden] { display: none; }
  .name { font-size: 13px; color: #444; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .price { font-size: 18px; font-weight: bold; margin-top: 4px; }
  .reason { margin: 14px 0 4px; color: #c62828; }
  .point { margin: 0 0 14px; color: #555; font-size: 13px; }
  button { display: block; width: 100%; margin-top: 8px; padding: 11px; border: 0; border-radius: 8px; font: inherit; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .think { background: #3b6cf6; color: #fff; font-weight: bold; }
  .think small { display: block; font-weight: normal; font-size: 12px; opacity: .85; }
  .giveup { background: #e8eefe; color: #2448c4; }
  .buy { background: none; color: #888; font-size: 13px; text-decoration: underline; }
  .msg { min-height: 20px; margin: 10px 0 0; font-size: 13px; color: #c62828; }
  .done { text-align: center; }
  .done p { margin: 0 0 6px; }
  .link { background: #e8eefe; color: #2448c4; }
  .close { background: #3b6cf6; color: #fff; }
</style>
<div class="back">
  <div class="box" role="dialog" aria-modal="true" aria-labelledby="ipp-title">
    <div class="ask">
      <h2 id="ipp-title">잠깐, 정말 필요한가요?</h2>
      <div class="item">
        <img alt="" hidden>
        <div><div class="name"></div><div class="price"></div></div>
      </div>
      <p class="reason"></p>
      <p class="point"></p>
      <button type="button" class="think">조금 더 생각하기<small>24시간 담아두기</small></button>
      <button type="button" class="giveup">안 살래요</button>
      <button type="button" class="buy">그래도 구매하기</button>
      <p class="msg" role="status"></p>
    </div>
    <div class="done" hidden>
      <h2></h2>
      <p class="done-text"></p>
      <button type="button" class="link" hidden>타임머신 보기</button>
      <button type="button" class="close">닫기</button>
    </div>
  </div>
</div>`;

  function showModal(match, btn, item, d) {
    const host = document.createElement('div');
    host.style.cssText = 'all: initial; position: fixed; inset: 0; z-index: 2147483647;';
    const root = host.attachShadow({ mode: 'closed' });   // 쇼핑몰 CSS가 팝업에 섞이지 않게
    root.innerHTML = MODAL_HTML;
    const $ = (sel) => root.querySelector(sel);

    // 페이지에서 읽은 값은 textContent로만 넣는다
    $('.name').textContent  = item.name;
    $('.price').textContent = item.price > 0 ? item.price.toLocaleString() + '원' : '가격을 읽지 못했어요';
    if (item.image) {
      $('.item img').src = item.image;
      $('.item img').hidden = false;
    }

    const reasons = [];
    if (d.is_blocking) reasons.push('지금은 쇼핑 차단 시간이에요.');
    if (d.keyword)     reasons.push('\'' + d.keyword + '\' 키워드가 들어 있어요.');
    else if (d.is_impulse) reasons.push('심야 시간이거나 큰 금액의 결제예요.');
    if (!reasons.length && item.price <= 0) reasons.push('큰 금액의 결제인지 확인할 수 없어요. 한 번 더 생각해 볼까요?');   // 가격 칸에는 '가격을 읽지 못했어요'가 나온다
    $('.reason').textContent = reasons.join(' ');
    if (item.price > 0) {
      $('.point').textContent = '안 사면 +' + d.point.toLocaleString() + 'P, 24시간 참으면 +' + d.point2.toLocaleString() + 'P';
    } else {
      $('.think').disabled = true;
      $('.point').textContent = '가격을 읽지 못해 담아두기와 포인트를 쓸 수 없어요.';
    }

    const buttons = [$('.think'), $('.giveup'), $('.buy')];
    const setBusy = (on) => buttons.forEach((b) => { b.disabled = on || (b === $('.think') && item.price <= 0); });

    function close() {
      endBlocked();
      host.remove();
      modal = null;
      busy  = false;
    }

    function done(title, text, showLink) {
      endBlocked();
      $('.ask').hidden  = true;
      $('.done').hidden = false;
      $('.done h2').textContent    = title;
      $('.done-text').textContent  = text;
      $('.link').hidden = !showLink;
      $('.close').focus();
    }

    $('.think').addEventListener('click', async () => {
      setBusy(true);
      $('.msg').textContent = '담는 중…';
      const res = await api('cooldown', { item_name: item.name, price: item.price });
      if (!res.ok) {
        setBusy(false);
        $('.msg').textContent = res.msg;
        return;
      }
      done('타임머신에 담았어요', res.data.expire.slice(0, 16) + '까지 참으면 +' + d.point2.toLocaleString() + 'P를 받아요.', true);
    });

    $('.giveup').addEventListener('click', async () => {
      if (item.price <= 0) return done('잘 참았어요!', '이번 구매를 건너뛰었어요.', false);
      setBusy(true);
      $('.msg').textContent = '기록 중…';
      const res = await api('giveup', { item_name: item.name, price: item.price });
      if (!res.ok) {
        setBusy(false);
        $('.msg').textContent = res.msg;
        return;
      }
      const p = res.data.point;
      done('잘 참았어요!', p > 0 ? '+' + p.toLocaleString() + 'P를 받았어요.' : '오늘 받을 수 있는 포인트는 모두 받았어요.', false);
    });

    $('.buy').addEventListener('click', () => {
      close();
      proceed(match, btn, item);
    });

    $('.link').addEventListener('click', () => {
      try { chrome.runtime.sendMessage({ type: 'ipp:open', path: '/ipp/cooldown.php' }); } catch (e) { /* 연결 끊김 */ }
    });
    $('.close').addEventListener('click', close);

    (document.body || document.documentElement).appendChild(host);
    modal = { match, item, start: Date.now(), logged: false, host };
    $('.think').disabled ? $('.giveup').focus() : $('.think').focus();
  }

  /* ===== 차단 모드 (차단 시간 중 차단 사이트에 들어오면 전체 화면 안내) ===== */

  const WALL_HTML = `
<style>
  .back { position: fixed; inset: 0; background: #f3f5fa; display: flex; align-items: center; justify-content: center; padding: 16px;
          font: 15px/1.6 -apple-system, 'Malgun Gothic', sans-serif; color: #222; overflow: auto; }
  .box { width: 100%; max-width: 420px; text-align: center; }
  .icon { font-size: 48px; line-height: 1; }
  h2 { margin: 14px 0 6px; font-size: 22px; }
  .until { margin: 0; color: #555; }
  .remain { margin: 22px 0 6px; font-size: 13px; color: #777; }
  .time { margin: 0 0 22px; font-size: 34px; font-weight: bold; color: #3b6cf6; font-variant-numeric: tabular-nums; }
  .cheer { margin: 0 0 22px; color: #555; }
  button { display: block; width: 100%; margin-top: 8px; padding: 12px; border: 0; border-radius: 8px; font: inherit; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .closetab { background: #3b6cf6; color: #fff; font-weight: bold; }
  .setting { background: #e8eefe; color: #2448c4; }
  .recheck { background: none; color: #888; font-size: 13px; text-decoration: underline; }
  .msg { min-height: 20px; margin: 10px 0 0; font-size: 13px; color: #c62828; }
</style>
<div class="back">
  <div class="box" role="alertdialog" aria-modal="true" aria-labelledby="ipp-wall-title" aria-describedby="ipp-wall-until">
    <div class="icon" aria-hidden="true">⏳</div>
    <h2 id="ipp-wall-title">지금은 쇼핑 차단 시간이에요</h2>
    <p class="until" id="ipp-wall-until"></p>
    <p class="remain">남은 시간</p>
    <p class="time" role="timer"></p>
    <p class="cheer">스스로 정한 약속을 지키는 중이에요. 조금만 더 참아 봐요!</p>
    <button type="button" class="closetab">이 탭 닫기</button>
    <button type="button" class="setting">차단 설정 보기</button>
    <button type="button" class="recheck">설정에서 차단을 풀었다면 다시 확인</button>
    <p class="msg" role="status"></p>
  </div>
</div>`;

  // 설정 응답에서 이 사이트의 차단 종료 시각(ms). 차단 중이 아니거나 사이트가 꺼져 있으면 0
  // 쇼핑몰 전체 차단(block_all)이 켜져 있으면 사이트 on과 상관없이 차단한다
  function blockUntil(res, code) {
    if (!res.ok || !res.data.is_blocking) return 0;
    const site = (res.data.sites || []).find((s) => s.code === code);
    return (site && (res.data.block_all || site.on) && res.data.block_until_ms > Date.now()) ? res.data.block_until_ms : 0;
  }

  // 1시간 2분 3초 / 2일 3시간 4분 5초
  function formatRemain(ms) {
    let s = Math.max(0, Math.ceil(ms / 1000));
    const d = Math.floor(s / 86400); s %= 86400;
    const h = Math.floor(s / 3600);  s %= 3600;
    const m = Math.floor(s / 60);    s %= 60;
    const parts = [];
    if (d) parts.push(d + '일');
    if (d || h) parts.push(h + '시간');
    if (d || h || m) parts.push(m + '분');
    parts.push(s + '초');
    return parts.join(' ');
  }

  // 서버(캐시)에 물어보고 차단 중이면 차단 화면을 띄운다. 서버에 연결되지 않으면 막지 않는다
  async function checkWall() {
    const code = matchSite();
    if (!code || wall) return;
    const res = await getSetting(false);
    if (!res.ok) return console.warn('[impulse-guard] 차단 설정을 확인하지 못했습니다:', res.msg);
    const until = blockUntil(res, code);
    if (until && !wall) showWall(code, until, res.data.sites.find((s) => s.code === code).name);
  }

  // 차단 화면을 본 시간과 함께 blocked 기록 (화면이 닫히거나 페이지를 떠날 때 한 번)
  // 상품/장바구니 페이지면 상품 정보를, 다른 페이지면 주소만 남긴다
  function endWall() {
    if (!wall || wall.logged) return;
    wall.logged = true;
    const item = wall.match.page ? extract(wall.match.page) : { name: '', price: 0 };
    log(wall.match, 'blocked', item, secFrom(wall.start), wall.url);
  }

  function showWall(code, until, siteName) {
    const page  = matchPage();
    const match = { code, type: page ? page.type : '', page: page ? page.page : null };

    const host = document.createElement('div');
    host.style.cssText = 'all: initial; position: fixed; inset: 0; z-index: 2147483647;';
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = WALL_HTML;
    const $ = (sel) => root.querySelector(sel);

    const untilText = () => new Date(wall.until).toLocaleString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' });
    function tick() {
      const left = wall.until - Date.now();
      if (left <= 0) return closeWall();   // 차단 시간이 끝나면 저절로 풀린다
      $('.time').textContent  = formatRemain(left);
      $('.until').textContent = siteName + ' 차단은 ' + untilText() + '에 끝나요.';
    }

    function closeWall() {
      endWall();
      clearInterval(wall.timer);
      host.remove();
      wall = null;
      startVisit();
    }

    $('.closetab').addEventListener('click', () => send({ type: 'ipp:closeTab' }));
    $('.setting').addEventListener('click', () => send({ type: 'ipp:open', path: '/ipp/setting.php' }));
    $('.recheck').addEventListener('click', async () => {
      $('.recheck').disabled = true;
      $('.msg').textContent = '확인 중…';
      const res = await getSetting(true);   // 캐시를 건너뛰고 서버에서 다시 받는다
      $('.recheck').disabled = false;
      if (!res.ok) return ($('.msg').textContent = res.msg);
      const next = blockUntil(res, code);
      if (!next) return closeWall();
      wall.until = next;
      tick();
      $('.msg').textContent = '아직 차단 시간이에요.';
    });

    visit = null;   // 차단 화면 뒤의 페이지는 방문으로 세지 않는다
    (document.body || document.documentElement).appendChild(host);
    wall = { match, url: cleanUrl(page ? page.page : {}), until, start: Date.now(), logged: false, host, timer: 0 };
    wall.timer = setInterval(tick, 1000);
    tick();
    if (wall) $('.closetab').focus();
  }

  /* ===== 선택자 확인용 (개발자 도구 콘솔에서 impulse-guard 컨텍스트를 고르고 ippInspect() 실행) ===== */

  window.ippInspect = () => {
    const match = matchPage();
    if (!match) return console.log('[impulse-guard] sites.js에 이 페이지 설정이 없습니다:', location.href);

    const rows = [];
    for (const key of ['name', 'price', 'image']) {
      for (const sel of match.page[key] || []) {
        let list = [];
        try { list = document.querySelectorAll(sel); } catch (e) { /* 잘못된 선택자 */ }
        rows.push({ 항목: key, 선택자: sel, 개수: list.length, 첫번째: list[0] ? (textOf(list[0]) || list[0].src || '').slice(0, 60) : '' });
      }
    }
    for (const sel of match.page.buttons.selectors || []) {
      let list = [];
      try { list = document.querySelectorAll(sel); } catch (e) { /* 잘못된 선택자 */ }
      rows.push({ 항목: 'button', 선택자: sel, 개수: list.length, 첫번째: list[0] ? textOf(list[0]).slice(0, 60) : '' });
    }
    const byText = [...document.querySelectorAll(CLICKABLE)].filter((b) => isBuyText(b, match.page));
    rows.push({ 항목: 'button', 선택자: '(글자) ' + match.page.buttons.texts.join(', '), 개수: byText.length, 첫번째: byText[0] ? textOf(byText[0]) : '' });

    console.log('[impulse-guard] 사이트:', match.code, '페이지:', match.type);
    console.table(rows);
    console.log('[impulse-guard] 추출 결과:', extract(match.page));
    console.log('[impulse-guard] 글자로 찾은 버튼:', byText);
  };
})();
