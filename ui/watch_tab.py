"""分頁：看屋清單（可新增、編輯、刪除，並與實價登錄行情比較）。"""
import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from urllib.parse import quote

from core import geo, prices, watchlist
from . import kit
from .dialogs import WatchDialog


ALL_DIST = "全部行政區"
# 到各大平台找物件：用 Google 限定網站搜尋「台南 某區 買房」，任何一區都能用（各平台網址格式常改，直接連搜尋頁容易失效）
PLATFORMS = [("591 房屋交易", "sale.591.com.tw"), ("樂屋網", "rakuya.com.tw"), ("永慶房屋", "yungching.com.tw"),
             ("信義房屋", "sinyi.com.tw"), ("住商不動產", "hbhousing.com.tw"), ("台灣房屋", "twhg.com.tw")]


def platform_search_url(site, district, kind=""):
    q = "site:%s 台南 %s %s 買房" % (site, district if district != ALL_DIST else "", kind)
    return "https://www.google.com/search?q=" + quote(" ".join(q.split()))


class WatchTab(tk.Frame):
    def __init__(self, master, app, search_urls=None, open_search=None):
        super().__init__(master, bg=kit.PAGE)
        self.app = app
        self.watch = app.watch
        f = app.fonts
        self._sel = None

        top = tk.Frame(self, bg=kit.SURFACE, padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="看屋清單", bg=kit.SURFACE, fg=kit.INK, font=f.h2).pack(side="left")
        ttk.Button(top, text="新增物件", command=self.add).pack(side="left", padx=(14, 2))
        self.btn_edit = ttk.Button(top, text="編輯", command=self.edit, state="disabled")
        self.btn_edit.pack(side="left", padx=2)
        self.btn_del = ttk.Button(top, text="刪除", command=self.delete, state="disabled")
        self.btn_del.pack(side="left", padx=2)
        self.btn_pin = ttk.Button(top, text="在地圖上標位置", command=self.pin, state="disabled")
        self.btn_pin.pack(side="left", padx=(10, 2))
        self.btn_map = ttk.Button(top, text="在 3D 地圖上看", command=self.to_map, state="disabled")
        self.btn_map.pack(side="left", padx=2)
        self.v_dist = tk.StringVar(value=ALL_DIST)
        tk.Label(top, text="行政區", bg=kit.SURFACE, fg=kit.MUTED, font=f.base).pack(side="left", padx=(16, 4))
        self.cb_dist = ttk.Combobox(top, textvariable=self.v_dist, state="readonly", width=10, font=f.base)
        self.cb_dist.pack(side="left")
        self.cb_dist.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.lbl_count = tk.Label(top, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small)
        self.lbl_count.pack(side="left", padx=8)
        self.mb_search = ttk.Menubutton(top, text="到房仲平台找物件")
        self.menu_search = tk.Menu(self.mb_search, tearoff=0, font=f.base, postcommand=self._fill_search_menu)
        self.mb_search["menu"] = self.menu_search
        self.mb_search.pack(side="right")

        self.banner_box = tk.Frame(self, bg="#fff6e5")
        self.btn_clear = ttk.Button(self.banner_box, text="清除示意資料", command=self.clear_samples)
        self.btn_clear.pack(side="right", padx=8, pady=3)
        self.banner = tk.Label(self.banner_box, bg="#fff6e5", fg="#6b4a00", font=f.small, anchor="w", justify="left",
                               padx=12, pady=5)
        self.banner.pack(side="left", fill="x", expand=True)
        self.banner.bind("<Configure>", lambda e: self.banner.config(wraplength=max(200, e.width - 28)))   # 太長時自動換行

        paned = tk.PanedWindow(self, orient="horizontal", bg=kit.BORDER, sashwidth=5, bd=0)
        paned.pack(fill="both", expand=True)
        left = tk.Frame(paned, bg=kit.SURFACE)
        frame, self.tree = kit.scrolled(left, lambda p: ttk.Treeview(
            p, columns=("name", "dist", "type", "price", "ping", "unit", "vs"), show="headings"))
        kit.table_columns(self.tree, f,
                          [("name", "物件", 150, "w"), ("dist", "行政區", 70, "w"), ("type", "類型", 96, "w"),
                           ("price", "總價(萬)", 72, "e"), ("ping", "建坪", 52, "e"), ("unit", "萬/坪", 58, "e"),
                           ("vs", "對區中位總價", 120, "e")], stretch=("name",))
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.edit())
        # 左邊給到「表格所有欄位都看得到」的寬度（字放大時跟著變寬），但最多佔視窗的六成五
        paned.add(left, minsize=320, width=min(int(app.win_w * 0.65), max(int(app.win_w * 0.5), kit.table_width(self.tree, f))),
                  stretch="never")

        right = tk.Frame(paned, bg=kit.SURFACE)
        btns = tk.Frame(right, bg=kit.SURFACE, padx=8, pady=6)
        btns.pack(fill="x")
        self.btn_src = ttk.Button(btns, text="開啟物件網址", command=self._open_source, state="disabled")
        self.btn_src.pack(side="left", padx=2)
        self.btn_gmap = ttk.Button(btns, text="Google 地圖", command=self._open_maps, state="disabled")
        self.btn_gmap.pack(side="left", padx=2)
        frame2, self.text = kit.scrolled(right, lambda p: kit.RichText(p, f))
        frame2.pack(fill="both", expand=True)
        paned.add(right, minsize=320, stretch="always")
        self._paned = paned
        self.refresh()

    # ------------------------------------------------------------------ 比較行情
    def compare(self, it):
        """回傳 dict：cat、區中位總價/單價、差距百分比、同路段行情。"""
        book = self.app.book
        cat = watchlist.TYPE_CAT.get(it.get("type"))
        out = {"cat": cat, "unit": watchlist.unit_price(it), "dist_total": None, "dist_unit": None,
               "vs_total": None, "vs_unit": None, "road": None}
        d = it.get("district")
        if not cat or d not in self.app.dmap:
            return out
        bt, bu = book.best(d, cat, "t"), book.best(d, cat, "u")
        out["dist_total"], out["dist_unit"] = bt, bu
        try:
            price = float(it.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        if price > 0 and bt["value"]:
            out["vs_total"] = (price - bt["value"]) / bt["value"] * 100.0
        if out["unit"] and bu["value"]:
            out["vs_unit"] = (out["unit"] - bu["value"]) / bu["value"] * 100.0
        if self.app.txs and it.get("address") and cat != "presale":
            road = prices.road_of(it["address"], d)
            for r in prices.road_stats(self.app.txs, d, cat, self.app.book.windows["y12"][0]):
                if r["name"] == road:
                    out["road"] = r
                    break
        return out

    @staticmethod
    def _pct(v):
        if v is None:
            return "—"
        return "%s %.0f%%" % ("高" if v >= 0 else "低", abs(v))

    def districts_in_list(self):
        """清單裡出現過的行政區（依 37 區的順序）。"""
        have = {it.get("district") for it in self.watch.items}
        return [d["name"] for d in self.app.districts if d["name"] in have]

    def refresh(self, keep=None):
        keep = keep or (self._sel["id"] if self._sel else None)
        self.tree.delete(*self.tree.get_children())
        # 行政區下拉：清單裡有的區排前面（後面括號是筆數），其餘的區也列出來（選了可以直接到平台找那一區）
        counts = {}
        for it in self.watch.items:
            counts[it.get("district") or ""] = counts.get(it.get("district") or "", 0) + 1
        have = self.districts_in_list()
        rest = [d["name"] for d in self.app.districts if d["name"] not in have]
        self.cb_dist.config(values=[ALL_DIST] + ["%s（%d）" % (d, counts[d]) for d in have] + rest)
        dist = self.selected_district()
        shown = [it for it in self.watch.items if dist == ALL_DIST or it.get("district") == dist]
        self.lbl_count.config(text="%s 共 %d 筆" % ("" if dist == ALL_DIST else dist, len(shown)) if self.watch.items else "")
        self.mb_search.config(text="到房仲平台找%s物件" % ("" if dist == ALL_DIST else dist))
        for it in shown:
            c = self.compare(it)
            self.tree.insert("", "end", iid=it["id"], values=(
                it.get("name", ""), it.get("district") or "", it.get("type") or "",
                "—" if not it.get("price") else kit.fmt_num(it["price"]),
                "—" if not it.get("ping") else "%g" % it["ping"],
                "—" if c["unit"] is None else "%.1f" % c["unit"], self._pct(c["vs_total"])))
        if any(it.get("sample") for it in self.watch.items):
            self.banner.config(text="清單裡的舊資料是從原本的 house_data.py 帶過來的示意物件（只有善化區、地址只有路名、網址只到首頁），"
                                    "可以按右邊「清除示意資料」一次刪掉，或按「編輯」改成真正在看的房子。")
            self.banner_box.pack(fill="x", before=self._paned)
        elif not self.watch.items:
            self.banner.config(text="清單是空的：按「新增物件」把正在看的房子記下來（任何一區都可以），"
                                    "就能和那一區的實價登錄行情比較；上方「行政區」選一區，再按右邊的按鈕可以到各大平台找那一區的物件。")
            self.btn_clear.pack_forget()
            self.banner_box.pack(fill="x", before=self._paned)
        else:
            self.banner_box.pack_forget()
        if any(it.get("sample") for it in self.watch.items) and not self.btn_clear.winfo_ismapped():
            self.btn_clear.pack(side="right", padx=8, pady=3, before=self.banner)
        self._sel = None
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        else:
            self._show(None)

    def selected_district(self):
        v = self.v_dist.get()
        return v.split("（")[0] if v else ALL_DIST

    def clear_samples(self):
        n = sum(1 for it in self.watch.items if it.get("sample"))
        if not n:
            return
        if not messagebox.askyesno("清除示意資料", "要刪掉 %d 筆舊版帶過來的示意物件嗎？你自己新增的物件不受影響。" % n, parent=self):
            return
        self.watch.remove_samples()
        self.v_dist.set(ALL_DIST)
        self.refresh()
        self.app.map_tab.refresh_pins()

    def _fill_search_menu(self):
        """「到房仲平台找物件」：依上方選的行政區，用 Google 限定各平台網站搜尋。"""
        m = self.menu_search
        m.delete(0, "end")
        dist = self.selected_district()
        where = "台南全市" if dist == ALL_DIST else dist
        for name, site in PLATFORMS:
            m.add_command(label="%s：%s" % (name, where), command=lambda s=site: kit.open_url(platform_search_url(s, dist)))
        m.add_separator()
        for kind in ("透天", "大樓", "預售屋"):
            m.add_command(label="所有平台：%s %s" % (where, kind),
                          command=lambda k=kind: kit.open_url(
                              "https://www.google.com/search?q=" + quote("台南 %s %s 買房" % ("" if dist == ALL_DIST else dist, k))))

    def _on_select(self, _e):
        sel = self.tree.selection()
        self._show(self.watch.get(sel[0]) if sel else None)

    def _show(self, it):
        self._sel = it
        state = "normal" if it else "disabled"
        for b in (self.btn_edit, self.btn_del, self.btn_pin, self.btn_gmap):
            b.config(state=state)
        self.btn_map.config(state="normal" if it and it.get("lat") is not None else "disabled")
        self.btn_src.config(state="normal" if it and it.get("url") else "disabled")
        t = self.text
        t.clear()
        if not it:
            t.line("還沒有選取物件", "h1")
            t.line("按「新增物件」把正在看的房子記下來：填行政區、類型、總價與坪數，就會自動和實價登錄行情比較。", "muted")
            t.line("按「在地圖上標位置」再點一下地圖，物件就會以紫色圖釘顯示在 3D 地圖上。", "muted")
            t.done()
            return
        c = self.compare(it)
        t.line(it.get("name", ""), "h1")
        t.line(" | ".join(x for x in (it.get("district"), it.get("type"), it.get("address")) if x), "muted")
        t.line("基本資料", "h2")
        parts = []
        if it.get("price"):
            parts.append("總價 %s 萬" % kit.fmt_num(it["price"]))
        if it.get("ping"):
            parts.append("建坪 %g 坪" % it["ping"])
        if c["unit"]:
            parts.append("單價 %.1f 萬/坪" % c["unit"])
        t.line(" | ".join(parts) if parts else "尚未填價格與坪數")
        if it.get("year"):
            t.line("屋齡約 %d 年（%d 年完工）" % (max(0, datetime.date.today().year - int(it["year"])), int(it["year"])))
        t.line("與實價登錄行情比較", "h2")
        if not c["cat"]:
            t.line("這個類型沒有可對照的行情。", "muted")
        elif c["dist_total"] is None or c["dist_total"]["value"] is None:
            t.line("%s的%s近一年沒有足夠成交可比較。" % (it.get("district") or "此區", prices.CAT_LABEL.get(c["cat"], "")), "muted")
        else:
            label = prices.CAT_LABEL[c["cat"]]
            bt, bu = c["dist_total"], c["dist_unit"]
            win = "近半年" if bt["window"] == "h6" else "近一年"
            t.line("%s %s %s中位總價 %s 萬（%d 件%s）%s" % (
                it["district"], label, win, kit.fmt_num(bt["value"]), bt["n"], "，樣本少" if bt["low"] else "",
                "" if c["vs_total"] is None else "：本物件%s" % self._pct(c["vs_total"])))
            if bu["value"]:
                t.line("%s %s %s中位單價 %.1f 萬/坪%s" % (
                    it["district"], label, win, bu["value"],
                    "" if c["vs_unit"] is None else "：本物件%s" % self._pct(c["vs_unit"])))
            if c["road"]:
                r = c["road"]
                t.line("同路段「%s」近一年 %d 件：中位總價 %s 萬、中位單價 %.1f 萬/坪" % (
                    r["name"], r["n"], kit.fmt_num(r["t"]), r["u"]))
            elif not self.app.txs:
                t.line("更新實價登錄後，還會顯示同一路段的成交行情。", "muted")
            if c["cat"] == "house":
                t.line("透天厝單價以建物面積計（含土地），請以總價為主。", "muted")
            t.line("開價通常高於成交價；行情是整區的中位數，屋況、地坪、臨路條件不同都會有差距。", "muted")
        if it.get("note"):
            t.line("備註", "h2")
            t.line(it["note"])
        if it.get("lat") is None:
            t.line()
            t.line("尚未標示位置。按上方「在地圖上標位置」後在地圖點一下即可。", "muted")
        t.done()

    # ------------------------------------------------------------------ 動作
    def add(self):
        WatchDialog(self, self.app, on_save=lambda data: self._saved(self.watch.add(data)))

    def edit(self):
        if self._sel:
            ident = self._sel["id"]
            WatchDialog(self, self.app, item=self._sel,
                        on_save=lambda data: self._saved(self.watch.update(ident, data)))

    def _saved(self, item):
        self.refresh(keep=item["id"] if item else None)
        self.app.map_tab.refresh_pins()

    def delete(self):
        if self._sel and messagebox.askyesno("刪除物件", "確定要把「%s」從看屋清單刪除嗎？" % self._sel.get("name", ""), parent=self):
            self.watch.remove(self._sel["id"])
            self.refresh()
            self.app.map_tab.refresh_pins()

    def pin(self):
        """切到地圖，讓使用者點一下位置。"""
        if not self._sel:
            return
        ident = self._sel["id"]
        d = self.app.dmap.get(self._sel.get("district") or "")
        self.app.nb.select(self.app.map_tab)
        if d:
            self.app.map_tab.view.focus(d["lat"], d["lng"], zoom=max(self.app.map_tab.view.zoom, 60.0))

        def picked(lat, lng):
            if lat is not None:
                self.watch.update(ident, {"lat": round(lat, 5), "lng": round(lng, 5)})
                self.app.map_tab.show_watch.set(True)
                self.app.map_tab.refresh_pins()
                self.app.map_tab.view.select("pin", ident)
            self.refresh(keep=ident)
        self.app.map_tab.view.start_pick_location(picked)

    def to_map(self):
        it = self._sel
        if it and it.get("lat") is not None:
            self.app.map_tab.show_watch.set(True)
            self.app.map_tab.refresh_pins()
            self.app.show_on_map(it["lat"], it["lng"], "pin", it["id"], zoom=80.0)

    def show(self, ident):
        if self.tree.exists(ident):
            self.tree.selection_set(ident)
            self.tree.see(ident)

    def _open_source(self):
        if self._sel:
            kit.open_url(self._sel.get("url"))

    def _open_maps(self):
        it = self._sel
        if not it:
            return
        if it.get("lat") is not None:
            kit.open_url(geo.google_satellite_url(it["lat"], it["lng"], 18))
        else:
            kit.open_url(geo.google_search_url("台南市%s%s" % (it.get("district") or "", it.get("address") or "")))
