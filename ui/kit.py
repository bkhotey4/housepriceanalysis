"""共用介面工具：字型挑選、設定檔、可點連結的文字區、開啟網址。"""
import json
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import ttk

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(APP_DIR, "data", "settings.json")
IS_ANDROID = "ANDROID_ROOT" in os.environ or hasattr(sys, "getandroidapilevel")

INK = "#1f2328"
MUTED = "#5b6168"
SURFACE = "#ffffff"
PAGE = "#f4f6f8"
ACCENT = "#0b5d57"
LINK = "#1c5cab"
BORDER = "#d9dde2"

_FONT_CANDIDATES = [
    "Microsoft JhengHei UI", "Microsoft JhengHei", "微軟正黑體", "PingFang TC", "Noto Sans CJK TC",
    "Noto Sans TC", "Source Han Sans TW", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "wenquanyi zen hei",
    "Droid Sans Fallback",
]


def pick_font_family(root):
    try:
        fams = set(tkfont.families(root))
    except tk.TclError:
        fams = set()
    for f in _FONT_CANDIDATES:
        if f in fams:
            return f
    return tkfont.nametofont("TkDefaultFont").actual("family")


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(d):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def open_url(url):
    if url:
        try:
            webbrowser.open(url)
        except Exception:
            pass


def open_file(path):
    """用系統預設程式開啟檔案（圖片等）。"""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)  # Windows
        else:
            webbrowser.open("file://" + os.path.abspath(path))
    except Exception:
        pass


class Fonts:
    """集中管理字型；改變 size 後所有引用同一物件的元件會一起更新。"""

    def __init__(self, root, size):
        self.family = pick_font_family(root)
        self.size = size
        self.base = tkfont.Font(root, family=self.family, size=size)
        self.bold = tkfont.Font(root, family=self.family, size=size, weight="bold")
        self.small = tkfont.Font(root, family=self.family, size=max(7, size - 1))
        self.h1 = tkfont.Font(root, family=self.family, size=size + 8, weight="bold")
        self.h2 = tkfont.Font(root, family=self.family, size=size + 3, weight="bold")
        self.kpi = tkfont.Font(root, family=self.family, size=size + 7, weight="bold")

    def set_size(self, size):
        self.size = size
        self.base.configure(size=size)
        self.bold.configure(size=size)
        self.small.configure(size=max(7, size - 1))
        self.h1.configure(size=size + 8)
        self.h2.configure(size=size + 3)
        self.kpi.configure(size=size + 7)

    def apply_ttk(self, root):
        style = ttk.Style(root)
        row_h = int(self.base.metrics("linespace") * 1.55)
        style.configure("Treeview", font=self.base, rowheight=row_h)
        style.configure("Treeview.Heading", font=self.bold)
        style.configure("TButton", font=self.base)
        style.configure("TRadiobutton", font=self.base)
        style.configure("TCheckbutton", font=self.base)
        style.configure("TLabel", font=self.base)
        style.configure("TNotebook.Tab", font=self.bold, padding=(12, 6))
        style.configure("TCombobox", font=self.base)
        style.configure("TMenubutton", font=self.base)
        root.option_add("*TCombobox*Listbox.font", self.base)


class RichText(tk.Text):
    """唯讀文字區，支援標題、灰字與可點擊連結。"""

    def __init__(self, master, fonts, **kw):
        kw.setdefault("wrap", "word")
        kw.setdefault("bg", "#fbfbfa")
        kw.setdefault("relief", "flat")
        kw.setdefault("padx", 12)
        kw.setdefault("pady", 10)
        kw.setdefault("cursor", "arrow")
        kw.setdefault("spacing1", 2)
        kw.setdefault("spacing3", 2)
        super().__init__(master, font=fonts.base, fg=INK, **kw)
        self.fonts = fonts
        self._links = 0
        self.tag_configure("h1", font=fonts.h2, foreground=INK, spacing1=4, spacing3=6)
        self.tag_configure("h2", font=fonts.bold, foreground=ACCENT, spacing1=10, spacing3=3)
        self.tag_configure("muted", foreground=MUTED, font=fonts.small)
        self.tag_configure("bold", font=fonts.bold)
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        for t in self.tag_names():
            if t.startswith("link"):
                self.tag_delete(t)
        self._links = 0

    def done(self):
        self.configure(state="disabled")
        self.yview_moveto(0)

    def add(self, text, tag=None):
        self.insert("end", text, tag or ())

    def line(self, text="", tag=None):
        self.insert("end", text + "\n", tag or ())

    def link(self, label, callback_or_url):
        self._links += 1
        tag = "link%d" % self._links
        self.tag_configure(tag, foreground=LINK, underline=True)
        if callable(callback_or_url):
            self.tag_bind(tag, "<Button-1>", lambda e: callback_or_url())
        else:
            self.tag_bind(tag, "<Button-1>", lambda e, u=callback_or_url: open_url(u))
        self.tag_bind(tag, "<Enter>", lambda e: self.configure(cursor="hand2"))
        self.tag_bind(tag, "<Leave>", lambda e: self.configure(cursor="arrow"))
        self.insert("end", label, tag)

    def sources(self, sources):
        srcs = [s for s in (sources or []) if s.get("url")]
        if not srcs:
            return
        self.line("資料來源", "h2")
        for s in srcs:
            self.add("· ")
            self.link(s.get("title") or s["url"], s["url"])
            if s.get("date"):
                self.add("  （%s）" % s["date"], "muted")
            self.line()


