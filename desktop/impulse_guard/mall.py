"""팝업에 보일 쇼핑몰 이름 (C-2 확인 중 사용자 요청)

팝업 상품 칸에는 쇼핑몰 이름만 보인다. OCR로 읽은 상품명은 쓰지 않는다.
정하는 순서 (앞에서 찾으면 그 근거를 쓴다)
1. 창 제목의 주소(도메인)가 알려진 쇼핑몰 (config.MALLS)       예: 'zigzag.kr/checkout/order-sheets/...'
2. 창 제목에 알려진 쇼핑몰 이름                                   예: '주문/결제 : 네이버페이 - Chrome'
3. 주소창(화면 맨 위 줄) OCR 글자의 도메인이 알려진 쇼핑몰 (OCR 오인식 0/o, 1/l, i/l, 빠진 마침표를 감안)
4. 화면 글자의 쇼핑몰 이름/로고 (page.find_site, config.SITE_HINTS)
5. 모르는 쇼핑몰이지만 창 제목에 도메인이 있으면 그 도메인     예: 'example.co.kr'
6. 그래도 모르면 '쇼핑몰'. 주소창 OCR로 읽은 모르는 도메인은 글자가 틀릴 수 있어 팝업에 보이지 않고 로그(근거)에만 남긴다
창 제목 원문은 여기서 쓰고 버린다. 로그에는 근거(찾은 도메인 또는 쇼핑몰 이름 단어)만 남긴다.
"""
import difflib
import re
from dataclasses import dataclass

from . import config

UNKNOWN_NAME = '쇼핑몰'
DOMAIN_RE = re.compile(r'(?<![a-z0-9.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:co\.kr|or\.kr|com|net|kr|shop|store|se|io))(?![a-z0-9-])')
SECOND_LEVEL = ('co.kr', 'or.kr', 'ne.kr', 'go.kr')
DOT_LIKE = '•·∙ㆍ'          # OCR이 주소의 '.'을 이렇게 읽는다 ('oliveyoung•co.kr')
# 주소창 OCR 오인식을 감안해 알려진 도메인과 비교할 때의 모양: 0→o, 1→l, i→l, 마침표·공백 없음
# (실제 Windows OCR: '0hveyoung•c0.kr', '11stc0.kr', 'muslnsa.com', 'ku rly.com', 'zigzagkr.')
SKELETON = str.maketrans({'0': 'o', '1': 'l', 'i': 'l', '|': 'l'})
OCR_TLD_FIXES = {'.c0.kr': '.co.kr', '.c0m': '.com', '.corn': '.com', '.c0rn': '.com'}
FUZZY_MIN = 0.8              # 주소창 도메인 이름이 알려진 쇼핑몰과 이만큼 비슷하면 그 쇼핑몰 ('0hveyoung' ≈ 'oliveyoung' 0.84)
FUZZY_MIN_LEN = 5            # 짧은 이름은 비슷하다고 보기 어려워 비교하지 않는다


@dataclass
class Mall:
    name: str                # 팝업에 보일 이름
    code: str = ''           # config.MALLS 코드 ('' = 모르는 쇼핑몰)
    basis: str = ''          # 로그용 근거

    def note(self):
        return f'쇼핑몰 이름 {self.name} ({self.basis})'


def skeleton(text):
    t = (text or '').lower()
    for c in DOT_LIKE:
        t = t.replace(c, '.')
    return re.sub(r'[\s.]+', '', t).translate(SKELETON)


def known_in_ocr(text):
    """OCR 글자(주소창)에 알려진 쇼핑몰 도메인이 있으면 (코드, 도메인). 오인식을 감안해 skeleton으로 비교하고,
    그래도 없으면 도메인 이름(맨 앞 이름)이 알려진 쇼핑몰과 FUZZY_MIN 이상 비슷한지 본다"""
    sk = skeleton(text)
    for code, (_, domains, _) in config.MALLS.items():
        for d in domains:
            if skeleton(d) in sk:
                return code, d
    for found in domains_in(text, ocr=True):
        label = skeleton(base_domain(found).split('.')[0])
        if len(label) < FUZZY_MIN_LEN:
            continue
        for code, (_, domains, _) in config.MALLS.items():
            for d in domains:
                if difflib.SequenceMatcher(None, label, skeleton(d.split('.')[0])).ratio() >= FUZZY_MIN:
                    return code, d
    return '', ''


