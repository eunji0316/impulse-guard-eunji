"""OCR 노이즈 (C-1 가상 데이터)

실제 캡처에서 본 오류를 바탕으로 한다.
- 비슷한 글자로 잘못 읽기: 금액→금억/금역, 총→좀/촘, 원→윈, l/1/I, O/0 (B-4, B-5 실측)
- 한글 받침/모음 하나가 바뀌는 일반 오인식
- 띄어쓰기: 붙여 읽거나, Windows OCR처럼 글자마다 띄어 읽기
- 글자 빠짐, 상자 통째로 빠짐 (흰 글자 버튼을 못 읽는 경우 등)
- 쓰레기 토큰 ('5ITnn3I' 같은 아이콘/로고 오인식)
- 읽는 순서: 여러 열 화면에서 영역 순서가 섞임
- 화면 일부만 보임: 스크롤 위치에 따라 위/중간/아래만, 작은 창이면 한 영역만
- 아이콘을 글자로 읽음: 한 글자짜리 상자('수', '기', '口', '〉')나 단어 앞에 붙은 글자('O좋아요')
  (Windows OCR 실측에서 자주 보인다. heavy 강도는 이것과 음절 변형을 크게 늘린 것)
"""
import random
import string

# 실측에서 본 오인식 (맞는 글자 → 틀린 글자 후보)
CONFUSIONS = {
    '금액': ['금억', '금역', '금맥'], '총': ['좀', '촘'], '원': ['윈', '웜', '원'], '결제': ['결재', '걸제', '결세'],
    '배송': ['베송', '배손'], '쿠폰': ['쿠뽄', '쿠픈'], '할인': ['할민', '활인'], '수량': ['수랑'], '장바구니': ['장바구L', '장바구나'],
    '상품': ['상풍', '삼품'], '주문': ['주무', '주룬'], '구매': ['구메', '구머'], '리뷰': ['리부', '라뷰'],
    'l': ['1', 'I', '|'], 'O': ['0', 'o'], '0': ['O', 'o'], 'S': ['5'], 'B': ['8'], ',': ['.', ''], '%': ['X', '9'],
}
# 한글 음절의 중성(모음), 종성(받침) 바꾸기용
_HANGUL_BASE, _JUNG, _JONG = 0xAC00, 21, 28

LEVELS = {
    # 이름: (글자 오인식 확률, 음절 변형, 글자 빠짐, 상자 빠짐, 쓰레기 토큰 수, 띄어쓰기 변형, 영역 섞기, 잘라내기 확률)
    'none': (0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0),
    'normal': (0.15, 0.02, 0.01, 0.06, 2, 0.15, 0.3, 0.35),
    'strong': (0.35, 0.06, 0.03, 0.15, 5, 0.3, 0.6, 0.5),
    'heavy': (0.5, 0.15, 0.05, 0.25, 10, 0.3, 0.6, 0.6),
}
# 강도별 (아이콘 글자 상자 수 최대, 단어 앞에 아이콘 글자가 붙을 확률, 한 영역만 보일 정도로 작게 자를 확률)
ICON_LEVELS = {'none': (0, 0.0, 0.0), 'normal': (3, 0.03, 0.1), 'strong': (6, 0.06, 0.2), 'heavy': (12, 0.1, 0.3)}
ICON_GLYPHS = ['수', '기', '구', 'O', 'I', '0', '口', '凸', '十', '〉', '>', '<', '•', '·', 'Ü', '㉦', 'Q', 'A', '♡', '♥',
               '×', '①', 'j', '|', '=', '-', '+', '*', '⋯', '용', '의']


def garbage(rng):
    k = rng.randint(2, 8)
    pool = string.ascii_letters + string.digits + '|·•<>[]()=-_/\\~'
    return ''.join(rng.choice(pool) for _ in range(k))


def mutate_syllable(ch, rng):
    code = ord(ch) - _HANGUL_BASE
    if not 0 <= code < 11172:
        return ch
    cho, rest = divmod(code, _JUNG * _JONG)
    jung, jong = divmod(rest, _JONG)
    if rng.random() < 0.5:
        jong = rng.randrange(_JONG) if rng.random() < 0.6 else 0
    else:
        jung = rng.randrange(_JUNG)
    return chr(_HANGUL_BASE + (cho * _JUNG + jung) * _JONG + jong)


def noisy_box(text, rng, level):
    p_conf, p_syl, p_drop, _, _, p_space, _, _ = LEVELS[level]
    if p_conf and rng.random() < p_conf:
        keys = [k for k in CONFUSIONS if k in text]
        if keys:
            k = rng.choice(keys)
            text = text.replace(k, rng.choice(CONFUSIONS[k]), 1)
    if p_syl or p_drop:
        out = []
        for ch in text:
            r = rng.random()
            if r < p_drop:
                continue
            out.append(mutate_syllable(ch, rng) if r < p_drop + p_syl else ch)
        text = ''.join(out)
    if p_space and rng.random() < p_space:
        if rng.random() < 0.5:
            text = text.replace(' ', '')                       # 붙여 읽기
        else:
            text = ' '.join(text) if len(text) < 12 else text  # 글자마다 띄어 읽기 (짧은 상자만)
    return text


def apply(sections, rng, level='normal', chrome=()):
    """영역 목록 → OCR full_text와 같은 한 줄 글자 (상자를 공백으로 이어 붙임)

    chrome: 브라우저 탭/주소창 상자 (항상 맨 앞, 잘라내기 영향 없음)
    """
    _, _, _, p_box, n_garbage, _, p_shuffle, p_crop = LEVELS[level]
    n_icon, p_prefix, p_small = ICON_LEVELS[level]
    sections = [list(s) for s in sections if s]
    if p_shuffle and len(sections) > 3 and rng.random() < p_shuffle:
        # 머리(첫 영역)와 꼬리(끝 영역)는 두고 가운데 이웃 영역끼리 몇 번 바꾼다
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(1, len(sections) - 2)
            sections[i], sections[i + 1] = sections[i + 1], sections[i]
    boxes = [b for s in sections for b in s if b]
    if p_crop and len(boxes) > 8 and rng.random() < p_crop:
        keep = rng.uniform(0.15, 0.4) if rng.random() < p_small else rng.uniform(0.45, 0.9)
        n = max(6, int(len(boxes) * keep))
        start = rng.choice([0, rng.randrange(0, len(boxes) - n + 1), len(boxes) - n])
        boxes = boxes[start:start + n]
    if p_box:
        boxes = [b for b in boxes if rng.random() >= p_box] or boxes[:1]
    boxes = list(chrome) + boxes
    boxes = [noisy_box(b, rng, level) for b in boxes]
    boxes = [(rng.choice(ICON_GLYPHS) + b) if p_prefix and rng.random() < p_prefix else b for b in boxes]
    for _ in range(rng.randint(0, n_garbage)):
        boxes.insert(rng.randrange(len(boxes) + 1), garbage(rng))
    for _ in range(rng.randint(0, n_icon)):
        boxes.insert(rng.randrange(len(boxes) + 1), ' '.join(rng.choices(ICON_GLYPHS, k=rng.randint(1, 3))))
    return ' '.join(b for b in boxes if b)