_TABLES = []


def table_columns(tree, fonts, specs, stretch=()):
    """設定 Treeview 的欄位，欄寬依字級放大（字放大後數字與短文字才不會被截掉）。

    specs: [(欄位, 標題, 以 11pt 字為準的寬度, 對齊)]；stretch: 視窗有多餘寬度時可以拉寬的欄位。
    """
    tree._col_specs = (specs, tuple(stretch))
    for col, text, _w, anchor in specs:
        tree.heading(col, text=text)
        tree.column(col, anchor=anchor, stretch=(col in stretch))
    _TABLES.append(tree)
    _apply_table(tree, fonts)


def _apply_table(tree, fonts):
    specs, _stretch = tree._col_specs
    k = max(1.0, fonts.size / 11.0)
    for col, _text, width, _anchor in specs:
        tree.column(col, width=int(width * k), minwidth=int(min(width, 40) * k))


def table_width(tree, fonts):
    """依目前字級，表格所有欄位加起來需要的寬度（含捲軸）。"""
    specs, _stretch = tree._col_specs
    k = max(1.0, fonts.size / 11.0)
    return sum(int(w * k) for _c, _t, w, _a in specs) + 26


def rescale_tables(fonts):
    """字級改變後呼叫：把所有登錄過的表格欄寬重新算一次。"""
    for tree in list(_TABLES):
        try:
            if tree.winfo_exists():
                _apply_table(tree, fonts)
            else:
                _TABLES.remove(tree)
        except tk.TclError:
            _TABLES.remove(tree)


class FlowFrame(tk.Frame):
    """工具列容器：子元件由左到右排，放不下就自動換到下一行（窄螢幕或字放大時不會被切掉）。

    用法：子元件以這個 Frame 為 master 建立後呼叫 add()；right=True 的元件靠右對齊。
    """

    def __init__(self, master, gap=(12, 5), **kw):
        super().__init__(master, **kw)
        self._items = []
        self._gap = gap
        self._width = None
        self._pending = None
        self.bind("<Configure>", self._on_configure)

    def add(self, widget, right=False):
        self._items.append((widget, right))
        # 子元件大小變了（字級改變、文字變長）就重排，免得換行後高度沒跟上
        widget.bind("<Configure>", self._on_child_configure, add="+")
        return widget

    def _on_child_configure(self, _e):
        if self._pending is None:
            self._pending = self.after_idle(self._relayout_pending)

    def _relayout_pending(self):
        self._pending = None
        self.relayout()

    def _on_configure(self, e):
        if e.width != self._width:
            self._width = e.width
            self.relayout()

    def relayout(self):
        width = self._width or self.winfo_width()
        if width <= 1:
            width = self.winfo_reqwidth()
        gx, gy = self._gap
        rows, x = [[]], 0
        for w, right in self._items:
            ww = w.winfo_reqwidth()
            if rows[-1] and x + ww > width:
                rows.append([])
                x = 0
            rows[-1].append((w, right, ww))
            x += ww + gx
        y = 0
        for row in rows:
            h = max(w.winfo_reqheight() for w, _r, _ww in row)
            x = 0
            for w, right, ww in row:
                if not right:
                    w.place(x=x, y=y + (h - w.winfo_reqheight()) // 2)
                    x += ww + gx
            xr = width
            for w, right, ww in reversed(row):
                if right:
                    xr -= ww
                    w.place(x=max(x, xr), y=y + (h - w.winfo_reqheight()) // 2)
                    xr -= gx
            y += h + gy
        self.rows = len(rows)
        height = max(1, y - gy)
        if int(self.cget("height")) != height:
            self.configure(height=height)


def scrolled(parent, widget_factory):
    """建立帶垂直捲軸的元件，回傳 (外框, 元件)。"""
    frame = tk.Frame(parent, bg=SURFACE)
    w = widget_factory(frame)
    sb = ttk.Scrollbar(frame, orient="vertical", command=w.yview)
    w.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    w.pack(side="left", fill="both", expand=True)
    return frame, w


def fmt_num(v, digits=0):
    if v is None:
        return "—"
    if digits:
        return "%.*f" % (digits, v)
    return "{:,}".format(int(round(v)))
