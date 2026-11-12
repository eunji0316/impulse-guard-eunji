"""가상 화면 만들기 (C-1): 화면 한 장 = 영역(section) 목록, 영역 = OCR 상자 글자 목록

분류 (데스크톱 detector/stage.py와 같은 값)
- product (상품 화면): 상품 상세, 상품 목록/검색, 장바구니, 배달앱 가게·메뉴 화면
- checkout (결제 화면): 주문서/결제 화면, 배달앱 주문 화면
- none (쇼핑 아님): 쇼핑몰이 아닌 모든 화면 + 쇼핑몰 안의 주문 완료, 주문 내역, 배송 조회, 고객센터
  (주문 완료/내역: 이미 산 뒤라 개입 의미가 없고, 차단 기간에 배송 조회할 때 차단 창이 뜨면 안 된다)

쇼핑몰 화면은 쇼핑몰마다 정해진 이름, 메뉴, 버튼 문구, 가격 표기 방식을 쓴다.
쇼핑몰이 아닌 화면도 사이트(site)를 정해 두어, 평가 때 사이트 단위로 나눌 수 있게 한다.
"""
import random
import string

from . import vocab as V


class Filler(dict):
    """'{n}', '{p}' 같은 자리를 그때그때 무작위 값으로 채운다"""

    def __init__(self, rng, mall=None, **fixed):
        super().__init__(**fixed)
        self.rng = rng
        self.mall = mall

    def __missing__(self, key):
        r = self.rng
        gen = {
            'n': lambda: r.choice([r.randint(1, 99), r.randint(100, 9999), r.randint(10000, 99999)]),
            'x': lambda: f'{r.randint(1, 500) * 100:,}', 'y': lambda: f'{r.choice([15, 20, 30, 50, 70]) * 1000:,}',
            'p': lambda: f'{r.randint(10, 3000) * 100:,}', 'd': lambda: r.randint(1, 60), 'e': lambda: r.randint(1, 90),
            'k': lambda: r.choice([2, 3, 6, 10, 12]), 'r': lambda: f'{r.uniform(3.5, 5.0):.1f}',
            'h': lambda: r.randint(1, 12), 'm2': lambda: f'{r.randint(0, 59):02d}', 'mm': lambda: r.randint(1, 12),
            'dd': lambda: r.randint(1, 28), 'w': lambda: r.choice('월화수목금토일'), 'name': lambda: person(r),
            'name2': lambda: person(r), 'item': lambda: item_name(r), 'topic': lambda: r.choice(V.NEWS_TOPICS),
            'q': lambda: r.choice(V.QUERIES), 't': lambda: won(r, r.randint(50, 3000) * 100),
            'biz': lambda: f'{r.randint(100, 999)}-{r.randint(10, 99)}-{r.randint(10000, 99999)}',
            'year': lambda: r.randint(2015, 2026), 'tel': lambda: f'{r.choice(["1588", "1644", "1577", "02"])}-{r.randint(1000, 9999)}',
            'addr': lambda: address(r), 'brand': lambda: r.choice(V.BRANDS), 'mat': lambda: r.choice(V.MATERIALS),
            'merit': lambda: r.choice(V.MERITS), 'care': lambda: r.choice(V.CARE), 'country': lambda: r.choice(V.COUNTRIES),
            's': lambda: r.choice(['S', 'M', 'L', 'FREE', '95', '100']), 'fn': lambda: r.choice(V.CODE_FUNCS),
            'var': lambda: r.choice(V.CODE_VARS), 'cls': lambda: r.choice(['Cart', 'Order', 'Analyzer', 'Config', 'Model']),
            'comment': lambda: r.choice(V.COMMENTS_CODE), 'file': lambda: r.choice(V.CODE_FILES),
            'port': lambda: r.choice([3000, 8000, 8001, 5173, 8080]),
            'mall': lambda: self.mall['name'] if self.mall else fake_mall_name(r),
        }
        return gen[key]() if key in gen else ''


def fill(rng, template, mall=None, **fixed):
    return template.format_map(Filler(rng, mall, **fixed))


