/*
 * impulse-guard 백그라운드 (service worker)
 * 서버 호출은 모두 여기서 한다. host_permissions가 있는 주소는 CORS 제한 없이 요청할 수 있다.
 * 팝업과 (3-2의) content script는 chrome.runtime.sendMessage({ type: 'ipp:api', action, data })로 요청한다.
 */

const IPP_DEFAULT_SERVER = 'http://localhost:8000';
const IPP_TIMEOUT_MS     = 10000;

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

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;   // 다른 확장 프로그램의 메시지는 무시
  if (!msg || msg.type !== 'ipp:api') return false;

  ippApi(msg.action, msg.data || {}).then(sendResponse);
  return true;   // 비동기 응답
});
