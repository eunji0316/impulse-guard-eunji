"""서버 통신 (그누보드 서버의 외부 프로그램 API ipp/api/client.php, 명세는 docs/API.md)

- 서버 주소와 토큰은 desktop/local_config.json에서 읽는다 (Git에 올리지 않음, 예시: local_config.example.json)
- 모든 요청은 Client.call() 하나를 지난다. 응답이 config.SERVER_TIMEOUT_SEC(2초)를 넘거나 실패하면
  예외를 던지지 않고 ApiResult(ok=False, offline=True)를 돌려준다. 프로그램은 감지를 계속한다.
- 시작할 때 me로 회원을 확인한다. 실패하면 오프라인 모드이고, F4를 누를 때 60초 간격으로 다시 연결해 본다.
  토큰이 틀리면(401) 다시 시도하지 않는다 (토큰을 다시 발급해야 함).
- 회원 설정(차단 시간, 키워드)은 1분간 캐시한다 (config.SETTING_CACHE_SEC). 자동 감지는 쇼핑 화면에 들어설 때 캐시를 무시하고 다시 받는다. 남은 차단 시간은 서버가 준 남은 초로 계산한다 (PC 시계와 무관).
- 캡처 이미지는 보내지 않는다. 상품명, 가격 등 필요한 값만 보낸다.
- 테스트에서는 transport(실제 HTTP 호출 함수)와 clock(현재 시각 함수)을 바꿔 끼운다.
- B-3부터 감지 작업 스레드와 팝업 버튼 스레드가 함께 부르므로 요청은 잠금(lock)으로 하나씩 보낸다.
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import config, timing

DESKTOP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class ApiResult:
    ok: bool
    data: dict = field(default_factory=dict)
    status: int = None           # HTTP 상태 (연결 실패면 None)
    msg: str = ''                # 서버의 msg 또는 연결 오류 설명
    offline: bool = False        # 서버에 닿지 못함 (시간 초과, 연결 거부, 토큰 없음 등)


def auto_settings(data=None):
    """local_config.json의 "auto_detect" 값을 config.AUTO_DETECT_DEFAULTS에 덮어쓴다. 잘못된 값은 기본값"""
    out = dict(config.AUTO_DETECT_DEFAULTS)
    data = data if isinstance(data, dict) else {}
    for key in ('enabled', 'save_ocr_text'):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    programs = data.get('exclude_programs')
    if isinstance(programs, list) and all(isinstance(p, str) for p in programs):
        out['exclude_programs'] = [p.strip() for p in programs if p.strip()][:100]   # [] 이면 아무것도 제외하지 않음
    limits = {'interval_sec': (1, 60), 'same_order_minutes': (0, 24 * 60), 'blocked_repeat_sec': (0, 24 * 3600)}
    for key, (lo, hi) in limits.items():
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            out[key] = v
    return out


def load_config(path=None):
    """local_config.json 읽기. 파일이 없거나 깨졌으면 토큰 없는 기본값 (→ 오프라인 모드)
    auto: 자동 감지 설정 (auto_settings)"""
    path = path or os.path.join(DESKTOP_DIR, config.LOCAL_CONFIG)
    conf = {'server': config.DEFAULT_SERVER, 'token': '', 'timeout_sec': config.SERVER_TIMEOUT_SEC, 'error': '',
            'auto': auto_settings(), 'auto_source': '기본값'}   # auto_source: 자동 감지 설정을 어디서 읽었나 (로그용)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        conf['server'] = str(data.get('server') or conf['server']).rstrip('/')
        conf['token'] = str(data.get('token') or '').strip()
        conf['timeout_sec'] = float(data.get('timeout_sec') or conf['timeout_sec'])
        conf['auto'] = auto_settings(data.get('auto_detect'))
        conf['auto_source'] = (config.LOCAL_CONFIG if isinstance(data.get('auto_detect'), dict)
                               else f'기본값 ({config.LOCAL_CONFIG}에 auto_detect 없음)')
    except FileNotFoundError:
        conf['error'] = f'{config.LOCAL_CONFIG} 파일이 없습니다'
    except (ValueError, OSError) as e:
        conf['error'] = f'{config.LOCAL_CONFIG}을 읽지 못했습니다: {e}'
    return conf


def http_post(url, body, token, timeout):
    """실제 HTTP POST. (상태 코드, JSON 사전)을 돌려준다. 연결 실패/시간 초과는 예외"""
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:      # 4xx/5xx도 서버는 JSON을 보낸다
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except ValueError:
            return e.code, {'ok': False, 'msg': f'HTTP {e.code}'}


class Client:
    def __init__(self, server=config.DEFAULT_SERVER, token='', timeout=config.SERVER_TIMEOUT_SEC,
                 transport=http_post, clock=time.monotonic):
        self.server = server.rstrip('/')
        self.token = token
        self.timeout = timeout
        self.transport = transport
        self.clock = clock
        self.online = False
        self.auth_failed = False     # 토큰이 틀림 (401). 다시 연결하지 않는다
        self.member = {}             # me 응답
        self.last_error = '' if token else '토큰이 없습니다'
        self._last_connect = None    # 마지막 연결 시도 시각
        self._setting = None         # setting 응답
        self._setting_at = None      # setting을 받은 시각
        self._lock = threading.RLock()   # 여러 스레드(감지 작업, 팝업 버튼)의 요청을 하나씩 보낸다

    @classmethod
    def from_config(cls, path=None, **kwargs):
        conf = load_config(path)
        client = cls(conf['server'], conf['token'], conf['timeout_sec'], **kwargs)
        if conf['error'] and not conf['token']:
            client.last_error = conf['error']
        return client

    # ── 요청 ───────────────────────────────────────────────
    def call(self, action, **data):
        """API 호출. 어떤 경우에도 예외를 던지지 않는다"""
        with self._lock:
            return self._call(action, data)

    def _call(self, action, data):
        if not self.token:
            return ApiResult(False, msg=self.last_error or '토큰이 없습니다', offline=True)
        body = {'client': config.CLIENT_NAME, 'action': action, **data}
        try:
            with timing.measure_server(action):
                status, resp = self.transport(self.server + config.API_PATH, body, self.token, self.timeout)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as e:
            reason = getattr(e, 'reason', e)
            msg = '응답 시간 초과' if isinstance(reason, (socket.timeout, TimeoutError)) else f'연결 실패: {reason}'
            self._went_offline(msg)
            return ApiResult(False, msg=msg, offline=True)

        if not isinstance(resp, dict):
            resp = {}
        msg = str(resp.get('msg', ''))
        if status == 401:
            self.auth_failed = True
            self._went_offline(msg or '토큰이 올바르지 않습니다')
            return ApiResult(False, resp, status, msg, offline=True)
        if self.member and not self.online:
            self.online, self.last_error = True, ''   # 서버가 다시 응답함 (한 번 연결된 적이 있을 때만)
        ok = status == 200 and bool(resp.get('ok'))
        return ApiResult(ok, resp, status, msg)

    def _went_offline(self, msg):
        self.online = False
        self.last_error = msg

    # ── 연결 ───────────────────────────────────────────────
    def connect(self):
        """me로 회원 확인. 성공하면 online"""
        self._last_connect = self.clock()
        r = self.call('me')
        if r.ok:
            self.online, self.member, self.last_error = True, r.data, ''
        elif not r.offline:
            self._went_offline(r.msg or f'HTTP {r.status}')
        return r

    def ensure_online(self):
        """오프라인이면 RECONNECT_SEC 간격으로 다시 연결해 본다. 토큰이 틀렸으면 시도하지 않는다"""
        if self.online:
            return True
        if not self.token or self.auth_failed:
            return False
        if self._last_connect is None or self.clock() - self._last_connect >= config.RECONNECT_SEC:
            self.connect()
        return self.online

    # ── 회원 설정 (1분 캐시) ───────────────────────────────
    def get_setting(self, force=False):
        """setting 응답. 캐시가 SETTING_CACHE_SEC 안이면 캐시, 아니면(또는 force) 서버에 다시 묻는다. 실패하면 예전 캐시(없으면 None)"""
        fresh = self._setting_at is not None and self.clock() - self._setting_at < config.SETTING_CACHE_SEC
        if fresh and not force:
            return self._setting
        if self.online:
            r = self.call('setting')
            if r.ok:
                self._setting, self._setting_at = r.data, self.clock()
        return self._setting

    def setting_age(self):
        return None if self._setting_at is None else self.clock() - self._setting_at

    def block_remain(self):
        """캐시된 설정 기준 남은 차단 시간(초). 차단 중이 아니거나 모르면 0"""
        st = self._setting
        if not st or not st.get('is_blocking'):
            return 0
        return max(0, int(st.get('block_remain', 0) - self.setting_age()))

    def is_blocking_for(self, site):
        """캐시된 설정으로 이 쇼핑몰이 지금 차단 대상인지 (서버 ipp_is_blocking()과 같은 규칙, B-4)
        쇼핑몰 전체 차단(block_all, 없으면 켬)이면 모두, 끄면 켜 둔 사이트만. 사이트를 모르면('') 차단 시간만 본다"""
        if not self.block_remain():
            return False
        st = self._setting or {}
        if st.get('block_all', True) or not site:
            return True
        return any(s.get('code') == site and s.get('on') for s in st.get('sites', []))

    def site_hints(self):
        """서버 사이트 목록의 이름 {코드: [이름]} (사이트 찾기에 더한다)"""
        st = self._setting or {}
        return {s['code']: [s.get('name', '')] for s in st.get('sites', []) if 'code' in s}

    # ── 감지 ───────────────────────────────────────────────
    def check(self, site, item_name, price, orig_price=0, discount_rate=0, is_checkout=False, page='', log=True):
        """상품 판단 + detect 기록 (log=True). 결과: ApiResult (data: is_blocking, is_impulse, keyword, point, point2, bl_id)"""
        if not self.ensure_online():
            return ApiResult(False, msg=self.last_error or '오프라인', offline=True)
        return self.call('check', site=site, item_name=item_name, price=int(price or 0),
                         orig_price=int(orig_price or 0), discount_rate=int(discount_rate or 0),
                         is_checkout=bool(is_checkout), page=page, log=log)

    # ── 팝업 결정 (B-3) ────────────────────────────────────
    # 팝업 버튼은 오프라인이어도 한 번은 실제로 보내 본다 (check가 성공한 직후라 서버가 살아 있을 가능성이 크다)
    def cooldown(self, item_name, price, bl_id=0):
        """조금 더 생각하기: 쿨다운 시작 + 감지 기록에 hold. data: cd_id, expire, point2"""
        return self.call('cooldown', item_name=item_name, price=int(price or 0), bl_id=int(bl_id or 0))

    def giveup(self, item_name, price, bl_id=0):
        """안 살래요: 즉시 포기 + 포인트 지급 + 감지 기록에 giveup. data: cd_id, point"""
        return self.call('giveup', item_name=item_name, price=int(price or 0), bl_id=int(bl_id or 0))

    def fill_amount(self, bl_id, price):
        """결제 화면 감지 기록(금액 0)에 나중에 읽은 금액을 채운다 (B-5). 이미 금액이 있으면 409"""
        return self.call('amount', bl_id=int(bl_id or 0), price=int(price or 0))

    def decide(self, bl_id, decision):
        """기록만 남기는 결정: buy(그래도 구매), close(창 닫기), giveup(가격을 몰라 포인트 없이 포기)"""
        return self.call('decide', bl_id=int(bl_id or 0), decision=decision)
