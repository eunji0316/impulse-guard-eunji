"""화면 캡처

자동 감지와 F4는 grab_for_detect()로 맨 앞 창 영역만 캡처한다 (B-5, config.CAPTURE_ACTIVE_WINDOW).
창 영역은 DwmGetWindowAttribute(그림자를 뺀 실제 창 영역)로 구하고 화면 밖으로 나간 부분은 자른다.
못 구하면 원본처럼 주 모니터 전체(grab_screen). Frame.origin은 이미지 왼쪽 위의 화면 좌표 (팝업 영역을 지울 때 쓴다).
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
    origin: tuple = (0, 0)       # 이미지 왼쪽 위의 화면 좌표
    scope: str = 'monitor'       # 'window' (맨 앞 창) / 'monitor' (주 모니터 전체)


def grab_for_detect():
    """자동 감지/F4용 캡처: 맨 앞 창 영역 (못 구하면 주 모니터 전체)"""
    title, exe = foreground_title(), foreground_exe()
    img, origin, scope = grab_active() if config.CAPTURE_ACTIVE_WINDOW else (grab_screen(), monitor_origin(), 'monitor')
    return Frame(img=img, foreground_title=title, foreground_exe=exe, origin=origin, scope=scope)


def foreground_rect():
    """맨 앞 창의 화면 영역 (left, top, right, bottom). 최소화됐거나 못 구하면 None"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd or user32.IsIconic(hwnd):
            return None
        rect = wintypes.RECT()
        DWMWA_EXTENDED_FRAME_BOUNDS = 9          # 보이지 않는 테두리/그림자를 뺀 영역
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                                      ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return None


def clip_region(rect, screen, min_size=None):
    """창 영역을 전체 화면(mss monitors[0]) 안으로 자른 mss 영역. 너무 작거나 없으면 None"""
    if not rect:
        return None
    min_size = config.CAPTURE_MIN_SIZE if min_size is None else min_size
    left, top = max(rect[0], screen['left']), max(rect[1], screen['top'])
    right = min(rect[2], screen['left'] + screen['width'])
    bottom = min(rect[3], screen['top'] + screen['height'])
    if right - left < min_size or bottom - top < min_size:
        return None
    return {'left': left, 'top': top, 'width': right - left, 'height': bottom - top}


def grab_active():
    """(이미지, 왼쪽 위 화면 좌표, 'window'/'monitor')"""
    import mss
    with mss.mss() as sct:
        region, scope = clip_region(foreground_rect(), sct.monitors[0]), 'window'
        if region is None:
            region, scope = sct.monitors[config.CAPTURE_MONITOR], 'monitor'
        img = np.array(sct.grab(region))
    return img[:, :, :3], (region['left'], region['top']), scope


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
