"""分頁 3：未來開發、議會與建商情資、市況走勢。"""
import tkinter as tk
from tkinter import ttk

from core import geo
from . import kit

TYPE_ORDER = ["商辦", "商場", "科學園區", "產業園區", "重劃區", "公共建設", "交通建設", "住宅開發", "議會", "開發商", "市況"]


class IntelTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=kit.PAGE)
        self.app = app
        f = app.fonts
        self.v_type = tk.StringVar(value="全部類別")
        self.v_dist = tk.StringVar(value="全部行政區")
        self.v_level = tk.StringVar(value="不限影響度")
        self.v_kw = tk.StringVar(value="")

        top = tk.Frame(self, bg=kit.SURFACE, padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="開發與情資", bg=kit.SURFACE, fg=kit.INK, font=f.h2).pack(side="left")
        tk.Label(top, text="  大型商辦、園區、重劃區、議會決議、建商動向。查證日 %s" % app.intel_as_of,
                 bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=8)

        flt = tk.Frame(self, bg=kit.SURFACE, padx=12, pady=4)
        flt.pack(fill="x")
        types = ["全部類別"] + [t for t in TYPE_ORDER if any(it["type"] == t for it in app.intel)]
        dists = ["全部行政區", "全市"] + [d["name"] for d in app.districts]
        for var, values, width in [(self.v_type, types, 13), (self.v_dist, dists, 14),
                                   (self.v_level, ["不限影響度", "影響 3 以上", "影響 4 以上", "影響 5"], 14)]:
            cb = ttk.Combobox(flt, textvariable=var, values=values, state="readonly", width=width, font=app.fonts.base)
            cb.pack(side="left", padx=(0, 6))
            cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        tk.Label(flt, text="關鍵字", bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=(6, 3))
        ent = ttk.Entry(flt, textvariable=self.v_kw, width=16, font=f.base)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self._fill())
        self.lbl_count = tk.Label(flt, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small)
        self.lbl_count.pack(side="right")

        paned = tk.PanedWindow(self, orient="horizontal", bg=kit.BORDER, sashwidth=5, bd=0)
        paned.pack(fill="both", expand=True)
        left = tk.Frame(paned, bg=kit.SURFACE)
        frame, self.tree = kit.scrolled(left, lambda p: ttk.Treeview(
            p, columns=("name", "type", "dist", "lvl", "conf"), show="headings"))
        kit.table_columns(self.tree, app.fonts,
                          [("name", "項目", 280, "w"), ("type", "類別", 74, "w"), ("dist", "行政區", 96, "w"),
                           ("lvl", "影響", 46, "e"), ("conf", "可信度", 62, "w")], stretch=("name",))
        for col in ("name", "type", "dist", "lvl", "conf"):
            self.tree.heading(col, command=lambda c=col: self._sort_by(c))
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(left, minsize=320, stretch="never",
                  width=min(int(app.win_w * 0.6), max(int(app.win_w * 0.46), kit.table_width(self.tree, app.fonts))))

        right = tk.Frame(paned, bg=kit.SURFACE)
        btns = tk.Frame(right, bg=kit.SURFACE, padx=8, pady=6)
        btns.pack(fill="x")
        self.btn_map = ttk.Button(btns, text="在 3D 地圖上看", command=self._to_map, state="disabled")
        self.btn_map.pack(side="left", padx=2)
        self.btn_google = ttk.Button(btns, text="Google 地圖", command=self._google, state="disabled")
        self.btn_google.pack(side="left", padx=2)
        frame2, self.text = kit.scrolled(right, lambda p: kit.RichText(p, f))
        frame2.pack(fill="both", expand=True)
        paned.add(right, minsize=320, stretch="always")

        self._sort = ("lvl", True)
        self._current = None
        self._fill()

    def _filtered(self):
        ty, di, lv, kw = self.v_type.get(), self.v_dist.get(), self.v_level.get(), self.v_kw.get().strip()
        th = {"影響 3 以上": 3, "影響 4 以上": 4, "影響 5": 5}.get(lv, 0)
        out = []
        for it in self.app.intel:
            if ty != "全部類別" and it["type"] != ty:
                continue
            if di != "全部行政區" and di not in (it.get("district") or ""):
                continue
            if th and (it.get("impact_level") or 0) < th:
                continue
            if kw:
                blob = " ".join(str(it.get(k) or "") for k in ("name", "status", "developer", "impact", "timeline", "scale"))
                if kw not in blob:
                    continue
            out.append(it)
        key, desc = self._sort
        field = {"name": "name", "type": "type", "dist": "district", "lvl": "impact_level", "conf": "confidence"}[key]
        if key == "type":
            out.sort(key=lambda it: TYPE_ORDER.index(it["type"]) if it["type"] in TYPE_ORDER else 99, reverse=desc)
        else:
            out.sort(key=lambda it: (it.get(field) is None, it.get(field) or (0 if key == "lvl" else "")), reverse=False)
            if desc:
                head = [it for it in out if it.get(field) is not None]
                tail = [it for it in out if it.get(field) is None]
                out = head[::-1] + tail
        return out

    def _sort_by(self, col):
        key, desc = self._sort
        self._sort = (col, not desc if key == col else (col == "lvl"))
        self._fill()

    def _fill(self):
        keep = self._current
        self.tree.delete(*self.tree.get_children())
        items = self._filtered()
        for it in items:
            self.tree.insert("", "end", iid=str(it["id"]), values=(
                it["name"], it["type"], it.get("district") or "", it.get("impact_level") or "—", it.get("confidence") or ""))
        self.lbl_count.config(text="%d 筆" % len(items))
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
        elif items:
            self.tree.selection_set(str(items[0]["id"]))

    def show(self, ident):
        if not self.tree.exists(str(ident)):
            self.v_type.set("全部類別")
            self.v_dist.set("全部行政區")
            self.v_level.set("不限影響度")
            self.v_kw.set("")
            self._fill()
        if self.tree.exists(str(ident)):
            self.tree.selection_set(str(ident))
            self.tree.see(str(ident))

    def _on_select(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        it = self.app.intel_by_id[int(sel[0])]
        self._current = it["id"]
        self.text.clear()
        self.app.write_intel(self.text, it)
        self.text.done()
        has_geo = it.get("lat") is not None and it.get("lng") is not None
        self.btn_map.config(state="normal" if has_geo else "disabled")
        self.btn_google.config(state="normal" if has_geo else "disabled")

    def _to_map(self):
        it = self.app.intel_by_id.get(self._current)
        if it and it.get("lat") is not None:
            self.app.show_on_map(it["lat"], it["lng"], "marker", it["id"])

    def _google(self):
        it = self.app.intel_by_id.get(self._current)
        if it and it.get("lat") is not None:
            kit.open_url(geo.google_terrain_url(it["lat"], it["lng"], 15))