def pick(rng, pool, lo, hi=None, mall=None, **fixed):
    """pool에서 lo~hi개를 골라 자리를 채운다"""
    k = min(len(pool), rng.randint(lo, hi if hi is not None else lo))
    return [fill(rng, t, mall, **fixed) for t in rng.sample(pool, k)]


def person(rng):
    return rng.choice(V.LAST_NAMES) + rng.choice(V.FIRST_NAMES)


def masked_person(rng):
    name = person(rng)
    return rng.choice([name, name[0] + '*' + name[2:], name[0] + '**'])


def phone(rng):
    mid = rng.choice([f'{rng.randint(1000, 9999)}', '****'])
    return f'010-{mid}-{rng.randint(1000, 9999)}'


def address(rng):
    return (f'{rng.choice(V.CITIES)} {rng.choice(V.DISTRICTS)} {rng.choice(V.ROADS)} {rng.randint(1, 300)}'
            + rng.choice(['', f' {rng.randint(101, 120)}동 {rng.randint(101, 1504)}호',
                          f' {rng.choice(V.APT)} {rng.randint(1, 20)}층']))


def item_name(rng, cat=None):
    cat = cat or rng.choice(list(V.ITEMS))
    parts = [rng.choice(V.ITEMS[cat])]
    if rng.random() < 0.6:
        parts.insert(0, rng.choice(V.ADJECTIVES))
    if cat != 'delivery' and rng.random() < 0.7:
        parts.insert(0, rng.choice(V.BRANDS))
    return ' '.join(parts)


def fake_mall_name(rng):
    if rng.random() < 0.5:
        return rng.choice(V.MALL_HEAD_KO) + rng.choice(V.MALL_TAIL_KO)
    return (rng.choice(V.MALL_HEAD_EN) + rng.choice(V.MALL_TAIL_EN)).upper()


def won(rng, value, fmt='{:,}원'):
    return fmt.format(value)


# ── 쇼핑몰 ────────────────────────────────────────────────────────

PRICE_FORMATS = ['{:,}원', '{:,}원', '{:,} 원', '₩{:,}', '{:,}', 'KRW {:,}', '{:,}원~']


def make_mall(rng, idx, cat=None):
    """가상 쇼핑몰 하나. 메뉴, 버튼 문구, 가격 표기를 몰마다 다르게 고른다"""
    cat = cat or rng.choice(V.CATEGORIES)
    ko = rng.random() < 0.55
    name = (rng.choice(V.MALL_HEAD_KO) + rng.choice(V.MALL_TAIL_KO)) if ko else \
        (rng.choice(V.MALL_HEAD_EN) + rng.choice(V.MALL_TAIL_EN))
    domain = ''.join(c for c in (name if not ko else rng.choice(V.MALL_HEAD_EN) + rng.choice(V.MALL_TAIL_EN)).lower()
                     if c in string.ascii_lowercase)
    sub = lambda pool, frac: rng.sample(pool, max(2, int(len(pool) * frac)))   # noqa: E731
    return {
        'id': f'mall{idx:02d}', 'name': name if ko else rng.choice([name, name.upper(), name.capitalize()]),
        'cat': cat, 'domain': domain + rng.choice(['.com', '.co.kr', '.kr', '.shop']),
        'nav': sub(V.NAV_COMMON, 0.3) + sub(V.NAV_BY_CAT[cat], 0.6),
        'user_menu': sub(V.USER_MENU, 0.4),
        'buttons': sub(V.PRODUCT_BUTTONS, 0.4),
        'price_labels': sub(V.PRICE_LABELS, 0.3),
        'pay_buttons': sub(V.PAY_BUTTONS, 0.4),
        'checkout_titles': sub(V.CHECKOUT_TITLES, 0.3),
        'easy_pays': sub(V.EASY_PAYS, 0.4) + ([name + '페이'] if rng.random() < 0.3 else []),
        'price_fmt': rng.choice(PRICE_FORMATS),
        'url_product': rng.choice(['/product/{n}', '/goods/{n}', '/p/{n}', '/item/{n}', '/products/{n}',
                                   '/shop/item.php?it_id={n}', '/store/{n}']),
        'url_checkout': rng.choice(['/order', '/checkout', '/orderform', '/payment', '/order/sheet', '/shop/orderform.php',
                                    '/cart/checkout']),
        'url_done': rng.choice(['/order/complete', '/order/result', '/mypage/order', '/orderinquiry', '/order/done']),
        'has_banner': rng.random() < 0.5,
        'has_footer': rng.random() < 0.8,
        'has_url': rng.random() < 0.75,
    }


