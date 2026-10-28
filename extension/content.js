/*
 * content script: 쇼핑 페이지에서 상품 정보 추출, 방문 기록, 결제 버튼 가로채기, 차단 팝업
 * - 선택자는 sites.js의 IPP_SITES에 있다. 이 파일에는 사이트별 값을 두지 않는다.
 * - 서버 호출은 background.js에 메시지로 맡긴다.
 * - document_start에 실행해서 페이지 스크립트보다 먼저 클릭 리스너를 단다.
 * - 서버에 연결되지 않으면(토큰 없음, 서버 꺼짐) 구매를 막지 않는다.
 */
(() => {
  const CLICKABLE = 'button, a, input[type="submit"], input[type="button"], [role="button"]';

  let visit  = null;    // { match, start, sent } 상품 페이지 방문
  let modal  = null;    // { match, item, start, logged, host } 떠 있는 차단 팝업
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
      price: parsePrice(textOf(findAll(page.price)[0])),
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

  function api(action, data) {
    try {
      return chrome.runtime.sendMessage({ type: 'ipp:api', action, data })
        .catch(() => ({ ok: false, status: 0, msg: '확장 프로그램에 연결할 수 없습니다.' }));
    } catch (e) {
      // 확장 프로그램을 새로고침하면 이미 열린 페이지의 content script는 연결이 끊긴다
      return Promise.resolve({ ok: false, status: 0, msg: '확장 프로그램이 새로고침되었습니다. 페이지를 새로고침하세요.' });
    }
  }

  function log(match, event, item, staySec) {
    return api('log', {
      site: match.code, url: cleanUrl(match.page), item_name: item.name,
      price: item.price, event, stay_sec: staySec
    });
  }

  /* ===== 방문 기록 (페이지를 떠날 때 체류 시간과 함께 한 번) ===== */

  function startVisit() {
    const match = matchPage();
    visit = (match && match.page.logVisit) ? { match, start: Date.now(), sent: false } : null;
  }

  function endVisit() {
    if (!visit || visit.sent) return;
    visit.sent = true;
    log(visit.match, 'visit', extract(visit.match.page), secFrom(visit.start));
  }

  // 차단 팝업을 본 시간과 함께 blocked 기록 (선택했거나 페이지를 떠날 때 한 번)
  function endBlocked() {
    if (!modal || modal.logged) return;
    modal.logged = true;
    log(modal.match, 'blocked', modal.item, secFrom(modal.start));
  }

  addEventListener('pagehide', () => { endBlocked(); endVisit(); });
  addEventListener('pageshow', (e) => { if (e.persisted) startVisit(); });   // 뒤로 가기 캐시에서 돌아옴
  startVisit();

  /* ===== 결제 버튼 가로채기 ===== */

  addEventListener('click', async (e) => {
    if (bypass) return;
    const match = matchPage();
    if (!match) return;
    const btn = matchButton(e.target, match.page);
    if (!btn) return;

    e.preventDefault();
    e.stopImmediatePropagation();
    if (busy) return;   // 확인 중에 다시 누른 클릭은 버린다
    busy = true;

    const item = extract(match.page);
    const res  = await api('check', { site: match.code, item_name: item.name, price: item.price });
    if (!res.ok) {
      console.warn('[impulse-guard] 확인하지 못해 그대로 진행합니다:', res.msg);
      return proceed(match, btn, item);
    }
    if (!res.data.is_blocking && !res.data.is_impulse) return proceed(match, btn, item);
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
