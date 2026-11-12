"""차단 팝업 화면 (B-3, tkinter: Python 기본 포함이라 추가 설치 없음)

스레드 규칙
- tkinter는 한 스레드에서만 다뤄야 한다. 창을 만들고 고치는 일은 모두 main 스레드(UiHost.run의 mainloop)가 한다.
- F4 콜백(keyboard 스레드)과 감지 작업 스레드는 창을 직접 만지지 않고 UiHost.post(함수)로 넘긴다.
  main 스레드가 config.POPUP_UI_POLL_MS마다 큐를 비우며 실행한다.
- 버튼의 서버 요청은 UiHost.run_bg()로 작은 스레드에서 하고, 결과만 다시 post로 받아 화면을 바꾼다.
  그래서 서버가 늦어도 창이 멈추지 않는다.

창 두 가지
- ImpulsePopup: 충동구매 팝업 (상품, 이유, 포인트, 버튼 세 개)
- BlockedNotice: 차단 시간 안내 (남은 시간, 확인)

포커스 (B-4)
- F4로 띄운 창은 포커스를 가져온다 (사용자가 방금 키를 눌러 Windows가 대체로 허용한다).
- 자동 감지로 띄운 창(take_focus=False)은 포커스를 억지로 가져가지 않고 작업 표시줄만 깜빡인다.
  사용자가 브라우저에서 치던 Space/Enter가 팝업 버튼을 누르지 않게 하기 위해서다.
- 창이 뜬 뒤 POPUP_INPUT_GUARD_SEC 동안은 버튼 입력을 무시한다 (창이 뜨는 순간의 클릭이 버튼에 들어가는 것 방지).
- 창이 떠 있는 동안 POPUP_KEEP_TOP_MS마다 맨 위로 다시 올린다 (다른 항상 위 창에 가려지는 것 완화).
"""
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont

from . import config
from . import popup_model
from .popup_model import NO_PRICE_TEXT, Outcome, hms

C = config.POPUP_COLORS


