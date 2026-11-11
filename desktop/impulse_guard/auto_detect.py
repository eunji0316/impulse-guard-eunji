"""자동 감지 루프 (B-4)

F4 없이 interval_sec마다 화면을 확인한다. OCR(CPU 약 9초)은 비싸므로 아래 순서로 거른다.

    1. 일시 중지: 알림 창이 떠 있거나 분석 중(F4 포함), 맨 앞 창이 이 프로그램의 콘솔이면 건너뜀
    2. 캡처 → dHash (capture.grab_for_detect, frame.dhash)
    3. 직전에 분석한 화면과 거의 같으면(FRAME_SAME_DISTANCE 이하) OCR 생략 → app.still_same()
       결제 화면에 머무는 동안 같은 화면을 반복 분석/기록하지 않는다
    4. 바로 앞 회차와도 다르면 아직 바뀌는 중(스크롤, 페이지 이동)이라 기다린다
       화면이 한 간격 동안 멈췄을 때만 OCR → app.run_auto(이미지, 해시)

종료: stop()이 이벤트를 세우면 다음 대기에서 바로 끝난다. OCR 중이면 끝날 때까지 AUTO_STOP_WAIT_SEC만 기다리고,
그래도 안 끝나면 daemon 스레드라 프로그램과 함께 끝난다.
"""
import threading

from . import capture, config, frame

SKIP_PAUSED, SKIP_OWN_CONSOLE, SKIP_SAME, SKIP_CHANGING, SKIP_BUSY, ANALYZED = (
    'paused', 'own-console', 'same', 'changing', 'busy', 'analyzed')


class AutoDetector(threading.Thread):
    def __init__(self, app, interval_sec, grab=None, hasher=None, log=None):
        super().__init__(name='auto-detect', daemon=True)
        self.app = app
        self.interval = interval_sec
        self.grab = grab or capture.grab_for_detect
        self.hasher = hasher or frame.dhash
        self.log = log
        self._stop_event = threading.Event()
        self.last_analyzed = None    # 마지막으로 OCR한 화면의 해시
        self.prev = None             # 바로 앞 회차의 해시
        self.counts = {}             # 회차 결과별 횟수 (종료할 때 요약)

    def run(self):
        while not self._stop_event.wait(self.interval):
            try:
                self.tick()
            except Exception as e:      # 한 회차가 실패해도 루프는 계속
                print(f'!!! 자동 감지 중 오류가 발생했습니다: {e}')
                if self.log:
                    self.log.info(f'자동 감지 오류: {e!r}', console=False)

    def tick(self):
        """한 회차. 결과 문자열을 돌려준다 (테스트와 요약용)"""
        result = self._tick()
        self.counts[result] = self.counts.get(result, 0) + 1
        if self.log and result != ANALYZED:
            self.log.debug(f'auto {result}')
        return result

    def _tick(self):
        if self.app.paused():
            self.prev = None
            return SKIP_PAUSED
        fr = self.grab()
        if fr.foreground_title == config.CONSOLE_TITLE:
            return SKIP_OWN_CONSOLE
        h = self.hasher(fr.img)
        if frame.distance(h, self.last_analyzed) <= config.FRAME_SAME_DISTANCE:
            self.prev = h
            self.app.still_same()
            return SKIP_SAME
        if self.prev is None or frame.distance(h, self.prev) > config.FRAME_SAME_DISTANCE:
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
