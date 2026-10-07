"""分頁 1：3D 地圖 + 各區房價柱 + 近半年走勢 + 預算／通勤篩選 + 疊圖。"""
import datetime
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core import errlog, address, basemap, geo, landmarks as landmarks_mod, plvr, prices, region, report, roads
from core.charts import TrendChart
from core.view3d import View3D, mix
from . import kit
from .dialogs import MortgageDialog, ReportDialog

# 房價高低：單一色相由淺到深
SEQ = ["#fbe3cf", "#f6b98a", "#eb8a4c", "#d2601f", "#9a3f0c"]
# 半年起伏：藍（跌）— 灰（持平）— 紅（漲）
DIV_NEG, DIV_MID, DIV_POS = "#1c5cab", "#d8d7d2", "#c0302f"
NO_DATA = "#b9bfc6"
TREND_SPAN = 8.0  # 顏色飽和的漲跌幅（%）

MARKER_TYPES = [("商辦", "#2a78d6"), ("商場", "#eb6834"), ("科學園區", "#1baf7a"), ("產業園區", "#eda100"),
                ("重劃區", "#e87ba4"), ("公共建設", "#008300"), ("交通建設", "#4a3aa7"), ("住宅開發", "#e34948")]
MARKER_COLOR = dict(MARKER_TYPES)
MARKER_OTHER = "#6b7178"
NEAR_KM = 6.0
PICK_ON_MAP = "在地圖上點選…"
NO_WORK = "（不設定）"
WORK_COLOR = "#1f2328"
WORK_COLORS = [WORK_COLOR, "#12408a"]        # 上班地點 A、B
WORK_TAGS = ["A", "B"]
CUSTOM_WORK = "自訂位置"
WATCH_COLOR = "#7a3fb5"
FLOOD_URL = "https://dmap.ncdr.nat.gov.tw/1109/map/"

# 路段房價：由便宜到貴（與行政區房價柱的橘色系區隔）
ADDRESS_ZOOM = 120.0     # 門牌圖釘：只知道在哪條路（或聚落）時拉近到看得到那條路周邊
PIN_ZOOM = {"lane": 400.0, "alley_mouth": 400.0, "interp": 250.0, "lane_mouth": 250.0, "near_lane": 200.0}
YEAR_SPAN = 9            # 建設年份滑桿：從今年拉到幾年後
DISTRICT_ZOOM = 40.0     # 點行政區：至少拉近到這個大小（每公里幾個像素），區內的路段看得出來
POINT_ZOOM = 60.0        # 點地標、開發案、車站：至少拉近到這個大小
AUTO_CHECK_MS = 6 * 3600 * 1000   # 程式一直開著時，每 6 小時檢查一次有沒有新一期實價登錄
AUTO_START_MS = 4000              # 開程式後多久開始檢查（先讓畫面出來）
PREFETCH_NOTE = "背景下載道路位置"
PREFETCH_PAUSE_MS = 6000   # 背景補抓道路位置：每一區之間停多久
SEARCH_HINT = "輸入地址或路名，例如：善化區中山路123號"
SEARCH_COLOR = "#d81b60"   # 搜尋位置的圖釘
ROAD_RAMP = ["#fff3b0", "#ffc857", "#f98e3a", "#e2543d", "#a5236f"]
OVERLAYS = [("town", "區界"), ("roads", "路名"), ("liq", "土壤液化"), ("slide", "山崩地滑"), ("fault", "活動斷層")]
FLOOD_URL = "https://dmap.ncdr.nat.gov.tw/1109/map/?group-layer=%E6%B7%B9%E6%B0%B4%E6%BD%9B%E5%8B%A2"   # 國家災害防救科技中心 3D 災害潛勢地圖
OVERLAY_LEGEND = {
    "liq": [("title", "土壤液化潛勢"), ("swatch", "高", "#ff3355"), ("swatch", "中", "#ffc21a"), ("swatch", "低", "#afff2a"),
            ("note", "強震時的可能程度，不是平時危險")],
    "slide": [("title", "山崩與地滑地質敏感區"), ("note", "著色範圍為經濟部公告的地質敏感區")],
    "fault": [("title", "活動斷層"), ("line", "斷層線（虛線為推測）", "#e0201a", False),
              ("note", "紅色帶狀為斷層地質敏感區")],
}


def seq_color(t):
    t = max(0.0, min(1.0, t))
    pos = t * (len(SEQ) - 1)
    i = min(int(pos), len(SEQ) - 2)
    return mix(SEQ[i], SEQ[i + 1], pos - i)


def road_color(t):
    t = max(0.0, min(1.0, t))
    pos = t * (len(ROAD_RAMP) - 1)
    i = min(int(pos), len(ROAD_RAMP) - 2)
    return mix(ROAD_RAMP[i], ROAD_RAMP[i + 1], pos - i)


def trend_color(pct):
    if pct is None:
        return NO_DATA
    t = max(-1.0, min(1.0, pct / TREND_SPAN))
    return mix(DIV_MID, DIV_NEG, -t) if t < 0 else mix(DIV_MID, DIV_POS, t)


def trend_text(pct):
    if pct is None:
        return "樣本不足"
    if abs(pct) < 0.5:
        return "持平 %.1f%%" % abs(pct)
    return ("▲ 漲 %.1f%%" if pct > 0 else "▼ 跌 %.1f%%") % abs(pct)


def parse_number(text):
    """把使用者輸入的數字轉成 float；空白或不是正數回傳 None。"""
    try:
        v = float(str(text).replace(",", "").strip())
    except ValueError:
        return None
    return v if v > 0 else None


