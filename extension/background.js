/*
 * impulse-guard 백그라운드 (service worker)
 * 서버 호출은 모두 여기서 한다. host_permissions가 있는 주소는 CORS 제한 없이 요청할 수 있다.
 * 팝업과 content script는 chrome.runtime.sendMessage({ type: 'ipp:api', action, data })로 요청한다.
 * content script의 차단 팝업은 { type: 'ipp:open', path }로 서버의 정해진 화면을 새 탭으로 연다.
 * content script는 { type: 'ipp:setting', force }로 회원 설정(차단 시간, 차단 사이트)을 받는다. 5분간 캐시한다.
 * 차단 화면의 '이 탭 닫기'는 { type: 'ipp:closeTab' }로 보낸 탭을 닫는다.
 */

const IPP_DEFAULT_SERVER   = 'http://localhost:8000';
const IPP_TIMEOUT_MS       = 10000;
const IPP_SETTING_CACHE_MS = 5 * 60 * 1000;   // 회원 설정 캐시 시간 (5분)
const IPP_OPEN_PATHS       = ['/ipp/cooldown.php', '/ipp/setting.php'];   // ipp:open으로 열 수 있는 서버 화면

// 저장된 서버 주소와 토큰
async function ippGetConfig() {
  const cfg = await chrome.storage.local.get({ server: IPP_DEFAULT_SERVER, token: '' });
  return { server: cfg.server.replace(/\/+$/, ''), token: cfg.token };
}

// 서버 API 호출. 결과: { ok, status, data, msg }
async function ippApi(action, data = {}) {
  const { server, token } = await ippGetConfig();
  if (!token) return { ok: false, status: 0, data: null, msg: '토큰을 먼저 입력하세요.' };

  const ctrl  = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), IPP_TIMEOUT_MS);
  try {
    const res = await fetch(server + '/ipp/api/ext.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ ...data, action }),
      credentials: 'omit',   // 브라우저의 그누보드 로그인 쿠키는 보내지 않는다 (토큰으로만 인증)
      signal: ctrl.signal
    });
    const body = await res.json().catch(() => null);
    if (res.status === 401) return { ok: false, status: 401, data: body, msg: '토큰이 올바르지 않습니다. 설정 화면에서 다시 발급하세요.' };
    if (!body)              return { ok: false, status: res.status, data: null, msg: '서버 응답을 읽을 수 없습니다. (' + res.status + ')' };
    return { ok: !!body.ok, status: res.status, data: body, msg: body.msg || '' };
  } catch (e) {
    const msg = (e.name === 'AbortError') ? '서버 응답이 너무 늦습니다.' : '서버에 연결할 수 없습니다. 서버 주소와 실행 여부를 확인하세요.';
    return { ok: false, status: 0, data: null, msg };
  } finally {
    clearTimeout(timer);
  }
}

// 회원 설정. 성공한 응답만 IPP_SETTING_CACHE_MS 동안 캐시하고, force면 서버에서 다시 받는다
// - service worker는 쉬면 전역 변수가 사라지므로 chrome.storage.session(브라우저를 닫으면 지워짐)에 둔다
// - 서버 주소나 토큰이 바뀌면 캐시를 쓰지 않는다
// - data.block_until_ms: 차단 종료 시각(이 PC 시계 기준 ms). 서버가 준 남은 초로 계산해 PC 시계가 틀려도 남은 시간은 맞다
async function ippGetSetting(force = false) {
  const { server, token } = await ippGetConfig();
  const key = server + '|' + token;

  if (!force) {
    const { setting } = await chrome.storage.session.get('setting');
    if (setting && setting.key === key && Date.now() - setting.time < IPP_SETTING_CACHE_MS) return setting.res;
  }

  const res = await ippApi('setting');
  if (!res.ok) {
    await chrome.storage.session.remove('setting');
    return res;
  }
  res.data.block_until_ms = res.data.is_blocking ? Date.now() + res.data.block_remain * 1000 : 0;
  await chrome.storage.session.set({ setting: { key, time: Date.now(), res } });
  return res;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;   // 다른 확장 프로그램의 메시지는 무시
  if (!msg) return false;

  if (msg.type === 'ipp:open' && IPP_OPEN_PATHS.includes(msg.path)) {
    ippGetConfig().then(({ server }) => chrome.tabs.create({ url: server + msg.path }));
    return false;
  }
  if (msg.type === 'ipp:closeTab' && sender.tab) {
    chrome.tabs.remove(sender.tab.id);
    return false;
  }
  if (msg.type === 'ipp:setting') {
    ippGetSetting(!!msg.force).then(sendResponse);
    return true;
  }
  if (msg.type !== 'ipp:api') return false;

  ippApi(msg.action, msg.data || {}).then(sendResponse);
  return true;   // 비동기 응답
});