def domains_in(text, ocr=False):
    """글자 안의 도메인 (소문자, 앞의 www./m. 제외). OCR이 '.'을 '•'로 읽은 것도 찾는다.
    ocr=True(주소창 OCR)면 'c0.kr', 'c0m' 같은 끝부분 오인식도 고친다"""
    out = []
    text = (text or '').lower()
    for c in DOT_LIKE:
        text = text.replace(c, '.')
    if ocr:
        for wrong, right in OCR_TLD_FIXES.items():
            text = text.replace(wrong, right)
    for m in DOMAIN_RE.finditer(text):
        d = m.group(1)
        for prefix in ('www.', 'm.'):
            if d.startswith(prefix):
                d = d[len(prefix):]
        out.append(d)
    return out


def base_domain(host):
    """'order.pay.naver.com' → 'naver.com', 'shop.example.co.kr' → 'example.co.kr'"""
    parts = host.split('.')
    n = 3 if '.'.join(parts[-2:]) in SECOND_LEVEL else 2
    return '.'.join(parts[-n:])


def known_by_domain(host):
    """도메인 → MALLS 코드 (뒤가 같으면 같은 쇼핑몰: 'order.pay.naver.com'은 'pay.naver.com')"""
    for code, (_, domains, _) in config.MALLS.items():
        if any(host == d or host.endswith('.' + d) for d in domains):
            return code
    return ''


def known_by_word(text):
    """글자에 들어 있는 알려진 쇼핑몰 이름 → (코드, 찾은 단어)"""
    n = re.sub(r'\s+', '', (text or '').lower())
    for code, (_, _, words) in config.MALLS.items():
        for w in words:
            if re.sub(r'\s+', '', w.lower()) in n:
                return code, w
    return '', ''


def address_bar_text(boxes):
    """화면 맨 위(주소창 높이) 줄의 OCR 글자. 상자가 없으면 ''"""
    if not boxes:
        return ''
    top = min(b.y for b in boxes)
    return ' '.join(b.text for b in boxes if b.y - top <= config.MALL_ADDRESS_BAR_PX)


def identify(title='', boxes=None, page_site=''):
    """Mall. title: 맨 앞 창 제목 원문(쓰고 버린다), boxes: OCR 상자, page_site: page.find_site 결과"""
    title_domains = domains_in(title)
    for d in title_domains:
        code = known_by_domain(d)
        if code:
            return Mall(config.MALLS[code][0], code, f'창 제목 주소 {base_domain(d)}')
    code, word = known_by_word(title)
    if code:
        return Mall(config.MALLS[code][0], code, f"창 제목 '{word}'")
    bar = address_bar_text(boxes)
    code, d = known_in_ocr(bar)
    if code:
        return Mall(config.MALLS[code][0], code, f'주소창 {d}')
    bar_domains = domains_in(bar, ocr=True)
    if page_site in config.MALLS:
        return Mall(config.MALLS[page_site][0], page_site, '화면 글자의 쇼핑몰 이름')
    if title_domains:
        return Mall(base_domain(title_domains[0]), '', '모르는 쇼핑몰, 창 제목 도메인')
    if bar_domains:
        # 주소창 OCR 도메인은 글자가 틀릴 수 있어 팝업에 보이지 않고 로그에만 남긴다 (C-2 사용자 결정)
        return Mall(UNKNOWN_NAME, '', f'모르는 쇼핑몰, 주소창 OCR 도메인 {base_domain(bar_domains[0])} (팝업에는 안 보임)')
    return Mall(UNKNOWN_NAME, '', '근거 없음')
