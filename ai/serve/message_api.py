"""5 LLM 주간 리포트 요약 서비스

POST /message/weekly  {"this_week": {...}, "last_week": {...}, "top_reasons": [{"code", "count"}], "derived": {...}}
                      → {"headline", "summary", "tip", "model", "cached"}
- 입력은 회원 한 명의 두 주 집계 숫자와 이유 코드뿐이다. 회원 아이디, 쇼핑몰 이름, 상품명, 시각은 받지 않는다 (extra=forbid)
- derived: 서버 PHP가 미리 계산한 증감·배수·비율. LLM은 직접 계산하지 않고 이 값만 쓴다. 두 주 숫자와 맞지 않으면 422
- Claude API(기본 claude-haiku-5-5, effort low)로 짧은 요약을 JSON 형식으로 받아 검사한다.
  입력에 없는 숫자를 쓰거나, 너무 길거나, 거절·잘림이면 버린다 (502). 서버 PHP는 요약 칸을 보이지 않는다
- 키가 없으면 503. 하루 호출 상한을 넘으면 503. 같은 입력은 메모리 캐시에서 돌려준다 (요청·응답을 파일이나 로그에 남기지 않음)
"""
import hashlib
import json
import re
import threading
import time
from datetime import date
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator

from . import config
from .common import StrictBody

# 위험도 이유 코드 (ipp_risk_reason_text와 같음). LLM에는 코드 대신 뜻을 함께 준다
REASON_MEANING = {
    'night':        '심야(밤 11시~새벽 4시) 결제 시도',
    'evening':      '늦은 저녁(밤 9~11시) 결제 시도',
    'weekend':      '주말 결제 시도',
    'payday':       '월급일 직후 결제 시도',
    'amount':       '큰 금액',
    'amount_ratio': '평소보다 큰 금액',
    'discount':     '할인 상품',
    'pressure':     "'오늘만', '품절 임박' 같은 서두르게 하는 문구",
    'views':        '상품 화면을 여러 번 봄',
    'same_item':    '같은 상품을 반복해서 봄',
    'browse':       '상품을 짧게 보고 바로 결제하려 함',
    'frequency':    '최근 결제 화면에 자주 들어감',
    'history':      "지난 팝업에서 '그래도 구매'를 자주 고름",
    'cooldown':     '담아 둔 상품을 기다리지 못하고 삼',
}

Count  = Annotated[int, Field(strict=True, ge=0, le=100000)]
Amount = Annotated[int, Field(strict=True, ge=0, le=10**10)]


class WeekStats(StrictBody):
    checkouts: Count            # 결제 화면 감지 수
    buy: Count                  # 팝업: 그래도 구매
    giveup: Count               # 팝업: 안 살래요
    hold: Count                 # 팝업: 담아두기(24시간)
    hold_success: Count         # 이 기간에 끝난 담아두기 중 끝까지 참음
    hold_failed: Count          # 이 기간에 끝난 담아두기 중 참지 못하고 삼
    saved_amount: Amount        # 예상 절약 금액(원, 1,000원 단위로 반올림)
    risk_high: Count            # 위험 높음 결제 화면 수
    risk_mid: Count
    risk_low: Count
    night: Count                # 밤 11시~새벽 4시 결제 화면 수
    malls: Count                # 결제 화면이 나온 쇼핑몰 수 (이름은 보내지 않음)
    blocked: Count              # 차단 시간에 막은 횟수


class ReasonCount(StrictBody):
    code: Literal[tuple(REASON_MEANING)]
    count: Count


Diff  = Annotated[int, Field(strict=True, ge=-10**10, le=10**10)]
Ratio = Optional[Annotated[float, Field(strict=True, ge=0, le=100000, allow_inf_nan=False)]]
Rate  = Optional[Annotated[int, Field(strict=True, ge=0, le=100)]]

DIFF_FIELDS  = ('checkouts', 'night', 'blocked', 'buy', 'giveup', 'saved_amount')
RATIO_FIELDS = ('checkouts', 'night', 'blocked')


