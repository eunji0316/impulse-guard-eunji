"""충동구매 위험도(C-2)의 데이터 형식, 라벨 규칙, 모델 특성 정의

한 행 = 결제 화면 팝업 1건 (데스크톱이 결제 화면을 감지해 서버 check를 부른 순간).
generate.py(가상 데이터), export.py(실제 DB), train.py, model.py(기준 구현), 서버 PHP가 모두 이 정의를 따른다.
서버는 train.py가 내보낸 JSON(ipp/model/risk_model.json)만 읽으므로, 서버와 공유할 값은 RAW_PARAMS로 JSON에 함께 넣는다.

4-1(ai/features.py)과 다른 점
- 4-1은 쿨다운 1건이 한 행이고 라벨은 쿨다운 결과뿐이었다. C-2는 팝업 결정(bl_decision)을 라벨로 쓴다
- 확장 프로그램이 모으던 체류 시간/방문 수 대신, 데스크톱이 상품 화면에서 센 숫자를 쓴다
- 업종(category)은 뺐다. 데스크톱은 쇼핑몰만 알고, 쇼핑몰 → 업종 대응이 거칠다
- 결제 화면 여부는 뺐다. 예측 시점이 항상 결제 화면이라 값이 늘 1이다
"""

# ── 원시 값 (서버가 DB와 check 요청으로 만드는 값) ─────────────
# 빈 값(None/NaN) = 모름. 모름은 모델 입력에서 학습 평균으로 채우고 '모름' 표시 특성을 따로 둔다
RAW = {
    # 서버 시각
    'hour':                '0~23, 결제 화면을 감지한 시각',
    'weekday':             '0~6, 월=0',
    'days_since_payday':   '0~30, 가장 최근 월급일(25일 가정) 이후 경과일',
    # check 요청
    'amount':              '결제 금액(원). 못 읽었으면 빈 값',
    'discount_rate':       '0~99, 같은 쇼핑몰에서 최근 본 상품의 할인율. 상품 화면을 못 봤거나 못 읽었으면 빈 값, 할인 없음은 0',
    'pressure':            '0/1, 최근 본 상품 화면에 서두르게 하는 문구(타임딜, 품절임박, 오늘만 등)',
    'product_views_24h':   '최근 24시간 이 쇼핑몰 상품 화면 분석 횟수 (데스크톱 메모리)',
    'same_item_views_24h': '최근 24시간 같은 상품(이름 해시) 상품 화면 횟수',
    'browse_sec':          '이 쇼핑몰 상품 화면을 처음 본 때부터 결제 화면까지 초. 상품 화면을 못 봤으면 빈 값',
    # 서버 DB (그 시점 이전 기록만)
    'amount_ratio':        '결제 금액 / 이전 90일 결제 화면 금액 평균. 이전 금액이 3건 미만이면 1.0, 금액 모름이면 빈 값',
    'checkouts_7d':        '직전 7일 결제 화면 감지 수 (같은 주문은 한 번)',
    'buy_rate':            "지난 팝업 결정 중 '그래도 구매' 비율 (전체 평균 쪽으로 당김)",
    'cooldown_fail_rate':  '지난 담아두기(쿨다운) 중 참지 못하고 산 비율 (전체 평균 쪽으로 당김)',
}
RAW_FIELDS = list(RAW)

# CSV 열: user는 회원 단위로 학습/시험을 나눌 때만, decision은 라벨의 출처 확인용
COLUMNS = ['user'] + RAW_FIELDS + ['decision', 'label']

# 서버와 공유하는 원시 값 계산 기준 (JSON의 raw_params)
RAW_PARAMS = {
    'payday': 25,                  # 월급일 가정값
    'ratio_window_days': 90,       # 금액 비율: 이 기간의 결제 화면 금액만
    'ratio_min_count': 3,          # 이보다 적으면 비율 1.0
    'checkouts_window_days': 7,
    'history_window_days': 180,    # 과거 선택 비율에 쓰는 기간
    'history_prior': 0.35,         # 기록이 적을 때 당겨 갈 '그래도 구매' 비율 (가상 데이터 전체 비율에 맞춤)
    'history_weight': 3,           # 가상 결정 몇 건만큼 당길지: (구매 수 + prior×weight) / (결정 수 + weight)
    'cooldown_prior': 0.25,
    'cooldown_weight': 3,
}