def price(rng, mall, value=None):
    value = value if value is not None else rng.randint(30, 4000) * 100
    return mall['price_fmt'].format(value), value


def browser_bar(rng, mall=None, path='', title=''):
    """브라우저 탭과 주소창 글자 (캡처에 함께 찍힌다)"""
    out = []
    if title:
        out.append(title)
    if mall is not None and mall['has_url']:
        out.append(mall['domain'] + fill(rng, path))
    elif mall is None and path:
        out.append(path)
    if rng.random() < 0.2:
        out += pick(rng, V.BROWSER, 1, 2)
    return out


def header(rng, mall, minimal=False):
    out = [rng.choice([mall['name'], mall['name'].upper()])]
    if mall['has_banner'] and not minimal and rng.random() < 0.6:
        out.append(fill(rng, rng.choice(V.TOP_BANNERS), mall))
    if not minimal:
        out += rng.sample(mall['nav'], min(len(mall['nav']), rng.randint(3, 9)))
        if rng.random() < 0.7:
            out.append(rng.choice(V.SEARCH_HINTS))
    out += rng.sample(mall['user_menu'], min(len(mall['user_menu']), rng.randint(1, 4)))
    return out


def footer(rng, mall):
    if not mall['has_footer'] or rng.random() < 0.3:
        return []
    return pick(rng, V.FOOTER, 2, 7, mall)


def product_card(rng, mall):
    """목록/추천 영역의 상품 하나"""
    out = [item_name(rng, mall['cat'])]
    p, v = price(rng, mall)
    if rng.random() < 0.6:
        out.append(f'{rng.randint(5, 70)}%')
    out.append(p)
    if rng.random() < 0.4:
        out.append(fill(rng, rng.choice(V.REVIEW_FMT)))
    if rng.random() < 0.3:
        out.append(rng.choice(V.BADGES))
    return out


def page(mall, kind, sections, path='', title=''):
    return {'sections': sections, 'kind': kind, 'path': path, 'title': title}


# ── 상품 화면 ─────────────────────────────────────────────────────

