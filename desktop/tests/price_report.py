"""이미지별 가격 분석 결과를 표로 보여 준다

실행 (desktop 폴더에서):
    .venv\\Scripts\\python.exe -X utf8 tests\\price_report.py          # 요약 표
    .venv\\Scripts\\python.exe -X utf8 tests\\price_report.py -v       # 후보별 단서 점수까지
"""
import sys

import cache
from impulse_guard.detector import price


def won(v):
    return f'{v:,}원' if v else '-'


def main(verbose):
    rows = []
    details = []
    for name in cache.names():
        img, boxes, reread = cache.load(name)
        r = price.analyze(boxes, img, reread=reread)
        rate = f'{r.discount_rate}%' if r.discount_rate is not None else '-'
        if r.discount_rate is not None and not r.rate_shown:
            rate += ' (계산)'
        rows.append([name, won(r.sale_price), f'{r.sale_conf:.2f}', won(r.original_price), f'{r.original_conf:.2f}',
                     rate, f'{r.rate_conf:.2f}', '통과' if r.verified else '-'])
        details.append((name, r))

    head = ['이미지', '할인가', '확신도', '원가', '확신도', '할인율', '확신도', '검산']
    print('| ' + ' | '.join(head) + ' |')
    print('|' + '---|' * len(head))
    for row in rows:
        print('| ' + ' | '.join(row) + ' |')

    print()
    for name, r in details:
        print(f'## {name}')
        for c in r.candidates:
            extra = f" (첫 OCR: {c.reread!r})" if c.reread else ''
            print(f'  가격 {c.text!r:16} {c.value:>10,} → {c.role:9} {c.reason}{extra}')
            if verbose and c.scores:
                print(f'      점수 {c.scores}')
                print(f'      단서 {c.features}')
        for t in r.rates:
            kind = '상품' if t.is_product else '기타'
            print(f'  할인율 {t.text!r:14} {t.value:>3}% → {kind} {t.reason}')
        print()


if __name__ == '__main__':
    main('-v' in sys.argv)