class Derived(StrictBody):
    """서버 PHP가 미리 계산한 파생 값 (ipp_report_derived). LLM은 직접 계산하지 않고 이 값만 쓴다"""
    checkouts_diff: Diff            # 이번 주 − 지난주
    night_diff: Diff
    blocked_diff: Diff
    buy_diff: Diff
    giveup_diff: Diff
    saved_amount_diff: Diff
    checkouts_ratio: Ratio          # 이번 주 ÷ 지난주 (소수 한 자리). 지난주가 0이면 null
    night_ratio: Ratio
    blocked_ratio: Ratio
    resist_rate_this: Rate          # 참은 비율 % = (안 살래요 + 담아두기) ÷ (그래도 구매 + 안 살래요 + 담아두기). 결정이 없으면 null
    resist_rate_last: Rate
    hold_success_rate_this: Rate    # 담아두기 성공 비율 % = 참음 ÷ (참음 + 삼). 끝난 담아두기가 없으면 null
    hold_success_rate_last: Rate


def _rate(num, den):
    return None if den <= 0 else 100 * num / den


def expected_derived(a, b):
    """두 주 숫자로 계산한 파생 값 (반올림 전). PHP가 보낸 값과 맞는지 확인할 때 쓴다"""
    out = {f'{k}_diff': a[k] - b[k] for k in DIFF_FIELDS}
    out.update({f'{k}_ratio': (a[k] / b[k] if b[k] > 0 else None) for k in RATIO_FIELDS})
    for w, s in ((a, 'this'), (b, 'last')):
        out[f'resist_rate_{s}'] = _rate(w['giveup'] + w['hold'], w['buy'] + w['giveup'] + w['hold'])
        out[f'hold_success_rate_{s}'] = _rate(w['hold_success'], w['hold_success'] + w['hold_failed'])
    return out


class WeeklyRequest(StrictBody):
    this_week: WeekStats
    last_week: WeekStats
    top_reasons: Annotated[List[ReasonCount], Field(max_length=5)] = []
    derived: Optional[Derived] = None

    @model_validator(mode='after')
    def _derived_matches(self):
        """파생 값이 두 주 숫자와 맞아야 한다 (반올림 차이만 허용: 배수 0.05, 비율 1%p)"""
        if self.derived is None:
            return self
        want = expected_derived(self.this_week.model_dump(), self.last_week.model_dump())
        got = self.derived.model_dump()
        for k, w in want.items():
            g = got[k]
            if (w is None) != (g is None):
                raise ValueError(f'derived {k} null mismatch')
            if w is None:
                continue
            tol = 0 if k.endswith('_diff') else (0.051 if k.endswith('_ratio') else 1.0)
            if abs(g - w) > tol:
                raise ValueError(f'derived {k} mismatch')
        return self


OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'headline': {'type': 'string', 'description': '한 줄 제목'},
        'summary':  {'type': 'string', 'description': '이번 주 요약, 3문장 이내'},
        'tip':      {'type': 'string', 'description': '다음 주를 위한 제안 한 문장'},
    },
    'required': ['headline', 'summary', 'tip'],
    'additionalProperties': False,
}
MAX_LEN = {'headline': 40, 'summary': 220, 'tip': 100}

SYSTEM = """당신은 충동구매 방지 앱의 주간 리포트를 쓰는 도우미입니다.
사용자에게 이번 주와 지난주의 쇼핑 집계 숫자가 주어집니다. 이것을 바탕으로 짧은 한국어 리포트를 씁니다.

규칙
- 해요체로 따뜻하고 담백하게 씁니다. 꾸짖거나 겁주지 않고, 참은 것은 구체적으로 칭찬합니다.
- headline은 40자 이내 한 줄, summary는 3문장 이내(220자 이내), tip은 다음 주에 해 볼 행동 하나(100자 이내)입니다.
- 숫자는 보낸 값만 그대로 씁니다. 차이, 배수, 비율, 퍼센트, 평균을 직접 계산하지 않습니다.
  지난주 대비 증감·배수·참은 비율이 필요하면 '미리 계산한 값'에 있는 숫자만 씁니다. 값이 null이면 그 비교는 쓰지 않습니다.
- 금액은 '32,000원', 배수는 '1.7배', 비율은 '67%'처럼 씁니다. 차이가 음수면 '줄었어요'로 씁니다(예: -2 → 2번 줄었어요).
- 입력에 없는 사실(상품, 쇼핑몰 이름, 요일, 날짜)을 지어내지 않습니다. 쇼핑몰은 개수만 압니다.
- 결제 화면이 두 주 모두 0이면 쇼핑 시도가 없었다고 짧게 말합니다.
- 금융·의료 조언이나 다른 서비스 추천은 하지 않습니다."""

