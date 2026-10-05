"""分頁：區域比較（2~3 個行政區並排）。"""
import tkinter as tk
from tkinter import ttk

from core import geo, prices
from core.charts import CompareChart
from . import kit
from .map_tab import NEAR_KM, trend_text

NONE = "（不比較）"


class CompareTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=kit.PAGE)
        self.app = app
        f = app.fonts
        names = [d["name"] for d in app.districts]
        saved = [n for n in app.settings.get("compare", []) if n in names]
        defaults = (saved + ["善化區", "新市區", "永康區"])[:3] if saved else ["善化區", "新市區", "永康區"]
        self.vars = [tk.StringVar(value=defaults[0]), tk.StringVar(value=defaults[1]),
                     tk.StringVar(value=defaults[2] if len(saved) != 2 else NONE)]
        self.cat = tk.StringVar(value="all")
        self.metric = tk.StringVar(value="u")

        top = tk.Frame(self, bg=kit.SURFACE, padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="區域比較", bg=kit.SURFACE, fg=kit.INK, font=f.h2).pack(side="left", padx=(0, 12))
        for i, v in enumerate(self.vars):
            cb = ttk.Combobox(top, textvariable=v, values=names if i < 2 else [NONE] + names, state="readonly", width=12, font=f.base)
            cb.pack(side="left", padx=3)
            cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        tk.Label(top, text="   房型", bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left")
        for value, label in prices.CATS:
            ttk.Radiobutton(top, text=label, value=value, variable=self.cat, command=self.refresh).pack(side="left", padx=2)
        tk.Label(top, text="   走勢圖", bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left")
        for value, label in (("u", "單價"), ("t", "總價")):
            ttk.Radiobutton(top, text=label, value=value, variable=self.metric, command=self.refresh).pack(side="left", padx=2)

        self.chart = CompareChart(self, font_family=f.family, font_size=max(7, f.size - 1),
                                  height=250 if app.win_h >= 800 else 200)
        self.chart.pack(fill="x", padx=12, pady=(8, 4))

        frame, self.table = kit.scrolled(self, lambda p: ttk.Treeview(p, columns=("k", "a", "b", "c"), show="headings"))
        frame.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        kit.table_columns(self.table, f, [("k", "項目", 215, "w"), ("a", "", 250, "w"), ("b", "", 250, "w"), ("c", "", 250, "w")],
                          stretch=("a", "b", "c"))
        self.table.tag_configure("head", background="#eef1f4")
        tk.Label(self, bg=kit.PAGE, fg=kit.MUTED, font=f.small, anchor="w", justify="left", padx=14,
                 text="數值為實價登錄中位數；距離為直線距離、站位與開發案位置為估算。在地圖分頁按「加入比較」可把選取的區帶進來。"
                 ).pack(fill="x", pady=(0, 6))
        self.refresh()

    def chosen(self):
        out = []
        for v in self.vars:
            n = v.get()
            if n and n != NONE and n in self.app.dmap and n not in out:
                out.append(n)
        return out

    def add(self, name):
        """由地圖分頁帶入一個行政區：已在清單就不動，否則放進空位或取代最後一個。"""
        cur = [v.get() for v in self.vars]
        if name in cur:
            return
        for v in self.vars:
            if v.get() == NONE:
                v.set(name)
                break
        else:
            self.vars[2].set(name)
        self.refresh()

    def _nearest_station(self, d):
        best = None
        for lname, ln in self.app.map_mrt.items():
            for sname, lat, lng in ln["stations"]:
                km = geo.dist_km(d["lat"], d["lng"], lat, lng)
                if best is None or km < best[0]:
                    best = (km, lname, sname)
        if not best or best[0] > NEAR_KM:
            return "%d 公里內沒有車站" % NEAR_KM
        return "%s %s，約 %.1f 公里" % (best[1], best[2].split("（")[0][:10], best[0])

    def rows(self):
        """回傳 [(項目, [各區的值])]，供表格與測試使用。"""
        app, book, cat = self.app, self.app.book, self.cat.get()
        names = self.chosen()
        works = app.map_tab.work_places() if getattr(app, "map_tab", None) else []

        def each(fn):
            return [fn(n) for n in names]

        def price(n, c, metric, unit):
            b = book.best(n, c, metric)
            if b["value"] is None:
                return "—"
            num = ("%.1f" % b["value"]) if metric == "u" else kit.fmt_num(b["value"])
            return "%s %s（%d 件%s%s）" % (num, unit, b["n"], "" if b["window"] == "h6" else "，近一年",
                                          "，樣本少" if b["low"] else "")

        def gap(n):
            g = book.presale_gap(n)
            return "—" if g is None else "預售%s %.0f%%" % ("高" if g >= 0 else "低", abs(g))

        def devs(n):
            items = sorted((it for it in app.intel if n in (it.get("district") or "") and (it.get("impact_level") or 0) >= 4),
                           key=lambda it: -(it.get("impact_level") or 0))
            if not items:
                return "—"
            return "%d 項：%s" % (len(items), "、".join(it["name"].split("（")[0][:12] for it in items[:2]))

        label = prices.CAT_LABEL[cat]
        out = [
            ("【%s】中位單價" % label, each(lambda n: price(n, cat, "u", "萬/坪"))),
            ("【%s】中位總價" % label, each(lambda n: price(n, cat, "t", "萬"))),
            ("【%s】近半年起伏" % label, each(lambda n: trend_text(book.trend(n, cat, "u")))),
            ("透天厝中位總價", each(lambda n: price(n, "house", "t", "萬"))),
            ("大樓／華廈中位單價", each(lambda n: price(n, "apt", "u", "萬/坪"))),
            ("預售屋中位單價", each(lambda n: price(n, "presale", "u", "萬/坪"))),
            ("預售屋對中古大樓", each(gap)),
            ("所屬生活圈", each(lambda n: app.dmap[n]["zone"])),
        ]
        for _i, _tag, work, _km in works:
            out.append(("距%s（直線）" % work["name"],
                        each(lambda n, w=work: "%.1f 公里" % geo.dist_km(app.dmap[n]["lat"], app.dmap[n]["lng"], w["lat"], w["lng"]))))
        out.append(("最近的車站（捷運、高鐵、台鐵）", each(lambda n: self._nearest_station(app.dmap[n]))))
        out.append(("影響度 4 以上的開發案", each(devs)))
        return out

    def refresh(self):
        names = self.chosen()
        self.app.settings["compare"] = names
        book, cat, metric = self.app.book, self.cat.get(), self.metric.get()
        self.chart.set_data([(n, book.series(n, cat, metric)) for n in names], "萬/坪" if metric == "u" else "萬",
                            "%s | 每月中位%s" % (prices.CAT_LABEL[cat], "單價（萬/坪）" if metric == "u" else "總價（萬）"))
        self.table.heading("k", text="項目")
        for i, col in enumerate(("a", "b", "c")):
            self.table.heading(col, text=names[i] if i < len(names) else "")
        self.table.configure(displaycolumns=("k", "a", "b", "c")[:1 + len(names)])
        self.table.delete(*self.table.get_children())
        for k, vals in self.rows():
            self.table.insert("", "end", values=[k] + vals + [""] * (3 - len(vals)))

    def set_font_size(self, size):
        self.chart.set_font_size(max(7, size - 1))
