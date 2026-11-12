"""화면 지각 해시 (B-4)

dHash: 화면을 회색 (N+1)×N으로 줄이고, 가로로 이웃한 칸의 밝기를 비교해 N×N비트를 만든다.
글자 몇 개, 마우스 커서, 깜빡이는 입력 커서처럼 작은 변화에는 몇 비트만 바뀌고,
스크롤이나 다른 페이지로 이동하면 많이 바뀐다. 해시만 기억하고 화면 이미지는 기억하지 않는다.
"""
import numpy as np

from . import config


def dhash(img, size=None):
    """BGR(또는 회색) 이미지 → size*size비트 정수"""
    import cv2
    size = size or config.FRAME_HASH_SIZE
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(''.join('1' if b else '0' for b in bits), 2)


def distance(a, b):
    """두 해시가 다른 비트 수 (해밍 거리). 하나라도 None이면 최대값"""
    if a is None or b is None:
        return config.FRAME_HASH_SIZE ** 2
    return (a ^ b).bit_count()