FIELD_LABEL = {
    'checkouts': '결제 화면 감지', 'buy': "팝업에서 '그래도 구매'", 'giveup': "팝업에서 '안 살래요'",
    'hold': "팝업에서 '담아두기(24시간)'", 'hold_success': '담아두기 끝까지 참음', 'hold_failed': '담아두기 중 참지 못하고 삼',
    'saved_amount': '예상 절약 금액(원)', 'risk_high': '위험 높음', 'risk_mid': '위험 보통', 'risk_low': '위험 낮음',
    'night': '심야 결제 화면', 'malls': '결제 화면이 나온 쇼핑몰 수', 'blocked': '차단 시간에 막은 횟수',
}

DERIVED_LABEL = {
    'checkouts_diff': '결제 화면 감지 차이(이번 주 − 지난주)', 'night_diff': '심야 결제 화면 차이(이번 주 − 지난주)',
    'blocked_diff': '차단 횟수 차이(이번 주 − 지난주)', 'buy_diff': "'그래도 구매' 차이(이번 주 − 지난주)",
    'giveup_diff': "'안 살래요' 차이(이번 주 − 지난주)", 'saved_amount_diff': '예상 절약 금액 차이(원, 이번 주 − 지난주)',
    'checkouts_ratio': '결제 화면 감지 배수(이번 주 ÷ 지난주)', 'night_ratio': '심야 결제 화면 배수(이번 주 ÷ 지난주)',
    'blocked_ratio': '차단 횟수 배수(이번 주 ÷ 지난주)',
    'resist_rate_this': '이번 주 참은 비율(%, 안 살래요·담아두기 ÷ 팝업 결정)', 'resist_rate_last': '지난주 참은 비율(%)',
    'hold_success_rate_this': '이번 주 담아두기 성공 비율(%)', 'hold_success_rate_last': '지난주 담아두기 성공 비율(%)',
}


def build_prompt(req: WeeklyRequest) -> str:
    """LLM에 보낼 사용자 메시지. 숫자와 이유의 뜻만 담는다"""
    data = {
        '이번 주(최근 7일)': {FIELD_LABEL[k]: v for k, v in req.this_week.model_dump().items()},
        '지난주(그 전 7일)': {FIELD_LABEL[k]: v for k, v in req.last_week.model_dump().items()},
        '이번 주 위험을 올린 이유 (횟수)': {REASON_MEANING[r.code]: r.count for r in req.top_reasons},
    }
    if req.derived is not None:
        data['미리 계산한 값 (이 숫자만 쓰고 직접 계산하지 마세요)'] = {DERIVED_LABEL[k]: v for k, v in req.derived.model_dump().items()}
    return '다음 집계로 주간 리포트를 써 주세요.\n' + json.dumps(data, ensure_ascii=False, indent=1)


NUM_RE = re.compile(r'\d[\d,]*(?:\.\d+)?')   # 1,234 / 1.7 (소수는 한 덩어리로)


def num_value(m):
    return float(m.replace(',', ''))   # 반올림하지 않는다 (1.67배는 보낸 1.7배와 다름)


def allowed_numbers(req: WeeklyRequest):
    """문장에 써도 되는 숫자: 보낸 글에 나온 숫자(입력 값, 파생 값, 이유 설명의 '밤 11시' 등), 두 주의 차이, 기간(7일, 24시간)"""
    a, b = req.this_week.model_dump(), req.last_week.model_dump()
    nums = {7, 24}
    for k in a:
        nums.update({a[k], b[k], abs(a[k] - b[k])})
    nums.update(r.count for r in req.top_reasons)
    nums.update(num_value(m) for m in NUM_RE.findall(build_prompt(req)))
    return nums


