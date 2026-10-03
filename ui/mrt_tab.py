"""分頁 2：捷運規劃線與鐵路立體化進度。"""
import os
import tkinter as tk
from tkinter import ttk
from urllib.parse import quote

from core import geo
from . import kit

ROUTE_MAP = os.path.join(kit.APP_DIR, "data", "images", "route_map.jpg")


class MrtTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=kit.PAGE)
        self.app = app
        f = app.fonts
        top = tk.Frame(self, bg=kit.SURFACE, padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="捷運與鐵路進度", bg=kit.SURFACE, fg=kit.INK, font=f.h2).pack(side="left")
        n_lines = len(app.mrt_lines)
        n_st = sum(d["stations_count"] for d in app.mrt_lines.values())
        tk.Label(top, text="  %d 條捷運規劃線、約 %d 站；全部尚未動工。查證日 %s" % (n_lines, n_st, app.mrt_as_of),
                 bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=8)
        ttk.Button(top, text="搜尋最新新聞", command=self._news).pack(side="right", padx=2)
        if os.path.exists(ROUTE_MAP):
            ttk.Button(top, text="官方整體路網圖", command=lambda: kit.open_file(ROUTE_MAP)).pack(side="right", padx=2)

        paned = tk.PanedWindow(self, orient="horizontal", bg=kit.BORDER, sashwidth=5, bd=0)
        paned.pack(fill="both", expand=True)

        left = tk.Frame(paned, bg=kit.SURFACE)
        frame, self.tree = kit.scrolled(left, lambda p: ttk.Treeview(
            p, columns=("name", "kind", "km", "st", "start", "open"), show="headings"))
        kit.table_columns(self.tree, app.fonts,
                          [("name", "路線／計畫", 190, "w"), ("kind", "類別", 50, "w"), ("km", "公里", 50, "e"),
                           ("st", "站數", 44, "e"), ("start", "動工", 110, "w"), ("open", "通車", 110, "w")],
                          stretch=("name", "start", "open"))
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # 左邊給到所有欄位都看得到的寬度（字放大時跟著變寬），但最多佔視窗的六成
        paned.add(left, minsize=300, stretch="never",
                  width=min(int(app.win_w * 0.6), max(int(app.win_w * 0.42), kit.table_width(self.tree, app.fonts))))

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

        self._current = None
        self._fill()

    @staticmethod
    def _short(s, n=14):
        s = (s or "未定").split("（")[0]
        return s if len(s) <= n else s[:n - 1] + "…"

    def _fill(self):
        for name, d in self.app.mrt_lines.items():
            self.tree.insert("", "end", iid="L:" + name, values=(
                name, "捷運", d["length_km"] or "—", d["stations_count"] or "—",
                self._short(d["construction_start"]), self._short(d["estimated_completion"])))
        for p in self.app.rail_projects:
            opens = [s.get("open") for s in (p.get("new_stations") or []) if s.get("open")]
            self.tree.insert("", "end", iid="R:" + p["name"], values=(
                p["name"], "鐵路", p.get("length_km") or "—", len(p.get("new_stations") or []) or "—",
                self._short(p.get("stage"), 12), self._short(opens[0] if opens else "未定")))
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])

    def show(self, name):
        for iid in ("L:" + name, "R:" + name):
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)
                return

    def _on_select(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        kind, name = sel[0][0], sel[0][2:]
        self._current = (kind, name)
        t = self.text
        t.clear()
        if kind == "L":
            d = self.app.mrt_lines[name]
            t.line(d["full_name"], "h1")
            t.line(d["status"])
            t.line("路線", "h2")
            t.line(d["route"] or "尚未定案")
            parts = []
            if d["length_km"]:
                parts.append("全長約 %s 公里" % d["length_km"])
            if d["stations_count"]:
                parts.append("%s 站" % d["stations_count"])
            for key in ("system", "cost", "depot"):
                if d[key]:
                    parts.append(d[key])
            t.line(" | ".join(parts), "muted")
            t.line("時程", "h2")
            for label, key in [("可行性研究", "feasibility"), ("綜合規劃", "comprehensive_plan"), ("環評", "eia"),
                               ("設計", "design"), ("動工", "construction_start"), ("通車", "estimated_completion")]:
                t.add("%s：" % label, "bold")
                t.line(d[key])
            t.line("進度說明", "h2")
            t.line(d["progress_detail"])
            t.line("議會決議與質詢", "h2")
            t.line(d["council_resolution"])
            t.line("車站", "h2")
            if d["stations"]:
                for s in d["stations"]:
                    t.line("· " + s[0])
                t.line("站位經緯度為依路口與地標估算，誤差可能達數百公尺。", "muted")
            else:
                t.line(d["stations_note"] or "站位尚未公布。", "muted")
            t.sources(d["sources"])
            has_geo = bool(d["stations"])
        else:
            p = next(x for x in self.app.rail_projects if x["name"] == name)
            t.line(p["name"], "h1")
            t.line(p.get("status") or "")
            t.line("範圍", "h2")
            t.line(p.get("route") or "")
            parts = []
            if p.get("length_km"):
                parts.append("約 %s 公里" % p["length_km"])
            if p.get("cost"):
                parts.append("經費 %s" % p["cost"])
            t.line(" | ".join(parts), "muted")
            t.line("進度說明", "h2")
            t.line(p.get("progress_detail") or "")
            if p.get("new_stations"):
                t.line("車站", "h2")
                for s in p["new_stations"]:
                    t.line("· %s%s" % (s["name"], (" | " + s["open"]) if s.get("open") else ""))
            if p.get("council_resolution"):
                t.line("議會決議", "h2")
                t.line(p["council_resolution"])
            t.sources(p.get("sources"))
            has_geo = any(s.get("lat") is not None for s in (p.get("new_stations") or []))
        t.done()
        self.btn_map.config(state="normal" if has_geo else "disabled")
        self.btn_google.config(state="normal" if has_geo else "disabled")

    def _center(self):
        if not self._current:
            return None
        kind, name = self._current
        if kind == "L":
            pts = [(s[1], s[2]) for s in self.app.mrt_lines[name]["stations"]]
        else:
            p = next(x for x in self.app.rail_projects if x["name"] == name)
            pts = [(s["lat"], s["lng"]) for s in (p.get("new_stations") or []) if s.get("lat") is not None]
        if not pts:
            return None
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def _to_map(self):
        c = self._center()
        if c:
            kind, name = self._current
            self.app.show_on_map(c[0], c[1], "line" if kind == "L" else None, name if kind == "L" else None, zoom=26.0)

    def _google(self):
        c = self._center()
        if c:
            kit.open_url(geo.google_terrain_url(c[0], c[1], 13))

    def _news(self):
        name = self._current[1] if self._current else "台南捷運"
        q = name if name.startswith("臺南") or name.startswith("台南") else "台南捷運 " + name
        kit.open_url("https://www.google.com/search?tbm=nws&q=" + quote(q + " 進度"))
