"""감지 로그 (B-4)

- detect.log: 감지 결과를 한 줄씩 (시간, 출처, 단계, 쇼핑몰, 금액, 점수와 근거, 중복 여부, 동작, OCR 시간)
  같은 화면이라 OCR을 건너뛴 회차처럼 자주 생기는 일은 DEBUG로 파일에만 남긴다.
- 콘솔: 단계가 바뀌었거나 동작(팝업, 서버 기록)이 있을 때만 출력한다. 3초마다 같은 줄이 쌓이지 않게
- ocr_samples.jsonl (save_ocr_text가 true일 때만): C-1 쇼핑 화면 분류 모델의 학습 데이터
  · 상품 화면과 쇼핑 아님만 저장한다. 결제 화면은 이름/주소/전화번호가 많아 저장하지 않는다
  · 저장 전에 이름, 전화번호, 주소, 카드번호, 이메일 패턴을 가린다 (mask_private)
- 캡처 이미지는 어디에도 저장하지 않는다.
"""
import json
import logging
import os
import re
import threading
import time
from logging.handlers import RotatingFileHandler

from . import config
from .detector import stage as stage_mod

DESKTOP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 개인정보 마스킹 ────────────────────────────────────────────
# 순서가 중요하다: 카드번호(긴 숫자)를 전화번호보다 먼저 가린다
_PROVINCES = ('서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|'
              '충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|강원도|경기도|제주도|전북특별자치도|강원특별자치도')
MASKS = [
    ('[카드번호]', re.compile(r'(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{3,4}(?!\d)')),
    ('[카드번호]', re.compile(r'(?<!\d)\d{4}[\s\-]?[\d*]{2,4}\*{2,}[\d*\s\-]*\d{0,4}')),          # 1234-56**-****-3456
    ('[전화번호]', re.compile(r'(?<!\d)01[016789][\s\-.]?\d{3,4}[\s\-.]?\d{4}(?!\d)')),
    ('[전화번호]', re.compile(r'(?<!\d)0(2|[3-6]\d)[\s\-.]\d{3,4}[\s\-.]\d{4}(?!\d)')),
    ('[이메일]', re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+')),
    # 주소: '서울특별시 강남구 테헤란로 123, 4층', '서울 성동구 아차산로13길 11' → 시/도부터 번지까지
    ('[주소]', re.compile(r'(' + _PROVINCES + r')(특별시|광역시|특별자치시|특별자치도|시|도)?\s*'
                          r'[가-힣]+(시|군|구)(\s*[가-힣]+(구|시))?\s*[가-힣\d]+(로|길|동|읍|면|리)(\s*\d+(-\d+)?(번길)?)*'
                          r'(\s*,?\s*\d+(층|호|동))*')),
    # 이름: 라벨 바로 뒤의 한글 2~4자 ('받는 분 김무신', '이름: 홍길동'). 라벨은 남기고 이름만 가린다
    # 라벨 뒤가 '정보', '입력' 같은 화면 글자면 이름이 아니다 ('구매자정보', '받는 분 정보 입력')
    (r'\g<1>[이름]', re.compile(r'((?:이름|성명|받는\s?분|받는\s?사람|수령인|주문자|구매자|예금주|보내는\s?분)\s*[:：]?\s*)'
                               r'(?!(?:정보|입력|변경|선택|확인|동일|주소|연락처|이름|성명|추가|등록|수정)(?![가-힣]))'
                               r'[가-힣]{2,4}(?![가-힣])')),
    ('[이름]님', re.compile(r'(?<![가-힣])[가-힣]{2,4}\s?님(?![가-힣])')),
]


def mask_private(text):
    """이름, 전화번호, 주소, 카드번호, 이메일 패턴을 [이름] 등으로 바꾼다 (완벽하지 않으므로 결제 화면은 아예 저장하지 않는다)"""
    for repl, pattern in MASKS:
        text = pattern.sub(repl, text)
    return text


# ── 로그 ───────────────────────────────────────────────────────

def _won(v):
    return f'{int(v):,}원' if v else '금액 모름'


class DetectLog:
    def __init__(self, log_dir=None, console=True, save_ocr_text=False, clock=time.time):
        self.dir = log_dir or os.path.join(DESKTOP_DIR, config.LOG_DIR)
        os.makedirs(self.dir, exist_ok=True)
        self.console = console
        self.save_ocr_text = save_ocr_text
        self.clock = clock
        self._last_console = None        # 콘솔에 마지막으로 찍은 (출처, 단계, 쇼핑몰, 금액, 중복)
        self._lock = threading.Lock()
        self.logger = logging.getLogger(f'impulse_guard.detect.{id(self)}')
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(os.path.join(self.dir, config.LOG_FILE), maxBytes=config.LOG_MAX_BYTES,
                                           backupCount=config.LOG_BACKUPS, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
        self.logger.addHandler(self.handler)

    def close(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()

    def event(self, source, analysis=None, dup='new', action='', ocr_sec=None, note=''):
        """감지 결과 한 줄. analysis: main.Analysis (없으면 쇼핑 아님)

        source: auto / f4, dup: new / same / revisit / wait(차단 안내 재표시 대기), action: popup / blocked / ''
        돌려주는 값: 기록한 한 줄 (테스트용)
        """
        st = analysis.stage if analysis is not None and analysis.stage is not None else None
        stage = st.stage if st else stage_mod.NONE
        site = (analysis.page.site if analysis is not None and analysis.page else '') or '-'
        amount = analysis.amount if analysis is not None and analysis.is_shopping else 0
        parts = [source, stage_mod.LABELS[stage], site, _won(amount) if stage != stage_mod.NONE else '-',
                 st.evidence() if st else '점수 0', dup]
        if action:
            parts.append(f'→ {action}')
        if ocr_sec is not None:
            parts.append(f'OCR {ocr_sec:.1f}초')
        if note:
            parts.append(note)
        line = ' | '.join(parts)
        with self._lock:
            self.logger.info(line)
            key = (source, stage, site, amount, dup if dup != 'same' else 'new')
            if self.console and (action or source == 'f4' or key != self._last_console):
                print(f'[{time.strftime("%H:%M:%S", time.localtime(self.clock()))}] {line}')
            self._last_console = key
        return line

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg, console=True):
        self.logger.info(msg)
        if console and self.console:
            print(msg)

    def sample(self, analysis, text):
        """C-1 학습용 OCR 원문 (save_ocr_text일 때만, 결제 화면 제외, 마스킹)"""
        if not self.save_ocr_text:
            return False
        stage = analysis.stage.stage if analysis is not None and analysis.stage else stage_mod.NONE
        if stage == stage_mod.CHECKOUT:
            return False
        row = {'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.clock())), 'stage': stage,
               'site': (analysis.page.site if analysis.page else '') if analysis else '',
               'is_mall': bool(analysis.shop.is_mall) if analysis else False,
               'text': mask_private(text)}
        with self._lock, open(os.path.join(self.dir, config.OCR_SAMPLE_FILE), 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return True


class NullLog:
    """로그를 쓰지 않을 때 (테스트, 예전 방식 호출). DetectLog와 같은 메서드"""
    save_ocr_text = False

    def event(self, *args, **kwargs):
        return ''

    def debug(self, msg):
        pass

    def info(self, msg, console=True):
        if console:
            print(msg)

    def sample(self, analysis, text):
        return False

    def close(self):
        pass