# ── 라벨 ───────────────────────────────────────────────────────
# 팝업 결정(g5_ipp_block_log.bl_decision)과 담아두기 결과(g5_ipp_cooldown.cd_status)
#   1: buy(그래도 구매), hold → failed(쿨다운 중 결제)
#   0: giveup(안 살래요), hold → success/gaveup
#   제외: close(X로 닫음, 결정 아님), hold → waiting(결과 모름), 결정 없음
DECISIONS = ['buy', 'hold_failed', 'giveup', 'hold_ok', 'close']
LABEL_OF = {'buy': 1, 'hold_failed': 1, 'giveup': 0, 'hold_ok': 0}


def label_of(decision, cd_status=''):
    """bl_decision과 쿨다운 상태 → 라벨 (1/0) 또는 None(제외)"""
    if decision == 'buy':
        return 1
    if decision == 'giveup':
        return 0
    if decision == 'hold':
        return {'failed': 1, 'success': 0, 'gaveup': 0}.get(cd_status)
    return None


# ── 모델 특성 (원시 값 → 모델 입력) ───────────────────────────
# kind: flag(조건이면 1), log(log(값/scale)), log1p(log(1+값)), linear(값/scale)
# group: 이유 문장 단위. 같은 group의 기여를 더해 하나의 이유로 보인다. None이면 이유로 쓰지 않는다('모름' 표시 등)
# clip: 변환 뒤 값의 범위 (극단값이 위험도를 혼자 끌고 가지 않게)
FEATURES = [
    {'name': 'night',          'raw': 'hour',                'kind': 'flag_hour', 'hours': [23, 0, 1, 2, 3], 'group': 'night'},
    {'name': 'late_evening',   'raw': 'hour',                'kind': 'flag_hour', 'hours': [21, 22],         'group': 'evening'},
    {'name': 'weekend',        'raw': 'weekday',             'kind': 'flag_ge',   'value': 5,                'group': 'weekend'},
    {'name': 'payday',         'raw': 'days_since_payday',   'kind': 'flag_le',   'value': 5,                'group': 'payday'},
    {'name': 'log_amount',     'raw': 'amount',              'kind': 'log',   'scale': 10000, 'clip': [-3, 4],  'group': 'amount'},
    {'name': 'log_ratio',      'raw': 'amount_ratio',        'kind': 'log',   'scale': 1,     'clip': [-3, 3],  'group': 'amount_ratio'},
    {'name': 'amount_unknown', 'raw': 'amount',              'kind': 'missing',                                 'group': None},
    {'name': 'discount',       'raw': 'discount_rate',       'kind': 'linear', 'scale': 100,  'clip': [0, 0.99], 'group': 'discount'},
    {'name': 'discount_unknown', 'raw': 'discount_rate',     'kind': 'missing',                                 'group': None},
    {'name': 'pressure',       'raw': 'pressure',            'kind': 'flag_ge',   'value': 1,                'group': 'pressure'},
    {'name': 'log_views',      'raw': 'product_views_24h',   'kind': 'log1p', 'clip': [0, 4],                  'group': 'views'},
    {'name': 'log_same_item',  'raw': 'same_item_views_24h', 'kind': 'log1p', 'clip': [0, 3],                  'group': 'same_item'},
    {'name': 'log_browse',     'raw': 'browse_sec',          'kind': 'log',   'scale': 60,    'clip': [-3, 4],  'group': 'browse'},
    {'name': 'browse_unknown', 'raw': 'browse_sec',          'kind': 'missing',                                 'group': None},
    {'name': 'log_checkouts',  'raw': 'checkouts_7d',        'kind': 'log1p', 'clip': [0, 4],                  'group': 'frequency'},
    {'name': 'buy_rate',       'raw': 'buy_rate',            'kind': 'linear', 'scale': 1,    'clip': [0, 1],   'group': 'history'},
    {'name': 'cooldown_fail',  'raw': 'cooldown_fail_rate',  'kind': 'linear', 'scale': 1,    'clip': [0, 1],   'group': 'cooldown'},
]
FEATURE_NAMES = [f['name'] for f in FEATURES]

# 이유로 보일 최소 기여 (로그오즈). 이보다 작으면 이유 목록에 넣지 않는다
REASON_MIN = 0.15
