"""쇼핑 화면 판정 (원본 규칙 그대로)

원본 check_shopping_mall()의 4~5단계를 옮긴 것이다.
- 화면 글자 전체에서 쇼핑 키워드와 가격 패턴을 찾는다
- 키워드가 2개 이상이거나 가격 패턴이 1개 이상이면 쇼핑몰
규칙을 바꾸면 원본과 결과가 달라지므로 tests/test_shopping.py로 확인한다.
(AI 분류 모델로 바꾸는 것은 이후 단계)
"""
import re
from dataclasses import dataclass, field

from .. import config


@dataclass
class ShoppingResult:
    is_mall: bool
    found_keywords: list = field(default_factory=list)
    price_patterns: list = field(default_factory=list)


def judge(text):
    """text: OCR 글자를 공백으로 이어 붙인 문자열 (ocr.full_text)"""
    found = [kw for kw in config.SHOPPING_KEYWORDS if kw in text]
    prices = re.findall(config.SHOPPING_PRICE_REGEX, text)
    is_mall = (len(found) >= config.SHOPPING_MIN_KEYWORDS
               or len(prices) >= config.SHOPPING_MIN_PRICES)
    return ShoppingResult(is_mall=is_mall, found_keywords=found, price_patterns=prices)
