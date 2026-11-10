/*
 * 팝업: 서버 주소와 토큰을 chrome.storage.local에 저장하고 연결을 확인한다.
 * storage.sync는 구글 계정으로 다른 기기에 동기화되므로 토큰 보관에 쓰지 않는다.
 */

const IPP_DEFAULT_SERVER = 'http://localhost:8000';
const $ = (id) => document.getElementById(id);

function showStatus(text, type) {
  $('status').textContent = text;
  $('status').className = 'status ' + (type || '');
}

// 주소 정리: http(s)만 허용, 끝의 / 제거. 잘못된 주소면 null
function normalizeServer(value) {
  try {
    const url = new URL(value.trim() || IPP_DEFAULT_SERVER);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    return (url.origin + url.pathname).replace(/\/+$/, '');
  } catch (e) {
    return null;
  }
}

// 기본 권한(localhost, 127.0.0.1) 밖의 서버면 그 주소만 권한을 요청한다. 버튼 클릭 안에서 불러야 한다
async function ensurePermission(server) {
  const origins = [new URL(server).origin + '/*'];
  if (await chrome.permissions.contains({ origins })) return true;
  return chrome.permissions.request({ origins });
}

function api(action, data) {
  return chrome.runtime.sendMessage({ type: 'ipp:api', action, data });
}

async function testConnection() {
  showStatus('연결 확인 중…');
  const res = await api('me');
  if (res.ok) showStatus('연결됨: ' + res.data.nick + ' (' + res.data.point.toLocaleString() + 'P)', 'ok');
  else        showStatus(res.msg, 'err');
}

$('save').addEventListener('click', async () => {
  const server = normalizeServer($('server').value);
  const token  = $('token').value.trim();
  if (!server)                       return showStatus('서버 주소가 올바르지 않습니다.', 'err');
  if (!/^[0-9a-f]{64}$/.test(token)) return showStatus('토큰은 64자리 영문 소문자와 숫자입니다.', 'err');

  $('save').disabled = true;
  try {
    if (!(await ensurePermission(server))) return showStatus('서버 주소 접근 권한을 허용해야 합니다.', 'err');
    await chrome.storage.local.set({ server, token });
    $('server').value = server;
    await testConnection();
  } finally {
    $('save').disabled = false;
  }
});

$('clear').addEventListener('click', async () => {
  await chrome.storage.local.remove('token');
  $('token').value = '';
  showStatus('연결을 해제했습니다.');
});

$('toggle').addEventListener('click', () => {
  const show = $('token').type === 'password';
  $('token').type = show ? 'text' : 'password';
  $('toggle').textContent = show ? '숨기기' : '보기';
});

// 팝업을 열면 저장된 값을 채우고, 토큰이 있으면 바로 연결 상태를 보여 준다
(async () => {
  const cfg = await chrome.storage.local.get({ server: IPP_DEFAULT_SERVER, token: '' });
  $('server').value = cfg.server;
  $('token').value  = cfg.token;
  if (cfg.token) testConnection();
  else           showStatus('설정 화면에서 발급한 토큰을 입력하세요.');
})();
