"""같은 화면/같은 주문 중복 방지 (B-4)

1. 같은 화면: 자동 감지 루프가 직전에 분석한 화면의 해시와 비교해 OCR을 건너뛴다 (auto_detect.py)
2. 같은 주문 (RecentOrders): 결제 화면에서 기록과 팝업을 한 번만 한다
   - 쇼핑몰이 다르면 다른 주문
   - 금액을 둘 다 읽었으면 금액이 같아야 같은 주문 (탭 제목은 보지 않는다. 지그재그는 같은 장바구니라도
     '구매하기'를 누를 때마다 주문서 주소(탭 제목)가 새로 생긴다)
   - 금액을 한쪽이라도 모르면: 탭 제목이 다르면 다른 주문. 같거나 모르면 결제 화면에 계속 머무는 중(스크롤해서 맨 위 → 총 결제금액)이거나,
     제목에 주문서 번호가 있고 같거나, 화면 해시 거리가 config.ORDER_SAME_DISTANCE 이하일 때 같은 주문
   - 처음에 금액을 못 읽었다가 나중에 읽으면 같은 주문에 채운다 (Verdict.filled)
     제목 원문은 기억하지 않고 해시(title_key)만 메모리에서 비교한다. 로그와 파일에도 남기지 않는다
   - 보류 주문 (resolve): 금액을 모르는 새 주문을 금액을 읽은 뒤 최근 주문과 같은지 다시 판단한다 (main의 금액 확인 기다림)
   - 기준 시간은 '마지막으로 본 시각'부터 same_order_minutes (sliding window)
     · 결제 화면에 계속 머무르면 볼 때마다 시각이 갱신되어 다시 뜨지 않는다
     · 다른 창에 갔다가 기준 시간 안에 돌아오면 같은 시도로 본다 (revisit으로 기록만)
     · 기준 시간보다 오래 떠나 있다가 돌아오면 새 시도로 본다
   - 팝업에서 무엇을 골랐든(안 살래요, 조금 더 생각하기, 그래도 구매, X) 그 주문의 팝업은 다시 띄우지 않는다
3. 차단 안내 창 (NoticeGate): 창을 닫은 뒤 같은 쇼핑몰에서 blocked_repeat_sec 동안은 다시 띄우지 않는다

기억은 프로그램이 켜져 있는 동안 메모리에만 둔다. 화면 이미지는 기억하지 않고 해시만 둔다.
"""
import hashlib
import re
import time
from dataclasses import dataclass

from . import config, frame


@dataclass(frozen=True)
class TitleKey:
    """탭 제목의 해시. 제목 원문은 두지 않는다"""
    digest: int
    specific: bool               # 주문서 번호처럼 주문마다 다른 값이 들어 있는 제목


def title_key(title):
    """탭 제목 → TitleKey (제목이 없으면 None). 원문은 여기서 버린다"""
    title = (title or '').strip().lower()
    if not title:
        return None
    digest = int.from_bytes(hashlib.blake2b(title.encode('utf-8'), digest_size=8).digest(), 'big')
    return TitleKey(digest, bool(re.search(config.ORDER_TITLE_ID_RE, title)))


def titles_differ(a, b):
    """두 탭 제목으로 다른 주문이라고 말할 수 있으면 True (C-2: 금액 모름 기다림을 건너뛸지)
    둘 다 알고, 둘 다 주문서 번호가 없는 제목이고, 서로 다를 때만. 주문서 번호가 든 제목(specific)은 지그재그처럼
    같은 장바구니라도 '구매하기'마다 새로 생기므로 제목이 달라도 다른 주문이라고 할 수 없다 (B-5 중복 팝업 버그)"""
    return a is not None and b is not None and not a.specific and not b.specific and a.digest != b.digest


@dataclass
class SeenOrder:
    site: str
    amount: int                  # 0 = 금액 모름
    frame_hash: int
    first_seen: float
    last_seen: float
    count: int = 1               # 본 횟수
    decision: str = ''           # 팝업 결정: hold, giveup, buy, close ('' = 아직)
    bl_id: int = 0               # 서버 감지 기록 번호 (check가 준 값. 팝업을 띄운 주문만)
    title: TitleKey = None       # 탭 제목 해시 (모르면 None)
    price_sent: bool = False     # 서버 감지 기록에 금액이 있다 (check 때 보냈거나 나중에 amount로 채움)

    @property
    def key(self):
        return self.site, self.amount


@dataclass
class Verdict:
    is_dup: bool
    order: SeenOrder
    reason: str = 'new'          # new / same (계속 머무름) / revisit (다른 화면에 갔다 옴)
    away_sec: float = 0.0        # revisit이면 떠나 있던 시간
    filled: bool = False         # 이번에 처음으로 금액을 읽어 같은 주문에 채웠다


