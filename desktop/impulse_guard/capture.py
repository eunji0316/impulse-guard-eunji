"""화면 캡처

지금은 원본처럼 주 모니터 전체를 캡처한다. (활성 창만 캡처하는 것은 이후 단계)
자동 감지(B-4)는 grab_for_detect()만 부른다. B-5(활성 창만 캡처, 이미지 축소)는 이 함수 안쪽만 바꾸면 된다.
반환 배열은 원본과 같다: mss가 주는 BGRA에서 알파 채널만 뺀 3채널(실제 순서는 BGR).
원본은 이 값을 RGB라고 부르며 그대로 OCR에 넘기므로, 판정을 맞추려고 순서를 바꾸지 않는다.
캡처 이미지는 파일로 저장하지 않는다 (개인정보 보호).
"""
from dataclasses import dataclass

import numpy as np

from . import config


@dataclass
class Frame:
    """자동 감지 한 회차의 캡처. img는 분석 뒤 바로 버린다 (파일로 저장하지 않음)"""
    img: np.ndarray
    foreground_title: str = ''   # 캡처할 때 맨 앞 창 제목 (우리 콘솔이면 건너뛴다)
    foreground_exe: str = ''     # 맨 앞 창의 실행 파일 이름 (예: 'chrome.exe'). 감지 제외 프로그램 확인용


def grab_for_detect():
    """자동 감지용 캡처. 지금은 F4와 같은 주 모니터 전체 (B-5에서 활성 창만, 축소로 바꿀 자리)"""
    return Frame(img=grab_screen(), foreground_title=foreground_title(), foreground_exe=foreground_exe())


def foreground_exe():
    """맨 앞 창을 가진 프로세스의 실행 파일 이름 (Windows가 아니거나 실패하면 '')"""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ''
            return buf.value.replace('/', '\\').rsplit('\\', 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ''


def foreground_title():
    """맨 앞 창의 제목 (Windows가 아니거나 실패하면 '')"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ''


def set_console_title(title):
    """이 프로그램 콘솔 창의 제목을 정한다 (자동 감지가 자기 콘솔을 쇼핑 화면으로 오인하지 않게)"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


_origin = None


def monitor_origin():
    """캡처하는 모니터의 왼쪽 위 화면 좌표 (팝업 영역을 이미지 좌표로 바꿀 때). 처음 한 번만 묻는다"""
    global _origin
    if _origin is None:
        try:
            import mss
            with mss.mss() as sct:
                m = sct.monitors[config.CAPTURE_MONITOR]
                _origin = (m['left'], m['top'])
        except Exception:
            _origin = (0, 0)
    return _origin


def grab_screen():
    import mss
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[config.CAPTURE_MONITOR])
        img = np.array(shot)
    return img[:, :, :3]


def load_image(path):
    """테스트용: 이미지 파일을 캡처와 같은 형식(BGR 3채널)으로 읽는다. 한글 경로도 읽을 수 있게 imdecode 사용"""
    import cv2
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img
