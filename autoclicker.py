import ctypes
import ctypes.wintypes as wt
import math
import random
import sys
import threading
import time
import tkinter as tk

if sys.platform != "win32":
    sys.exit("This app is Windows-only.")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
winmm = ctypes.windll.winmm

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetParent.argtypes = [wt.HWND]
user32.GetParent.restype = wt.HWND

# ----------------------------------------------------------------------------
# Input injection (SendInput, batched)
# ----------------------------------------------------------------------------
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT

_DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
_UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
_cache = {}


def send_clicks(buttons):
    key = tuple(buttons)
    arr = _cache.get(key)
    if arr is None:
        arr = (INPUT * (len(key) * 2))()
        for i, b in enumerate(key):
            arr[i * 2].u.mi.dwFlags = _DOWN[b]
            arr[i * 2 + 1].u.mi.dwFlags = _UP[b]
        if len(_cache) < 4096:
            _cache[key] = arr
    user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))


# ----------------------------------------------------------------------------
# Click engine
# ----------------------------------------------------------------------------
MAX_CPS = 10000
MAX_BATCH = 64


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.thread = None
        self.stop_evt = threading.Event()
        self.count = 0
        self.phase = "idle"
        self.extra_delay = 0.0

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, extra_delay=0.0):
        if self.running:
            return
        self.count = 0
        self.extra_delay = extra_delay
        self.phase = "delay"
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(self.stop_evt,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()

    def _run(self, stop):
        cfg = self.cfg
        clock = time.perf_counter
        try:
            delay = max(cfg["delay"], self.extra_delay)
            if delay > 0 and stop.wait(delay):
                return
            self.phase = "run"
            flip = False
            next_t = clock()
            while not stop.is_set():
                base = 1.0 / cfg["cps"]
                now = clock()
                if next_t - now > base * 2 + 0.01:
                    next_t = now + base
                gap = next_t - now
                if gap > 0:
                    if gap > 0.003:
                        stop.wait(min(gap - 0.002, 0.05))
                    continue

                n = min(MAX_BATCH, 1 + int(-gap / base))
                limit = cfg["limit"]
                if limit:
                    n = min(n, limit - self.count)
                    if n <= 0:
                        break

                mode = cfg["button"]
                if mode == "alt":
                    buttons = []
                    for _ in range(n):
                        buttons.append("right" if flip else "left")
                        flip = not flip
                else:
                    buttons = [mode] * n

                fixed = cfg["fixed"]
                if fixed:
                    user32.SetCursorPos(fixed[0], fixed[1])
                send_clicks(buttons)
                self.count += n
                if limit and self.count >= limit:
                    break

                step = base * n
                jit = cfg["jitter"]
                if jit:
                    step *= random.uniform(1 - jit, 1 + jit)
                next_t += step
                if clock() - next_t > 0.1:
                    next_t = clock()
        finally:
            self.phase = "idle"


# ----------------------------------------------------------------------------
# Theme + helpers
# ----------------------------------------------------------------------------
BG, CARD, BORDER = "#0a0a0a", "#131313", "#232323"
FG, MUTED, DIM = "#f4f4f4", "#8c8c8c", "#5c5c5c"
FIELD, HOVER = "#1b1b1b", "#272727"
GREEN, AMBER = "#4ade80", "#fbbf24"
SCALE = 1.0


def px(v):
    return int(round(v * SCALE))


def font(size, weight="normal"):
    return ("Segoe UI", size, weight)


def fmt(v):
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:.1f}".rstrip("0").rstrip(".")


def num(text, default, lo, hi):
    try:
        v = float(str(text).strip().replace(",", "."))
    except ValueError:
        return default
    if v != v or abs(v) == float("inf"):
        return default
    return min(hi, max(lo, v))


_VK_NAMES = {
    0x03: "Break", 0x04: "Mouse Mid", 0x05: "Mouse X1", 0x06: "Mouse X2",
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps",
    0x1B: "Esc", 0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End",
    0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete", 0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -",
    0x6E: "Num .", 0x6F: "Num /", 0xA0: "L Shift", 0xA1: "R Shift",
    0xA2: "L Ctrl", 0xA3: "R Ctrl", 0xA4: "L Alt", 0xA5: "R Alt",
    0xC0: "`", 0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
    0xBF: "/", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}


def vk_name(vk):
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return _VK_NAMES.get(vk, f"Key {vk:#04x}")


