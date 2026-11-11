"""자동 감지 루프 (B-4)

F4 없이 interval_sec마다 화면을 확인한다. OCR(CPU 약 9초)은 비싸므로 아래 순서로 거른다.

    1. 일시 중지: 알림 창이 떠 있거나 분석 중(F4 포함), 맨 앞 창이 이 프로그램의 콘솔이거나
       감지 제외 프로그램(local_config.json의 exclude_programs, 예: Code.exe)이면 건너뜀
    2. 캡처 → dHash (capture.grab_for_detect, frame.dhash)
    3. 직전에 분석한 화면과 거의 같으면(FRAME_SAME_DISTANCE 이하) OCR 생략 → app.still_same()
       결제 화면에 머무는 동안 같은 화면을 반복 분석/기록하지 않는다
    4. 바로 앞 회차와도 많이 다르면(FRAME_SETTLE_DISTANCE 초과) 아직 바뀌는 중(스크롤, 페이지 이동)이라
       AUTO_SETTLE_SEC(1초) 뒤 다시 본다. 멈췄으면 OCR → app.run_auto(이미지, 해시)
       F4가 방금 분석한 화면(app.last_frame_hash)도 같은 화면으로 본다

결제 금액 확인 중 팝업 (B-5): 결제 화면인데 금액을 못 읽고 팝업을 띄웠으면(app.wants_amount()) 쉬지 않고
같은 순서로 화면을 보다가 멈추면 app.run_amount(팝업 영역을 지우고 OCR → 금액을 읽으면 팝업과 주문 기록에 채움)를 부른다.

제목으로 빨리 확인 (B-5): 기다리는 동안 AUTO_TITLE_POLL_SEC마다 맨 앞 창 제목만 확인한다(캡처 없음).
제목이 결제 페이지(stage.is_checkout_title)로 바뀌면 interval_sec를 다 기다리지 않고 바로 확인하고,
제목이 결제 페이지인 동안은 확인 간격을 AUTO_CHECKOUT_INTERVAL_SEC, 멈춤 확인 간격을 AUTO_FAST_SETTLE_SEC로 줄인다. 판정은 그대로 OCR로 한다.

시간 측정 (B-5, timing.py): 화면이 바뀐 것을 처음 본 회차(change_at)와 그 앞 회차 사이 간격, 멈출 때까지 기다린 시간,
분석한 회차의 캡처/해시 시간을 Timing에 담아 run_auto를 부른다. OCR과 서버 시간은 그 안에서 더해진다.

종료: stop()이 이벤트를 세우면 다음 대기에서 바로 끝난다. OCR 중이면 끝날 때까지 AUTO_STOP_WAIT_SEC만 기다리고,
그래도 안 끝나면 daemon 스레드라 프로그램과 함께 끝난다.
"""
import threading

from . import capture, config, frame, timing
from .detector import stage

SKIP_PAUSED, SKIP_OWN_CONSOLE, SKIP_EXCLUDED, SKIP_SAME, SKIP_CHANGING, SKIP_BUSY, ANALYZED, AMOUNT = (
    'paused', 'own-console', 'excluded', 'same', 'changing', 'busy', 'analyzed', 'amount')