class RecentOrders:
    def __init__(self, window_sec=None, hash_distance=None, clock=time.monotonic):
        self.window = window_sec if window_sec is not None else config.AUTO_DETECT_DEFAULTS['same_order_minutes'] * 60
        self.hash_distance = config.ORDER_SAME_DISTANCE if hash_distance is None else hash_distance
        self.clock = clock
        self.orders = []
        self.current = None          # 지금 화면에 있는 주문 (다른 화면을 보면 None)

    def _expire(self, now):
        self.orders = [o for o in self.orders if now - o.last_seen <= self.window]
        if self.current is not None and self.current not in self.orders:
            self.current = None

    def _same(self, o, site, amount, frame_hash, title):
        if site and o.site and site != o.site:
            return False
        if amount and o.amount:
            return o.site == site and o.amount == amount
        if title is not None and o.title is not None and title.digest != o.title.digest:
            return False                          # 금액을 모를 때 탭 제목이 다르면 다른 주문
        # 금액을 한쪽이라도 모른다
        if o is self.current:
            return True                           # 결제 화면에 계속 머무는 중 (스크롤해서 금액이 보이게 됨)
        if title is not None and o.title is not None and title.specific:
            return True                           # 주문서 번호가 든 제목이 같다
        return frame.distance(o.frame_hash, frame_hash) <= self.hash_distance

    def see(self, site, amount, frame_hash, title=None):
        """결제 화면을 봤다. 같은 주문이 있으면 중복(갱신), 없으면 새로 기억한다. title: title_key()"""
        now = self.clock()
        self._expire(now)
        amount = int(amount or 0)
        for o in self.orders:
            if self._same(o, site, amount, frame_hash, title):
                away = now - o.last_seen
                reason = 'same' if o is self.current else 'revisit'
                o.last_seen, o.count = now, o.count + 1
                filled = bool(amount and not o.amount)
                if filled:
                    o.amount = amount            # 처음에 금액을 못 읽었으면 채운다
                if title is not None:
                    o.title = title
                o.frame_hash = frame_hash
                self.current = o
                return Verdict(True, o, reason, away if reason == 'revisit' else 0.0, filled)
        o = SeenOrder(site, amount, frame_hash, now, now, title=title)
        self.orders.append(o)
        self.current = o
        return Verdict(False, o)

    def recent_known(self, site, exclude=None):
        """같은 쇼핑몰에서 금액을 아는 최근 주문 (없으면 None)"""
        self._expire(self.clock())
        known = [o for o in self.orders if o is not exclude and o.amount and (not site or not o.site or o.site == site)]
        return max(known, key=lambda o: o.last_seen) if known else None

    def resolve(self, order, site, amount, frame_hash, title=None):
        """금액을 몰라 보류했던 주문(order)의 금액을 읽었다. 같은 쇼핑몰+금액의 다른 주문이 있으면 그 주문으로 합치고
        (order는 지운다) 중복, 없으면 order에 금액을 채우고 새 주문"""
        now = self.clock()
        self._expire(now)
        amount = int(amount or 0)
        for o in self.orders:
            if o is not order and o.amount and o.amount == amount and (not site or not o.site or o.site == site):
                if order in self.orders:
                    self.orders.remove(order)
                away = now - o.last_seen
                o.last_seen, o.count, o.frame_hash = now, o.count + 1, frame_hash
                if title is not None:
                    o.title = title
                self.current = o
                return Verdict(True, o, 'revisit', away)
        order.amount, order.frame_hash, order.last_seen = amount, frame_hash, now
        if title is not None:
            order.title = title
        if order not in self.orders:
            self.orders.append(order)
        self.current = order
        return Verdict(False, order, filled=True)

    def fill(self, order, site, amount, frame_hash, title=None):
        """'결제 금액 확인 중' 팝업이 떠 있는 동안 읽은 금액을 그 주문에 채운다 (B-5). 같은 주문으로 볼 수 없으면 False
        쇼핑몰이나 탭 제목이 다르면(사용자가 다른 주문서로 갔음) 채우지 않는다"""
        amount = int(amount or 0)
        if amount <= 0 or (site and order.site and site != order.site):
            return False
        if title is not None and order.title is not None and title.digest != order.title.digest:
            return False
        if order.amount and order.amount != amount:
            return False
        order.amount = amount
        order.frame_hash = frame_hash
        order.last_seen = self.clock()
        if title is not None:
            order.title = title
        self.current = order
        return True

    def still_here(self):
        """화면이 바뀌지 않아 OCR을 건너뛴 회차: 지금 주문을 계속 보고 있는 것으로 갱신"""
        if self.current is not None:
            self.current.last_seen = self.clock()

    def left(self):
        """결제 화면이 아닌 화면을 봤다 (다시 돌아오면 revisit)"""
        self.current = None

    def decide(self, order, decision, bl_id=0):
        order.decision = decision
        if bl_id:
            order.bl_id = bl_id


class NoticeGate:
    """차단 안내 창 재표시 간격 (쇼핑몰별). 닫은 시각부터 repeat_sec 동안은 다시 띄우지 않는다"""

    def __init__(self, repeat_sec=None, clock=time.monotonic):
        self.repeat = config.AUTO_DETECT_DEFAULTS['blocked_repeat_sec'] if repeat_sec is None else repeat_sec
        self.clock = clock
        self.closed_at = {}          # 쇼핑몰 코드('' = 모름) → 닫은 시각

    def allow(self, site):
        t = self.closed_at.get(site)
        return t is None or self.clock() - t >= self.repeat

    def wait_left(self, site):
        t = self.closed_at.get(site)
        return 0.0 if t is None else max(0.0, self.repeat - (self.clock() - t))

    def closed(self, site):
        self.closed_at[site] = self.clock()
