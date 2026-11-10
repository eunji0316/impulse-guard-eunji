"""
충동구매 위험도 예측의 데이터 형식과 특성 계산 규칙.

generate.py(가상 데이터), export.py(실제 DB), 4-2의 학습/서빙이 모두 이 파일을 쓴다.
열 이름, 업종 목록, 압박 문구, 월급일 기준을 바꾸면 데이터를 다시 만들고 다시 학습해야 한다.
"""
import re
from datetime import datetime

# CSV 열 순서. user는 특성이 아니라 회원 단위로 train/test를 나눌 때만 쓴다
COLUMNS = [
    'user',
    'hour',               # 0~23, 고민을 시작한 시각
    'weekday',            # 0~6, 월=0
    'amount',             # 원
    'amount_ratio',       # 금액 / 그 시점 이전 90일 회원 평균 결제액
    'category',           # CATEGORIES 중 하나
    'has_pressure',       # 0/1, 상품명에 할인/압박 문구
    'stay_sec',           # 상품 페이지 체류 시간(초). 모르면 빈 값
    'visits_24h',         # 직전 24시간 같은 사이트 방문 수
    'days_since_payday',  # 0~30, 가장 최근 월급일 이후 경과일
    'label',              # 1: 충동구매(failed), 0: 참음(gaveup, success)
]
FEATURES = [c for c in COLUMNS if c not in ('user', 'label')]
NUMERIC_FEATURES = ['hour', 'weekday', 'amount', 'amount_ratio', 'has_pressure', 'stay_sec', 'visits_24h', 'days_since_payday']
CATEGORICAL_FEATURES = ['category']

# 업종: ipp/bank.php 가짜 결제의 업종 목록 + 모를 때 etc
CATEGORIES = ['shopping', 'fashion', 'game', 'delivery', 'food', 'transport', 'etc']

# 쿨다운 상태 → 정답. waiting(진행 중)은 결과를 모르므로 뺀다
LABELS = {'failed': 1, 'gaveup': 0, 'success': 0}

# 할인/압박 문구. extend/ipp.extend.php의 IPP_DEFAULT_KEYWORDS(세일, 할인, 특가)를 포함한다
PRESSURE_PATTERN = re.compile(r'세일|할인|특가|마감|한정|오늘만|타임딜|품절\s*임박|마지막|1\s*\+\s*1|\d+\s*%', re.IGNORECASE)

# 월급일 (가정값). 회원별 월급일 데이터가 없어 한국에서 흔한 25일로 둔다
PAYDAY = 25

# 회원 평균 결제액 계산 기준
RATIO_WINDOW_DAYS = 90   # 이 기간의 결제만 평균에 쓴다
RATIO_MIN_COUNT   = 3    # 결제가 이보다 적으면 평균을 믿기 어려워 비율을 1.0으로 둔다

# 같은 사이트 방문 수를 세는 기간
VISIT_WINDOW_HOURS = 24


def has_pressure(text):
    """상품명에 할인/압박 문구가 있으면 1"""
    return 1 if text and PRESSURE_PATTERN.search(text) else 0


def days_since_payday(dt, payday=PAYDAY):
    """가장 최근 월급일(오늘 포함) 이후 경과일. 월급일이 그 달에 없으면(31일 등) 그 달 말일로 본다"""
    def payday_of(year, month):
        last = (datetime(year + month // 12, month % 12 + 1, 1) - datetime(year, month, 1)).days
        return datetime(year, month, min(payday, last))

    this_month = payday_of(dt.year, dt.month)
    if dt.date() >= this_month.date():
        return (dt.date() - this_month.date()).days
    prev_year, prev_month = (dt.year, dt.month - 1) if dt.month > 1 else (dt.year - 1, 12)
    return (dt.date() - payday_of(prev_year, prev_month).date()).days


def amount_ratio(amount, past_amounts):
    """금액 / 이전 결제 평균. 이전 결제가 RATIO_MIN_COUNT건 미만이면 1.0"""
    past = [a for a in past_amounts if a > 0]
    if len(past) < RATIO_MIN_COUNT:
        return 1.0
    mean = sum(past) / len(past)
    return round(amount / mean, 4) if mean > 0 else 1.0


def is_rule_impulse(row):
    """지금의 규칙 기반 감지(ipp_detect_impulse)를 특성으로 흉내 낸 값. 4-2에서 기준선으로 비교한다
    (규칙의 키워드 감지는 회원 키워드 대신 has_pressure로 대신한다)"""
    if row['has_pressure']:
        return 1
    if row['category'] not in ('shopping', 'fashion', 'game', 'delivery'):
        return 0
    return 1 if (row['hour'] >= 23 or row['hour'] < 4 or row['amount'] >= 50000) else 0
