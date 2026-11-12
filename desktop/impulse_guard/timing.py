"""단계별 시간 측정 (B-5)

결제 화면에 들어간 뒤 팝업까지 어디서 시간이 드는지 detect.log에 한 줄로 남긴다.

    timing auto | 간격 대기 ≤2.9 | 멈춤 확인 1.0 (바뀌는 중 1회) | 캡처 0.05 | 해시 0.01 | OCR 9.10 |
                  다시 읽기 0.80 (2회) | 판정 0.02 | 서버 0.31 (setting 0.05, check 0.26) | 팝업 표시 0.12 |
                  감지→팝업 11.5 | 화면 바뀜→팝업 ≤14.4 | 화면 1920x950

- 간격 대기: 화면이 바뀐 것을 처음 본 회차와 그 앞 회차 사이의 시간. 실제로 바뀐 순간은 이 사이 어딘가라 최댓값(≤)
- 멈춤 확인: 바뀐 것을 처음 본 회차부터 OCR을 시작한 회차까지 (바뀌는 중이면 AUTO_SETTLE_SEC마다 다시 봄)
- 감지→팝업: 바뀐 것을 처음 본 회차부터 팝업 창이 만들어질 때까지
- 화면 바뀜→팝업: 위에 간격 대기를 더한 최댓값 (사용자가 느끼는 시간의 상한)

측정 객체는 스레드마다 하나씩 둔다 (active). OCR, 서버 요청처럼 깊은 곳의 함수는 measure()로 현재 측정에 더하기만 하므로
함수 형식을 바꾸지 않고, 측정 중이 아니면 아무 일도 하지 않는다. 캡처 이미지나 화면 글자는 기록하지 않는다.
"""
import threading
import time
from contextlib import contextmanager

now = time.perf_counter

_local = threading.local()

# 줄에 찍는 순서와 이름. 여기에 없는 이름은 뒤에 붙는다
LABELS = [
    ('interval_wait', '간격 대기'),
    ('settle_wait', '멈춤 확인'),
    ('capture', '캡처'),
    ('hash', '해시'),
    ('ocr', 'OCR'),
    ('reread', '다시 읽기'),
    ('judge', '판정'),
    ('server', '서버'),
    ('popup', '팝업 표시'),
]


class Timing:
    def __init__(self, source='auto'):
        self.source = source
        self.sec = {}            # 이름 → 누적 초
        self.counts = {}         # 이름 → 횟수
        self.server = {}         # 서버 action → 누적 초 (서버 시간 나눠 보기)
        self.info = {}           # 화면 크기 등 숫자가 아닌 정보
        self.detected_at = None  # 화면이 바뀐 것을 처음 본 시각 (now 기준). 없으면 분석 시작 시각
        self.started_at = now()
        self.post_at = None      # 팝업 창을 main 스레드에 요청한 시각
        self.total = None        # 감지→팝업(또는 분석 끝)
        self.changing = 0        # 바뀌는 중으로 본 회차 수

    def add(self, name, sec):
        self.sec[name] = self.sec.get(name, 0.0) + sec
        self.counts[name] = self.counts.get(name, 0) + 1

    @contextmanager
    def measure(self, name):
        t0 = now()
        try:
            yield
        finally:
            self.add(name, now() - t0)

    def finish(self):
        """끝난 시각을 정한다 (팝업이 만들어졌거나, 띄우지 않고 분석이 끝났을 때)"""
        start = self.detected_at if self.detected_at is not None else self.started_at
        self.total = now() - start
        return self.total

    def line(self):
        if self.total is None:
            self.finish()
        parts = [f'timing {self.source}']
        known = {k for k, _ in LABELS}
        for key, label in LABELS + [(k, k) for k in self.sec if k not in known]:
            if key not in self.sec:
                continue
            v = self.sec[key]
            text = f'{label} ≤{v:.2f}' if key == 'interval_wait' else f'{label} {v:.2f}'
            if key == 'settle_wait':
                text += f' (바뀌는 중 {self.changing}회)'
            elif key == 'reread' or (key not in known and self.counts.get(key, 1) > 1):
                text += f' ({self.counts[key]}회)'
            elif key == 'server' and self.server:
                text += ' (' + ', '.join(f'{a} {s:.2f}' for a, s in self.server.items()) + ')'
            parts.append(text)
        if self.detected_at is not None:
            parts.append(f'감지→팝업 {self.total:.2f}')
            parts.append(f"화면 바뀜→팝업 ≤{self.total + self.sec.get('interval_wait', 0.0):.2f}")
        else:
            parts.append(f'전체 {self.total:.2f}')
        for k, v in self.info.items():
            parts.append(f'{k} {v}')
        return ' | '.join(parts)


def current():
    """이 스레드에서 진행 중인 측정 (없으면 None)"""
    return getattr(_local, 'timing', None)


@contextmanager
def active(t):
    """이 블록 안에서 measure()가 t에 더해진다"""
    prev = current()
    _local.timing = t
    try:
        yield t
    finally:
        _local.timing = prev


@contextmanager
def measure(name):
    """현재 측정에 name의 시간을 더한다. 측정 중이 아니면 아무 일도 하지 않는다"""
    t = current()
    if t is None:
        yield
        return
    with t.measure(name):
        yield


@contextmanager
def measure_server(action):
    """서버 요청 한 번. 서버 전체와 action별 시간에 같이 더한다"""
    t = current()
    if t is None:
        yield
        return
    t0 = now()
    try:
        yield
    finally:
        sec = now() - t0
        t.add('server', sec)
        t.server[action] = t.server.get(action, 0.0) + sec