def product_detail(rng, mall):
    cat = mall['cat']
    name = item_name(rng, cat)
    sale_p, sale_v = price(rng, mall)
    rate = rng.randint(5, 70)
    orig_p, _ = price(rng, mall, int(sale_v / (1 - rate / 100)) // 100 * 100)
    title_sec = [name] + ([rng.choice(V.BRANDS)] if rng.random() < 0.4 else [])
    if rng.random() < 0.3:
        title_sec.insert(0, ' > '.join(rng.sample(mall['nav'], min(2, len(mall['nav'])))))
    price_sec = []
    if rng.random() < 0.7:
        price_sec += [rng.choice(mall['price_labels']), orig_p]
    price_sec += [f'{rate}%' if rng.random() < 0.7 else f'{rate}% 할인', sale_p]
    if rng.random() < 0.4:
        price_sec.append(rng.choice(mall['price_labels']))
    sections = [title_sec, price_sec]
    if rng.random() < 0.75:
        sections.append(pick(rng, V.REVIEW_FMT, 1, 2))
    if rng.random() < 0.6:
        sections.append(pick(rng, V.BENEFITS, 1, 3))
    if cat == 'delivery':
        sections.append(pick(rng, V.DELIVERY_INFO, 2, 6))
    else:
        sections.append(pick(rng, V.SHIPPING, 1, 3))
    if rng.random() < 0.7:
        opt = pick(rng, V.OPTION_UI, 1, 3) + rng.sample(V.OPTION_NAMES, 1) + rng.sample(V.OPTION_VALUES, rng.randint(1, 4))
        if rng.random() < 0.5:
            opt.append(price(rng, mall, sale_v)[0])
        sections.append(opt)
    sections.append(rng.sample(mall['buttons'], min(len(mall['buttons']), rng.randint(1, 3))))
    sections[-1] = [fill(rng, b) for b in sections[-1]]
    if rng.random() < 0.5:
        sections.append(pick(rng, V.PRODUCT_TABS, 2, 5))
    if rng.random() < 0.5:
        sections.append(pick(rng, V.DETAIL_LINES, 1, 4))
    if rng.random() < 0.3:
        sections.append(pick(rng, V.REVIEWS, 1, 4))
    if rng.random() < 0.4:
        rel = [rng.choice(V.RELATED_TITLES)]
        for _ in range(rng.randint(1, 4)):
            rel += product_card(rng, mall)
        sections.append(rel)
    return page(mall, 'product_detail', sections, mall['url_product'], name)


def delivery_menu(rng, mall):
    """배달앱 가게 화면 (메뉴와 가격 목록) → 상품 화면"""
    store = rng.choice(['', '본점', '역삼점', '홍대점', '신촌점'])
    sections = [[fake_mall_name(rng) + ' ' + rng.choice(V.ITEMS['delivery'])[:2] + store],
                pick(rng, V.DELIVERY_INFO, 3, 7), pick(rng, V.REVIEW_FMT, 1, 2)]
    for _ in range(rng.randint(2, 6)):
        sections.append([item_name(rng, 'delivery'), price(rng, mall, rng.randint(30, 400) * 100)[0]]
                        + (pick(rng, V.REVIEWS, 1) if rng.random() < 0.2 else []))
    if rng.random() < 0.5:
        sections.append(pick(rng, ['장바구니 담기', '장바구니 보기', '{t} 담기', '배달 주문', '포장 주문', '수량', '- 1 +',
                                   '메뉴 옵션', '추가 선택', '맛 선택'], 1, 3))
    return page(mall, 'delivery_menu', sections, '/store/{n}', '')


def product_list(rng, mall):
    cat_title = rng.choice(mall['nav'])
    sections = [[cat_title] + pick(rng, ['총 {n}개 상품', '상품 {n}개', '{n}개의 상품', '검색결과 {n}건'], 1),
                pick(rng, V.LIST_SORT, 2, 5) + pick(rng, V.LIST_FILTER, 0, 4)]
    for _ in range(rng.randint(4, 14)):
        sections.append(product_card(rng, mall))
    return page(mall, 'product_list', sections, rng.choice(['/category/{n}', '/search?q=', '/list/{n}', '/best', '/event/{n}']),
                cat_title)


def cart(rng, mall):
    """장바구니 → 상품 화면 (결제 직전이지만 아직 결제 화면이 아님)"""
    sections = [pick(rng, V.STEPS, 0, 1) + ['장바구니' if rng.random() < 0.8 else 'CART'],
                pick(rng, ['전체선택', '선택삭제', '일반배송', '품절 상품 삭제', '총 {n}개'], 1, 3)]
    total = 0
    for _ in range(rng.randint(1, 5)):
        p, v = price(rng, mall)
        total += v
        sections.append([item_name(rng, mall['cat']), f'{rng.choice(V.OPTION_NAMES)}: {rng.choice(V.OPTION_VALUES)}',
                         f'{rng.randint(1, 3)}개', p] + pick(rng, ['옵션 변경', '수량 변경', '삭제', '쿠폰 적용 가능'], 0, 2))
    summ = pick(rng, V.CART_LINES, 3, 7) + [price(rng, mall, total)[0]]
    sections.append(summ)
    return page(mall, 'cart', sections, rng.choice(['/cart', '/basket', '/shop/cart.php', '/order/cart']),
                rng.choice(['장바구니', 'CART', '']))


# ── 결제 화면 ─────────────────────────────────────────────────────

def checkout(rng, mall):
    delivery = mall['cat'] == 'delivery'
    total_v = rng.randint(50, 6000) * 100
    total_p = price(rng, mall, total_v)[0]
    sections = [[rng.choice(mall['checkout_titles'])] + pick(rng, V.STEPS, 0, 1)]
    blocks = []
    if not delivery or rng.random() < 0.3:
        blocks.append(pick(rng, V.BUYER, 1, 3) + [masked_person(rng), phone(rng)])
    ship = pick(rng, V.SHIP, 2, 6) + [masked_person(rng)] + ([address(rng)] if rng.random() < 0.8 else []) + \
        ([phone(rng)] if rng.random() < 0.6 else [])
    if delivery:
        ship += pick(rng, V.DELIVERY_CHECKOUT, 2, 5)
    blocks.append(ship)
    items = pick(rng, V.ORDER_ITEMS, 1)
    for _ in range(rng.randint(1, 3)):
        items += [item_name(rng, mall['cat'])] + ([f'{rng.choice(V.OPTION_NAMES)}: {rng.choice(V.OPTION_VALUES)}']
                                                   if rng.random() < 0.5 else []) + \
                 [f'{rng.randint(1, 3)}개', price(rng, mall)[0]]
    blocks.append(items)
    if rng.random() < 0.75:
        blocks.append(pick(rng, V.DISCOUNT, 2, 5))
    pay = pick(rng, V.PAY_METHODS, 2, 6) + rng.sample(mall['easy_pays'], min(len(mall['easy_pays']), rng.randint(1, 4)))
    if rng.random() < 0.5:
        pay += rng.sample(V.CARDS, rng.randint(1, 4))
    if rng.random() < 0.6:
        pay += pick(rng, V.CHECKOUT_PROMO, 1, 4, card=rng.choice(V.CARDS), pay=rng.choice(mall['easy_pays']))
    rng.shuffle(pay)
    blocks.append(pay)
    rng.shuffle(blocks)
    sections += blocks
    summ = pick(rng, V.PAY_SUMMARY, 2, 6)
    summ = [x for s in summ for x in (s, price(rng, mall)[0] if rng.random() < 0.5 else '')] if rng.random() < 0.5 else summ
    summ = [s for s in summ if s] + [total_p]
    sections.append(summ)
    if rng.random() < 0.7:
        sections.append(pick(rng, V.AGREE, 1, 3))
    if rng.random() < 0.85:
        sections.append([fill(rng, rng.choice(mall['pay_buttons']), t=total_p)])
    return page(mall, 'checkout', sections, mall['url_checkout'], rng.choice(['주문/결제', '주문서', 'Checkout', '결제', '']))


# ── 쇼핑몰 안의 쇼핑 아님 ─────────────────────────────────────────

def order_done(rng, mall):
    sections = [pick(rng, V.STEPS, 0, 1) + pick(rng, V.ORDER_DONE[:4] + V.ORDER_DONE[16:18] + V.ORDER_DONE[21:], 1, 2),
                [rng.choice(['주문번호', '주문 번호', 'ORDER NO.']), f'{rng.randint(20250000, 20269999)}{rng.randint(10000, 99999)}'],
                pick(rng, V.ORDER_DONE, 2, 6) + [price(rng, mall)[0]]]
    if rng.random() < 0.5:
        sections.append([item_name(rng, mall['cat']), f'{rng.randint(1, 3)}개', price(rng, mall)[0]])
    if rng.random() < 0.5:
        sections.append([rng.choice(['결제수단', '결제 방법']), rng.choice(V.CARDS + V.EASY_PAYS + ['무통장입금', '가상계좌']),
                         rng.choice(['일시불', '', '{k}개월'])])
    if rng.random() < 0.4:
        sections.append(['배송지', masked_person(rng), address(rng)])
    sections.append(pick(rng, ['쇼핑 계속하기', '주문 상세보기', '주문내역 확인', '홈으로', '확인'], 1, 2))
    return page(mall, 'order_done', sections, mall['url_done'], rng.choice(['주문완료', '주문 완료', 'Order Complete', '']))


def order_history(rng, mall):
    sections = [pick(rng, V.ORDER_HIST, 3, 8)]
    for _ in range(rng.randint(1, 5)):
        sections.append([f'2026.{rng.randint(1, 12):02d}.{rng.randint(1, 28):02d}', rng.choice(V.ORDER_STATUS),
                         item_name(rng, mall['cat']), price(rng, mall)[0]]
                        + pick(rng, ['배송조회', '구매확정', '리뷰 작성', '교환 신청', '반품 신청', '주문 취소', '재구매',
                                     '다시 담기', '장바구니 담기', '주문상세'], 1, 3))
    if rng.random() < 0.3:
        sections.append(pick(rng, V.TRACKING, 3, 8))
    return page(mall, 'order_history', sections, rng.choice(['/mypage/order', '/order/list', '/mypage', '/orderinquiry']),
                rng.choice(['주문내역', '주문/배송조회', 'MY 쇼핑', '']))


def tracking(rng, mall):
    sections = [pick(rng, V.TRACKING, 4, 10) + [f'{rng.randint(100000000000, 999999999999)}'],
                [rng.choice(V.ORDER_STATUS), item_name(rng, mall['cat'])]]
    for _ in range(rng.randint(2, 5)):
        sections.append([f'{rng.randint(1, 12):02d}.{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}',
                         rng.choice(V.TRACKING[8:])])
    return page(mall, 'tracking', sections, '/delivery/tracking', '배송조회')


def customer_center(rng, mall):
    sections = [pick(rng, V.FAQ, 6, 14, mall)]
    return page(mall, 'faq', sections, rng.choice(['/cs', '/faq', '/board/notice', '/help']), '고객센터')


# ── 쇼핑몰이 아닌 화면 ────────────────────────────────────────────

def news(rng, site):
    topic = rng.choice(V.NEWS_TOPICS)
    sents = [fill(rng, s, topic=topic if rng.random() < 0.6 else rng.choice(V.NEWS_TOPICS))
             for s in rng.sample(V.NEWS_SENT, rng.randint(3, 8))]
    secs = [[site] + pick(rng, V.NEWS_MENU, 3, 8), [f'{topic} ' + rng.choice(['급증', '논란', '비상', '전망', '역대 최대', '주의보', '"꼼꼼히 비교해야"'])],
            pick(rng, V.NEWS_META, 2, 4), sents]
    if rng.random() < 0.5:
        secs.append([rng.choice(['많이 본 뉴스', '관련 기사', '이 시각 주요 뉴스'])]
                    + [f'{rng.choice(V.NEWS_TOPICS)} {rng.choice(["관련", "속보", "분석", "발표"])}' for _ in range(rng.randint(2, 5))])
    if rng.random() < 0.3:
        secs.append(pick(rng, ['광고', '{item} 최대 {d}% 할인', '지금 구매하기', '자세히 보기', 'AD'], 1, 3))
    return secs, 'https://news.' + site_domain(site) + '/article/{n}'


def blog(rng, site):
    item = item_name(rng)
    sents = [fill(rng, s, item=item) for s in rng.sample(V.BLOG_SENT, rng.randint(3, 8))]
    secs = [[site] + pick(rng, V.BLOG_UI, 3, 7, item=item), [f'{item} ' + rng.choice(['후기', '솔직 리뷰', '한 달 사용기', '구매 고민 끝'])
                                                           if rng.random() < 0.6 else rng.choice(['주말 일상', '카페 투어', '독서 기록', '여행 기록'])],
            sents]
    if rng.random() < 0.3:
        secs.append([f'{rng.choice(["구매 링크", "제품 정보", "가격"])}', fill(rng, '{p}원'), fake_mall_name(rng)])
    return secs, 'blog.' + site_domain(site) + '/{n}'


def hotdeal(rng, site):
    secs = [[site] + pick(rng, V.HOTDEAL_UI, 4, 9)]
    for _ in range(rng.randint(3, 9)):
        secs.append([fill(rng, rng.choice(V.HOTDEAL_TITLE)), fill(rng, rng.choice(['추천 {n}', '{h}분 전', '조회 {n}', '[{d}]']))])
    if rng.random() < 0.5:
        secs.append(pick(rng, V.COMMENTS, 2, 5))
    return secs, site_domain(site) + '/hotdeal/{n}'


def bank(rng, site):
    secs = [[site + rng.choice(['은행', '뱅크', ' 인터넷뱅킹'])] + pick(rng, V.BANK_UI, 6, 14),
            [masked_person(rng), f'{rng.randint(100, 999)}-{rng.randint(100000, 999999)}-{rng.randint(10, 99)}', fill(rng, '{p}원')]]
    for _ in range(rng.randint(0, 6)):
        secs.append([f'2026.{rng.randint(1, 12):02d}.{rng.randint(1, 28):02d}', rng.choice(['입금', '출금', '체크카드', '이체']),
                     rng.choice([fake_mall_name(rng), person(rng), '편의점', '급여', '관리비', '카드대금']), fill(rng, '{p}원')])
    return secs, 'banking.' + site_domain(site)


def card(rng, site):
    secs = [[site + '카드'] + pick(rng, V.CARD_UI, 6, 12)]
    for _ in range(rng.randint(2, 8)):
        secs.append([f'{rng.randint(1, 12):02d}.{rng.randint(1, 28):02d}', rng.choice([fake_mall_name(rng), '스타벅스', '편의점',
                     '택시', '배달앱', '온라인결제', '주유소', '마트']), fill(rng, '{p}원'), rng.choice(['일시불', '{k}개월', ''])])
    return [[fill(rng, x) for x in s] for s in secs], 'card.' + site_domain(site)


def ledger(rng, site):
    return [[site] + pick(rng, V.LEDGER_UI, 8, 16)], ''


def mail(rng, site):
    secs = [[site + ' 메일'] + pick(rng, V.MAIL_UI, 5, 10)]
    for _ in range(rng.randint(3, 10)):
        secs.append([rng.choice([person(rng), fake_mall_name(rng), '알림', 'noreply']), fill(rng, rng.choice(V.MAIL_SUBJECTS)),
                     fill(rng, rng.choice(['오후 {h}:{m2}', '{mm}월 {dd}일', '어제']))])
    if rng.random() < 0.4:
        secs.append(pick(rng, V.MAIL_BODY, 3, 8) + [fill(rng, '{p}원')] * (rng.random() < 0.5))
    return secs, 'mail.' + site_domain(site)


def stock(rng, site):
    secs = [[site] + pick(rng, V.STOCK_UI, 8, 16)]
    for _ in range(rng.randint(2, 8)):
        secs.append([rng.choice(V.STOCK_NAMES), fill(rng, '{p}'), f'{rng.choice("+-")}{rng.uniform(0, 15):.2f}%',
                     f'{rng.randint(1000, 9999999):,}'])
    return secs, site_domain(site) + '/stock'


def realty(rng, site):
    secs = [[site + ' 부동산'] + pick(rng, V.REALTY_UI, 8, 16)]
    for _ in range(rng.randint(2, 6)):
        secs.append([rng.choice(V.ROADS) + rng.choice(V.APT), fill(rng, rng.choice(['매매 {d}억 {e}천', '전세 {d}억', '월세 {d}천/{e}']))])
    return secs, 'land.' + site_domain(site)


def search(rng, site):
    q = rng.choice(V.QUERIES)
    secs = [[site, q] + pick(rng, V.SEARCH_UI, 5, 10)]
    for _ in range(rng.randint(3, 8)):
        secs.append([fill(rng, rng.choice(V.SEARCH_SNIPPET), q=q), f'www.{site_domain(fake_mall_name(rng))}',
                     fill(rng, rng.choice(V.NEWS_SENT + V.BLOG_SENT), topic=q, item=q)])
    return secs, site_domain(site) + '/search?query=' + q


def youtube(rng, site):
    secs = [pick(rng, V.YT_UI, 6, 14)]
    for _ in range(rng.randint(3, 10)):
        secs.append([fill(rng, rng.choice(V.YT_TITLES)), person(rng) + rng.choice(['TV', ' 채널', '', 'Vlog']),
                     fill(rng, rng.choice(['조회수 {n}만회', '조회수 {n}회'])), fill(rng, '{d}일 전')])
    if rng.random() < 0.15:
        secs.append(['광고', item_name(rng), '지금 구매하기', fake_mall_name(rng)])
    return secs, 'youtube.com/watch?v=' + ''.join(rng.choices(string.ascii_letters + string.digits, k=11))


def code(rng, site):
    secs = [pick(rng, V.CODE_UI, 6, 14), rng.sample(V.CODE_FILES, rng.randint(2, 8))]
    secs.append([fill(rng, rng.choice(V.CODE_LINES)) for _ in range(rng.randint(8, 30))])
    return secs, ''


def document(rng, site):
    secs = [pick(rng, V.DOC_UI, 5, 12), [fill(rng, rng.choice(V.DOC_SENT)) for _ in range(rng.randint(4, 14))]]
    return secs, rng.choice(['', 'docs.' + site_domain(site) + '/document/d/{n}'])


def chat(rng, site):
    secs = [pick(rng, V.CHAT_UI, 4, 9)]
    for _ in range(rng.randint(4, 14)):
        secs.append([fill(rng, rng.choice(['{name}', '나'])), fill(rng, rng.choice(V.CHAT_LINES)), fill(rng, '오후 {h}:{m2}')])
    return secs, ''


def admin(rng, site):
    secs = [[rng.choice(['그누보드 관리자', 'impulse-guard 관리자', '쇼핑몰 관리자', 'ADMIN'])] + pick(rng, V.ADMIN_UI, 8, 18)]
    for _ in range(rng.randint(2, 8)):
        secs.append([fill(rng, '{n}'), masked_person(rng), fill(rng, '{p}원'), rng.choice(V.ORDER_STATUS + ['차단', '쿨다운', '정상'])])
    return secs, 'localhost:8001/adm/{n}'


def webtoon(rng, site):
    secs = [[site] + pick(rng, V.WEBTOON_UI, 8, 16)]
    secs.append([f'{fake_mall_name(rng)[:3]}의 {rng.choice(["비밀", "하루", "모험", "학교", "식당"])}' for _ in range(rng.randint(3, 8))])
    return secs, site_domain(site) + '/webtoon'


def maps(rng, site):
    return [[site] + pick(rng, V.MAP_UI, 8, 16), [rng.choice(V.ROADS) + ' ' + rng.choice(['카페', '식당', '역', '공원', '병원'])]], \
        'map.' + site_domain(site)


def sheet(rng, site):
    secs = [pick(rng, V.SHEET_UI, 8, 16)]
    for _ in range(rng.randint(3, 10)):
        secs.append([fill(rng, '{mm}/{dd}'), rng.choice(['식비', '쇼핑', '교통', '카페', '월세', '구독', fake_mall_name(rng)]),
                     fill(rng, rng.choice(['{p}', '{p}원'])), rng.choice(['', '카드', '현금', '할부'])])
    return secs, ''


def site_domain(name):
    s = ''.join(c for c in name.lower() if c in string.ascii_lowercase)
    return (s or 'site') + '.com'


NON_MALL = {
    'news': (news, 0.16), 'blog': (blog, 0.10), 'hotdeal': (hotdeal, 0.08), 'bank': (bank, 0.06), 'card': (card, 0.06),
    'ledger': (ledger, 0.03), 'mail': (mail, 0.07), 'stock': (stock, 0.05), 'realty': (realty, 0.03), 'search': (search, 0.08),
    'youtube': (youtube, 0.08), 'code': (code, 0.06), 'document': (document, 0.05), 'chat': (chat, 0.04), 'admin': (admin, 0.03),
    'webtoon': (webtoon, 0.01), 'maps': (maps, 0.01), 'sheet': (sheet, 0.02),
}
