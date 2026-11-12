"""C-2 위험도용 상품 화면 숫자 특성 (결제 화면 check의 features)

자동 감지와 F4가 본 상품 화면을 메모리에만 모아 두었다가, 결제 화면에서 서버에 숫자로만 보낸다.
- 보내는 값: discount_rate, pressure, product_views_24h, same_item_views_24h, browse_sec (docs/API.md check)
- 개인정보: 상품명은 해시(blake2b 8바이트)로만 두고, OCR 원문·주소는 두지 않는다. 파일에 저장하지 않으므로
  프로그램을 다시 켜면 처음부터 센다. 24시간 지난 기록은 버린다
- 상품 화면 '한 번': 같은 쇼핑몰의 같은 상품을 RISK_VIEW_GAP_SEC 안에 다시 분석한 것(스크롤 등)은 같은 한 번으로 본다
- 머문 시간: 이 쇼핑몰 상품 화면을 연달아 본 묶음(간격 RISK_SESSION_GAP_MIN 이하)의 처음부터 결제 화면까지.
  최근 묶음이 없으면(상품 화면 없이 장바구니에서 바로 결제 등) 모름(None)
- 할인율·압박 문구: 그 묶음에서 가장 최근 상품 화면 값. 할인율을 못 읽었으면 모름(None).
  '할인 없음(0)'은 보내지 않는다. Windows OCR은 할인율 글자를 깨뜨리기도 해서('20%' → '209'.') 못 찾은 것을 할인 없음으로 볼 수 없다
"""
import hashlib
import re
from dataclasses import dataclass

from . import config

DAY = 24 * 3600


def item_key(name):
    """상품명 → 해시 (이름이 없으면 None). 원문은 여기서 버린다"""
    name = re.sub(r'\s+', '', (name or '')).lower()
    if not name:
        return None
    return int.from_bytes(hashlib.blake2b(name.encode('utf-8'), digest_size=8).digest(), 'big')


def has_pressure(text):
    """상품 화면 OCR 글자에 서두르게 하는 문구가 있으면 1 (공백 무시)"""
    n = ''.join((text or '').split())
    return 1 if any(w in n for w in config.RISK_PRESSURE_WORDS) or re.search(config.RISK_PRESSURE_RE, n) else 0


@dataclass
class View:
    site: str
    item: object                 # item_key (None = 상품명 모름)
    first: float                 # 이 상품 화면을 처음 본 시각
    last: float                  # 마지막으로 본 시각 (스크롤 등으로 다시 분석하면 늘어난다)
    discount_rate: object        # int 또는 None (모름)
    pressure: int


class ProductTracker:
    def __init__(self, clock):
        self.clock = clock
        self.views = []          # 시간순 View

    def _trim(self, now):
        self.views = [v for v in self.views if now - v.last <= DAY]

    def see(self, site, item_name, discount_rate, text):
        """상품 화면 하나를 봤다. discount_rate: 가격 분석의 할인율(None = 못 읽음), text: OCR 글자(압박 문구만 보고 버림)"""
        now = self.clock()
        self._trim(now)
        key = item_key(item_name)
        pressure = has_pressure(text)
        rate = int(discount_rate) if discount_rate is not None else None
        for v in reversed(self.views):
            if v.site == site and v.item == key and now - v.last <= config.RISK_VIEW_GAP_SEC:
                v.last = now                                   # 같은 상품 화면을 이어서 보는 중
                if rate is not None:
                    v.discount_rate = rate
                v.pressure = max(v.pressure, pressure)
                return v
            if v.site == site:
                break                                          # 이 쇼핑몰에서 가장 최근 화면이 다른 상품이면 새로 본 것
        v = View(site, key, now, now, rate, pressure)
        self.views.append(v)
        return v

    def _session(self, site, now):
        """이 쇼핑몰 상품 화면을 연달아 본 최근 묶음 (간격 RISK_SESSION_GAP_MIN 이하, 마지막이 결제 화면 직전)"""
        gap = config.RISK_SESSION_GAP_MIN * 60
        mine = [v for v in self.views if v.site == site]
        if not mine or now - mine[-1].last > gap:
            return []
        session = [mine[-1]]
        for v in reversed(mine[:-1]):
            if session[0].first - v.last > gap:
                break
            session.insert(0, v)
        return session

    def features(self, site):
        """결제 화면 check의 features (숫자와 None만)"""
        now = self.clock()
        self._trim(now)
        mine = [v for v in self.views if v.site == site]
        session = self._session(site, now)
        latest = session[-1] if session else None
        same = sum(1 for v in mine if latest is not None and latest.item is not None and v.item == latest.item)
        return {
            'discount_rate': latest.discount_rate if latest else None,
            'pressure': latest.pressure if latest else 0,
            'product_views_24h': len(mine),
            'same_item_views_24h': same,
            'browse_sec': int(now - session[0].first) if session else None,
        }


def summary(f):
    """로그용 한 줄 (숫자만)"""
    if not f:
        return ''
    rate = '모름' if f.get('discount_rate') is None else f"{f['discount_rate']}%"
    browse = '모름' if f.get('browse_sec') is None else f"{f['browse_sec']}초"
    return (f"특성 할인 {rate}, 압박 {f.get('pressure', 0)}, 상품 화면 {f.get('product_views_24h', 0)}"
            f"/같은 상품 {f.get('same_item_views_24h', 0)}, 머문 시간 {browse}")