def set_dpi_aware():
    """Windows 화면 배율(125%, 150%)에서 글자가 흐려지지 않게. Tk를 만들기 전에 부른다"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def pick_family(root):
    """config.POPUP_FONTS 중 설치된 첫 한글 글꼴. 없으면 tkinter 기본 글꼴"""
    families = set(tkfont.families(root))
    for name in config.POPUP_FONTS:
        if name in families:
            return name
    return tkfont.nametofont('TkDefaultFont', root).actual('family')


class UiHost:
    """숨긴 root 창과 화면 작업 큐. main 스레드에서 만들고 run()한다"""

    def __init__(self, root=None):
        if root is None:
            set_dpi_aware()
            root = tk.Tk()
        self.root = root
        self.root.withdraw()
        self.queue = queue.Queue()
        self._fonts = {}
        self.family = pick_family(root)
        self.scale = max(1.0, root.winfo_fpixels('1i') / 96)   # 화면 배율 (96dpi = 1.0)
        self._stopping = False
        self._after = self.root.after(config.POPUP_UI_POLL_MS, self._poll)

    def px(self, n):
        return int(round(n * self.scale))

    def font(self, size, bold=False, **kw):
        """글꼴 객체. 파이썬 객체가 사라지면 Tk 글꼴도 지워지므로 여기에 모아 둔다"""
        key = (size, bold, tuple(sorted(kw.items())))
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(self.root, family=self.family, size=size,
                                           weight='bold' if bold else 'normal', **kw)
        return self._fonts[key]

    # ── 스레드 사이 연결 ───────────────────────────────────
    def post(self, fn):
        """다른 스레드에서 화면 작업을 넘긴다 (main 스레드가 실행)"""
        self.queue.put(fn)

    def run_bg(self, work, done):
        """work()를 작은 스레드에서 실행하고, 결과(또는 예외)를 main 스레드의 done(결과)로 넘긴다"""
        def target():
            try:
                result = work()
            except Exception as e:          # 버튼 처리 중 예상 못 한 오류도 화면에 알린다
                result = e
            self.post(lambda: done(result))
        threading.Thread(target=target, daemon=True).start()

    def process(self):
        """큐에 쌓인 화면 작업을 지금 실행한다 (테스트에서도 부른다)"""
        while True:
            try:
                fn = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as e:
                print(f'!!! 팝업 처리 중 오류: {e}')

    def _poll(self):
        self.process()
        if self._stopping:
            self.root.quit()
            return
        self._after = self.root.after(config.POPUP_UI_POLL_MS, self._poll)

    def run(self):
        self.root.mainloop()

    def stop(self):
        """어느 스레드에서든 부를 수 있다 (Ctrl+C 처리). 다음 poll에서 mainloop를 끝낸다"""
        self._stopping = True

    def close(self):
        """main 스레드: 예약한 poll을 취소한다 (root를 없애기 전에)"""
        self.root.after_cancel(self._after)


def work_area(win=None):
    """주 모니터 작업 영역 (left, top, right, bottom). 작업 표시줄을 뺀 영역. 못 구하면 화면 전체"""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    if win is not None:
        return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()
    return 0, 0, 1920, 1080


class _Window:
    """두 창의 공통: 항상 위, 주 모니터 오른쪽 아래, 흰 카드"""

    title = '충동구매 방지'

    def __init__(self, host, on_closed=None, take_focus=True):
        self.host = host
        self.on_closed = on_closed
        self.take_focus = take_focus
        self.closed = False
        self.screen_rect = None                 # (x0, y0, x1, y1) 화면 좌표. place()가 정한다
        self.opened_at = time.monotonic()
        self._afters = {}                       # 이름 → after 예약 번호 (창을 닫을 때 모두 취소)
        self.width = host.px(config.POPUP_WIDTH)
        self.wrap = self.width - host.px(2 * (16 + 22) + 12)   # 창 여백 + 카드 안쪽 여백 + 테두리, 글자 폭 여유

        self.win = tk.Toplevel(host.root)
        self.win.title(self.title)
        self.win.configure(bg=C['back'])
        self.win.resizable(False, False)
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', self.on_x)
        self.card = tk.Frame(self.win, bg=C['card'], highlightthickness=1,
                             highlightbackground=C['border'], highlightcolor=C['border'])
        self.card.pack(fill='both', expand=True, padx=host.px(16), pady=host.px(16))
        self.schedule('keep_top', config.POPUP_KEEP_TOP_MS, self._keep_top)

    # 예약 작업 (같은 이름은 하나만)
    def schedule(self, name, ms, fn):
        old = self._afters.pop(name, None)
        if old is not None:
            self.win.after_cancel(old)
        self._afters[name] = self.win.after(ms, fn)

    def _keep_top(self):
        """다른 항상 위 창에 가려지지 않게 맨 위로 다시 올린다 (포커스는 건드리지 않음)"""
        if self.closed:
            return
        self.win.attributes('-topmost', True)
        self.win.lift()
        self.schedule('keep_top', config.POPUP_KEEP_TOP_MS, self._keep_top)

    def input_ready(self):
        """창이 뜬 직후의 입력은 무시한다 (사용자가 하던 클릭/키 입력이 버튼에 들어가지 않게)"""
        return time.monotonic() - self.opened_at >= config.POPUP_INPUT_GUARD_SEC

    def _guarded(self, command):
        def run(*_):
            if self.input_ready():
                command()
        return run

    def flash(self):
        """작업 표시줄 버튼을 깜빡여 창이 떴음을 알린다 (Windows만)"""
        try:
            import ctypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [('cbSize', ctypes.c_uint), ('hwnd', ctypes.c_void_p), ('dwFlags', ctypes.c_uint),
                            ('uCount', ctypes.c_uint), ('dwTimeout', ctypes.c_uint)]
            hwnd = int(self.win.wm_frame(), 16)
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x3 | 0xC, 0, 0)   # 창과 작업 표시줄, 앞에 올 때까지
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    # 위젯 만들기 도우미
    def label(self, parent, text, size=11, bold=False, fg=None, bg=None, **kw):
        lb = tk.Label(parent, text=text, font=self.host.font(size, bold, **kw.pop('font_kw', {})),
                      fg=fg or C['text'], bg=bg or C['card'], justify='left', anchor='w', **kw)
        return lb

    def button(self, parent, text, command, primary=True):
        b = tk.Button(parent, text=text, command=self._guarded(command), relief='flat', bd=0, cursor='hand2',
                      font=self.host.font(11, primary),
                      bg=C['primary'] if primary else C['secondary'],
                      fg='#ffffff' if primary else C['secondary_text'],
                      activebackground=C['primary_active'] if primary else C['secondary_active'],
                      activeforeground='#ffffff' if primary else C['secondary_text'],
                      disabledforeground='#ffffff' if primary else '#9ca3af',
                      padx=self.host.px(12), pady=self.host.px(9))
        b.pack(fill='x', pady=(self.host.px(8), 0))
        return b

    def link(self, parent, text, command):
        lb = self.label(parent, text, 10, fg=C['sub'], cursor='hand2', font_kw={'underline': 1})
        lb.configure(anchor='center', justify='center')
        lb.bind('<Button-1>', self._guarded(command))
        lb.pack(fill='x', pady=(self.host.px(12), 0))
        return lb

    def position(self, h):
        """창 왼쪽 위 좌표: 주 모니터 작업 영역(작업 표시줄 제외)의 오른쪽 아래"""
        left, top, right, bottom = work_area(self.win)
        m, bar = self.host.px(config.POPUP_EDGE_MARGIN), self.host.px(config.POPUP_TITLEBAR)
        x = max(left, right - self.width - m)
        y = max(top, bottom - h - bar - m)
        return x, y

    def place(self):
        """주 모니터 오른쪽 아래에 놓고 앞으로 가져온다. 내용이 바뀌면 다시 부른다"""
        self.win.update_idletasks()
        h = self.win.winfo_reqheight()
        x, y = self.position(h)
        self.win.geometry(f'{self.width}x{h}+{x}+{y}')
        self.win.deiconify()
        self.win.lift()
        self.win.attributes('-topmost', True)
        self._remember_rect()
        if not self.take_focus:
            self.flash()
            return
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    def resize(self):
        """내용이 바뀐 뒤 높이를 맞춘다. 아래쪽 끝은 그대로 두고 위로 늘어난다 (포커스는 그대로)"""
        self.win.update_idletasks()
        h = self.win.winfo_reqheight()
        x, y = self.position(h)
        self.win.geometry(f'{self.width}x{h}+{x}+{y}')
        self._remember_rect()

    def _remember_rect(self):
        """main 스레드: 화면에서 창이 차지하는 영역 (제목 표시줄과 그림자 여유 포함). 자동 감지가 이 영역을 빼고 OCR한다"""
        try:
            self.win.update_idletasks()
            m = self.host.px(config.POPUP_MASK_MARGIN)
            x, y = self.win.winfo_rootx(), self.win.winfo_rooty()
            self.screen_rect = (x - m, y - m - self.host.px(config.POPUP_TITLEBAR), x + self.win.winfo_width() + m,
                                y + self.win.winfo_height() + m)
        except tk.TclError:
            pass

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        for after_id in self._afters.values():   # 창이 사라진 뒤 예약 작업이 불리지 않게
            self.win.after_cancel(after_id)
        self._afters.clear()
        self.win.destroy()
        if self.on_closed:
            self.on_closed()

    def on_x(self):
        self.destroy()


class ImpulsePopup(_Window):
    """충동구매 팝업. view: popup_model.ImpulseView, actions: popup_model.Actions"""

    title = '충동구매 알림'

    def __init__(self, host, view, actions, on_closed=None, link_url='', take_focus=True):
        super().__init__(host, on_closed, take_focus)
        self.view = view
        self.actions = actions
        self.link_url = link_url
        self.busy = False
        self.done = False
        self.applied_seq = 0                    # 마지막으로 반영한 분석 회차 번호 (fill_price)
        px = host.px

        # ── 묻는 화면 ──
        self.ask = tk.Frame(self.card, bg=C['card'])
        self.ask.pack(fill='both', padx=px(22), pady=px(20))
        self.badge_label = None
        if view.risk_badge:
            # C-2 위험 단계: 색 배지 + 제목 색 (높음 빨강, 보통 주황, 낮음 파랑). 위험도가 없으면 예전 모양 그대로
            self.badge_label = self.label(self.ask, ' ' + view.risk_badge + ' ', 9, True,
                                          fg=view.title_color, bg=view.badge_bg)
            self.badge_label.pack(anchor='w', pady=(0, px(6)))
        self.title_label = self.label(self.ask, view.title, 16 if view.risk_level == 'high' else 15, True,
                                      fg=view.title_color or None)
        self.title_label.pack(fill='x')
        self.label(self.ask, view.subtitle, 10, fg=C['sub'], wraplength=self.wrap).pack(fill='x', pady=(px(2), 0))

        item = tk.Frame(self.ask, bg=C['item'])
        item.pack(fill='x', pady=(px(14), 0))
        inner = tk.Frame(item, bg=C['item'])
        inner.pack(fill='x', padx=px(12), pady=px(10))
        self.name_label = self.label(inner, view.item_name, 11, bg=C['item'], wraplength=self.wrap - px(24))
        self.name_label.pack(fill='x')
        row = tk.Frame(inner, bg=C['item'])
        row.pack(fill='x', pady=(px(4), 0))
        if view.price > 0:
            if view.rate_text:
                self.label(row, view.rate_text, 15, True, fg=C['danger'], bg=C['item']).pack(side='left', padx=(0, px(6)))
            self.price_label = self.label(row, view.price_text, 15, True, bg=C['item'])
        else:
            self.price_label = self.label(row, view.price_text or NO_PRICE_TEXT, 12, True, fg=C['sub'], bg=C['item'])
        self.price_label.pack(side='left')
        if view.orig_text:
            self.label(row, view.orig_text, 10, fg=C['sub'], bg=C['item'],
                       font_kw={'overstrike': 1}).pack(side='left', padx=(px(8), 0), pady=(px(4), 0))

        self.reason_labels = []
        for text in view.reasons:
            lb = self.label(self.ask, '• ' + text, 10, fg=C['danger'], wraplength=self.wrap)
            lb.pack(fill='x', pady=(px(10) if not self.reason_labels else px(2), 0))
            lb.reason = text
            self.reason_labels.append(lb)
        self.point_label = self.label(self.ask, view.point_text, 10, True, fg=C['point'], wraplength=self.wrap)
        self.point_label.pack(fill='x', pady=(px(10), 0))
        self.msg = self.label(self.ask, '', 10, fg=C['danger'], wraplength=self.wrap)
        self.msg.pack(fill='x', pady=(px(4), 0))

        self.hold_btn = self.button(self.ask, '조금 더 생각하기\n24시간 담아두기', self.on_hold, primary=True)
        self.giveup_btn = self.button(self.ask, '안 살래요', self.on_giveup, primary=False)
        self.buy_link = self.link(self.ask, '그래도 구매할래요', self.on_buy)
        self._set_busy(False)

        # ── 결과 화면 (담아두기, 안 살래요 뒤) ──
        self.result = tk.Frame(self.card, bg=C['card'])
        self.result_title = self.label(self.result, '', 15, True)
        self.result_title.pack(fill='x')
        self.result_text = self.label(self.result, '', 11, wraplength=self.wrap)
        self.result_text.pack(fill='x', pady=(px(6), px(4)))
        self.close_btn = self.button(self.result, '닫기', self.destroy, primary=True)
        self.timemachine_link = None

        self.place()

    # ── 결제 금액 채우기 (B-5) ──
    def fill_price(self, price, seq=None):
        """main 스레드: '결제 금액 확인 중' 팝업에 읽은 금액을 채운다. 채웠으면 True
        상태는 '확인 중 → 금액'으로만 바뀐다 (view.pending일 때만). seq(분석 회차 번호)가 이미 반영한 회차보다
        오래됐으면 무시한다 (늦게 도착한 결과가 최신 결과를 덮어쓰지 않게)"""
        if seq is not None:
            if seq <= self.applied_seq:
                return False
            self.applied_seq = seq
        if self.closed or self.done or self.busy or not popup_model.fill_price(self.view, price):
            return False
        self.price_label.configure(text=self.view.price_text, font=self.host.font(15, True), fg=C['text'])
        for lb in [lb for lb in self.reason_labels if getattr(lb, 'reason', '') == popup_model.CHECKOUT_PENDING_REASON]:
            lb.destroy()
            self.reason_labels.remove(lb)
        self.point_label.configure(text=self.view.point_text)
        self._set_busy(False)
        self.resize()
        return True

    # ── 버튼 ──
    def _set_busy(self, on):
        self.busy = on
        self.hold_btn.configure(state='normal' if (not on and self.view.can_hold) else 'disabled',
                                bg=C['primary'] if self.view.can_hold else C['primary_off'])
        self.giveup_btn.configure(state='disabled' if on else 'normal')

    def _start(self, work, wait_text):
        if self.busy or self.done or self.closed:
            return
        self._set_busy(True)
        self.msg.configure(text=wait_text, fg=C['sub'])
        self.host.run_bg(work, self._finish)

    def _finish(self, out):
        if isinstance(out, Exception):
            out = Outcome(error=f'처리 중 오류가 났어요: {out}', console=f'[팝업] 오류: {out}')
        if out.console:
            print(out.console)
        if self.closed:
            return
        if out.close:
            self.destroy()
        elif out.error:
            self._set_busy(False)
            self.msg.configure(text=out.error, fg=C['danger'])
        else:
            self.show_result(out)

    def on_hold(self):
        self._start(self.actions.hold, '담는 중…')

    def on_giveup(self):
        self._start(self.actions.giveup, '기록하는 중…')

    def on_buy(self):
        """기록은 뒤에서 보내고 창은 바로 닫는다 (구매를 막지 않는다)"""
        self._close_with(self.actions.buy)

    def on_x(self):
        """창의 X: 결과 화면에서는 그냥 닫고, 묻는 화면에서는 close로 기록한다 (포인트 없음)"""
        if self.done:
            self.destroy()
        elif not self.busy:
            self._close_with(self.actions.close)

    def _close_with(self, work):
        if self.busy or self.done or self.closed:
            return
        self.busy = True
        self.host.run_bg(work, self._log_only)
        self.destroy()

    @staticmethod
    def _log_only(out):
        """창을 닫은 뒤 도착한 기록 결과는 콘솔에만 남긴다"""
        if isinstance(out, Exception):
            print(f'[팝업] 기록 오류: {out}')
        elif out.console:
            print(out.console)

    def show_result(self, out):
        self.done = True
        self.ask.pack_forget()
        self.result.pack(fill='both', padx=self.host.px(22), pady=self.host.px(20))
        self.result_title.configure(text=out.title)
        self.result_text.configure(text=out.text)
        if out.show_link and self.link_url and self.timemachine_link is None:
            self.timemachine_link = self.link(self.result, '타임머신 보기', lambda: webbrowser.open(self.link_url))
        self.place()
        if self.take_focus:
            self.close_btn.focus_set()


class BlockedNotice(_Window):
    """차단 시간 안내. view: popup_model.BlockedView"""

    title = '쇼핑 차단 중'

    def __init__(self, host, view, on_closed=None, clock=time.monotonic, take_focus=True):
        super().__init__(host, on_closed, take_focus)
        self.view = view
        self.clock = clock
        self.start = clock()
        px = host.px

        body = tk.Frame(self.card, bg=C['card'])
        body.pack(fill='both', padx=px(22), pady=px(20))
        self.label(body, '지금은 쇼핑 차단 시간이에요', 15, True).pack(fill='x')
        self.label(body, '스스로 정한 차단 시간이 끝날 때까지 쇼핑을 쉬어요.', 10, fg=C['sub'],
                   wraplength=self.wrap).pack(fill='x', pady=(px(2), 0))
        if view.item_name:
            self.label(body, f'감지한 상품: {view.item_name}', 10, fg=C['sub'],
                       wraplength=self.wrap).pack(fill='x', pady=(px(8), 0))
        self.label(body, '남은 시간', 10, True, fg=C['sub']).pack(fill='x', pady=(px(16), 0))
        self.time_label = self.label(body, '', 24, True, fg=C['primary'])
        self.time_label.pack(fill='x')
        self.ok_btn = self.button(body, '확인', self.destroy, primary=True)
        self.ok_btn.pack_configure(pady=(px(16), 0))
        self.tick()
        self.place()
        if take_focus:
            self.ok_btn.focus_set()

    def remain(self):
        return max(0, int(self.view.remain_sec - (self.clock() - self.start)))

    def tick(self):
        """1초마다 남은 시간을 고친다"""
        if self.closed:
            return
        if self.view.remain_sec <= 0:
            self.time_label.configure(text='확인하지 못했어요', font=self.host.font(14, True))
            return
        left = self.remain()
        self.time_label.configure(text=hms(left) if left > 0 else '차단 시간이 끝났어요')
        if left > 0:
            self.schedule('tick', 1000, self.tick)   # 이미 예약된 tick은 취소하고 하나만 남긴다
