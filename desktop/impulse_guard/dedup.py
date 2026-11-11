"""같은 화면/같은 주문 중복 방지 (B-4)

1. 같은 화면: 자동 감지 루프가 직전에 분석한 화면의 해시와 비교해 OCR을 건너뛴다 (auto_detect.py)
2. 같은 주문 (RecentOrders): 결제 화면에서 기록과 팝업을 한 번만 한다
   - 쇼핑몰 + 결제 금액이 같으면 같은 주문
   - 금액을 못 읽었으면 화면 해시 거리가 config.ORDER_SAME_DISTANCE 이하일 때 같은 주문
   - 기준 시간은 '마지막으로 본 시각'부터 same_order_minutes (sliding window)
     · 결제 화면에 계속 머무르면 볼 때마다 시각이 갱신되어 다시 뜨지 않는다
     · 다른 창에 갔다가 기준 시간 안에 돌아오면 같은 시도로 본다 (revisit으로 기록만)
     · 기준 시간보다 오래 떠나 있다가 돌아오면 새 시도로 본다
   - 팝업에서 무엇을 골랐든(안 살래요, 조금 더 생각하기, 그래도 구매, X) 그 주문의 팝업은 다시 띄우지 않는다
3. 차단 안내 창 (NoticeGate): 창을 닫은 뒤 같은 쇼핑몰에서 blocked_repeat_sec 동안은 다시 띄우지 않는다

기억은 프로그램이 켜져 있는 동안 메모리에만 둔다. 화면 이미지는 기억하지 않고 해시만 둔다.
"""
import time
from dataclasses import dataclass

from . import config, frame


@dataclass
class SeenOrder:
    site: str
    amount: int                  # 0 = 금액 모름
    frame_hash: int
    first_seen: float
    last_seen: float
    count: int = 1               # 본 횟수
    decision: str = ''           # 팝업 결정: hold, giveup, buy, close ('' = 아직)
    bl_id: int = 0

    @property
    def key(self):
        return self.site, self.amount


@dataclass
class Verdict:
    is_dup: bool
    order: SeenOrder
    reason: str = 'new'          # new / same (계속 머무름) / revisit (다른 화면에 갔다 옴)
    away_sec: float = 0.0        # revisit이면 떠나 있던 시간


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

    def _same(self, o, site, amount, frame_hash):
        if amount and o.amount:
            return o.site == site and o.amount == amount
        return (not site or not o.site or o.site == site) and frame.distance(o.frame_hash, frame_hash) <= self.hash_distance

    def see(self, site, amount, frame_hash):
        """결제 화면을 봤다. 같은 주문이 있으면 중복(갱신), 없으면 새로 기억한다"""
        now = self.clock()
        self._expire(now)
        amount = int(amount or 0)
        for o in self.orders:
            if self._same(o, site, amount, frame_hash):
                away = now - o.last_seen
                reason = 'same' if o is self.current else 'revisit'
                o.last_seen, o.count = now, o.count + 1
                if amount and not o.amount:
                    o.amount = amount            # 처음에 금액을 못 읽었으면 채운다
                o.frame_hash = frame_hash
                self.current = o
                return Verdict(True, o, reason, away if reason == 'revisit' else 0.0)
        o = SeenOrder(site, amount, frame_hash, now, now)
        self.orders.append(o)
        self.current = o
        return Verdict(False, o)

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