class AutoDetector(threading.Thread):
    def __init__(self, app, interval_sec, grab=None, hasher=None, log=None, exclude_programs=None, title_fn=None):
        super().__init__(name='auto-detect', daemon=True)
        self.app = app
        self.interval = interval_sec
        self.grab = grab or capture.grab_for_detect
        self.hasher = hasher or frame.dhash
        self.title_fn = title_fn or capture.foreground_title
        self.log = log
        self.exclude = {p.lower() for p in (exclude_programs or [])}
        self._stop_event = threading.Event()
        self.last_analyzed = None    # 마지막으로 OCR한 화면의 해시
        self.prev = None             # 바로 앞 회차의 해시
        self.counts = {}             # 회차 결과별 횟수 (종료할 때 요약)
        self.last_result = None
        self.last_distance = None    # 로그용: 비교한 해시 거리
        self.last_tick_at = None     # 바로 앞 회차를 시작한 시각 (timing.now 기준)
        self.change_at = None        # 화면이 바뀐 것을 처음 본 회차의 시각 (분석하거나 원래 화면으로 돌아오면 지움)
        self.change_gap = None       # 그 회차와 앞 회차 사이 간격 (실제로 바뀐 순간은 이 안 어딘가)
        self.changing = 0            # 바뀐 뒤 '바뀌는 중'으로 본 회차 수
        self.grab_sec = self.hash_sec = None   # 이번 회차의 캡처/해시 시간
        self.last_title = None       # 마지막으로 본 맨 앞 창 제목 (기억만 하고 로그에 남기지 않음)
        self.checkout_title = False  # 그 제목이 결제 페이지 같은지
        self.title_woke = False      # 이번 회차가 제목 변화로 일찍 깼는지

    def next_wait(self):
        """다음 회차까지 기다릴 시간. 바뀌는 중이면 짧게 (멈추자마자 분석하도록), 제목이 결제 페이지면 더 짧게"""
        if self.last_result == SKIP_CHANGING:
            settle = config.AUTO_FAST_SETTLE_SEC if self.checkout_title else config.AUTO_SETTLE_SEC
            return min(settle, self.interval)
        if self.checkout_title:
            return min(config.AUTO_CHECKOUT_INTERVAL_SEC, self.interval)
        return self.interval

    def _see_title(self, title):
        self.last_title = title
        self.checkout_title = stage.is_checkout_title(title)

    def wait(self, sec):
        """sec 동안 기다린다. 멈추라고 하면 True.
        기다리는 동안 제목이 결제 페이지로 바뀌면 일찍 깬다 (False, title_woke=True)"""
        end = timing.now() + sec
        while True:
            left = end - timing.now()
            if left <= 0:
                return False
            if self._stop_event.wait(min(left, config.AUTO_TITLE_POLL_SEC)):
                return True
            if self.last_title is None:
                continue                    # 첫 회차 전에는 비교할 제목이 없다
            try:
                title = self.title_fn()
            except Exception:
                continue
            if title != self.last_title:
                self._see_title(title)
                if self.checkout_title:
                    self.title_woke = True
                    return False

    def run(self):
        if self.log:
            self.log.info(f'자동 감지 시작: {self.interval}초 간격 (바뀌는 중이면 {config.AUTO_SETTLE_SEC}초,'
                          f' 제목이 결제 페이지면 {config.AUTO_FAST_SETTLE_SEC}초 뒤 다시 확인.'
                          f' 제목은 {config.AUTO_TITLE_POLL_SEC}초마다 확인),'
                          f' 감지 제외 {sorted(self.exclude) or "없음"}')
        while not self.wait(self.next_wait()):
            try:
                self.tick()
            except Exception as e:      # 한 회차가 실패해도 루프는 계속
                self.last_result = None
                print(f'!!! 자동 감지 중 오류가 발생했습니다: {e}')
                if self.log:
                    self.log.info(f'자동 감지 오류: {e!r}', console=False)

    def tick(self):
        """한 회차. 결과 문자열을 돌려준다 (테스트와 요약용)"""
        self.last_distance = None
        self.grab_sec = self.hash_sec = None
        self.tick_at = timing.now()
        woke, self.title_woke = self.title_woke, False
        try:
            result = self._tick()
        finally:
            self.last_tick_at = self.tick_at
        if woke and self.log:
            self.log.debug('auto 제목이 결제 페이지로 바뀌어 바로 확인')
        self.last_result = result
        self.counts[result] = self.counts.get(result, 0) + 1
        if self.log and result != ANALYZED:
            extra = [f'거리 {self.last_distance}'] if self.last_distance is not None else []
            if self.grab_sec is not None:
                extra.append(f'캡처 {self.grab_sec:.2f}')
            if self.hash_sec is not None:
                extra.append(f'해시 {self.hash_sec:.2f}')
            self.log.debug(f'auto {result}' + (f" ({', '.join(extra)})" if extra else ''))
        return result

    def _saw_change(self):
        """화면이 바뀐 것을 처음 본 회차를 기억한다 (시간 측정용)"""
        if self.change_at is None:
            self.change_at = self.tick_at
            self.change_gap = None if self.last_tick_at is None else self.tick_at - self.last_tick_at
            self.changing = 0

    def _forget_change(self):
        self.change_at = self.change_gap = None
        self.changing = 0

    def _tick(self):
        amount_mode = False
        if self.app.paused():
            if not getattr(self.app, 'wants_amount', lambda: False)():
                self.prev = None
                self._forget_change()
                return SKIP_PAUSED
            amount_mode = True                  # 결제 금액 확인 중 팝업: 금액만 읽는다
        t0 = timing.now()
        fr = self.grab()
        self.grab_sec = timing.now() - t0
        self._see_title(fr.foreground_title)
        if fr.foreground_title == config.CONSOLE_TITLE:
            return SKIP_OWN_CONSOLE
        if fr.foreground_exe and fr.foreground_exe.lower() in self.exclude:
            self.prev = None                    # 돌아왔을 때 화면이 멈췄는지 처음부터 본다
            self._forget_change()
            return SKIP_EXCLUDED
        t0 = timing.now()
        h = self.hasher(fr.img)
        self.hash_sec = timing.now() - t0
        seen = min(frame.distance(h, self.last_analyzed), frame.distance(h, getattr(self.app, 'last_frame_hash', None)))
        if seen <= config.FRAME_SAME_DISTANCE:
            self.last_distance = seen
            self.prev = h
            self.app.still_same()
            self._forget_change()
            return SKIP_SAME
        moved = frame.distance(h, self.prev)
        self.last_distance = None if self.prev is None else moved
        if self.prev is None or moved > config.FRAME_SETTLE_DISTANCE:
            self.prev = h
            self._saw_change()
            self.changing += 1
            return SKIP_CHANGING
        self.prev = h
        if amount_mode:
            self.last_analyzed = h
            img, fr.img = fr.img, None
            t = self._timing(img, 'amount', fr.scope)
            with timing.active(t):
                self.app.run_amount(img, h, fr.foreground_title, fr.origin)
            del img
            return AMOUNT
        if not self.app.try_begin():
            return SKIP_BUSY
        self.last_analyzed = h
        img, fr.img = fr.img, None
        t = self._timing(img, scope=fr.scope)
        with timing.active(t):
            # 분석이 끝나면 app이 잠금을 푼다 (창을 띄우면 창이 닫힐 때). 제목은 app이 해시로만 바꿔 같은 주문 판단에 쓴다
            self.app.run_auto(img, h, fr.foreground_title)
        del img
        return ANALYZED

    def _timing(self, img, source='auto', scope=''):
        """분석할 회차의 측정 객체: 기다린 시간과 이 회차의 캡처/해시 시간"""
        self._saw_change()
        t = timing.Timing(source)
        t.detected_at = self.change_at
        if self.change_gap is not None:
            t.add('interval_wait', self.change_gap)
        t.add('settle_wait', self.tick_at - self.change_at)
        t.changing = self.changing
        if self.checkout_title:
            t.info['제목'] = '결제 페이지'        # 제목 글자는 남기지 않는다
        t.add('capture', self.grab_sec)
        t.add('hash', self.hash_sec)
        shape = getattr(img, 'shape', None)
        if shape is not None and len(shape) >= 2:
            t.info['화면'] = f'{shape[1]}x{shape[0]}' + {'window': ' (맨 앞 창)', 'monitor': ' (모니터 전체)'}.get(scope, '')
        self._forget_change()
        return t

    def stop(self, wait=None):
        """루프를 끝낸다. 끝났으면 True"""
        self._stop_event.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(config.AUTO_STOP_WAIT_SEC if wait is None else wait)
        return not self.is_alive()
