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

종료: stop()이 이벤트를 세우면 다음 대기에서 바로 끝난다. OCR 중이면 끝날 때까지 AUTO_STOP_WAIT_SEC만 기다리고,
그래도 안 끝나면 daemon 스레드라 프로그램과 함께 끝난다.
"""
import threading

from . import capture, config, frame

SKIP_PAUSED, SKIP_OWN_CONSOLE, SKIP_EXCLUDED, SKIP_SAME, SKIP_CHANGING, SKIP_BUSY, ANALYZED = (
    'paused', 'own-console', 'excluded', 'same', 'changing', 'busy', 'analyzed')


class AutoDetector(threading.Thread):
    def __init__(self, app, interval_sec, grab=None, hasher=None, log=None, exclude_programs=None):
        super().__init__(name='auto-detect', daemon=True)
        self.app = app
        self.interval = interval_sec
        self.grab = grab or capture.grab_for_detect
        self.hasher = hasher or frame.dhash
        self.log = log
        self.exclude = {p.lower() for p in (exclude_programs or [])}
        self._stop_event = threading.Event()
        self.last_analyzed = None    # 마지막으로 OCR한 화면의 해시
        self.prev = None             # 바로 앞 회차의 해시
        self.counts = {}             # 회차 결과별 횟수 (종료할 때 요약)
        self.last_result = None
        self.last_distance = None    # 로그용: 비교한 해시 거리

    def next_wait(self):
        """다음 회차까지 기다릴 시간. 바뀌는 중이면 짧게 (멈추자마자 분석하도록)"""
        if self.last_result == SKIP_CHANGING:
            return min(config.AUTO_SETTLE_SEC, self.interval)
        return self.interval

    def run(self):
        if self.log:
            self.log.info(f'자동 감지 시작: {self.interval}초 간격 (바뀌는 중이면 {config.AUTO_SETTLE_SEC}초 뒤 다시 확인),'
                          f' 감지 제외 {sorted(self.exclude) or "없음"}')
        while not self._stop_event.wait(self.next_wait()):
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
        result = self._tick()
        self.last_result = result
        self.counts[result] = self.counts.get(result, 0) + 1
        if self.log and result != ANALYZED:
            d = f' (거리 {self.last_distance})' if self.last_distance is not None else ''
            self.log.debug(f'auto {result}{d}')
        return result

    def _tick(self):
        if self.app.paused():
            self.prev = None
            return SKIP_PAUSED
        fr = self.grab()
        if fr.foreground_title == config.CONSOLE_TITLE:
            return SKIP_OWN_CONSOLE
        if fr.foreground_exe and fr.foreground_exe.lower() in self.exclude:
            self.prev = None                    # 돌아왔을 때 화면이 멈췄는지 처음부터 본다
            return SKIP_EXCLUDED
        h = self.hasher(fr.img)
        seen = min(frame.distance(h, self.last_analyzed), frame.distance(h, getattr(self.app, 'last_frame_hash', None)))
        if seen <= config.FRAME_SAME_DISTANCE:
            self.last_distance = seen
            self.prev = h
            self.app.still_same()
            return SKIP_SAME
        moved = frame.distance(h, self.prev)
        self.last_distance = None if self.prev is None else moved
        if self.prev is None or moved > config.FRAME_SETTLE_DISTANCE:
            self.prev = h
            return SKIP_CHANGING
        self.prev = h
        if not self.app.try_begin():
            return SKIP_BUSY
        self.last_analyzed = h
        img, fr.img = fr.img, None
        self.app.run_auto(img, h)       # 분석이 끝나면 app이 잠금을 푼다 (창을 띄우면 창이 닫힐 때)
        del img
        return ANALYZED

    def stop(self, wait=None):
        """루프를 끝낸다. 끝났으면 True"""
        self._stop_event.set()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(config.AUTO_STOP_WAIT_SEC if wait is None else wait)
        return not self.is_alive()
