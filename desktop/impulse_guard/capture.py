"""화면 캡처

지금은 원본처럼 주 모니터 전체를 캡처한다. (활성 창만 캡처하는 것은 이후 단계)
반환 배열은 원본과 같다: mss가 주는 BGRA에서 알파 채널만 뺀 3채널(실제 순서는 BGR).
원본은 이 값을 RGB라고 부르며 그대로 OCR에 넘기므로, 판정을 맞추려고 순서를 바꾸지 않는다.
캡처 이미지는 파일로 저장하지 않는다 (개인정보 보호).
"""
import numpy as np

from . import config


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
