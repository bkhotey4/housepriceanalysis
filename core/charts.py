"""近半年房價走勢圖（純 Tkinter Canvas）。

上半部：每月中位價折線（單一數列，不需圖例）。
下半部：每月成交件數長條（獨立的小圖，不與價格共用座標軸）。
最新一個月若資料未齊，以空心點＋虛線表示。
"""
import tkinter as tk
import tkinter.font as tkfont

from .prices import MIN_N, ym_label

SURFACE = "#fcfcfb"
INK = "#1f2328"
MUTED = "#6b7178"
GRID = "#e6e8eb"
SERIES = "#2a78d6"
VOLUME = "#a9b1ba"
BAND = "#f0f3f7"


def _nice_range(lo, hi):
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    lo2, hi2 = lo - span * 0.18, hi + span * 0.22
    return max(0, lo2), hi2


class TrendChart(tk.Canvas):
    def __init__(self, master, font_family="TkDefaultFont", font_size=9, **kw):
        kw.setdefault("bg", SURFACE)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#d9dde2")
        kw.setdefault("height", 230)
        super().__init__(master, **kw)
        self.font_family, self.font_size = font_family, font_size
        self._make_fonts()
        self.series = []
        self.half = set()
        self.unit = "萬/坪"
        self.title = ""
        self._xs = []
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_motion)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    def _make_fonts(self):
        self.f = tkfont.Font(family=self.font_family, size=self.font_size)
        self.fb = tkfont.Font(family=self.font_family, size=self.font_size, weight="bold")

    def set_font_size(self, size):
        self.font_size = size
        self._make_fonts()
        self.redraw()

    def set_data(self, series, half_months, unit, title):
        """series: [(ym, value|None, n, incomplete)]"""
        self.series = series
        self.half = set(half_months)
        self.unit = unit
        self.title = title
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 80 or not self.series:
            return
        f, fb = self.f, self.fb
        lh = f.metrics("linespace")
        left, right = 10 + f.measure("8,888"), 14
        top = 2 * lh + 16           # 標題一行，再留一行給最高點的數值標註，兩者才不會疊在一起
        bottom = lh + 8
        compact = h < top + bottom + 3 * lh + 50     # 高度不夠時省略成交件數，只畫價格走勢
        vol_h = 0 if compact else max(28, int((h - top - bottom) * 0.26))
        gap = 0 if compact else lh + 6
        px0, px1 = left, w - right
        py0, py1 = top, h - bottom - vol_h - gap      # 價格圖
        vy0, vy1 = h - bottom - vol_h, h - bottom       # 件數圖
        n = len(self.series)
        step = (px1 - px0) / float(n)
        xs = [px0 + step * (i + 0.5) for i in range(n)]
        self._xs = xs
        self._geom = (py0, py1, vy0, vy1, step)

        self.create_text(8, 6, text=self.title, anchor="nw", font=fb, fill=INK)

        # 近半年範圍底色
        idx = [i for i, s in enumerate(self.series) if s[0] in self.half]
        if idx:
            bx0, bx1 = xs[idx[0]] - step / 2, xs[idx[-1]] + step / 2
            self.create_rectangle(bx0, py0 - 2, bx1, vy1, fill=BAND, outline="")
            # 「近半年」寫在價格圖與件數圖之間的空白列，不會壓到折線與數值
            if not compact:
                self.create_text((bx0 + bx1) / 2, vy0 - 3, text="近半年", anchor="s", font=f, fill=MUTED)

        vals = [s[1] for s in self.series if s[1] is not None and s[2] >= 1]
        if vals:
            lo, hi = _nice_range(min(vals), max(vals))
            # 格線（3 條）
            for k in range(3):
                v = lo + (hi - lo) * k / 2.0
                y = py1 - (v - lo) / (hi - lo) * (py1 - py0)
                self.create_line(px0, y, px1, y, fill=GRID)
                self.create_text(px0 - 5, y, text=self._fmt(v), anchor="e", font=f, fill=MUTED)

            def ypos(v):
                return py1 - (v - lo) / (hi - lo) * (py1 - py0)

            pts = [(xs[i], ypos(s[1]), s) if s[1] is not None else None for i, s in enumerate(self.series)]
            # 折線：相鄰兩點都有值才連線；含資料未齊月份的線段用虛線
            for i in range(1, n):
                a, b = pts[i - 1], pts[i]
                if a and b:
                    opts = {"fill": SERIES, "width": 2}
                    if b[2][3] or a[2][3]:
                        opts["dash"] = (4, 3)
                        opts["fill"] = VOLUME
                    self.create_line(a[0], a[1], b[0], b[1], **opts)
            for p in pts:
                if not p:
                    continue
                x, y, s = p
                weak = s[3] or s[2] < MIN_N
                r = 4
                self.create_oval(x - r - 1, y - r - 1, x + r + 1, y + r + 1, fill=SURFACE, outline="")
                self.create_oval(x - r, y - r, x + r, y + r, fill=SURFACE if weak else SERIES,
                                 outline=VOLUME if s[3] else SERIES, width=2)
            # 直接標註：近半年第一點與最後一個完整月份
            full = [i for i in idx if pts[i] and not self.series[i][3]]
            for i in ({full[0], full[-1]} if full else set()):
                x, y, s = pts[i]
                self.create_text(x, y - 8, text=self._fmt(s[1]), anchor="s", font=fb, fill=INK)
        else:
            self.create_text((px0 + px1) / 2, (py0 + py1) / 2, text="此條件下沒有成交資料", font=f, fill=MUTED)

        # 成交件數
        nmax = max([s[2] for s in self.series] + [1])
        if not compact:
            self.create_text(px0, vy0 - 3, text="每月成交件數", anchor="sw", font=f, fill=MUTED)
        self.create_line(px0, vy1, px1, vy1, fill="#c9ced4")
        bw = max(3, min(22, step - 6))
        for i, s in enumerate(self.series):
            bh = (vy1 - vy0) * s[2] / float(nmax)
            if s[2] > 0 and not compact:
                self.create_rectangle(xs[i] - bw / 2, vy1 - max(1, bh), xs[i] + bw / 2, vy1,
                                      fill=SURFACE if s[3] else VOLUME, outline=VOLUME)
        # 月份標籤（隔月顯示避免擁擠）
        need = f.measure("25/12") + 8
        every = 1
        while step * every < need and every < n:
            every += 1
        for i, s in enumerate(self.series):
            if (n - 1 - i) % every == 0:
                self.create_text(xs[i], vy1 + 3, text=ym_label(s[0]), anchor="n", font=f, fill=MUTED)

    def _fmt(self, v):
        if v is None:
            return "—"
        return ("%.1f" % v) if self.unit == "萬/坪" else "{:,}".format(int(round(v)))

    def _on_motion(self, e):
        self.delete("hover")
        if not self._xs or not self.series:
            return
        py0, py1, vy0, vy1, step = self._geom
        i = min(range(len(self._xs)), key=lambda k: abs(self._xs[k] - e.x))
        if abs(self._xs[i] - e.x) > step:
            return
        ym, v, n, incomplete = self.series[i]
        x = self._xs[i]
        self.create_line(x, py0, x, vy1, fill="#8a929b", dash=(2, 2), tags="hover")
        lines = ["%s 年 %d 月" % (ym[:4], int(ym[5:7])),
                 "中位%s：%s %s" % ("單價" if self.unit == "萬/坪" else "總價", self._fmt(v), self.unit if v is not None else ""),
                 "成交 %d 件" % n]
        if incomplete:
            lines.append("（申報尚未到齊）")
        elif 0 < n < MIN_N:
            lines.append("（樣本少，僅供參考）")
        f = self.f
        tw = max(f.measure(s) for s in lines)
        th = f.metrics("linespace") * len(lines)
        w = self.winfo_width()
        bx = x + 10 if x + tw + 30 < w else x - tw - 22
        by = py0 + 4
        self.create_rectangle(bx, by, bx + tw + 12, by + th + 8, fill="#1f2328", outline="", tags="hover")
        self.create_text(bx + 6, by + 4, text="\n".join(lines), anchor="nw", font=f, fill="#ffffff", tags="hover")


SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]     # 依固定順序指定給第 1~3 個比較對象


class CompareChart(tk.Canvas):
    """多個行政區的每月中位價折線（最多 3 條）。"""

    def __init__(self, master, font_family="TkDefaultFont", font_size=9, **kw):
        kw.setdefault("bg", SURFACE)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", "#d9dde2")
        kw.setdefault("height", 260)
        super().__init__(master, **kw)
        self.font_family, self.font_size = font_family, font_size
        self.f = tkfont.Font(family=font_family, size=font_size)
        self.fb = tkfont.Font(family=font_family, size=font_size, weight="bold")
        self.series = []        # [(名稱, [(ym, value|None, n, incomplete)])]
        self.unit = "萬/坪"
        self.title = ""
        self._xs = []
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_motion)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    def set_font_size(self, size):
        self.font_size = size
        self.f.configure(size=size)
        self.fb.configure(size=size)
        self.redraw()

    def set_data(self, series, unit, title):
        self.series = series[:3]
        self.unit = unit
        self.title = title
        self.redraw()

    def _fmt(self, v):
        if v is None:
            return "—"
        return ("%.1f" % v) if self.unit == "萬/坪" else "{:,}".format(int(round(v)))

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80 or h < 90 or not self.series:
            return
        f, fb = self.f, self.fb
        lh = f.metrics("linespace")
        self.create_text(10, 6, text=self.title, anchor="nw", font=fb, fill=INK)
        # 圖例（兩條以上才需要）
        lx = 10
        ly = 10 + lh
        for i, (name, _pts) in enumerate(self.series):
            self.create_line(lx, ly + lh / 2, lx + 18, ly + lh / 2, fill=SERIES_COLORS[i], width=2)
            self.create_oval(lx + 5, ly + lh / 2 - 4, lx + 13, ly + lh / 2 + 4, fill=SERIES_COLORS[i], outline=SURFACE)
            self.create_text(lx + 24, ly, text=name, anchor="nw", font=f, fill=INK)
            lx += 24 + f.measure(name) + 18
        left, right = 12 + f.measure("8,888"), 16 + f.measure("88.8")
        px0, px1 = left, w - right
        py0, py1 = ly + lh + 12, h - lh - 12
        months = [p[0] for p in self.series[0][1]]
        n = len(months)
        step = (px1 - px0) / float(max(1, n))
        xs = [px0 + step * (i + 0.5) for i in range(n)]
        self._xs, self._geom = xs, (py0, py1, step)
        vals = [p[1] for _name, pts in self.series for p in pts if p[1] is not None and p[2] >= 1]
        if not vals:
            self.create_text((px0 + px1) / 2, (py0 + py1) / 2, text="這些條件下沒有成交資料", font=f, fill=MUTED)
            return
        lo, hi = _nice_range(min(vals), max(vals))
        for k in range(4):
            v = lo + (hi - lo) * k / 3.0
            y = py1 - (v - lo) / (hi - lo) * (py1 - py0)
            self.create_line(px0, y, px1, y, fill=GRID)
            self.create_text(px0 - 5, y, text=self._fmt(v), anchor="e", font=f, fill=MUTED)
        every = 1 if step >= f.measure("25/12") + 6 else 2
        for i, m in enumerate(months):
            if (n - 1 - i) % every == 0:
                self.create_text(xs[i], py1 + 4, text=ym_label(m), anchor="n", font=f, fill=MUTED)
        ends = []
        for si, (name, pts) in enumerate(self.series):
            color = SERIES_COLORS[si]
            prev = None
            last_full = None
            for i, (_m, v, cnt, incomplete) in enumerate(pts):
                if v is None:
                    prev = None
                    continue
                y = py1 - (v - lo) / (hi - lo) * (py1 - py0)
                if prev is not None:
                    opts = {"fill": color, "width": 2}
                    if incomplete:
                        opts["dash"] = (4, 3)
                    self.create_line(prev[0], prev[1], xs[i], y, **opts)
                weak = incomplete or cnt < MIN_N
                self.create_oval(xs[i] - 5, y - 5, xs[i] + 5, y + 5, fill=SURFACE, outline="")
                self.create_oval(xs[i] - 4, y - 4, xs[i] + 4, y + 4, fill=SURFACE if weak else color,
                                 outline=color, width=2)
                prev = (xs[i], y)
                if not incomplete:
                    last_full = (xs[i], y, v)
            if last_full:
                ends.append([last_full[1], last_full[2], last_full[0]])
        # 在右側直接標出各數列最後一個完整月份的數值（文字用墨色，避免與線重疊時錯開）
        ends.sort()
        for k in range(1, len(ends)):
            if ends[k][0] - ends[k - 1][0] < lh:
                ends[k][0] = ends[k - 1][0] + lh
        for y, v, x in ends:
            self.create_text(px1 + 6, y, text=self._fmt(v), anchor="w", font=fb, fill=INK)

    def _on_motion(self, e):
        self.delete("hover")
        if not self._xs or not self.series:
            return
        py0, py1, step = self._geom
        i = min(range(len(self._xs)), key=lambda k: abs(self._xs[k] - e.x))
        if abs(self._xs[i] - e.x) > step:
            return
        x = self._xs[i]
        ym = self.series[0][1][i][0]
        self.create_line(x, py0, x, py1, fill="#8a929b", dash=(2, 2), tags="hover")
        lines = ["%s 年 %d 月" % (ym[:4], int(ym[5:7]))]
        for name, pts in self.series:
            _m, v, cnt, incomplete = pts[i]
            lines.append("%s：%s%s（%d 件）" % (name, self._fmt(v), (" " + self.unit) if v is not None else "", cnt))
        if self.series[0][1][i][3]:
            lines.append("（申報尚未到齊）")
        f = self.f
        tw = max(f.measure(s) for s in lines)
        th = f.metrics("linespace") * len(lines)
        bx = x + 10 if x + tw + 30 < self.winfo_width() else x - tw - 22
        self.create_rectangle(bx, py0 + 4, bx + tw + 12, py0 + th + 12, fill="#1f2328", outline="", tags="hover")
        self.create_text(bx + 6, py0 + 8, text="\n".join(lines), anchor="nw", font=f, fill="#ffffff", tags="hover")