def check_output(data, req: WeeklyRequest):
    """LLM 응답 검사. 문제가 있으면 이유 문자열, 없으면 None"""
    if not isinstance(data, dict) or set(data) != set(MAX_LEN):
        return 'shape'
    nums = allowed_numbers(req)
    for k, limit in MAX_LEN.items():
        v = data[k]
        if not isinstance(v, str) or not v.strip():
            return f'{k} empty'
        if len(v) > limit:
            return f'{k} too long'
        if '<' in v or '>' in v:
            return f'{k} markup'
        for m in NUM_RE.findall(v):
            if num_value(m) not in nums:
                return f'{k} unknown number'
    return None


class Unavailable(Exception):
    pass


class WeeklyService:
    def __init__(self, client_factory=None, model=None, daily_limit=None, credentials=None, now=time.time, today=date.today):
        self.model = model or config.LLM_MODEL
        self.daily_limit = config.LLM_DAILY_LIMIT if daily_limit is None else daily_limit
        self.credentials = config.llm_credentials() if credentials is None else credentials
        self._factory = client_factory or self._default_client
        self._client = None
        self._auth_failed = False
        self._now, self._today = now, today
        self._lock = threading.Lock()
        self._cache = {}            # 입력 해시 → (만든 시각, 결과). 회원 아이디는 키에 없다
        self._day, self._calls = None, 0

    @staticmethod
    def _default_client():
        import anthropic
        return anthropic.Anthropic(timeout=config.LLM_TIMEOUT, max_retries=1)

    def available(self):
        return bool(self.credentials) and not self._auth_failed

    def health(self):
        if not self.available():
            return None
        with self._lock:
            calls = self._calls if self._day == self._today() else 0
        return {'model': self.model, 'credentials': self.credentials, 'calls_today': calls, 'daily_limit': self.daily_limit}

    def _key(self, req):
        raw = json.dumps(req.model_dump(), sort_keys=True) + '|' + self.model
        return hashlib.sha256(raw.encode()).hexdigest()

    def _take_call(self):
        with self._lock:
            if self._day != self._today():
                self._day, self._calls = self._today(), 0
            if self._calls >= self.daily_limit:
                return False
            self._calls += 1
            return True

    def weekly(self, req: WeeklyRequest):
        if not self.available():
            raise Unavailable('no credentials')
        key = self._key(req)
        with self._lock:
            hit = self._cache.get(key)
            if hit and self._now() - hit[0] < config.LLM_CACHE_SEC:
                return {**hit[1], 'cached': True}
        if not self._take_call():
            raise Unavailable('daily limit')
        result = self._call(req)
        with self._lock:
            if len(self._cache) >= 1000:   # 오래된 것부터 정리
                for k in sorted(self._cache, key=lambda k: self._cache[k][0])[:200]:
                    del self._cache[k]
            self._cache[key] = (self._now(), result)
        return {**result, 'cached': False}

    def _call(self, req):
        import anthropic
        if self._client is None:
            self._client = self._factory()
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=SYSTEM,
                messages=[{'role': 'user', 'content': build_prompt(req)}],
                output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.CredentialsError):
            self._auth_failed = True      # 키가 틀림: 서버를 다시 켤 때까지 부르지 않는다
            raise Unavailable('auth')
        except anthropic.RateLimitError:
            raise HTTPException(502, 'rate limited')
        except anthropic.APIStatusError as e:
            raise HTTPException(502, f'api error {e.status_code}')
        except anthropic.APIConnectionError:   # 시간 초과 포함
            raise HTTPException(502, 'connection')

        if resp.stop_reason != 'end_turn':    # refusal, max_tokens 등은 쓰지 않는다
            raise HTTPException(502, f'stop {resp.stop_reason}')
        text = next((b.text for b in resp.content if getattr(b, 'type', '') == 'text'), None)
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        problem = check_output(data, req)
        if problem:
            raise HTTPException(502, f'bad output: {problem}')
        return {k: data[k].strip() for k in MAX_LEN} | {'model': self.model}


def make_router(service=None):
    svc = service or WeeklyService()
    router = APIRouter(prefix='/message', tags=['message'])

    @router.post('/weekly')
    def weekly(req: WeeklyRequest):
        try:
            return svc.weekly(req)
        except Unavailable as e:
            raise HTTPException(503, f'llm unavailable: {e}')

    return router, svc.health