def card(parent, **pack):
    outer = tk.Frame(parent, bg=CARD, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=BORDER)
    outer.pack(fill="x", **pack)
    inner = tk.Frame(outer, bg=CARD)
    inner.pack(fill="x", padx=px(16), pady=px(14))
    return inner


def heading(parent, text):
    tk.Label(parent, text=text, bg=CARD, fg=DIM, font=font(8, "bold")).pack(
        anchor="w", pady=(0, px(8)))


def entry(parent, var, width):
    return tk.Entry(parent, textvariable=var, width=width, justify="center",
                    font=font(10), bg=FIELD, fg=FG, insertbackground=FG,
                    relief="flat", highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor="#ffffff", selectbackground="#3a3a3a",
                    selectforeground=FG)


class Btn(tk.Label):
    def __init__(self, parent, text, command, bg=FIELD, fg=FG, hover=HOVER,
                 size=9, padx=12, pady=6):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font(size, "bold"),
                         padx=px(padx), pady=px(pady), cursor="hand2")
        self.base, self.over = bg, hover
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self.config(bg=self.over))
        self.bind("<Leave>", lambda e: self.config(bg=self.base))

    def style(self, bg, fg, hover):
        self.base, self.over = bg, hover
        self.config(bg=bg, fg=fg)


class Segmented(tk.Frame):
    def __init__(self, parent, options, value, command=None, bg=CARD, size=9):
        super().__init__(parent, bg=bg)
        self.command, self.value, self.items = command, value, {}
        last = len(options) - 1
        for i, (text, val) in enumerate(options):
            lb = tk.Label(self, text=text, font=font(size, "bold"),
                          pady=px(6), padx=px(10), cursor="hand2")
            lb.grid(row=0, column=i, sticky="ew", padx=(0, px(4)) if i < last else 0)
            self.columnconfigure(i, weight=1, uniform="seg")
            lb.bind("<Button-1>", lambda e, v=val: self.set(v, fire=True))
            lb.bind("<Enter>", lambda e, v=val: self._paint(v, True))
            lb.bind("<Leave>", lambda e, v=val: self._paint(v, False))
            self.items[val] = lb
        self.set(value)

    def _paint(self, val, hover=False):
        lb = self.items[val]
        if val == self.value:
            lb.config(bg="#ffffff", fg="#000000")
        else:
            lb.config(bg=HOVER if hover else FIELD, fg=FG if hover else MUTED)

    def set(self, val, fire=False):
        self.value = val
        for v in self.items:
            self._paint(v)
        if fire and self.command:
            self.command(val)