class MapTab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=kit.PAGE)
        self.app = app
        self.fonts = app.fonts
        st = app.settings
        self.cat = tk.StringVar(value="all")
        self.metric = tk.StringVar(value="u")
        self.color_mode = tk.StringVar(value="price")
        self.show_lines = tk.BooleanVar(value=True)
        self.show_markers = tk.BooleanVar(value=True)
        self.show_labels = tk.BooleanVar(value=True)
        self.show_legend = tk.BooleanVar(value=bool(st.get("legend", app.win_w >= 1300)))   # 小螢幕預設收起圖例
        self.show_watch = tk.BooleanVar(value=True)
        self.show_roads = tk.BooleanVar(value=bool(st.get("roads", True)))          # 路段房價（選了行政區才畫）
        self.show_landmarks = tk.BooleanVar(value=bool(st.get("landmarks", True)))  # 知名地標的立體圖案
        self.show_projects = tk.BooleanVar(value=bool(st.get("projects", True)))    # 重大建設的立體圖案
        this_year = datetime.date.today().year
        self.year_min, self.year_max = this_year, this_year + YEAR_SPAN
        self.build_year = tk.IntVar(value=this_year)        # 年份滑桿：看某一年時各建設的狀態
        self.v_road_kw = tk.StringVar()
        self._road_data = {}            # 行政區 -> 道路位置（OpenStreetMap）；False 表示這次下載失敗
        self._road_queue = None
        self._road_error = None         # 最近一次道路位置下載失敗的原因（細節另外記在 data/cache/roads/_log.txt）
        self.v_search = tk.StringVar()
        self._addr = None               # 目前搜尋的地址：dict(district, road, lane, alley, num, sub, text)
        self._addr_pending = None       # 路名在好幾個行政區都有：等使用者在「路段」清單挑一區
        self._pin_req = None            # 要標在地圖上的門牌（搜尋的地址，或在「成交」清單點的那一筆）
        self._pin_wait = False          # 那一區的道路位置還在下載，下載好要自動標出來
        self._road_next = None          # 背景補抓時使用者要看的區：補抓完這一區就先下載它
        self._search_pin = None         # 地圖上的門牌圖釘 dict(lat, lng, label, tip, radius)
        self._tx_rows = []              # 「成交」清單每一列對應的成交紀錄
        self._auto_job = None           # 自動更新實價登錄的下一次檢查
        self._update_quiet = False      # 目前的實價登錄下載是不是自動更新（不跳視窗）
        self._update_before = 0
        self._road_expect = None        # 程式剛剛在「路段」清單選的那一列（用來分辨是不是使用者點的）
        self._road_quiet = False        # 目前這次道路位置下載是不是背景補抓
        self._prefetch_fails = 0
        self._prefetch_started = False
        self._roads = []
        self.hires = tk.BooleanVar(value=bool(st.get("hires", True)))
        self.marker_min = tk.StringVar(value="影響 3 以上")
        self.ov_vars = {lid: tk.BooleanVar(value=False) for lid, _ in OVERLAYS}
        self.v_budget = tk.StringVar(value=("%g" % st["budget"]) if st.get("budget") else "")
        # 上班地點 A、B：各自的名稱、公里數、自己在地圖上點的位置 [lat, lng]
        self.works = []
        for key in ("work", "work2"):
            self.works.append({"key": key, "name": tk.StringVar(value=st.get(key) or NO_WORK),
                               "km": tk.StringVar(value=("%g" % st[key + "_km"]) if st.get(key + "_km") else ""),
                               "pos": st.get(key + "_pos"), "cb": None})
        self.v_work, self.v_km = self.works[0]["name"], self.works[0]["km"]
        self.v_work2, self.v_km2 = self.works[1]["name"], self.works[1]["km"]
        self.liq_opacity = tk.DoubleVar(value=float(st.get("liq_opacity", basemap.LAYERS["liq"]["opacity"])))
        self._opacity_job = None
        self.current = prices.CITY
        self._sort = ("u", True)
        self._queue = None
        self._bm_queue = None
        self._bm_auto = False
        self._bm_layer = "photo"
        self._road_filter = None
        self.base = tk.StringVar(value="terrain")
        self._build()
        self.refresh_all()

    # ------------------------------------------------------------------ 版面
    def _build(self):
        f = self.fonts
        st = self.app.settings

        def cap(parent, text):
            tk.Label(parent, text=text, bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=(0, 4))

        def group(parent, title, var, options, cmd):
            g = tk.Frame(parent, bg=kit.SURFACE)
            cap(g, title)
            for value, label in options:
                ttk.Radiobutton(g, text=label, value=value, variable=var, command=cmd).pack(side="left", padx=2)
            return g

        def strip():
            """一列工具列：外框負責留白，裡面的 FlowFrame 在放不下時自動換行。"""
            outer = tk.Frame(self, bg=kit.SURFACE, padx=10, pady=5)
            flow = kit.FlowFrame(outer, bg=kit.SURFACE, gap=(9, 5))
            flow.pack(fill="x")
            return outer, flow

        # ---- 主列：永遠顯示
        bar_outer, bar = strip()
        bar_outer.pack(fill="x")
        self._bar_outer = bar_outer
        bar.add(group(bar, "房型", self.cat, prices.CATS, self._on_cat))
        bar.add(group(bar, "柱高", self.metric, [("u", "單價"), ("t", "總價")], self.refresh_all))
        bar.add(group(bar, "顏色", self.color_mode, [("price", "價格高低"), ("trend", "近半年漲跌")], self.refresh_all))
        bar.add(group(bar, "底圖", self.base, [("satellite", "衛星影像"), ("terrain", "立體地形")], self._on_base))
        # width=-1：按鈕寬度跟著文字走（ttk 預設最少 11 個字寬，會把主列擠到換行）
        self.btn_layers = bar.add(ttk.Button(bar, width=-1, command=lambda: self._toggle_panel("layers")))
        self.btn_cond = bar.add(ttk.Button(bar, width=-1, command=lambda: self._toggle_panel("cond")))

        # ---- 可收合：圖層與疊圖
        lay_outer, lay = strip()
        g = tk.Frame(lay, bg=kit.SURFACE)
        cap(g, "圖層")
        ttk.Checkbutton(g, text="捷運", variable=self.show_lines, command=self._layers).pack(side="left", padx=2)
        ttk.Checkbutton(g, text="開發案", variable=self.show_markers, command=self._layers).pack(side="left", padx=2)
        cb = ttk.Combobox(g, textvariable=self.marker_min, state="readonly", width=11, font=f.base,
                          values=["全部", "影響 3 以上", "影響 4 以上", "影響 5"])
        cb.pack(side="left", padx=(0, 6))
        cb.bind("<<ComboboxSelected>>", lambda e: (self.refresh_markers(), self.refresh_landmarks()))
        ttk.Checkbutton(g, text="看屋", variable=self.show_watch, command=self.refresh_pins).pack(side="left", padx=2)
        ttk.Checkbutton(g, text="標籤", variable=self.show_labels, command=self._layers).pack(side="left", padx=2)
        ttk.Checkbutton(g, text="路段房價", variable=self.show_roads, command=self._on_show_roads).pack(side="left", padx=2)
        ttk.Checkbutton(g, text="地標", variable=self.show_landmarks, command=self._on_show_landmarks).pack(side="left", padx=2)
        ttk.Checkbutton(g, text="重大建設 3D", variable=self.show_projects,
                        command=self._on_show_projects).pack(side="left", padx=2)
        lay.add(g)
        g = tk.Frame(lay, bg=kit.SURFACE)
        cap(g, "疊圖")
        for lid, label in OVERLAYS:
            ttk.Checkbutton(g, text=label, variable=self.ov_vars[lid],
                            command=lambda i=lid: self._toggle_overlay(i)).pack(side="left", padx=2)
        lay.add(g)
        g = tk.Frame(lay, bg=kit.SURFACE)
        cap(g, "液化濃淡")
        ttk.Scale(g, from_=0.2, to=1.0, variable=self.liq_opacity, length=90,
                  command=lambda v: self._on_opacity()).pack(side="left")
        lay.add(g)
        lay.add(ttk.Checkbutton(lay, text="高解析影像", variable=self.hires, command=self._on_hires))
        lay.add(ttk.Button(lay, text="淹水潛勢↗", command=lambda: kit.open_url(FLOOD_URL)))

        # ---- 可收合：預算與通勤
        cond_outer, cond = strip()
        g = tk.Frame(cond, bg=kit.SURFACE)
        tk.Label(g, text="總價預算", bg=kit.SURFACE, fg=kit.INK, font=f.base).pack(side="left")
        e1 = ttk.Entry(g, textvariable=self.v_budget, width=7, font=f.base, justify="right")
        e1.pack(side="left", padx=3)
        tk.Label(g, text="萬", bg=kit.SURFACE, fg=kit.INK, font=f.base).pack(side="left")
        ttk.Button(g, text="房貸試算", command=self.open_mortgage).pack(side="left", padx=(6, 0))
        cond.add(g)
        entries = [e1]
        for i, slot in enumerate(self.works):
            g = tk.Frame(cond, bg=kit.SURFACE)
            tk.Label(g, text="上班地點 %s" % WORK_TAGS[i], bg=kit.SURFACE, fg=kit.INK, font=f.base).pack(side="left")
            slot["cb"] = ttk.Combobox(g, textvariable=slot["name"], state="readonly", width=18, font=f.base,
                                      values=self._work_values(i))
            slot["cb"].pack(side="left", padx=3)
            slot["cb"].bind("<<ComboboxSelected>>", lambda e, k=i: self._on_work(k))
            e = ttk.Entry(g, textvariable=slot["km"], width=4, font=f.base, justify="right")
            e.pack(side="left", padx=(4, 3))
            tk.Label(g, text="公里內", bg=kit.SURFACE, fg=kit.INK, font=f.base).pack(side="left")
            cond.add(g)
            entries.append(e)
        self.cb_work, self.cb_work2 = self.works[0]["cb"], self.works[1]["cb"]
        for e in entries:
            e.bind("<Return>", lambda ev: self.apply_filters())
            e.bind("<FocusOut>", lambda ev: self.apply_filters())
        cond.add(ttk.Button(cond, text="清除條件", command=self.clear_filters))
        self.lbl_match = tk.Label(cond, text="")      # 只用來記錄「符合 N 區」；實際顯示在「篩選」按鈕上

        self._flows = [bar, lay, cond]
        self._panels = {"layers": [lay_outer, self.btn_layers, "圖層", False],
                        "cond": [cond_outer, self.btn_cond, "篩選", False]}
        # 上次開著的面板照舊；設了條件的話條件列一定打開，才看得到目前的條件
        self._show_panel("layers", bool(st.get("panel_layers", False)))
        self._show_panel("cond", bool(st.get("panel_cond", False)) or self.filters_active())

        # ---- 狀態列（最下方，整個視窗寬，文字不會被工具列擠掉）
        status = tk.Frame(self, bg=kit.SURFACE, padx=10, pady=2)
        status.pack(side="bottom", fill="x")
        self.btn_update = ttk.Button(status, text="更新實價登錄", command=self.start_update)
        self.btn_update.pack(side="right")
        self.auto_update = tk.BooleanVar(value=bool(self.app.settings.get("auto_update", True)))
        ttk.Checkbutton(status, text="自動更新", variable=self.auto_update,
                        command=self._on_auto_update).pack(side="right", padx=(0, 8))
        self.lbl_source = tk.Label(status, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small, anchor="w")
        self.lbl_source.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(self, mode="determinate")

        self.paned = tk.PanedWindow(self, orient="horizontal", bg=kit.BORDER, sashwidth=5, bd=0)
        self.paned.pack(fill="both", expand=True)

        # ---- 左：3D 地圖
        left = tk.Frame(self.paned, bg=kit.PAGE)
        self.view = View3D(left, self.app.terrain, font_family=f.family, font_size=f.size,
                           quality=self.app.settings.get("quality", 2 if kit.IS_ANDROID else 1))
        self.view.pack(fill="both", expand=True)
        if self.app.county != "D":
            # 其他縣市：總覽以成交集中的區為主（佔近一年成交 85% 的那幾區），山區、離島可以拖過去看
            t = self.app.terrain
            self.view.set_home(0.0, 0.0, (t.east - t.west) * geo.KM_PER_DEG_LNG * 1.0,
                               (t.north - t.south) * geo.KM_PER_DEG_LAT * 1.0)
            core = self._core_districts()
            if core:
                xs, ys = zip(*[geo.to_xy(d["lat"], d["lng"]) for d in core])
                keep = self.view.MIN_ZOOM                  # 最小縮放仍以整個縣市為準，才拉得遠看全縣
                self.view.set_home((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                                   max(xs) - min(xs) + 10, max(ys) - min(ys) + 10)
                self.view.MIN_ZOOM = keep
        self.view.on_pick = self.on_pick
        self.view.on_status = lambda text: self.lbl_source.config(text=text)
        self.view.show["legend"] = self.show_legend.get()
        self.view.show["roads"] = self.show_roads.get()
        self.view.show["landmarks"] = True     # 地標、重大建設各自有開關，在 refresh_landmarks 裡決定要畫哪些
        self.view.on_legend_toggle = self._on_legend_toggle
        self.view.raster.detail = self.hires.get()
        self.view.raster.set_opacity("liq", self.liq_opacity.get())
        self._build_search()
        self._init_basemap()
        self.after(AUTO_START_MS, self.check_auto_update)
        ctl_outer = tk.Frame(left, bg=kit.SURFACE, padx=6, pady=5)
        # 先排控制列、地圖拿剩下的高度：畫面矮（字放大、兩列面板都打開）時縮的是地圖，按鈕不會被切掉
        ctl_outer.pack(side="bottom", fill="x", before=self.view)
        ctl = kit.FlowFrame(ctl_outer, bg=kit.SURFACE, gap=(2, 4))
        ctl.pack(fill="x")
        self._flows.append(ctl)
        for text, cmd in [("左轉", lambda: self.view.rotate_by(d_az=-15)), ("右轉", lambda: self.view.rotate_by(d_az=15)),
                          ("俯視", lambda: self.view.rotate_by(d_pitch=10)), ("平視", lambda: self.view.rotate_by(d_pitch=-10)),
                          ("放大", lambda: self.view.zoom_by(1.3)), ("縮小", lambda: self.view.zoom_by(1 / 1.3)),
                          ("正上方", self.view.top_view), ("重置", self.view.reset_view)]:
            ctl.add(ttk.Button(ctl, text=text, command=cmd, width=len(text) * 2 + 1))
        self.btn_mode = ctl.add(ttk.Button(ctl, text="拖曳：平移", command=self._toggle_mode, width=10))
        g = tk.Frame(ctl, bg=kit.SURFACE)
        tk.Label(g, text="地形誇張", bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=(8, 2))
        self.zex = tk.DoubleVar(value=self.view.zex)
        ttk.Scale(g, from_=1, to=10, variable=self.zex, length=90,
                  command=lambda v: self.view.set_exaggeration(float(v))).pack(side="left")
        ctl.add(g)
        # 年份滑桿：拉到某一年，重大建設的圖案就顯示那一年的狀態（完工／施工中／規劃中）
        g = tk.Frame(ctl, bg=kit.SURFACE)
        tk.Label(g, text="建設年份", bg=kit.SURFACE, fg=kit.MUTED, font=f.small).pack(side="left", padx=(8, 2))
        self.year_scale = ttk.Scale(g, from_=self.year_min, to=self.year_max, length=110)
        self.year_scale.set(self.build_year.get())
        self.year_scale.config(command=self._on_year)
        self.year_scale.pack(side="left")
        self.lbl_year = tk.Label(g, text="%d 年" % self.build_year.get(), bg=kit.SURFACE, fg=kit.INK, font=f.small, width=7)
        self.lbl_year.pack(side="left")
        self.year_group = g
        ctl.add(g)
        self.paned.add(left, stretch="always", minsize=320)

        # ---- 右：資訊面板
        right = tk.Frame(self.paned, bg=kit.SURFACE)
        self.paned.add(right, stretch="never", minsize=300, width=self.app.panel_width)

        head = tk.Frame(right, bg=kit.SURFACE, padx=12, pady=6)
        head.pack(fill="x")
        self.lbl_name = tk.Label(head, text="", bg=kit.SURFACE, fg=kit.INK, font=f.h1, anchor="w")
        self.lbl_name.pack(side="left")
        ttk.Button(head, text="全市總覽", command=lambda: self.select_district(prices.CITY)).pack(side="right")
        self.btn_compare = ttk.Button(head, text="加入比較", command=self._add_compare)
        self.btn_compare.pack(side="right", padx=4)
        self.lbl_sub = tk.Label(right, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small, anchor="w",
                                justify="left", padx=12, wraplength=self.app.panel_width - 28)
        self.lbl_sub.pack(fill="x")

        kpis = tk.Frame(right, bg=kit.SURFACE, padx=8, pady=3)
        kpis.pack(fill="x")
        self.kpi = {}
        for col, (key, title) in enumerate([("u", "中位單價"), ("t", "中位總價"), ("n", "成交件數"), ("trend", "近半年起伏")]):
            tile = tk.Frame(kpis, bg="#f6f7f9", padx=8, pady=4, highlightthickness=1, highlightbackground=kit.BORDER)
            tile.grid(row=col // 2, column=col % 2, sticky="nsew", padx=3, pady=3)
            tk.Label(tile, text=title, bg="#f6f7f9", fg=kit.MUTED, font=f.small, anchor="w").pack(fill="x")
            line = tk.Frame(tile, bg="#f6f7f9")
            line.pack(fill="x")
            sw = tk.Canvas(line, width=12, height=12, bg="#f6f7f9", highlightthickness=0)
            if key == "trend":
                sw.pack(side="left", padx=(0, 5))
            val = tk.Label(line, text="—", bg="#f6f7f9", fg=kit.INK, font=f.kpi, anchor="w")
            val.pack(side="left")
            unit = tk.Label(line if key != "trend" else tile, text="", bg="#f6f7f9", fg=kit.MUTED, font=f.small, anchor="w")
            if key == "trend":
                unit.pack(fill="x")
            else:
                unit.pack(side="left", padx=(4, 0), pady=(6, 0))
            self.kpi[key] = (val, unit, sw)
        kpis.columnconfigure(0, weight=1, uniform="k")
        kpis.columnconfigure(1, weight=1, uniform="k")

        self.lbl_insight = tk.Label(right, text="", bg="#eef6f5", fg=kit.INK, font=f.small, anchor="w",
                                    justify="left", padx=10, pady=4, wraplength=self.app.panel_width - 28)
        self.lbl_insight.pack(fill="x", padx=11, pady=(2, 0))

        def on_resize(e):
            self.lbl_sub.config(wraplength=max(160, e.width - 28))
            self.lbl_insight.config(wraplength=max(160, e.width - 44))
        right.bind("<Configure>", on_resize)

        # 走勢圖有兩份：一份固定在面板上，一份在下方分頁裡。畫面高度相對字級不夠時（小螢幕、平板、字放大）
        # 只用分頁那一份，排行等清單才有地方顯示；由 _apply_panel_mode() 切換。
        self.chart = TrendChart(right, font_family=f.family, font_size=max(7, f.size - 1), height=self._chart_height(f.size))

        links_outer = tk.Frame(right, bg=kit.SURFACE, padx=9, pady=4)
        # 連結按鈕固定在面板最下方，而且最先分配高度：畫面再矮也不會被切掉
        links_outer.pack(side="bottom", fill="x", before=head)
        links = kit.FlowFrame(links_outer, bg=kit.SURFACE, gap=(4, 4))     # 放不下時自動換行
        links.pack(fill="x")
        self._flows.append(links)
        self._links = links_outer
        links.add(ttk.Button(links, text="Google 地形圖", command=lambda: self._google("terrain")))
        links.add(ttk.Button(links, text="淹水潛勢", command=lambda: kit.open_url(FLOOD_URL)))
        links.add(ttk.Button(links, text="Google 衛星圖", command=lambda: self._google("satellite")))
        links.add(ttk.Button(links, text="通勤路線", command=self._google_route))
        self.btn_report = links.add(ttk.Button(links, text="行情報告", command=self.open_report))

        self.sub = ttk.Notebook(right)
        self.sub.pack(fill="both", expand=True, padx=8, pady=8)
        self.chart_tab = TrendChart(self.sub, font_family=f.family, font_size=max(7, f.size - 1), height=self._chart_height(f.size))
        self.sub.add(self.chart_tab, text="走勢")

        # 排行
        rank_frame, self.rank = kit.scrolled(self.sub, lambda p: ttk.Treeview(
            p, columns=("d", "u", "t", "n", "km", "km2", "tr"), show="headings", height=8))
        for col, text, width, anchor in [("d", "行政區", 70, "w"), ("u", "單價", 50, "e"), ("t", "總價", 58, "e"),
                                         ("n", "件數", 46, "e"), ("km", "距離", 50, "e"), ("km2", "距B", 50, "e"),
                                         ("tr", "半年起伏", 92, "e")]:
            self.rank.heading(col, text=text, command=lambda c=col: self._sort_by(c))
            self.rank.column(col, width=width, anchor=anchor, stretch=True)
        self.rank.tag_configure("low", foreground="#8a929b")
        self.rank.tag_configure("out", foreground="#b3b9c0")
        self.rank.bind("<<TreeviewSelect>>", self._on_rank_select)
        self.sub.add(rank_frame, text="排行")

        # 路段
        road_frame = tk.Frame(self.sub, bg=kit.SURFACE)
        self.lbl_road = tk.Label(road_frame, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small, anchor="w",
                                 justify="left", wraplength=360, padx=6, pady=4)
        road_top = tk.Frame(road_frame, bg=kit.SURFACE, padx=6, pady=3)
        road_top.pack(fill="x")
        tk.Label(road_top, text="搜尋路名", bg=kit.SURFACE, fg=kit.INK, font=f.base).pack(side="left")
        ent = ttk.Entry(road_top, textvariable=self.v_road_kw, width=12, font=f.base)
        ent.pack(side="left", padx=4)
        ent.bind("<KeyRelease>", lambda e: self._fill_roads(self.current))
        ttk.Button(road_top, text="清除", width=-1, command=lambda: (self.v_road_kw.set(""), self._fill_roads(self.current))
                   ).pack(side="left")
        self.lbl_road.pack(fill="x")
        road_inner, self.road = kit.scrolled(road_frame, lambda p: ttk.Treeview(
            p, columns=("dist", "name", "n", "u", "t", "last"), show="headings", height=6))
        for col, text, width, anchor in [("dist", "行政區", 62, "w"), ("name", "路段", 110, "w"), ("n", "件數", 44, "e"),
                                         ("u", "萬/坪", 54, "e"), ("t", "總價(萬)", 66, "e"), ("last", "最近", 56, "e")]:
            self.road.heading(col, text=text)
            self.road.column(col, width=width, anchor=anchor, stretch=(col == "name"))
        self.road.tag_configure("low", foreground="#8a929b")
        road_inner.pack(fill="both", expand=True)
        self.road.bind("<<TreeviewSelect>>", self._on_road_select)
        self.sub.add(road_frame, text="路段")
        self._road_tab = road_frame

        info_frame, self.info = kit.scrolled(self.sub, lambda p: kit.RichText(p, f, height=8))
        self.sub.add(info_frame, text="捷運與開發")

        tx_frame = tk.Frame(self.sub, bg=kit.SURFACE)
        tx_top = tk.Frame(tx_frame, bg=kit.SURFACE)
        tx_top.pack(fill="x")
        self.btn_tx_all = ttk.Button(tx_top, text="顯示全區", command=self._clear_road_filter)
        self.lbl_tx = tk.Label(tx_top, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small, anchor="w",
                               justify="left", wraplength=300, padx=6, pady=4)
        self.lbl_tx.pack(side="left", fill="x", expand=True)
        tx_inner, self.tx = kit.scrolled(tx_frame, lambda p: ttk.Treeview(
            p, columns=("date", "type", "addr", "tw", "u", "ping", "age"), show="headings", height=6))
        for col, text, width, anchor in [("date", "日期", 84, "w"), ("type", "類型", 64, "w"), ("addr", "地址／建案", 190, "w"),
                                         ("tw", "總價(萬)", 70, "e"), ("u", "萬/坪", 56, "e"), ("ping", "建坪", 52, "e"),
                                         ("age", "屋齡", 46, "e")]:
            self.tx.heading(col, text=text)
            self.tx.column(col, width=width, anchor=anchor, stretch=(col == "addr"))
        self.tx.tag_configure("exact", background="#fbd9a8")       # 搜尋地址：同門牌
        self.tx.bind("<<TreeviewSelect>>", self._on_tx_select)     # 點一列：在地圖上標出大概位置
        self.tx.tag_configure("lane", background="#fdf1dc")        # 同一條巷
        tx_inner.pack(fill="both", expand=True)
        self.sub.add(tx_frame, text="成交")
        self._tx_tab = tx_frame

        pick_frame, self.pick_text = kit.scrolled(self.sub, lambda p: kit.RichText(p, f, height=8))
        self.sub.add(pick_frame, text="點選")
        self._pick_tab = pick_frame
        self._info_tab = info_frame
        self.compact_panel = None
        self._apply_panel_mode()

    # ------------------------------------------------------------------ 資料 -> 畫面
    def refresh_landmarks(self):
        """地圖上的立體小圖案：知名地標，加上重大建設（依年份滑桿顯示完工／施工中／規劃中）。"""
        items = []
        if self.show_landmarks.get():
            for lm in self.app.landmarks:
                item = dict(lm)
                item["label"] = lm["name"]
                item["tip"] = "%s | %s\n%s" % (lm["name"], lm.get("district") or "", lm.get("note") or "")
                items.append(item)
        items.extend(self._project_items())
        self.view.set_landmarks(items)
        self.view.legend_projects = self._project_legend() if self.show_projects.get() else []
        self.view.request_redraw()

    def projects(self):
        """有 build 欄位（時程與圖案）的重大建設，依影響度過濾（和「開發案」標記用同一個門檻）。"""
        th = self._marker_threshold()
        return [it for it in self.app.intel
                if it.get("build") and it.get("lat") is not None and (it.get("impact_level") or 0) >= th]

    def _project_items(self):
        if not self.show_projects.get():
            return []
        year = self.build_year.get()
        out = []
        for it in self.projects():
            b = it["build"]
            state = landmarks_mod.build_state(b, year)
            short = it["name"].split("（")[0].split("—")[0][:14]
            lvl = it.get("impact_level") or 2
            when = ("預計 %d 完工" % b["done"]) if b.get("done") and b["done"] > year and state != "完工" else ""
            out.append({"id": it["id"], "hit": "project", "model": b["model"], "state": state,
                        "lat": it["lat"], "lng": it["lng"], "rank": 1 if lvl >= 5 else (2 if lvl >= 4 else 3),
                        "size": 0.9, "name": it["name"],
                        "label": short if state == "完工" else "%s（%s）" % (short, when or state),
                        "tip": "%s\n%d 年：%s｜%s" % (it["name"][:34], year, state, b.get("note") or "")})
        return out

    def _project_legend(self):
        return [("title", "重大建設（%d 年的狀態）" % self.build_year.get()),
                ("swatch", "完工／營運中", "#9aa5ae"),
                ("swatch", "施工中（旁邊有黃色塔吊）", "#f2b632"),
                ("swatch", "規劃中（淡色）", "#e8ebee"),
                ("note", "下方「建設年份」可以拉到未來看")]

    def _on_show_projects(self):
        self.app.settings["projects"] = self.show_projects.get()
        kit.save_settings(self.app.settings)
        self.refresh_markers()
        self.refresh_landmarks()

    def _on_year(self, value):
        year = int(round(float(value)))
        self.lbl_year.config(text="%d 年" % year)
        if year == self.build_year.get():
            return
        self.build_year.set(year)
        self.refresh_landmarks()
        if self.view.selected and self.view.selected[0] == "project":
            self.on_pick("project", self.view.selected[1], fly=False)

    # ------------------------------------------------------------------ 地址搜尋
    def _build_search(self):
        """地圖上方的搜尋框：輸入地址或路名，地圖滑到那一段，右邊列出那一段的成交價格。"""
        f = self.fonts
        box = tk.Frame(self.view, bg="#ffffff", highlightthickness=1, highlightbackground="#c9ced4")
        self.btn_search = ttk.Button(box, text="搜尋", width=5, command=self.search_address)
        self.btn_search.pack(side="right", padx=(2, 3), pady=3)
        self.ent_search = tk.Entry(box, textvariable=self.v_search, font=f.base, relief="flat", bd=0,
                                   bg="#ffffff", fg="#9aa1a9", insertbackground=kit.INK)
        self.ent_search.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=3, ipady=2)
        self.v_search.set(SEARCH_HINT)
        self.ent_search.bind("<FocusIn>", self._search_focus_in)
        self.ent_search.bind("<FocusOut>", self._search_focus_out)
        self.ent_search.bind("<Return>", lambda e: self.search_address())
        self.ent_search.bind("<KP_Enter>", lambda e: self.search_address())
        self.ent_search.bind("<Escape>", lambda e: (self.v_search.set(""), self.view.focus_set()))
        self.search_box = box
        self.view.topbar = box

    def _search_focus_in(self, _e=None):
        if self.v_search.get() == SEARCH_HINT:
            self.v_search.set("")
        self.ent_search.config(fg=kit.INK)

    def _search_focus_out(self, _e=None):
        if not self.v_search.get().strip():
            self.ent_search.config(fg="#9aa1a9")
            self.v_search.set(SEARCH_HINT)

    def _say(self, text):
        self.lbl_source.config(text=text)

    def search_address(self, text=None):
        """搜尋地址、路名、行政區或地標；回傳做了什麼（"landmark"、"district"、"address"、"choose"、"none"）。"""
        if text is not None:
            self.v_search.set(text)
            self.ent_search.config(fg=kit.INK)
        text = self.v_search.get().strip()
        if not text or text == SEARCH_HINT:
            return "none"
        app = self.app
        names = [d["name"] for d in app.districts]
        q = address.parse(text, names)
        s = q["text"]
        self._addr_pending = None
        # 1) 只有行政區
        only = s if s in names else (s + "區" if s + "區" in names else None)
        if only or (q["district"] and not q["road"]):
            self.select_district(only or q["district"])
            self._say("已移到%s。右邊可以看這一區的走勢、排行與各路段行情。" % (only or q["district"]))
            return "district"
        # 2) 地標名稱（輸入的不是門牌才比對）
        if q["num"] is None and q["lane"] is None and q["district"] is None:
            for lm in app.landmarks:
                if len(s) >= 2 and (s in lm["name"] or lm["name"] in s):
                    self._drop_search()
                    self.on_pick("landmark", lm["id"])
                    self._say("已移到地標「%s」。" % lm["name"])
                    return "landmark"
        if not q["road"]:
            self._say("看不出這是哪一條路。請輸入像「善化區中山路123號」「大同路一段」這樣的地址或路名。")
            return "none"
        if not app.txs:
            self._say("地址搜尋需要逐筆成交資料：請先按右下角的「更新實價登錄」下載一次。")
            return "none"
        # 3) 沒寫行政區：從成交資料找這條路在哪幾區
        if q["district"] is None:
            on_road = [x for x in app.txs if prices.road_of(x["addr"], x["dist"]) == q["road"]]
            found = sorted({x["dist"] for x in on_road})
            if len(found) > 1 and q["lane"] is not None:     # 有寫巷號：只有一區有這條巷的成交就是那一區
                narrow = sorted({x["dist"] for x in on_road if address.tx_parts(x)[1] == q["lane"]})
                found = narrow if len(narrow) == 1 else found
            if not found and not roads.search(app.txs, q["road"], self.cat.get(), app.book.windows["y12"][0], limit=1):
                self._say("實價登錄裡找不到路名含「%s」的成交。請確認路名，或加上行政區再試。" % q["road"])
                return "none"
            if len(found) == 1:
                q["district"] = found[0]
            else:
                self.select_district(prices.CITY, focus=False)
                self._addr_pending = q
                self.v_road_kw.set(q["road"])
                self._fill_roads(prices.CITY)
                self.sub.select(self._road_tab)
                if found:
                    self._say("有 %d 個行政區都有「%s」：請在右邊的清單點要看的那一區（或在地址前面加上行政區再搜尋）。" % (
                        len(found), q["road"]))
                else:
                    self._say("沒有剛好叫「%s」的路段，右邊列出路名相近的 %d 個路段，點一列就會過去。" % (q["road"], len(self._roads)))
                return "choose"
        self.show_address(q)
        return "address"

    def show_address(self, q):
        """地圖移到這個地址所在的路段（有巷就到那條巷），右邊「成交」分頁依門牌遠近列出價格。"""
        d = q["district"]
        self._addr_pending = None
        if self.current != d:
            self.select_district(d)                 # 先滑到那一區；道路位置沒下載過會在這裡開始下載
        self._addr = q
        self._road_filter = q["road"]
        self.view.select("road", q["road"])
        self._fill_tx(d)
        self.sub.select(self._tx_tab)
        self._select_road_row(q["road"], d)
        self._focus_search()

    def _ensure_road_data(self, name, retry=False):
        """這一區的道路位置（已下載或快取裡有）；沒有就開始下載並回傳 None。"""
        data = self._road_data.get(name)
        if data is None or (data is False and retry):
            data = roads.load(name)
            if data is not None:
                self._road_data[name] = data
            elif self.app.auto_download or retry:
                self._road_data.pop(name, None)
                if self._road_queue is not None and self._road_quiet:
                    self._road_next = name          # 正在背景補抓別區：抓完馬上換這一區
                    self._road_quiet = False        # 狀態列改顯示進度
                else:
                    self._start_roads(name)
        return data or None

    def _focus_search(self, retry=True):
        """搜尋地址後：把畫面移到那個門牌的大概位置並插上圖釘。"""
        q = self._addr
        if not q or q["district"] != self.current:
            return
        self._pin_req = {"dist": q["district"], "q": q, "label": address.describe(q), "search": True,
                         "what": "%s %s" % (q["district"], address.describe(q))}
        self._show_pin(retry=retry)

    def _on_tx_select(self, _e=None):
        """點「成交」清單的一列：在地圖上用圖釘標出這筆成交的大概位置。"""
        sel = self.tx.selection()
        if not sel or not sel[0].isdigit() or int(sel[0]) >= len(self._tx_rows):
            return
        x = self._tx_rows[int(sel[0])]
        q = dict(zip(("road", "lane", "alley", "num", "sub"), address.tx_parts(x)))
        where = address.normalize(x["addr"]).replace(x["dist"], "", 1)
        if not q["road"]:
            self._say("看不出「%s」是哪一條路，無法標在地圖上。" % where)
            return
        q["district"] = x["dist"]
        self._pin_req = {"dist": x["dist"], "q": q, "search": False, "what": "%s%s" % (x["dist"], where),
                         "label": "%s %s萬" % (address.describe(dict(q, road=q["road"])).replace(" ", ""), kit.fmt_num(x["tw"]))}
        self._show_pin(retry=True)

    def _show_pin(self, retry=True):
        """依 self._pin_req 插上圖釘並把地圖移過去；那一區的道路位置還沒下載就先下載，好了再自動移過去。"""
        req = self._pin_req
        self._pin_wait = False
        if not req:
            return
        what, dist = req["what"], req["dist"]
        tail = "價格清單在右邊。" if req["search"] else ""
        data = self._ensure_road_data(dist, retry=retry)
        if not data:
            self._pin_wait = self._road_queue is not None
            if self._pin_wait:
                self._say("%s：%s正在下載%s的道路位置（只有第一次需要，約 10~40 秒），好了會自動標出來。" % (what, tail, dist))
            elif self._road_data.get(dist) is False:
                self._say("%s：%s道路位置下載失敗（公開伺服器忙線），暫時無法標在地圖上；過幾分鐘再試一次會重新下載。" % (what, tail))
            else:
                self._say("%s：%s這一區的道路位置還沒下載，暫時無法標在地圖上。" % (what, tail))
            return
        pos = address.position(data, req["q"])
        if pos is None:
            self._search_pin = None
            self.refresh_pins()
            self._say("%s：%sOpenStreetMap 上找不到「%s」的位置，無法標在地圖上。" % (what, tail, req["q"]["road"]))
            return
        self._search_pin = {"lat": pos["lat"], "lng": pos["lng"], "label": req["label"], "radius": pos["radius_km"],
                            "tip": "%s\n位置：%s" % (what, pos["note"])}
        self.refresh_pins()
        if req["search"] and self.show_roads.get():
            self.refresh_roads()                    # 近一年沒有成交的路也要標出來
        if dist == self.current and self._road_filter:
            self.view.select("road", self._road_filter)
        zoom = PIN_ZOOM.get(pos["precision"], ADDRESS_ZOOM)    # 位置越準，拉得越近
        self.view.fly_to(pos["lat"], pos["lng"], zoom=max(self.view.zoom, zoom))
        self._say("已標出 %s（%s）。%s" % (what, pos["note"], "右邊「成交」是這一段的價格清單。" if req["search"] else ""))

    def _drop_search(self):
        """離開地址搜尋的狀態：拿掉圖釘與門牌排序。"""
        had = self._addr is not None or self._search_pin is not None
        self._addr, self._pin_req, self._pin_wait, self._search_pin = None, None, False, None
        if had:
            self.refresh_pins()

    def refresh_all(self):
        self.refresh_landmarks()
        self.refresh_lines()
        self.refresh_markers()
        self.refresh_pins()
        self.refresh_bars()
        self.refresh_rank()
        self.show_district(self.current)
        self.lbl_source.config(text=self.app.book.describe_source())

    def _on_cat(self):
        self._road_filter = self._addr["road"] if self._addr else None     # 搜尋地址後換房型：仍然看同一個地址
        self.refresh_all()
        if self._addr:
            self.view.select("road", self._addr["road"])

    def _layers(self):
        self.view.show["lines"] = self.show_lines.get()
        self.view.show["markers"] = self.show_markers.get()
        self.view.show["labels"] = self.show_labels.get()
        self.view.show["legend"] = self.show_legend.get()
        self.view.request_redraw()

    def _show_panel(self, name, on):
        outer, btn, title, _ = self._panels[name]
        self._panels[name][3] = on
        note = ""
        if name == "cond" and getattr(self, "lbl_match", None) is not None and self.lbl_match.cget("text"):
            note = "（%s）" % self.lbl_match.cget("text")
        btn.config(text="%s%s %s" % (title, note, "▲" if on else "▼"))
        if on:
            if name == "layers" or not self._panels["layers"][3]:
                outer.pack(fill="x", after=self._bar_outer)
            else:
                outer.pack(fill="x", after=self._panels["layers"][0])
        else:
            outer.pack_forget()

    def _toggle_panel(self, name):
        self._show_panel(name, not self._panels[name][3])
        self.app.settings["panel_" + name] = self._panels[name][3]
        kit.save_settings(self.app.settings)
        self.after_idle(self.relayout)

    def relayout(self):
        """字級或視窗大小改變後，重新排一次會自動換行的工具列。"""
        for flow in self._flows:
            flow.relayout()

    def _apply_panel_mode(self):
        """依「視窗高度可以放幾行字」決定右側面板的排法：放得下就把走勢圖固定在上面，放不下就收進分頁。"""
        compact = self.app.win_h / float(max(1, self.fonts.base.metrics("linespace"))) < 42
        if compact == self.compact_panel:
            return
        self.compact_panel = compact
        if compact:
            self.chart.pack_forget()
            self.sub.add(self.chart_tab)             # 重新顯示「走勢」分頁（位置不變）
            self.sub.select(self.chart_tab)
        else:
            self.chart.pack(fill="x", padx=11, pady=(4, 6), after=self.lbl_insight)
            self.sub.hide(self.chart_tab)
        self.sub.tab(self._info_tab, text="建設" if compact else "捷運與開發")

    def _chart_height(self, size):
        """走勢圖高度：字放大時跟著加高，座標軸的數字才不會擠在一起。"""
        return self.app.chart_height + max(0, size - 10) * 6

    def _on_legend_toggle(self, on):
        self.show_legend.set(on)
        self.app.settings["legend"] = bool(on)
        kit.save_settings(self.app.settings)

    def _on_opacity(self):
        """拖動濃淡滑桿：停下來才重新合成底圖（每次合成要零點幾秒）。"""
        if self._opacity_job:
            self.after_cancel(self._opacity_job)
        self._opacity_job = self.after(180, self._apply_opacity)

    def _apply_opacity(self):
        self._opacity_job = None
        v = round(float(self.liq_opacity.get()), 2)
        self.view.set_overlay_opacity("liq", v)
        self.app.settings["liq_opacity"] = v
        kit.save_settings(self.app.settings)

    def _on_hires(self):
        self.view.raster.detail = self.hires.get()
        self.app.settings["hires"] = self.hires.get()
        kit.save_settings(self.app.settings)
        self.view.request_redraw()

    def _toggle_mode(self):
        self.view.drag_mode = "pan" if self.view.drag_mode == "rotate" else "rotate"
        self.btn_mode.config(text="拖曳：平移" if self.view.drag_mode == "pan" else "拖曳：旋轉")

    def refresh_lines(self):
        lines = []
        for name, d in self.app.map_mrt.items():
            if not d["segments"]:
                continue
            lines.append({"id": name, "name": name, "color": d["color"],
                          "dashed": not d["approved"], "segments": [s["points"] for s in d["segments"]],
                          "stations": d["stations"]})
        self.view.set_lines(lines)

    def _marker_threshold(self):
        v = self.marker_min.get()
        return {"全部": 0, "影響 3 以上": 3, "影響 4 以上": 4, "影響 5": 5}.get(v, 3)

    def refresh_markers(self):
        th = self._marker_threshold()
        markers = []
        for it in self.app.intel:
            if it.get("lat") is None or it.get("lng") is None:
                continue
            lvl = it.get("impact_level") or 0
            if lvl < th:
                continue
            if it.get("build") and self.show_projects.get():
                continue                                # 已經畫成 3D 圖案，不再重複畫菱形
            color = MARKER_COLOR.get(it["type"], MARKER_OTHER)
            short = it["name"].split("（")[0].split("—")[0]
            markers.append({"id": it["id"], "name": it["name"], "lat": it["lat"], "lng": it["lng"], "color": color,
                            "type": it["type"] if it["type"] in MARKER_COLOR else "議會／建商情資",
                            "level": lvl or 2, "label": short[:16],
                            "tip": "%s | %s\n%s" % (it["type"], it["name"][:34], (it.get("status") or "")[:40])})
        self.view.set_markers(markers)

    # ------------------------------------------------------------------ 條件：預算與通勤
    @property
    def custom_work(self):
        return self.works[0]["pos"]

    @custom_work.setter
    def custom_work(self, value):
        self.works[0]["pos"] = value

    def _work_values(self, i=0):
        names = [NO_WORK] + [p["name"] for p in self.app.workplaces]
        if self.works[i]["pos"]:
            names.append(CUSTOM_WORK)
        return names + [PICK_ON_MAP]

    def work_place(self, i=0):
        """第 i 個上班地點 dict(name, lat, lng)；沒設定回傳 None。"""
        slot = self.works[i]
        name = slot["name"].get()
        if name == CUSTOM_WORK and slot["pos"]:
            return {"name": CUSTOM_WORK, "lat": slot["pos"][0], "lng": slot["pos"][1]}
        for p in self.app.workplaces:
            if p["name"] == name:
                return p
        return None

    def work_places(self):
        """已設定的上班地點 [(i, 標籤, 地點, 公里數或 None)]；兩個都設時標籤是「A」「B」，只有一個時是空字串。"""
        found = [(i, self.work_place(i)) for i in range(len(self.works))]
        found = [(i, w) for i, w in found if w]
        both = len(found) > 1
        return [(i, WORK_TAGS[i] if both else "", w, parse_number(self.works[i]["km"].get())) for i, w in found]

    def _on_work(self, i=0):
        slot = self.works[i]
        if slot["name"].get() == PICK_ON_MAP:
            self.lbl_source.config(text="請在地圖上點上班地點 %s（按右鍵取消）" % WORK_TAGS[i])

            def picked(lat, lng):
                if lat is None:
                    slot["name"].set(NO_WORK)
                else:
                    slot["pos"] = [round(lat, 5), round(lng, 5)]
                    slot["cb"].config(values=self._work_values(i))
                    slot["name"].set(CUSTOM_WORK)
                self.lbl_source.config(text=self.app.book.describe_source())
                self.apply_filters()
            self.view.start_pick_location(picked)
            return
        self.apply_filters()

    def distance_to_work(self, name, i=0):
        w = self.work_place(i)
        if not w or name == prices.CITY:
            return None
        d = self.app.dmap[name]
        return geo.dist_km(d["lat"], d["lng"], w["lat"], w["lng"])

    def passes(self, name):
        """行政區是否符合目前的預算與通勤條件（兩個上班地點都設了範圍時，兩邊都要在範圍內）。"""
        budget = parse_number(self.v_budget.get())
        if budget is not None:
            v = self.app.book.best(name, self.cat.get(), "t")["value"]
            if v is None or v > budget:
                return False
        for i, _tag, _w, km in self.work_places():
            if km is not None and self.distance_to_work(name, i) > km:
                return False
        return True

    def filters_active(self):
        return parse_number(self.v_budget.get()) is not None or any(km is not None for _i, _t, _w, km in self.work_places())

    def apply_filters(self):
        st = self.app.settings
        st["budget"] = parse_number(self.v_budget.get())
        for i, slot in enumerate(self.works):
            key = slot["key"]
            st[key] = slot["name"].get() if self.work_place(i) else None
            st[key + "_km"] = parse_number(slot["km"].get())
            st[key + "_pos"] = slot["pos"]
        kit.save_settings(st)
        self.refresh_pins()
        self.refresh_bars()
        self.refresh_rank()
        self.show_district(self.current)

    def clear_filters(self):
        self.v_budget.set("")
        for slot in self.works:
            slot["km"].set("")
            slot["name"].set(NO_WORK)
        self.apply_filters()

    def open_mortgage(self):
        price = parse_number(self.v_budget.get())
        if price is None:
            price = self.app.book.best(self.current, self.cat.get(), "t")["value"] or 1000
        MortgageDialog(self, self.app, price, on_apply=self._apply_budget)

    def _apply_budget(self, price):
        self.v_budget.set("%g" % price)
        self.apply_filters()

    def refresh_pins(self):
        pins, rings = [], []
        for i, tag, w, km in self.work_places():
            pins.append({"id": self.works[i]["key"], "kind": "work", "lat": w["lat"], "lng": w["lng"], "color": WORK_COLORS[i],
                         "label": "上班%s：%s" % (tag, w["name"]), "tip": "上班地點%s：%s\n位置為約略估計" % (tag, w["name"])})
            if km is not None:
                rings.append({"lat": w["lat"], "lng": w["lng"], "km": km, "color": WORK_COLORS[i]})
        if self.show_watch.get():
            for it in self.app.watch.items:
                if it.get("lat") is None or it.get("lng") is None:
                    continue
                price = ("%s 萬" % kit.fmt_num(it["price"])) if it.get("price") else ""
                pins.append({"id": it["id"], "kind": "watch", "lat": it["lat"], "lng": it["lng"], "color": WATCH_COLOR,
                             "label": ("%s %s" % (it["name"][:10], price)).strip(),
                             "tip": "看屋清單：%s\n%s %s" % (it["name"], it.get("type") or "", price)})
        if self._search_pin:
            sp = self._search_pin
            pins.append({"id": "search", "kind": "search", "lat": sp["lat"], "lng": sp["lng"], "color": SEARCH_COLOR,
                         "label": sp["label"], "tip": sp["tip"]})
            if sp.get("radius"):
                rings.append({"lat": sp["lat"], "lng": sp["lng"], "km": sp["radius"], "color": SEARCH_COLOR})
        self.view.set_pins(pins)
        self.view.set_rings(rings)

    # ------------------------------------------------------------------ 房價柱、圖例、排行
    def _values(self):
        book, cat, metric = self.app.book, self.cat.get(), self.metric.get()
        out = {}
        for d in self.app.districts:
            b = book.best(d["name"], cat, metric)
            out[d["name"]] = (b, book.trend(d["name"], cat, metric))
        return out

    def refresh_bars(self):
        cat, metric, mode = self.cat.get(), self.metric.get(), self.color_mode.get()
        vals = self._values()
        solid = [b["value"] for b, _ in vals.values() if b["value"] is not None and not b["low"]]
        if not solid:
            solid = [b["value"] for b, _ in vals.values() if b["value"] is not None] or [1.0]
        vmin, vmax = min(solid), max(solid)
        span = (vmax - vmin) or 1.0
        unit = "萬/坪" if metric == "u" else "萬"
        active = self.filters_active()
        bars, matched = [], 0
        for d in self.app.districts:
            name = d["name"]
            b, tr = vals[name]
            v = b["value"]
            ok = self.passes(name) if active else True
            matched += 1 if (ok and active) else 0
            if v is None:
                color, label, frac = NO_DATA, "%s —" % name, 0.0
            else:
                frac = min(1.15, v / vmax)
                if mode == "trend":
                    color = trend_color(tr)
                else:
                    color = NO_DATA if b["low"] else seq_color((v - vmin) / span)
                num = ("%.1f" % v) if metric == "u" else kit.fmt_num(v)
                label = "%s %s%s" % (name, num, "*" if b["low"] else "")
            tip = ["%s | %s" % (name, prices.CAT_LABEL[cat])]
            if v is None:
                tip.append("近一年沒有符合條件的成交")
            else:
                win = "近半年" if b["window"] == "h6" else "近一年"
                tip.append("%s中位%s %s %s（%d 件）" % (win, "單價" if metric == "u" else "總價",
                                                    ("%.1f" % v) if metric == "u" else kit.fmt_num(v), unit, b["n"]))
                tip.append("近半年起伏：%s" % trend_text(tr))
                if b["low"]:
                    tip.append("* 樣本少，僅供參考")
            for i, tag, _w, _km in self.work_places():
                tip.append("距上班地點%s約 %.1f 公里（直線）" % (tag, self.distance_to_work(name, i)))
            if active and not ok:
                tip.append("不符合目前的預算／通勤條件")
            bars.append({"id": name, "name": name, "lat": d["lat"], "lng": d["lng"], "value": v, "frac": frac,
                         "color": color, "label": label, "n": b["n"], "tip": "\n".join(tip), "dim": active and not ok})
        self.view.set_bars(bars)
        text = ("符合 %d 區" % matched) if active else ""
        if text != self.lbl_match.cget("text"):
            self.lbl_match.config(text=text)
            outer, btn, title, on = self._panels["cond"]      # 把「符合 N 區」寫在按鈕上，條件列收著也看得到
            btn.config(text="%s%s %s" % (title, "（%s）" % text if text else "", "▲" if on else "▼"))
            self.after_idle(self.relayout)

        what = "中位單價（萬/坪）" if metric == "u" else "中位總價（萬）"
        if mode == "price":
            stops = []
            for k in range(5):
                v = vmin + span * k / 4.0
                stops.append((("%.0f" % v) if metric == "u" else kit.fmt_num(v), seq_color(k / 4.0)))
            legend = {"title": "柱高與顏色：" + what, "stops": stops + [("樣本少／無資料", NO_DATA)]}
        else:
            stops = [("跌 %d%% 以上" % TREND_SPAN, trend_color(-TREND_SPAN)), ("跌 %d%%" % (TREND_SPAN / 2), trend_color(-TREND_SPAN / 2)),
                     ("持平", trend_color(0)), ("漲 %d%%" % (TREND_SPAN / 2), trend_color(TREND_SPAN / 2)),
                     ("漲 %d%% 以上" % TREND_SPAN, trend_color(TREND_SPAN)), ("樣本不足", NO_DATA)]
            legend = {"title": "柱高：%s | 顏色：近半年起伏" % what, "stops": stops}
        if active:
            legend["stops"] = legend["stops"] + [("不符合條件", "#e3e5e8")]
        legend["marker_types"] = MARKER_TYPES + [("議會／建商情資", MARKER_OTHER)]
        legend["overlay_rows"] = OVERLAY_LEGEND
        self.view.set_legend(legend)

    def refresh_rank(self):
        book, cat = self.app.book, self.cat.get()
        active = self.filters_active()
        places = self.work_places()
        rows = []
        for d in self.app.districts:
            name = d["name"]
            bu, bt = book.best(name, cat, "u"), book.best(name, cat, "t")
            tr = book.trend(name, cat, self.metric.get())
            rows.append({"d": name, "u": bu["value"], "t": bt["value"], "n": bu["n"], "tr": tr, "low": bu["low"],
                         "km": self.distance_to_work(name, 0), "km2": self.distance_to_work(name, 1),
                         "ok": self.passes(name) if active else True})
        key, desc = self._sort

        def sort_key(r):
            v = r[key]
            head = 0 if r["ok"] else 1          # 符合條件的排前面
            if key == "d":
                return (head, 0, v)
            return (head, 1, 0) if v is None else (head, 0, -v if desc else v)

        rows.sort(key=sort_key)
        if len(places) == 2:
            cols = ("d", "u", "t", "km", "km2", "tr")
            self.rank.heading("km", text="距A")
        elif places:
            cols = ("d", "u", "t", "km" if places[0][0] == 0 else "km2", "tr")
            self.rank.heading("km", text="距離")
            self.rank.heading("km2", text="距離")
        else:
            cols = ("d", "u", "t", "n", "tr")
        if len(places) == 2:
            self.rank.heading("km2", text="距B")
        # 兩個距離欄都顯示時把各欄收窄一點，最右邊的「半年起伏」才不會被擠出去
        tight = len(cols) > 5
        for col, width in (("d", 70), ("u", 50), ("t", 58), ("km", 50), ("km2", 50), ("tr", 92)):
            self.rank.column(col, width=int(width * 0.86) if tight else width, minwidth=30)
        self.rank.configure(displaycolumns=cols)
        self.rank.delete(*self.rank.get_children())
        for r in rows:
            tags = ("out",) if not r["ok"] else (("low",) if r["low"] else ())
            self.rank.insert("", "end", iid=r["d"], tags=tags, values=(
                r["d"] + ("*" if r["low"] and r["u"] is not None else ""),
                "—" if r["u"] is None else "%.1f" % r["u"],
                "—" if r["t"] is None else kit.fmt_num(r["t"]),
                r["n"], "—" if r["km"] is None else "%.1f" % r["km"], "—" if r["km2"] is None else "%.1f" % r["km2"],
                trend_text(r["tr"]) if r["tr"] is not None else "—"))
        if self.current in self.rank.get_children():
            self._select_rank_silent(self.current)

    def _sort_by(self, col):
        key, desc = self._sort
        self._sort = (col, not desc if key == col else (col not in ("d", "km", "km2")))
        self.refresh_rank()

    def _select_rank_silent(self, name):
        self._rank_silent = True
        self.rank.selection_set(name)
        self.rank.see(name)
        self.after_idle(lambda: setattr(self, "_rank_silent", False))

    def _on_rank_select(self, _e):
        if getattr(self, "_rank_silent", False):
            return
        sel = self.rank.selection()
        if sel and sel[0] != self.current:
            self.select_district(sel[0], focus=True)

    # ------------------------------------------------------------------ 選取
    def select_district(self, name, focus=True):
        """選一個行政區（或回到全市）；focus=True 時地圖會滑到那一區，並拉近到看得到區內道路的大小。"""
        self.current = name
        self._road_filter = None
        self._drop_search()
        if name != prices.CITY:
            self._addr_pending = None
        if name == prices.CITY:
            self.view.select(None, None)
            self.rank.selection_remove(self.rank.selection())
            if focus:
                self.view.fly_home()
        else:
            self.view.select("district", name)
            d = self.app.dmap[name]
            if focus:
                self.view.fly_to(d["lat"], d["lng"], zoom=max(self.view.zoom, DISTRICT_ZOOM))
            self._select_rank_silent(name)
        self.show_district(name)

    # ------------------------------------------------------------------ 行情報告
    def report_target(self):
        """報告的對象：搜尋中的地址（有的話），否則目前選的行政區；全市總覽時回傳 None。"""
        if self._addr and self._addr["district"] == self.current:
            return self.current, self._addr
        if self.current == prices.CITY:
            return None
        return self.current, None

    def open_report(self):
        target = self.report_target()
        if target is None:
            messagebox.showinfo("行情報告", "請先選一個行政區，或在地圖上方搜尋一個地址，再按「行情報告」。", parent=self)
            return
        dist, q = target
        title = dist if not q else "%s %s" % (dist, address.describe(q))
        ReportDialog(self, self.app, title, lambda agent: self.make_report(agent))

    def make_report(self, agent=None, open_it=True):
        """產生行情報告並存檔；回傳檔案路徑。"""
        target = self.report_target()
        if target is None:
            return None
        dist, q = target
        app = self.app
        if self._search_pin and q:
            point = (self._search_pin["lat"], self._search_pin["lng"])
        else:
            point = (app.dmap[dist]["lat"], app.dmap[dist]["lng"])
        works = [(w["name"], geo.dist_km(point[0], point[1], w["lat"], w["lng"])) for _i, _tag, w, _km in self.work_places()]
        text = report.build(app.book, app.txs, app.intel, dist, self.cat.get(), q=q, point=point, agent=agent or {},
                            works=works)
        path = report.save(text, dist if not q else "%s%s" % (dist, address.describe(q)))
        self._say("已產生行情報告：%s（用瀏覽器打開，可以列印或存成 PDF）" % os.path.relpath(path, geo.BASE_DIR))
        if open_it:
            kit.open_file(path)
        return path

    def _add_compare(self):
        if self.current != prices.CITY:
            self.app.add_to_compare(self.current)

    def show_district(self, name):
        book, cat, metric = self.app.book, self.cat.get(), self.metric.get()
        self.lbl_name.config(text=name)
        self.btn_compare.config(state="normal" if name != prices.CITY else "disabled")
        self.btn_report.config(state="normal" if name != prices.CITY else "disabled")
        bu, bt = book.best(name, cat, "u"), book.best(name, cat, "t")
        tr = book.trend(name, cat, metric)
        win = bu["window"]
        if win is None:
            period = "近一年沒有符合條件的成交"
        else:
            period = "%s（%s）%s" % ("近半年" if win == "h6" else "近一年", book.window_label(win),
                                    "" if win == "h6" else "，近半年樣本不足")
        zone = "" if name == prices.CITY else "%s | " % self.app.dmap[name]["zone"]
        self.lbl_sub.config(text="%s%s | %s" % (zone, prices.CAT_LABEL[cat], period))

        self.kpi["u"][0].config(text="—" if bu["value"] is None else "%.1f" % bu["value"])
        self.kpi["u"][1].config(text="萬/坪")
        self.kpi["t"][0].config(text="—" if bt["value"] is None else kit.fmt_num(bt["value"]))
        self.kpi["t"][1].config(text="萬")
        self.kpi["n"][0].config(text=kit.fmt_num(bu["n"]))
        self.kpi["n"][1].config(text="件" + ("（樣本少）" if bu["low"] and bu["n"] else ""))
        val, unit, sw = self.kpi["trend"]
        val.config(text=trend_text(tr) if tr is not None else "—")
        unit.config(text="後 3 個月對前 3 個月" if tr is not None else "樣本不足，不計算")
        sw.delete("all")
        sw.create_rectangle(1, 1, 11, 11, fill=trend_color(tr), outline="")

        self.lbl_insight.config(text=self._insight(name, bu, bt))
        title = "%s | 每月中位%s" % (name, "單價（萬/坪）" if metric == "u" else "總價（萬）")
        for chart in (self.chart, self.chart_tab):
            chart.set_data(book.series(name, cat, metric), book.half_year_months(),
                           "萬/坪" if metric == "u" else "萬", title)
        self._fill_info(name)
        self._fill_roads(name)
        self._fill_tx(name)
        self.refresh_roads()

    def _insight(self, name, bu, bt):
        """右側那一行「重點」：預算、通勤、預售價差。"""
        book, cat = self.app.book, self.cat.get()
        parts = []
        budget = parse_number(self.v_budget.get())
        if name == prices.CITY:
            if self.filters_active():
                ok = [d["name"] for d in self.app.districts if self.passes(d["name"])]
                parts.append("符合條件的有%d區%s" % (len(ok), ("：" + "、".join(ok[:8]) + ("…" if len(ok) > 8 else "")) if ok else ""))
            else:
                parts.append("輸入預算或選上班地點，可以只看符合條件的行政區。")
        else:
            if budget is not None:
                if bt["value"] is None:
                    parts.append("預算 %s 萬：本區沒有足夠成交可比較" % kit.fmt_num(budget))
                elif bt["value"] <= budget:
                    parts.append("預算 %s 萬：高於本區中位總價 %s 萬" % (kit.fmt_num(budget), kit.fmt_num(bt["value"])))
                else:
                    parts.append("預算 %s 萬：比本區中位總價少 %s 萬" % (kit.fmt_num(budget), kit.fmt_num(bt["value"] - budget)))
                if bu["value"] and cat != "house":
                    parts.append("以中位單價估約 %.0f 坪" % (budget / bu["value"]))
            for i, _tag, w, _km in self.work_places():
                parts.append("距%s約 %.1f 公里（直線）" % (w["name"], self.distance_to_work(name, i)))
            gap = book.presale_gap(name)
            if gap is not None and cat in ("presale", "apt", "all"):
                parts.append("預售屋單價比中古大樓%s %.0f%%" % ("高" if gap >= 0 else "低", abs(gap)))
        if cat == "house":
            parts.append("透天請以總價為主")
        return " | ".join(parts)

    def _nearby_transit(self, d):
        out = []
        for lname, ln in self.app.map_mrt.items():
            best = None
            for sname, lat, lng in ln["stations"]:
                km = geo.dist_km(d["lat"], d["lng"], lat, lng)
                if best is None or km < best[0]:
                    best = (km, sname)
            if best and best[0] <= NEAR_KM:
                out.append((best[0], lname, best[1], ln))
        out.sort(key=lambda x: x[0])
        return out

    def _fill_info(self, name):
        t = self.info
        t.clear()
        app = self.app
        if name == prices.CITY:
            t.line("全市重點", "h1")
            t.line("點地圖上的房價柱，或在「排行」點行政區，可查看該區的捷運與開發資訊。", "muted")
            t.line("影響最大的開發案", "h2")
            items = [it for it in app.intel if (it.get("impact_level") or 0) >= 5]
        else:
            d = app.dmap[name]
            t.line("%s 的交通與開發" % name, "h1")
            t.line("捷運站（營運中與規劃，距區中心 %d 公里內）" % NEAR_KM, "h2")
            near = self._nearby_transit(d)
            if not near:
                t.line("附近沒有營運中或已公布站位的捷運。", "muted")
            for km, lname, sname, ln in near:
                t.add("· ")
                t.link(lname, lambda n=lname: app.show_mrt(n))
                t.line(" | 最近站 %s，約 %.1f 公里" % (sname.split("（")[0][:18], km))
                t.line("   %s" % ln["status"][:70], "muted")
            rails = []
            for p in app.map_rail:
                for st in p.get("new_stations") or []:
                    if st.get("lat") is not None and geo.dist_km(d["lat"], d["lng"], st["lat"], st["lng"]) <= NEAR_KM:
                        rails.append(p)
                        break
            if rails:
                t.line("鐵路立體化", "h2")
                for p in rails:
                    t.add("· ")
                    t.link(p["name"], lambda n=p["name"]: app.show_mrt(n))
                    t.line()
                    t.line("   %s" % (p.get("status") or "")[:80], "muted")
            t.line("開發案與在地情資", "h2")
            items = [it for it in app.intel if name in (it.get("district") or "")]
        items.sort(key=lambda it: -(it.get("impact_level") or 0))
        if not items:
            t.line("目前沒有蒐集到此區的項目。", "muted")
        for it in items:
            lvl = it.get("impact_level")
            t.add("· [%s] " % it["type"])
            t.link(it["name"], lambda i=it["id"]: app.show_intel(i))
            if lvl:
                t.add("  影響 %d/5" % lvl, "muted")
            t.line()
            t.line("   %s" % (it.get("status") or "")[:90], "muted")
        if name != prices.CITY:
            t.line()
            t.line("距離以區公所附近為基準、站位為估算值，僅供概略參考。", "muted")
        t.done()

    # ------------------------------------------------------------------ 路段與成交明細
    def _fill_roads(self, name):
        """右側「路段」分頁：選了行政區就列出區內各路段；在全市總覽時可以用路名搜尋全市。"""
        self.road.delete(*self.road.get_children())
        cat = self.cat.get()
        presale = cat == "presale"
        self.road.heading("name", text="建案" if presale else "路段")
        self.lbl_road.config(wraplength=max(200, self.sub.winfo_width() - 30))
        self._roads = []
        if not self.app.txs:
            self.road.configure(displaycolumns=("name", "n", "u", "t", "last"))
            self.lbl_road.config(text="需要逐筆成交資料。按「更新實價登錄」下載後，這裡會列出各路段的中位價，地圖上也會依路段上色。")
            return
        since = self.app.book.windows["y12"][0]
        kw = self.v_road_kw.get().strip()
        if name == prices.CITY:
            self.road.configure(displaycolumns=("dist", "name", "n", "u", "t", "last"))
            if not kw or presale:
                self.lbl_road.config(text="輸入路名（例如「中山路」）可以搜尋全市各區同名路段的行情；"
                                          "或先選一個行政區，列出區內所有%s，地圖上也會依價格上色。" % ("建案" if presale else "路段"))
                return
            self._roads = roads.search(self.app.txs, kw, cat, since)
            note = "全市路名含「%s」的路段共%d個，點一列會跳到該區並在地圖上標出來。" % (kw, len(self._roads))
        else:
            self.road.configure(displaycolumns=("name", "n", "u", "t", "last"))
            if presale:
                rows = prices.road_stats(self.app.txs, name, cat, since, min_n=1)
                for r in rows:
                    r["low"] = r["n"] < 3
            else:
                rows = roads.road_prices(self.app.txs, name, cat, since)
            for r in rows:
                r["dist"] = name
            self._roads = [r for r in rows if kw in r["name"]] if kw else rows
            note = "%s，%s：近一年有成交的%s共%d個（灰字是不到3件、僅供參考），點一列可看逐筆成交並在地圖上標出來。%s" % (
                name, prices.CAT_LABEL[cat], "建案" if presale else "路段", len(self._roads),
                "" if cat != "house" else "透天單價含土地，請以總價為主。")
        for i, r in enumerate(self._roads):
            self.road.insert("", "end", iid=str(i), tags=("low",) if r.get("low") else (), values=(
                r["dist"], r["name"] + ("*" if r.get("low") else ""), r["n"], "%.1f" % r["u"], kit.fmt_num(r["t"]),
                r["last"][2:7].replace("-", "/")))
        self.lbl_road.config(text=note)

    def _select_road_row(self, name, dist):
        """讓「路段」清單選到某一列，但不當成使用者點的（選取事件稍後才送到，所以先記下「這一次是程式選的」）。"""
        for i, r in enumerate(self._roads):
            if r["name"] == name and r["dist"] == dist:
                iid = str(i)
                if tuple(self.road.selection()) != (iid,):
                    self._road_expect = iid
                    self.road.selection_set(iid)
                self.road.see(iid)
                return True
        if self.road.selection():
            self._road_expect = ""
            self.road.selection_remove(self.road.selection())
        return False

    def _on_road_select(self, _e):
        sel = self.road.selection()
        expect, self._road_expect = self._road_expect, None
        if expect is not None and (sel[0] if sel else "") == expect:
            return                                  # 程式自己選的那一次
        if not sel:
            return
        r = self._roads[int(sel[0])]
        pending = self._addr_pending
        if pending and r["name"] == pending["road"]:        # 搜尋的路名在好幾區都有：現在挑定了行政區
            self.v_road_kw.set("")
            self.show_address(dict(pending, district=r["dist"]))
            return
        self._addr_pending = None
        if r["dist"] != self.current:
            self.v_road_kw.set("")
            self.select_district(r["dist"])
        self.select_road(r["name"], focus=True)

    def select_road(self, name, focus=False, show_tx=True):
        """選取一個路段：成交明細只列這條路，地圖上把它標出來。"""
        if self._addr and self._addr["road"] != name:
            self._drop_search()
        self._road_filter = name
        self._fill_tx(self.current)
        self.view.select("road", name)
        self._select_road_row(name, self.current)
        if focus:
            for item in self.view.roads:
                if item["id"] == name:
                    self.view.fly_to(item["point"][0], item["point"][1], zoom=max(self.view.zoom, 70.0))
                    break
        if show_tx:
            self.sub.select(self._tx_tab)

    # ------------------------------------------------------------------ 路段房價圖層（地圖）
    def _on_show_roads(self):
        self.view.show["roads"] = self.show_roads.get()
        self.app.settings["roads"] = self.show_roads.get()
        kit.save_settings(self.app.settings)
        if self.show_roads.get():
            self._road_data = {k: v for k, v in self._road_data.items() if v}     # 重新勾選時，之前下載失敗的再試一次
        self.refresh_roads(user=True)

    def _on_show_landmarks(self):
        self.app.settings["landmarks"] = self.show_landmarks.get()
        kit.save_settings(self.app.settings)
        self.refresh_landmarks()

    def refresh_roads(self, user=False):
        """把目前選取的行政區各路段的中位價畫到地圖上（道路位置來自 OpenStreetMap，第一次要下載）。"""
        name, cat, metric = self.current, self.cat.get(), self.metric.get()
        view = self.view
        if (not self.show_roads.get() or name == prices.CITY or not self.app.txs or cat == "presale"):
            view.set_roads([])
            view.legend_extra = []
            view.extra_attribution = []
            return
        data = self._road_data.get(name)
        if data is None:
            data = roads.load(name)
            if data is not None:
                self._road_data[name] = data
        if not data:
            view.set_roads([])
            view.legend_extra = []
            view.extra_attribution = []
            if data is None and (user or self.app.auto_download):
                self._start_roads(name)
            return
        if self.app.auto_download and not self._prefetch_started:
            self._prefetch_started = True               # 這一區有了：有空時把其他區也抓好
            self.after(PREFETCH_PAUSE_MS, self._prefetch_roads)
        found, missing = roads.layer(self.app.txs, name, cat, self.app.book.windows["y12"][0], data)
        key = "u" if metric == "u" else "t"
        solid = [r[key] for r in found if not r["low"]] or [r[key] for r in found] or [0, 1]
        lo, hi = min(solid), max(solid)
        span = (hi - lo) or 1.0
        unit = "萬/坪" if metric == "u" else "萬"

        def fmt(v):
            return ("%.1f" % v) if metric == "u" else kit.fmt_num(v)

        items = []
        for r in found:
            tip = ["%s %s | %s" % (name, r["name"], prices.CAT_LABEL[cat]),
                   "近一年 %d 件：中位單價 %.1f 萬/坪、中位總價 %s 萬" % (r["n"], r["u"], kit.fmt_num(r["t"])),
                   "最近成交 %s" % r["last"]]
            if r["low"]:
                tip.append("* 不到 3 件，僅供參考")
            if not r["segments"]:
                tip.append("聚落式門牌，圓點是大概位置")
            tip.append("點一下看逐筆成交")
            items.append({"id": r["name"], "name": r["name"], "n": r["n"], "color": road_color((r[key] - lo) / span),
                          "segments": r["segments"], "lanes": r["lanes"], "point": r["point"], "dot": not r["segments"],
                          "label": "%s %s%s" % (r["name"], fmt(r[key]), "*" if r["low"] else ""), "tip": "\n".join(tip)})
        q = self._addr
        if q and q["district"] == name and not any(it["id"] == q["road"] for it in items):
            loc = roads.locate(data, q["road"])
            if loc:
                items.append({"id": q["road"], "name": q["road"], "n": 0, "color": "#aeb4bb", "segments": loc["segments"],
                              "lanes": loc["lanes"], "point": loc["point"], "dot": not loc["segments"],
                              "label": "%s（近一年無成交）" % q["road"],
                              "tip": "%s %s\n近一年沒有成交，所以沒有上色" % (name, q["road"])})
        view.set_roads(items)
        view.extra_attribution = [data.get("attribution") or roads.ATTRIBUTION]
        view.legend_extra = [("title", "路段房價：%s（%s）" % (name, "中位單價" if metric == "u" else "中位總價")),
                             ("swatch", "%s %s" % (fmt(lo), unit), road_color(0.0)),
                             ("swatch", "%s %s" % (fmt(lo + span / 2.0), unit), road_color(0.5)),
                             ("swatch", "%s %s" % (fmt(hi), unit), road_color(1.0)),
                             ("note", "線是道路、圓點是聚落；* 表示不到 3 件")]
        self._road_missing = missing

    def _start_roads(self, district, quiet=False):
        """在背景下載一區的道路位置。quiet=True 是「順便把其他區也抓好」，不打擾使用者、失敗也不跳訊息。"""
        if self._road_queue is not None:
            return
        self._road_queue = q = queue.Queue()
        self._road_quiet = quiet
        if not quiet:
            self.lbl_source.config(text="下載%s的道路位置（OpenStreetMap，只有第一次需要）…" % district)

        def work():
            try:
                q.put(("done", district, roads.download(district, progress=lambda t: q.put(("progress", district, t)))))
            except Exception as e:
                errlog.write("下載%s道路位置" % district)
                q.put(("error", district, "%s" % e))

        threading.Thread(target=work, daemon=True).start()
        self.after(200, self._poll_roads)

    def _poll_roads(self):
        q = self._road_queue
        if q is None:
            return
        try:
            kind, district, payload = q.get_nowait()
        except queue.Empty:
            self.after(200, self._poll_roads)
            return
        quiet = self._road_quiet
        if kind == "progress":
            if not quiet:
                self.lbl_source.config(text=payload)
            self.after(200, self._poll_roads)
            return
        self._road_queue = None
        if kind == "done":
            self._road_data[district] = payload
            self._prefetch_fails = 0
            if not quiet:
                self.lbl_source.config(text=self.app.book.describe_source())
        else:
            self._road_data[district] = False       # 這次不再重試；重新勾選「路段房價」或重開程式會再試
            self._road_error = payload
            if quiet:
                self._prefetch_fails += 1
            else:
                self.lbl_source.config(text="道路位置下載失敗，地圖上先不畫路段（右側「路段」清單照常可用；重新勾「圖層 > 路段房價」會再試）")
        if self.current != prices.CITY and (district == self.current or not self._road_data.get(self.current)):
            self.refresh_roads()                    # 下載期間換到別區的話，接著處理現在這一區
        nxt, self._road_next = self._road_next, None
        if nxt and self._road_queue is None and not self._road_data.get(nxt) and not roads.cached(nxt):
            self._start_roads(nxt)                  # 剛剛在背景補抓別區時，使用者要看的那一區：現在下載
            return
        if self._pin_wait and self._pin_req and self._pin_req["dist"] == district:
            self._show_pin(retry=False)             # 在等這一區的道路位置才能標圖釘：現在標出來
        if self._road_queue is None and self.app.auto_download and (kind == "done" or quiet):
            self.after(PREFETCH_PAUSE_MS, self._prefetch_roads)

    def _prefetch_roads(self):
        """有空的時候把還沒下載過的行政區道路位置一區一區抓好，之後換區、搜尋地址就不用等。

        一次只抓一區、每區之間停幾秒（公開伺服器是志願者維運的）；連續失敗兩次就停，下次開程式再繼續。
        """
        if self._road_queue is not None or not self.app.auto_download or not self.app.txs:
            return
        if self._prefetch_fails >= 2 or not self.winfo_exists():
            return
        names = [d["name"] for d in self.app.districts]
        todo = [n for n in names if self._road_data.get(n) is None and not roads.cached(n)]
        # 狀態列只在沒有別的訊息時才顯示背景進度，免得蓋掉剛剛搜尋、下載的結果
        idle = self.lbl_source.cget("text")
        idle = idle == self.app.book.describe_source() or idle.startswith(PREFETCH_NOTE)
        if not todo:
            if idle:
                self.lbl_source.config(text=self.app.book.describe_source())
            return
        todo.sort(key=lambda n: -(self.app.book.best(n, "all", "u")["n"] or 0))     # 成交多的區先抓
        if idle:
            self.lbl_source.config(text="%s：%s（已完成 %d/%d 區，之後換區、搜尋地址就不用等；不影響操作）" % (
                PREFETCH_NOTE, todo[0], len(names) - len(todo), len(names)))
        self._start_roads(todo[0], quiet=True)

    def _clear_road_filter(self):
        self._road_filter = None
        self._drop_search()
        self._fill_tx(self.current)
        if self.view.selected and self.view.selected[0] == "road":
            self.view.select("district" if self.current != prices.CITY else None, self.current)
        self.road.selection_remove(self.road.selection())

    def _fill_tx(self, name):
        self.tx.delete(*self.tx.get_children())
        self._tx_rows = []
        txs = self.app.txs
        self.lbl_tx.config(wraplength=max(200, self.sub.winfo_width() - 120))
        self.btn_tx_all.pack_forget()
        if not txs:
            self.lbl_tx.config(text="內建快照只有統計值。按右上角「更新實價登錄」下載原始資料後，這裡會列出逐筆成交。")
            return
        cat = self.cat.get()
        rows = [x for x in txs if (name == prices.CITY or x["dist"] == name) and prices.in_cat(x, cat)]
        if self._road_filter and name != prices.CITY:
            if cat == "presale":
                rows = [x for x in rows if (x.get("proj") or "未命名建案") == self._road_filter]
            else:
                rows = [x for x in rows if prices.road_of(x["addr"], name) == self._road_filter]
            self.btn_tx_all.pack(side="right", padx=4)
        q = self._addr
        if not (q and name == q["district"] and self._road_filter == q["road"] and cat != "presale"):
            q = None
        if q:
            ranked = address.rank(rows, q)
        else:
            rows.sort(key=lambda x: x["date"], reverse=True)
            ranked = [(1, x) for x in rows]
        self._tx_rows = [x for _level, x in ranked[:300]]
        for i, (level, x) in enumerate(ranked[:300]):
            age = "" if not x.get("built") else str(max(0, int(x["date"][:4]) - x["built"]))
            where = region.strip_city(x["addr"])
            if x.get("proj"):
                where = "%s（%s）" % (x["proj"], where[:14])
            self.tx.insert("", "end", iid=str(i), tags=("exact",) if level == 3 else (("lane",) if level == 2 else ()),
                           values=(x["date"], x["btype"], where,
                                   kit.fmt_num(x["tw"]), "%.1f" % x["u"], "%.1f" % x["ping"], age))
        if q:
            self.lbl_tx.config(text=self._address_summary(q, ranked, cat))
            return
        scope = name if not self._road_filter else "%s %s" % (name, self._road_filter)
        self.lbl_tx.config(text="%s | %s | 共 %d 筆，列出最近 %d 筆（已排除親友等特殊交易）" % (
            scope, prices.CAT_LABEL[cat], len(rows), min(300, len(rows))))

    def _address_summary(self, q, ranked, cat):
        """搜尋地址後，「成交」分頁上方的摘要：同門牌、同巷、整條路各有幾筆、中位價多少。"""
        st = address.summary(ranked)

        def part(title, g):
            return "%s %d 筆：中位單價 %.1f 萬/坪、中位總價 %s 萬" % (title, g["n"], g["u"], kit.fmt_num(g["t"]))
        lines = ["%s %s | %s" % (q["district"], address.describe(q), prices.CAT_LABEL[cat])]
        if not ranked:
            lines.append("實價登錄裡這條路沒有符合的成交紀錄（已排除親友等特殊交易）。可以換一個房型，或看同區其他路段。")
            return "\n".join(lines)
        if q["num"] is not None:
            lines.append(part("同門牌", st["exact"]) if st["exact"]["n"] else "同門牌沒有成交紀錄，下面依門牌號碼由近到遠排列。")
        if q["lane"] is not None and st["lane"]["n"] > st["exact"]["n"]:
            lines.append(part("同一條巷", st["lane"]))
        lines.append(part("整條路", st["road"]))
        note = []
        if st["exact"]["n"]:
            note.append("深色底是同門牌")
        if q["lane"] is not None and st["lane"]["n"] > st["exact"]["n"]:
            note.append("淺色底是同一條巷")
        if len(ranked) > 300:
            note.append("只列出前 300 筆")
        if cat == "all" or cat == "house":
            note.append("透天單價含土地，請以總價為主")
        if note:
            lines.append("（%s）" % "；".join(note))
        return "\n".join(lines)

    # ------------------------------------------------------------------ 地圖點選
    def on_pick(self, kind, ident, fly=True):
        if kind == "project":
            self._show_project(ident, fly=fly)
            return
        if kind == "district":
            self.select_district(ident)
            return
        if kind == "road":
            self.select_road(ident, focus=True)
            return
        app = self.app
        work_keys = [slot["key"] for slot in self.works]
        if kind == "pin" and ident == "search":
            if self._search_pin:
                self.view.fly_to(self._search_pin["lat"], self._search_pin["lng"], zoom=max(self.view.zoom, ADDRESS_ZOOM))
            self.sub.select(self._tx_tab)
            return
        if kind == "pin" and ident not in work_keys:
            app.show_watch(ident)
            return
        t = self.pick_text
        t.clear()
        if kind == "landmark":
            lm = next(x for x in app.landmarks if x["id"] == ident)
            self.view.select("landmark", ident)
            self._fly_near(lm["lat"], lm["lng"])
            t.line(lm["name"], "h1")
            t.line(lm.get("district") or "", "muted")
            t.line(lm.get("note") or "")
            t.line()
            t.link("在 Google 地圖查看", geo.google_search_url(self.app.cinfo["short"][:2] + " " + lm["name"]))
            t.line()
            for dn in [d["name"] for d in app.districts if d["name"] in (lm.get("district") or "")]:
                b = app.book.best(dn, self.cat.get(), "u")
                t.add("· ")
                t.link("看%s的房價" % dn, lambda n=dn: self.select_district(n))
                if b["value"] is not None:
                    t.add("  中位單價 %.1f 萬/坪" % b["value"], "muted")
                t.line()
            t.line()
            t.line("圖案是示意造型，位置取自 OpenStreetMap。", "muted")
        elif kind == "marker":
            it = app.intel_by_id[ident]
            self.view.select("marker", ident)
            if it.get("lat") is not None and it.get("lng") is not None:
                self._fly_near(it["lat"], it["lng"])
            app.write_intel(t, it, compact=True)
            t.line()
            t.link("在「開發與情資」分頁開啟", lambda: app.show_intel(ident))
            t.line()
        elif kind == "station":
            lname, sname = ident
            ln = app.mrt_lines.get(lname) or app.map_mrt[lname]
            self.view.select("line", lname)
            for st_name, st_lat, st_lng in ln["stations"]:
                if st_name == sname:
                    self._fly_near(st_lat, st_lng)
                    break
            t.line("%s | %s" % (lname, sname), "h1")
            t.line(ln["status"])
            if ln.get("operating"):
                if ln.get("network"):
                    t.line(ln["network"], "muted")
                t.line()
                t.link("在 Google 地圖查看", geo.google_search_url("%s %s" % (sname, ln.get("kind", ""))))
                t.line()
                t.line("路線與車站位置取自 OpenStreetMap。", "muted")
            else:
                t.line("預計動工：%s | 預計通車：%s" % (ln["construction_start"], ln["estimated_completion"]), "muted")
                t.line()
                t.link("查看這條路線的完整進度", lambda: app.show_mrt(lname))
                t.line()
                t.line("站位為依路口與地標估算，誤差可能達數百公尺。", "muted")
        elif kind == "pin":
            k = work_keys.index(ident)
            w = self.work_place(k)
            if w:
                self._fly_near(w["lat"], w["lng"])
            t.line("上班地點 %s：%s" % (WORK_TAGS[k], w["name"] if w else ""), "h1")
            t.line("位置為約略估計；各區距離是直線距離，實際車程請按「通勤路線」用 Google 地圖查。", "muted")
            near = sorted(((self.distance_to_work(d["name"], k), d["name"]) for d in app.districts))[:8] if w else []
            t.line("最近的行政區", "h2")
            for km, dn in near:
                t.add("· ")
                t.link(dn, lambda n=dn: self.select_district(n, focus=True))
                t.line("  約 %.1f 公里" % km)
        t.done()
        self.sub.select(self._pick_tab)

    def _show_project(self, ident, fly=True):
        """點了重大建設的 3D 圖案：右邊「點選」分頁列出時程、這一年的狀態與所在區的房價。"""
        app = self.app
        it = app.intel_by_id.get(ident)
        if not it or not it.get("build"):
            return
        b, year = it["build"], self.build_year.get()
        self.view.select("project", ident)
        if fly:
            self._fly_near(it["lat"], it["lng"])
        t = self.pick_text
        t.clear()
        t.line(it["name"], "h1")
        t.line("%s | %s" % (it["type"], it.get("district") or ""), "muted")
        t.line("時程", "h2")
        state = landmarks_mod.build_state(b, year)
        t.line("目前：%s；%s" % (b["phase"], b.get("note") or ""))
        bits = []
        if b.get("start"):
            bits.append("動工 %d" % b["start"])
        if b.get("done"):
            bits.append("完工 %d" % b["done"])
        if bits:
            t.line("年份：" + "、".join(bits) + "（依報導與官方說法整理，常會延後）", "muted")
        t.line("拉到 %d 年：%s" % (year, state), "muted")
        dists = [d["name"] for d in app.districts if d["name"] in (it.get("district") or "")]
        if dists:
            t.line("所在區的房價", "h2")
            for dn in dists:
                bu = app.book.best(dn, self.cat.get(), "u")
                tr = app.book.trend(dn, self.cat.get(), "u")
                t.add("· ")
                t.link(dn, lambda n=dn: self.select_district(n))
                if bu["value"] is not None:
                    t.add("  中位單價 %.1f 萬/坪" % bu["value"], "muted")
                if tr is not None:
                    t.add("、近半年 %s" % trend_text(tr), "muted")
                t.line()
        t.line()
        app.write_intel(t, it, compact=True)
        t.line()
        t.link("在「開發與情資」分頁開啟", lambda: app.show_intel(ident))
        t.line()
        t.line("圖案是示意造型，位置為約略位置。", "muted")
        t.done()
        self.sub.select(self._pick_tab)

    def _fly_near(self, lat, lng, zoom=POINT_ZOOM):
        """點了地圖上的東西：把它滑到畫面中央，離得太遠就順便拉近。"""
        self.view.fly_to(lat, lng, zoom=max(self.view.zoom, zoom))

    def focus_point(self, lat, lng, kind=None, ident=None, zoom=34.0):
        self.view.fly_to(lat, lng, zoom=max(self.view.zoom, zoom))
        if kind:
            self.view.select(kind, ident)

    def _core_districts(self):
        """近一年成交佔 85% 的那幾區（至少 3 區）；行政區少或沒有成交資料時回傳 []（用整個縣市）。"""
        ds = self.app.districts
        def n(d):
            c = self.app.book.cell(d["name"], "all")
            return c["y12"][0] if c and c.get("y12") else 0
        ranked = sorted(((n(d), d) for d in ds), key=lambda x: -x[0])
        total = sum(k for k, _ in ranked)
        if not total or len(ds) <= 6:
            return []
        core, acc = [], 0
        for k, d in ranked:
            core.append(d)
            acc += k
            if acc >= total * 0.85 and len(core) >= 3:
                break
        return core

    def busy(self):
        """有下載正在進行（實價登錄、底圖、道路）。切換縣市前要先等它做完。"""
        return self._queue is not None or self._bm_queue is not None

    def _google(self, kind):
        if self.current == prices.CITY:
            lat, lng, zoom = (23.06, 120.27, 11) if self.app.county == "D" else (geo.LAT0, geo.LNG0, 10)
        else:
            d = self.app.dmap[self.current]
            lat, lng, zoom = d["lat"], d["lng"], 14
        kit.open_url(geo.google_terrain_url(lat, lng, zoom) if kind == "terrain"
                     else geo.google_satellite_url(lat, lng, zoom + 1))

    def _google_route(self):
        places = self.work_places()
        if not places or self.current == prices.CITY:
            messagebox.showinfo("通勤路線", "請先選一個行政區，並按上方「篩選」設定上班地點。", parent=self)
            return
        d = self.app.dmap[self.current]
        for _i, _tag, w, _km in places:          # 兩個上班地點各開一個分頁
            kit.open_url(geo.google_directions_url(d["lat"], d["lng"], w["lat"], w["lng"]))

    def set_font_size(self, size):
        self.view.set_font_size(size)
        self.chart.config(height=self._chart_height(size))
        for chart in (self.chart, self.chart_tab):
            chart.set_font_size(max(7, size - 1))
        self._apply_panel_mode()
        self.after(80, self.relayout)        # 等各元件依新字級算好大小後，再重排會自動換行的工具列

    # ------------------------------------------------------------------ 衛星影像底圖與疊圖
    def _init_basemap(self):
        """啟動時：有快取就直接用衛星影像；沒有就先顯示地形，背景下載完成後自動切換。"""
        pref = self.app.settings.get("base", "satellite")
        bm = basemap.load()
        if bm:
            self.view.set_basemap(bm)
        self.base.set("satellite" if (bm and pref == "satellite") else "terrain")
        self.view.set_base_mode(self.base.get())
        if bm:
            for lid in self.app.settings.get("overlays", []):       # 上次開著的疊圖（只用已快取的，不自動連網）
                if lid in self.ov_vars:
                    ov = basemap.load(layer=lid)
                    if ov:
                        self.view.set_overlay(lid, ov)
                        self.view.enable_overlay(lid, True)
                        self.ov_vars[lid].set(True)
        if not bm and pref == "satellite" and basemap.HAVE_PIL and self.app.auto_download:
            self.after(900, lambda: self._start_layer("photo", auto=True))

    def _need_pillow(self):
        how = ("在 Pydroid 3 的選單點 Pip，輸入 pillow 後按 Install" if kit.IS_ANDROID
               else "在命令提示字元輸入：pip install pillow")
        messagebox.showinfo("需要 Pillow", "衛星影像與疊圖需要 Pillow 這個套件來解碼與旋轉影像。\n\n%s\n\n"
                            "裝好後重新開啟本程式即可。" % how, parent=self)

    def _on_base(self):
        want = self.base.get()
        if want == "terrain":
            self.view.set_base_mode("terrain")
            self._remember_base("terrain")
            return
        if self.view.basemap is not None:
            self.view.set_base_mode("satellite")
            self._remember_base("satellite")
            return
        self.base.set("terrain")
        if not basemap.HAVE_PIL:
            self._need_pillow()
            return
        self._start_layer("photo", auto=False)

    def _remember_base(self, mode):
        self.app.settings["base"] = mode
        kit.save_settings(self.app.settings)

    def _remember_overlays(self):
        self.app.settings["overlays"] = [lid for lid, _ in OVERLAYS if self.ov_vars[lid].get()]
        kit.save_settings(self.app.settings)

    def _toggle_overlay(self, lid):
        var = self.ov_vars[lid]
        if not var.get():
            self.view.enable_overlay(lid, False)
            self._remember_overlays()
            return
        if not basemap.HAVE_PIL:
            var.set(False)
            self._need_pillow()
            return
        if self.view.basemap is None:
            var.set(False)
            messagebox.showinfo("需要衛星底圖", "疊圖要畫在衛星影像上。請先把「底圖」切到「衛星影像」（第一次會自動下載）。", parent=self)
            return
        if self.base.get() != "satellite":
            self.base.set("satellite")
            self.view.set_base_mode("satellite")
            self._remember_base("satellite")
        if lid not in self.view.raster.overlays:
            ov = basemap.load(layer=lid)
            if ov is None:
                var.set(False)
                self._start_layer(lid, auto=False)
                return
            self.view.set_overlay(lid, ov)
        self.view.enable_overlay(lid, True)
        self._remember_overlays()

    def _start_layer(self, layer, auto, insecure=False):
        """背景下載某個圖層（衛星底圖或疊圖）的全區拼圖。"""
        if self._bm_queue is not None or self._queue is not None:
            if not auto:
                messagebox.showinfo("請稍候", "有其他下載正在進行，完成後再試一次。", parent=self)
            return
        self._bm_queue = q = queue.Queue()
        self._bm_auto, self._bm_layer = auto, layer
        self.progress.pack(fill="x", before=self.paned)
        if basemap.LAYERS[layer].get("wms"):
            # 單一張大圖、伺服器要算幾十秒，沒有進度可報：用來回跑的動畫表示「還在下載」
            self.progress.config(mode="indeterminate", value=0, maximum=100)
            self.progress.start(40)
        else:
            self.progress.config(mode="determinate", value=0, maximum=100)
        label = "衛星底圖" if layer == "photo" else basemap.LAYERS[layer]["name"]
        self.lbl_source.config(text="準備下載%s（只有第一次需要）…" % label)
        z = self.view.basemap.z if (layer != "photo" and self.view.basemap is not None) else \
            basemap.base_zoom(top=12 if kit.IS_ANDROID else 13)

        def work():
            try:
                bm = basemap.download(z=z, progress=lambda d, tot, msg: q.put(("progress", d, tot, msg)),
                                      insecure=insecure, layer=layer)
                q.put(("done", bm))
            except plvr.CertError as e:
                q.put(("cert", str(e)))
            except Exception as e:
                errlog.write("下載底圖")
                q.put(("error", "%s" % e))

        threading.Thread(target=work, daemon=True).start()
        self.after(150, self._poll_basemap)

    def _poll_basemap(self):
        q = self._bm_queue
        if q is None:
            return
        last = None
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "progress":
                    last = msg
                else:
                    self._finish_layer(msg)
                    return
        except queue.Empty:
            pass
        if last:
            if str(self.progress.cget("mode")) == "determinate":
                self.progress.config(maximum=max(1, last[2]), value=last[1])
            self.lbl_source.config(text=last[3])
        self.after(150, self._poll_basemap)

    def _finish_layer(self, msg):
        auto, layer = self._bm_auto, self._bm_layer
        self._bm_queue = None
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.progress.pack_forget()
        self.lbl_source.config(text=self.app.book.describe_source())
        label = "衛星底圖" if layer == "photo" else basemap.LAYERS[layer]["name"]
        if msg[0] == "done":
            if layer == "photo":
                self.view.set_basemap(msg[1])
                self.base.set("satellite")
                self.view.set_base_mode("satellite")
                self._remember_base("satellite")
            else:
                self.view.set_overlay(layer, msg[1])
                self.view.enable_overlay(layer, True)
                self.ov_vars[layer].set(True)
                self._remember_overlays()
            return
        if layer == "photo":
            self.base.set("terrain")
            self.view.set_base_mode("terrain")
        else:
            self.ov_vars[layer].set(False)
        if msg[0] == "cert":
            if auto:
                self.lbl_source.config(text="%s：憑證驗證失敗，再點一次可重試" % label)
                return
            again = messagebox.askyesno(
                "憑證驗證失敗",
                "這台裝置無法驗證圖資網站的 HTTPS 憑證。\n\n"
                "要改用「不驗證憑證」的方式下載嗎？下載的只是公開的圖資，"
                "但不驗證憑證代表無法確認連到的是真正的官方網站。", parent=self)
            if again:
                if self.view.raster.loader:
                    self.view.raster.loader.insecure = True
                self._start_layer(layer, auto=False, insecure=True)
        elif auto:
            self.lbl_source.config(text="%s下載失敗（%s），先顯示立體地形" % (label, msg[1][:30]))
        else:
            messagebox.showerror("%s下載失敗" % label, "%s" % msg[1], parent=self)

    # ------------------------------------------------------------------ 更新實價登錄
    def start_update(self):
        if self._queue is not None:
            return
        if self._bm_queue is not None:
            messagebox.showinfo("請稍候", "正在下載圖資，完成後再更新實價登錄。", parent=self)
            return
        ok = messagebox.askyesno(
            "更新實價登錄",
            ("將從內政部「不動產成交案件實際資訊資料供應系統」下載臺南市買賣與預售屋資料並重新統計。\n\n"
             "第一次約需下載 100~150MB（最近幾期是全國壓縮檔，每期約 15MB），"
             "之後只會補抓新的部分。建議在 Wi-Fi 下進行。\n\n要開始嗎？") if self.app.county == "D" else
            ("將從內政部「不動產成交案件實際資訊資料供應系統」下載全國買賣與預售屋資料，再統計%s。\n\n"
             "第一次約需下載 150~250MB，下載一次全台 22 縣市都能用（切換縣市不用重新下載），"
             "之後只會補抓新的部分。建議在 Wi-Fi 下進行。\n\n要開始嗎？" % self.app.cinfo["short"]), parent=self)
        if ok:
            self._run_update(insecure=False)

    # ---- 自動更新：內政部每月 1、11、21 日發布新一期；之前下載過逐筆資料的話，開程式時自動補抓新的一期
    def _on_auto_update(self):
        self.app.settings["auto_update"] = self.auto_update.get()
        kit.save_settings(self.app.settings)
        if self.auto_update.get():
            self.check_auto_update()

    def check_auto_update(self, today=None):
        """需要的話在背景補抓新一期實價登錄；回傳是否開始下載。之後每 6 小時再檢查一次（程式一直開著也會更新）。"""
        if self._auto_job:
            self.after_cancel(self._auto_job)
        self._auto_job = self.after(AUTO_CHECK_MS, self.check_auto_update)
        if not (self.app.auto_download and self.auto_update.get()):
            return False
        if self._queue is not None or self._bm_queue is not None:
            self.after_cancel(self._auto_job)
            self._auto_job = self.after(60 * 1000, self.check_auto_update)    # 正在下載別的：一分鐘後再看
            return False
        today = today or datetime.date.today()
        if self.app.settings.get("auto_update_failed") == today.isoformat():
            return False                                # 今天已經失敗過一次：明天再試，不一直打擾伺服器
        if not region.has_live_cache():
            if self.lbl_source.cget("text") == self.app.book.describe_source():
                self.lbl_source.config(text="%s（按右邊「更新實價登錄」下載一次逐筆資料後，之後每期都會自動更新）" %
                                       self.app.book.describe_source())
            return False
        if not region.needs_update(today):
            return False
        self._run_update(insecure=bool(self.app.settings.get("plvr_insecure")), quiet=True)
        return True

    def _run_update(self, insecure, quiet=False):
        self._update_quiet = quiet
        self._update_before = len(self.app.txs)
        self._queue = queue.Queue()
        self.btn_update.config(state="disabled")
        self.progress.pack(fill="x", before=self.paned)
        self.progress.config(mode="determinate", value=0, maximum=100)
        q = self._queue

        def work():
            try:
                book, n = region.update(progress=lambda d, tot, msg: q.put(("progress", d, tot, msg)), insecure=insecure)
                q.put(("done", book, n))
            except plvr.CertError as e:
                q.put(("cert", str(e)))
            except Exception as e:  # 顯示給使用者，不讓執行緒默默結束
                errlog.write("更新實價登錄")
                q.put(("error", "%s" % e))

        threading.Thread(target=work, daemon=True).start()
        self.after(150, self._poll_update)

    def _poll_update(self):
        q = self._queue
        if q is None:
            return
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "progress":
                    _, d, tot, text = msg
                    self.progress.config(maximum=max(1, tot), value=d)
                    self.lbl_source.config(text=text)
                else:
                    self._finish_update(msg)
                    return
        except queue.Empty:
            pass
        self.after(150, self._poll_update)

    def _finish_update(self, msg):
        self._queue = None
        self.progress.pack_forget()
        self.btn_update.config(state="normal")
        if self._update_quiet:
            self._update_quiet = False
            if msg[0] == "done":
                self.app.settings.pop("auto_update_failed", None)
                kit.save_settings(self.app.settings)
                self.app.reload_prices()
                added = max(0, len(self.app.txs) - self._update_before)
                self.lbl_source.config(text="已自動更新實價登錄（%s新一期，新增 %d 筆）｜下一期 %s 發布 | %s" % (
                    plvr.last_release().strftime("%m/%d "), added, plvr.next_release().strftime("%m/%d"),
                    self.app.book.describe_source()))
            else:
                self.app.settings["auto_update_failed"] = datetime.date.today().isoformat()
                kit.save_settings(self.app.settings)
                why = "憑證驗證失敗，請按「更新實價登錄」手動更新" if msg[0] == "cert" else "暫時連不上內政部網站，明天會再試"
                self.lbl_source.config(text="自動更新實價登錄沒有成功（%s）。目前仍使用原有資料。" % why)
            return
        if msg[0] == "done":
            self.app.reload_prices()
            messagebox.showinfo("更新完成", "已更新，共 %d 筆住宅交易（含預售屋）。\n%s" % (msg[2], self.app.book.describe_source()),
                                parent=self)
        elif msg[0] == "cert":
            again = messagebox.askyesno(
                "憑證驗證失敗",
                "這台裝置無法驗證實價登錄網站的 HTTPS 憑證（常見於缺少中繼憑證）。\n\n"
                "要改用「不驗證憑證」的方式下載嗎？資料是公開的統計資料，"
                "但不驗證憑證代表無法確認連到的是真正的官方網站。\n\n"
                "選「否」則取消，繼續使用現有資料。", parent=self)
            if again:
                self.app.settings["plvr_insecure"] = True     # 之後自動更新也用同樣方式
                kit.save_settings(self.app.settings)
                self._run_update(insecure=True)
                return
            self.lbl_source.config(text=self.app.book.describe_source())
        else:
            self.lbl_source.config(text=self.app.book.describe_source())
            messagebox.showerror("更新失敗", "%s\n\n目前仍使用原有資料。" % msg[1], parent=self)