class Toggle(tk.Canvas):
    def __init__(self, parent, value=False, command=None, bg=CARD):
        self.w, self.h = px(40), px(22)
        super().__init__(parent, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, cursor="hand2")
        self.value, self.command = value, command
        self.bind("<Button-1>", self._click)
        self.draw()

    def _click(self, _):
        self.value = not self.value
        self.draw()
        if self.command:
            self.command(self.value)

    def draw(self):
        self.delete("all")
        w, h = self.w, self.h
        fill = "#ffffff" if self.value else "#2a2a2a"
        self.create_oval(0, 0, h, h, fill=fill, outline=fill)
        self.create_oval(w - h - 1, 0, w - 1, h, fill=fill, outline=fill)
        self.create_rectangle(h // 2, 0, w - h // 2, h, fill=fill, outline=fill)
        pad = px(3)
        d = h - 2 * pad
        x = w - 1 - pad - d if self.value else pad
        self.create_oval(x, pad, x + d, pad + d,
                         fill="#000000" if self.value else "#8c8c8c", outline="")


class Slider(tk.Canvas):
    def __init__(self, parent, command, bg=CARD):
        super().__init__(parent, height=px(24), bg=bg, highlightthickness=0, cursor="hand2")
        self.command, self.pos = command, 0.0
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def set(self, pos):
        self.pos = min(1.0, max(0.0, pos))
        self.draw()

    def _drag(self, e):
        pad = px(10)
        span = max(1, self.winfo_width() - 2 * pad)
        self.pos = min(1.0, max(0.0, (e.x - pad) / span))
        self.draw()
        self.command(self.pos)

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        pad, cy = px(10), h // 2
        x = pad + self.pos * (w - 2 * pad)
        self.create_line(pad, cy, w - pad, cy, fill="#2a2a2a", width=px(4), capstyle="round")
        self.create_line(pad, cy, x, cy, fill="#ffffff", width=px(4), capstyle="round")
        r = px(8)
        self.create_oval(x - r, cy - r, x + r, cy + r, fill="#ffffff", outline="")


def dark_titlebar(root):
    try:
        hwnd = user32.GetParent(root.winfo_id())
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        cap, txt = ctypes.c_int(0x000A0A0A), ctypes.c_int(0x00FFFFFF)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class App:
    PRESETS = (5, 10, 25, 50, 100, 250, 500, 1000)

    def __init__(self):
        global SCALE
        self.root = root = tk.Tk()
        SCALE = root.winfo_fpixels("1i") / 96.0
        root.withdraw()
        root.title("Raven Clicker")
        root.configure(bg=BG)
        root.resizable(False, False)
        winmm.timeBeginPeriod(1)

        self.cfg = {"cps": 20.0, "button": "left", "jitter": 0.0,
                    "limit": 0, "delay": 0.0, "fixed": None}
        self.engine = Engine(self.cfg)
        self.hotkey = 0x75  # F6
        self.hk_mode = "toggle"
        self.fixed = None
        self.capturing = False
        self._sliding = False
        self._was_down = False
        self._state = None
        self._stat_t, self._stat_c = time.perf_counter(), 0

        self._build()
        self._wire()

        root.update_idletasks()
        w, h = px(760), root.winfo_reqheight()
        x = (root.winfo_screenwidth() - w) // 2
        y = max(0, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"{w}x{h}+{x}+{y}")
        dark_titlebar(root)
        root.deiconify()
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_state("idle")
        self._tick()

    # ---- layout -----------------------------------------------------------
    def row(self, parent, text):
        r = tk.Frame(parent, bg=CARD)
        r.pack(fill="x", pady=px(5))
        tk.Label(r, text=text, bg=CARD, fg=FG, font=font(9)).pack(side="left")
        right = tk.Frame(r, bg=CARD)
        right.pack(side="right")
        return right

    def _build(self):
        root, pad = self.root, px(16)

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=pad, pady=(pad, px(12)))
        tk.Label(head, text="RAVEN CLICKER", bg=BG, fg=FG, font=font(12, "bold")).pack(side="left")
        self.status = tk.Label(head, text="IDLE", bg=FIELD, fg=MUTED, font=font(8, "bold"),
                               padx=px(12), pady=px(4))
        self.status.pack(side="right")

        body = tk.Frame(root, bg=BG)
        body.pack(fill="x", padx=pad)
        body.columnconfigure(0, weight=1, uniform="cols")
        body.columnconfigure(1, weight=1, uniform="cols")
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="new", padx=(0, px(8)))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="new", padx=(px(8), 0))
        gap = (0, px(12))

        # speed
        c = card(left, pady=gap)
        heading(c, "SPEED")
        big = tk.Frame(c, bg=CARD)
        big.pack(pady=(px(2), 0))
        self.cps_var = tk.StringVar(value="20")
        tk.Entry(big, textvariable=self.cps_var, width=5, justify="right",
                 font=font(34, "bold"), bg=CARD, fg=FG, insertbackground=FG,
                 relief="flat", highlightthickness=0, selectbackground="#333333",
                 selectforeground=FG).pack(side="left")
        tk.Label(big, text="CPS", bg=CARD, fg=MUTED, font=font(14, "bold")).pack(
            side="left", padx=(px(6), 0), pady=(px(16), 0))
        self.slider = Slider(c, self._on_slide)
        self.slider.pack(fill="x", pady=(px(6), px(8)))
        chips = tk.Frame(c, bg=CARD)
        chips.pack(fill="x")
        for i, v in enumerate(self.PRESETS):
            chips.columnconfigure(i, weight=1, uniform="chip")
            Btn(chips, str(v), lambda v=v: self.cps_var.set(str(v)),
                size=8, padx=0, pady=5).grid(row=0, column=i, sticky="ew",
                                             padx=(0, px(3)) if i < len(self.PRESETS) - 1 else 0)

        # button
        c = card(left, pady=gap)
        heading(c, "MOUSE BUTTON")
        self.btn_seg = Segmented(c, [("Left", "left"), ("Right", "right"),
                                     ("Middle", "middle"), ("Alternate", "alt")],
                                 "left", self._on_button)
        self.btn_seg.pack(fill="x")
        self.hint = tk.Label(c, text="", bg=CARD, fg=MUTED, font=font(8), anchor="nw",
                             justify="left", wraplength=px(310), height=2)
        self.hint.pack(fill="x", pady=(px(8), 0))
        self._on_button("left")

        # options
        c = card(right, pady=gap)
        heading(c, "OPTIONS")
        r = self.row(c, "Speed variation")
        tk.Label(r, text="%", bg=CARD, fg=MUTED, font=font(9)).pack(side="right", padx=(px(6), 0))
        self.jit_var = tk.StringVar(value="0")
        entry(r, self.jit_var, 5).pack(side="right", ipady=px(3))

        r = self.row(c, "Stop after")
        self.limit_tg = Toggle(r, False, lambda v: self.read_cfg())
        self.limit_tg.pack(side="right", padx=(px(10), 0))
        tk.Label(r, text="clicks", bg=CARD, fg=MUTED, font=font(9)).pack(side="right", padx=(px(6), 0))
        self.limit_var = tk.StringVar(value="100")
        entry(r, self.limit_var, 7).pack(side="right", ipady=px(3))

        r = self.row(c, "Start delay")
        tk.Label(r, text="sec", bg=CARD, fg=MUTED, font=font(9)).pack(side="right", padx=(px(6), 0))
        self.delay_var = tk.StringVar(value="0")
        entry(r, self.delay_var, 5).pack(side="right", ipady=px(3))

        r = self.row(c, "Always on top")
        Toggle(r, False, lambda v: self.root.attributes("-topmost", v)).pack()

        # position + hotkey
        c = card(right, pady=gap)
        heading(c, "POSITION & HOTKEY")
        r = self.row(c, "Click at")
        self.pos_seg = Segmented(r, [("Cursor", "cursor"), ("Fixed", "fixed")],
                                 "cursor", lambda v: self._sync_pos())
        self.pos_seg.pack()

        r = self.row(c, "Fixed spot")
        self.pick_btn = Btn(r, "Pick spot", self._pick_pos, size=8, padx=10, pady=5)
        self.pick_btn.pack(side="right")
        self.xy_lbl = tk.Label(r, text="not set", bg=CARD, fg=MUTED, font=font(9))
        self.xy_lbl.pack(side="right", padx=(0, px(8)))

        r = self.row(c, "Hotkey")
        self.hk_btn = Btn(r, vk_name(self.hotkey), self._begin_capture, size=9, padx=16, pady=5)
        self.hk_btn.pack()

        r = self.row(c, "Hotkey mode")
        self.hk_seg = Segmented(r, [("Toggle", "toggle"), ("Hold", "hold")], "toggle",
                                self._on_hk_mode)
        self.hk_seg.pack()

        # footer
        foot = tk.Frame(root, bg=BG)
        foot.pack(fill="x", padx=pad, pady=(px(2), px(8)))
        self.go = Btn(foot, "START", self._on_go, bg="#ffffff", fg="#000000",
                      hover="#d6d6d6", size=12, pady=12)
        self.go.pack(fill="x")

        stats = tk.Frame(root, bg=BG)
        stats.pack(fill="x", padx=pad, pady=(0, px(14)))
        self.clicks_lbl = tk.Label(stats, text="Clicks  0", bg=BG, fg=MUTED, font=font(9))
        self.clicks_lbl.pack(side="left")
        self.live_lbl = tk.Label(stats, text="Live  0 CPS", bg=BG, fg=MUTED, font=font(9))
        self.live_lbl.pack(side="right")
        tk.Label(stats, text="Esc = emergency stop", bg=BG, fg=DIM, font=font(8)).pack(
            side="left", expand=True)

    def _wire(self):
        self.cps_var.trace_add("write", self._on_cps)
        for v in (self.jit_var, self.delay_var, self.limit_var):
            v.trace_add("write", self.read_cfg)
        self.read_cfg()
        self._on_cps()

    # ---- settings ---------------------------------------------------------
    def read_cfg(self, *_):
        c = self.cfg
        c["cps"] = num(self.cps_var.get(), c["cps"], 0.1, MAX_CPS)
        c["jitter"] = num(self.jit_var.get(), 0, 0, 90) / 100
        c["delay"] = num(self.delay_var.get(), 0, 0, 3600)
        c["limit"] = int(num(self.limit_var.get(), 100, 1, 10 ** 9)) if self.limit_tg.value else 0

    def _on_cps(self, *_):
        self.read_cfg()
        if not self._sliding:
            self.slider.set(math.log10(max(self.cfg["cps"], 1.0)) / 3)

    def _on_slide(self, pos):
        v = 10 ** (3 * pos)
        v = round(v, 1) if v < 10 else round(v)
        self._sliding = True
        self.cps_var.set(fmt(v))
        self._sliding = False

    def _on_button(self, val):
        self.cfg["button"] = val
        self.hint.config(text={
            "left": "Every click goes to the left button.",
            "right": "Every click goes to the right button.",
            "middle": "Every click goes to the middle button.",
            "alt": "Left, right, left, right on every click. CPS counts both, "
                   "so 20 CPS = 10 left + 10 right per second.",
        }[val])

    def _on_hk_mode(self, val):
        self.hk_mode = val

    def _sync_pos(self):
        use = self.pos_seg.value == "fixed" and self.fixed
        self.cfg["fixed"] = self.fixed if use else None
        self.xy_lbl.config(text=f"{self.fixed[0]}, {self.fixed[1]}" if self.fixed else "not set")

    def _pick_pos(self):
        def step(n):
            if n == 0:
                pt = wt.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                self.fixed = (pt.x, pt.y)
                self.pos_seg.set("fixed")
                self.pick_btn.config(text="Pick spot")
                self._sync_pos()
                return
            self.pick_btn.config(text=f"Move mouse  {n}")
            self.root.after(1000, step, n - 1)
        step(3)

    def _begin_capture(self):
        self.capturing = True
        self.hk_btn.config(text="Press a key")

    # ---- run control ------------------------------------------------------
    def _begin(self, extra=0.0):
        self.read_cfg()
        self.engine.start(extra)

    def _toggle(self, extra=0.0):
        if self.engine.running:
            self.engine.stop()
        else:
            self._begin(extra)

    def _on_go(self):
        # 2s grace so the cursor isn't sitting on this button when clicks start
        self._toggle(extra=2.0)

    def _apply_state(self, state):
        self._state = state
        key = vk_name(self.hotkey)
        if state == "idle":
            self.status.config(text="IDLE", fg=MUTED, bg=FIELD)
            self.go.style("#ffffff", "#000000", "#d6d6d6")
            self.go.config(text=f"START   ({key})")
        else:
            on = state == "running"
            self.status.config(text="RUNNING" if on else "STARTING",
                               fg=GREEN if on else AMBER,
                               bg="#10281a" if on else "#2b2410")
            self.go.style("#1f1f1f", "#ff6b6b", "#2a2a2a")
            self.go.config(text=f"STOP   ({key})")

    # ---- polling loop -----------------------------------------------------
    def _tick(self):
        try:
            self._poll()
        finally:
            self.root.after(8, self._tick)

    def _poll(self):
        eng = self.engine

        if self.capturing:
            for vk in range(3, 255):
                if vk in (0x10, 0x11, 0x12):
                    continue
                if user32.GetAsyncKeyState(vk) & 0x8000:
                    if vk != 0x1B:
                        self.hotkey = vk
                    self.capturing = False
                    self.hk_btn.config(text=vk_name(self.hotkey))
                    self._was_down = bool(user32.GetAsyncKeyState(self.hotkey) & 0x8000)
                    self._apply_state(self._state)
                    break
            return

        down = bool(user32.GetAsyncKeyState(self.hotkey) & 0x8000)
        if down != self._was_down:
            self._was_down = down
            if self.hk_mode == "toggle":
                if down:
                    self._toggle()
            elif down:
                self._begin()
            else:
                eng.stop()

        if eng.running and user32.GetAsyncKeyState(0x1B) & 0x8000:
            eng.stop()

        st = "idle" if not eng.running else ("starting" if eng.phase == "delay" else "running")
        if st != self._state:
            self._apply_state(st)

        now = time.perf_counter()
        if now - self._stat_t >= 0.25:
            c = eng.count
            live = (c - self._stat_c) / (now - self._stat_t) if st == "running" else 0
            self._stat_t, self._stat_c = now, c
            self.clicks_lbl.config(text=f"Clicks  {c:,}")
            self.live_lbl.config(text=f"Live  {live:.1f} CPS" if live < 10 else f"Live  {live:,.0f} CPS")

    def _close(self):
        self.engine.stop()
        winmm.timeEndPeriod(1)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
