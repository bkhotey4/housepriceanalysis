"""純 Tkinter Canvas 的 3D 地形檢視器。

不依賴 numpy / matplotlib / OpenGL，只用 Canvas 多邊形 + 畫家演算法（由遠到近繪製），
因此在 Windows 的 Python 與 Android 平板的 Pydroid 3 都能執行。

座標系：x 向東、y 向北（公里），z 向上（公里，乘上垂直誇張倍率）。
投影：正交（等角）投影，可旋轉方位角 az 與俯角 pitch。
"""
import math
import time
import tkinter as tk
import tkinter.font as tkfont

from . import basemap as basemap_mod
from . import landmarks as landmarks_mod
from .geo import KM_PER_DEG_LAT, KM_PER_DEG_LNG, LAT0, LNG0, to_xy

SEA = "#cfdfea"
BG = "#eef1f4"
INK = "#1f2328"
INK_MUTED = "#5b6168"

# 地形分層設色（低彩度，讓房價柱與路線成為主角）
_HYPSO = [(0, (229, 234, 219)), (15, (218, 228, 205)), (60, (205, 219, 190)), (150, (198, 208, 174)),
          (300, (208, 198, 164)), (600, (191, 173, 145)), (1200, (163, 149, 133))]


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def shade(hexcolor, k):
    r, g, b = _rgb(hexcolor)
    return _hex((r * k, g * k, b * k))


def mix(c1, c2, t):
    a, b = _rgb(c1), _rgb(c2)
    return _hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def ramp_color(stops, t):
    """stops: [hex,...] 等距色階；t: 0~1。"""
    t = max(0.0, min(1.0, t))
    pos = t * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    return mix(stops[i], stops[i + 1], pos - i)


def _hypso(elev):
    for k in range(1, len(_HYPSO)):
        e0, c0 = _HYPSO[k - 1]
        e1, c1 = _HYPSO[k]
        if elev <= e1:
            t = (elev - e0) / float(e1 - e0)
            return tuple(c0[i] + (c1[i] - c0[i]) * t for i in range(3))
    return _HYPSO[-1][1]


class View3D(tk.Canvas):
    DEFAULT = {"az": -24.0, "pitch": 40.0, "zoom": None, "tx": -6.0, "ty": -3.0}
    BAR_MAX_KM = 6.5      # 最高房價柱的高度（世界座標公里）
    BAR_HALF_KM = 0.62    # 房價柱半寬
    animate = True        # 點選後滑過去、滾輪縮放的過場動畫（測試時關掉，結果才是立即的）
    FLY_MS = 420          # 「拉到那個點」的動畫長度（毫秒）

    def __init__(self, master, terrain, font_family="TkDefaultFont", font_size=10, quality=1, **kw):
        kw.setdefault("bg", BG)
        kw.setdefault("highlightthickness", 0)
        super().__init__(master, **kw)
        self.terrain = terrain
        self.font_family = font_family
        self.font_size = font_size
        self.quality = quality          # 靜止時的網格間距（1 最細；平板建議 2）
        self.zex = 4.0                  # 地形垂直誇張倍率
        self.az = self.DEFAULT["az"]
        self.pitch = self.DEFAULT["pitch"]
        self.zoom = 10.0
        self._auto_zoom = True
        self.tx, self.ty = self.DEFAULT["tx"], self.DEFAULT["ty"]
        self.drag_mode = "pan"          # 左鍵拖曳：pan 平移（預設）| rotate 旋轉；右鍵拖曳是另一種
        self.show = {"lines": True, "markers": True, "labels": True, "legend": True, "roads": True, "landmarks": True}
        self.bars, self.lines, self.markers = [], [], []
        self.pins, self.rings = [], []  # 圖釘（上班地點、看屋物件）與距離圈
        self.roads = []                 # 路段房價：依中位價上色的道路折線與聚落圓點
        self.landmarks = []             # 知名地標的立體小模型
        self.extra_attribution = []     # 額外的資料來源標示（例如道路位置的 OpenStreetMap）
        self.legend_extra = []          # 額外的圖例列（路段房價的色階）
        self.legend_projects = []       # 重大建設三種狀態的圖例
        self._road_labels = []
        self.legend = None
        self.raster = basemap_mod.RasterStack()   # 衛星影像＋疊圖＋高解析補丁
        self.base_mode = "terrain"      # "terrain" 立體地形 | "satellite" 衛星影像（平面）
        self._photo = None
        self._raster_job = None
        self.pick_location = None       # 設定後，下一次點地圖會回呼 (lat, lng)
        self.on_status = None           # 需要提示使用者時回呼 (文字)
        self.on_legend_toggle = None    # 使用者在地圖上收合／展開圖例時回呼 (bool)
        self._legend_box = None         # 圖例是疊在地圖上的子畫布：內容沒變就不用每一格重畫
        self._legend_sig = None
        self._legend_w = 0
        self.selected = None            # (kind, id)
        self.on_pick = None
        self.on_view_change = None
        self._fonts = {}
        self._measure = {}
        self._cells = {}
        self._hit = []                  # [(kind, id, x0, y0, x1, y1, depth)]
        self._pending = None
        self._full_job = None
        self._fast = False
        self._drag = None
        self._hover = None
        self._fly = None                # 進行中的「滑過去」動畫
        self._fly_job = None
        self._zoom_target = None        # 滾輪縮放的目標倍率（分幾格滑過去）
        self._zoom_anchor = None        # 縮放時要固定在游標下的螢幕位置
        self._zoom_job = None
        self._sprites = {}              # 地標圖案的快取：平移時不用每一格重算
        self.topbar = None              # 疊在地圖上方的小工具列（地址搜尋框），排在圖例右邊
        self.topbar_max = 360
        self._topbar_geom = None
        self._build_static()

        self.bind("<Configure>", self._on_configure)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<ButtonPress-3>", lambda e: self._on_press(e, alt=True))
        self.bind("<B3-Motion>", self._on_drag)
        self.bind("<ButtonRelease-3>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda e: self.zoom_by(1.2, at=(e.x, e.y)))
        self.bind("<Button-5>", lambda e: self.zoom_by(1 / 1.2, at=(e.x, e.y)))
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # ------------------------------------------------------------------ 靜態資料
    def _build_static(self):
        t = self.terrain
        self._xw = [to_xy(t.north, t.west + i * t.dx)[0] for i in range(t.nx)]
        self._yw = [to_xy(t.north - j * t.dy, t.west)[1] for j in range(t.ny)]
        self._ekm = [[t.node_elev(i, j) / 1000.0 for i in range(t.nx)] for j in range(t.ny)]

    def _cells_for(self, step):
        """回傳該精細度的網格：(I 索引, J 索引, cells[(a, b, color)])，a/b 為 I/J 內的位置。"""
        if step in self._cells:
            return self._cells[step]
        t = self.terrain
        I = list(range(0, t.nx, step))
        if I[-1] != t.nx - 1:
            I.append(t.nx - 1)
        J = list(range(0, t.ny, step))
        if J[-1] != t.ny - 1:
            J.append(t.ny - 1)
        cells = []
        for b in range(len(J) - 1):
            j0, j1 = J[b], J[b + 1]
            for a in range(len(I) - 1):
                i0, i1 = I[a], I[a + 1]
                corners = ((i0, j0), (i1, j0), (i1, j1), (i0, j1))
                sea = sum(1 for (i, j) in corners if t.is_sea_node(i, j))
                if sea == 4:
                    continue
                e = [t.node_elev(i, j) for (i, j) in corners]
                mean = sum(e) / 4.0
                # 坡向陰影：光源在西北上方（朝西北的坡面較亮）
                dzdx = ((e[1] + e[2]) - (e[0] + e[3])) / 2.0 / ((self._xw[i1] - self._xw[i0]) * 1000.0)
                dzdy = ((e[0] + e[1]) - (e[3] + e[2])) / 2.0 / ((self._yw[j0] - self._yw[j1]) * 1000.0)
                k = 1.0 + 2.2 * (dzdx * 0.7 - dzdy * 0.7)
                k = max(0.74, min(1.10, k))
                r, g, bl = _hypso(mean)
                cells.append((a, b, _hex((r * k, g * k, bl * k))))
        self._cells[step] = (I, J, cells)
        return self._cells[step]

    def font(self, size_delta=0, bold=False):
        key = (size_delta, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=self.font_family, size=max(6, self.font_size + size_delta),
                                           weight="bold" if bold else "normal")
        return self._fonts[key]

    def _line_height(self, font):
        key = ("lh", id(font))
        h = self._measure.get(key)
        if h is None:
            h = self._measure[key] = font.metrics("linespace")
        return h

    def measure(self, font, text):
        """font.measure 的快取版（某些平台每次量測都要往返視窗系統，很慢）。"""
        key = (id(font), text)
        w = self._measure.get(key)
        if w is None:
            w = self._measure[key] = font.measure(text)
        return w

    def set_font_size(self, size):
        self.font_size = size
        self._fonts = {}
        self._measure = {}
        self._legend_sig = None
        self.request_redraw()

    # ------------------------------------------------------------------ 對外 API
    def set_bars(self, bars):
        self.bars = bars
        self.request_redraw()

    def set_lines(self, lines):
        self.lines = lines
        self.request_redraw()

    def set_markers(self, markers):
        self.markers = markers
        self.request_redraw()

    @property
    def basemap(self):
        return self.raster.base

    @basemap.setter
    def basemap(self, value):
        self.raster.base = value

    def set_basemap(self, basemap):
        self.raster.base = basemap
        self.request_redraw()

    def set_overlay(self, layer_id, bm):
        """登錄一張疊圖（行政區界、道路、土壤液化、活動斷層）。"""
        if bm is None:
            self.raster.overlays.pop(layer_id, None)
        else:
            bm.levels = bm.levels[:1]       # 疊圖會先合成到底圖上，不需要自己的縮圖層級（省記憶體）
            self.raster.overlays[layer_id] = bm
        self.request_redraw()

    def set_overlay_opacity(self, layer_id, value):
        self.raster.set_opacity(layer_id, value)
        self.request_redraw()

    def enable_overlay(self, layer_id, on):
        if on:
            self.raster.enabled.add(layer_id)
        else:
            self.raster.enabled.discard(layer_id)
        self.request_redraw()

    def start_pick_location(self, callback):
        """進入「在地圖上點位置」模式；下一次點擊回呼 callback(lat, lng)，右鍵取消則回呼 (None, None)。"""
        self.pick_location = callback
        self.config(cursor="crosshair")
        self.request_redraw()

    def set_roads(self, roads):
        """路段房價圖層。每筆 dict：id、color、segments、lanes、point、label、tip、dot（聚落圓點）。

        這裡先把經緯度換成世界座標並記下地面高度，之後每一格只需要做投影。
        """
        prepared = []
        for r in roads:
            def conv(seg):
                out = []
                for lat, lng in seg:
                    x, y = to_xy(lat, lng)
                    out.append((x, y, self.terrain.elev(lat, lng) / 1000.0))
                return out
            item = dict(r)
            item["_segs"] = [conv(seg) for seg in r.get("segments", [])]
            item["_lanes"] = [conv(seg) for seg in r.get("lanes", [])]
            lat, lng = r["point"]
            x, y = to_xy(lat, lng)
            item["_pt"] = (x, y, self.terrain.elev(lat, lng) / 1000.0)
            prepared.append(item)
        prepared.sort(key=lambda r: -r.get("n", 0))     # 成交多的排前面：拖曳時只畫前面的一部分
        self.roads = prepared
        self.request_redraw()

    def set_landmarks(self, landmarks):
        self.landmarks = landmarks
        self.request_redraw()

    def set_pins(self, pins):
        self.pins = pins
        self.request_redraw()

    def set_rings(self, rings):
        self.rings = rings
        self.request_redraw()

    def set_base_mode(self, mode):
        self.base_mode = mode
        self.request_redraw()

    @property
    def flat(self):
        """衛星影像模式下地面是平的（影像無法貼在起伏的地形上）。"""
        return self.base_mode == "satellite" and self.basemap is not None

    def set_legend(self, legend):
        self.legend = legend
        self.request_redraw()

    def select(self, kind, ident):
        self.selected = (kind, ident) if kind else None
        self.request_redraw()

    def _zoom_limit(self, z):
        return max(3.0, min(1500.0 if self.flat else 260.0, z))

    def _stop_motion(self):
        """使用者自己動手（拖曳、按按鈕）時，停掉進行中的動畫。"""
        for name in ("_fly_job", "_zoom_job"):
            job = getattr(self, name)
            if job:
                self.after_cancel(job)
                setattr(self, name, None)
        self._fly = None
        self._zoom_target = None

    def focus(self, lat, lng, zoom=None):
        """立刻把畫面中心移到某個位置。"""
        self._stop_motion()
        self.tx, self.ty = to_xy(lat, lng)
        if zoom:
            self.zoom = self._zoom_limit(zoom)
            self._auto_zoom = False
        self.request_redraw()

    def fly_to(self, lat, lng, zoom=None, ms=None):
        """把畫面中心滑到某個位置（可順便縮放）；關掉動畫或畫面還沒顯示時直接跳過去。"""
        x, y = to_xy(lat, lng)
        self._fly_xy(x, y, zoom, ms)

    def fly_home(self, ms=None):
        """滑回全市總覽的位置與大小（不改變旋轉角度）。"""
        self._stop_motion()
        w, h = self.winfo_width(), self.winfo_height()
        zoom = max(3.0, min((w - self._legend_inset()) / 62.0, h / 45.0)) if w > 50 and h > 50 else None
        self._fly_xy(self.DEFAULT["tx"], self.DEFAULT["ty"], zoom, ms, auto=True)

    def _fly_xy(self, x, y, zoom, ms, auto=False):
        self._stop_motion()
        ms = self.FLY_MS if ms is None else ms
        z1 = self._zoom_limit(zoom) if zoom else self.zoom
        far = abs(x - self.tx) + abs(y - self.ty) > 1e-6 or abs(z1 - self.zoom) > 1e-6
        if not self.animate or ms <= 0 or not far or not self.winfo_viewable():
            self.tx, self.ty, self.zoom = x, y, z1
            self._auto_zoom = auto if zoom else self._auto_zoom
            self.request_redraw()
            if self.on_view_change:
                self.on_view_change()
            return
        if zoom:
            self._auto_zoom = False
        self._fly = {"t0": time.time(), "ms": float(ms), "from": (self.tx, self.ty, self.zoom), "to": (x, y, z1),
                     "auto": auto and bool(zoom)}
        self._fly_step()

    def _fly_step(self):
        f = self._fly
        self._fly_job = None
        if not f:
            return
        k = min(1.0, (time.time() - f["t0"]) * 1000.0 / f["ms"])
        e = 1.0 - (1.0 - k) ** 3                       # 先快後慢
        (x0, y0, z0), (x1, y1, z1) = f["from"], f["to"]
        self.tx, self.ty = x0 + (x1 - x0) * e, y0 + (y1 - y0) * e
        self.zoom = z0 * (z1 / z0) ** e
        if k >= 1.0:
            self._fly = None
            if f["auto"]:
                self._auto_zoom = True
            self.request_redraw(fast=True)
            if self.on_view_change:
                self.on_view_change()
            return
        self.request_redraw(fast=True)
        self._fly_job = self.after(12, self._fly_step)

    def reset_view(self):
        self._stop_motion()
        self.az, self.pitch = self.DEFAULT["az"], self.DEFAULT["pitch"]
        self.tx, self.ty = self.DEFAULT["tx"], self.DEFAULT["ty"]
        self._auto_zoom = True
        self._fit_zoom()
        self.request_redraw()

    def top_view(self):
        self.az, self.pitch = 0.0, 89.0
        self.request_redraw()

    def _zoom_at(self, zoom, at=None):
        """把倍率設成 zoom；at=(螢幕 x, y) 時，那個位置底下的地面保持不動（對著游標縮放）。"""
        zoom = self._zoom_limit(zoom)
        if at is None:
            self.zoom = zoom
            return
        a, p = math.radians(self.az), math.radians(self.pitch)
        ca, sa, sp = math.cos(a), math.sin(a), max(1e-3, math.sin(p))
        w2 = (self.winfo_width() + self._legend_inset()) / 2.0
        h2 = self.winfo_height() * 0.54
        k = 1.0 / self.zoom - 1.0 / zoom
        xr, yr = (at[0] - w2) * k, (h2 - at[1]) * k / sp
        self.tx = max(-45.0, min(45.0, self.tx + xr * ca + yr * sa))
        self.ty = max(-40.0, min(40.0, self.ty - xr * sa + yr * ca))
        self.zoom = zoom

    def zoom_by(self, factor, at=None):
        """縮放；at=(螢幕 x, y) 對著那個位置縮放（滾輪用），不給就對著畫面中心。"""
        self._auto_zoom = False
        if self._fly:
            self._stop_motion()
        base = self._zoom_target or self.zoom
        target = self._zoom_limit(base * factor)
        if not self.animate or not self.winfo_viewable():
            self._zoom_target = None
            self._zoom_at(target, at)
            self.request_redraw(fast=True)
            if self.on_view_change:
                self.on_view_change()
            return
        self._zoom_target, self._zoom_anchor = target, at
        if self._zoom_job is None:
            self._zoom_step()

    def _zoom_step(self):
        self._zoom_job = None
        target = self._zoom_target
        if target is None:
            return
        ratio = target / self.zoom
        if abs(math.log(ratio)) < 0.012:
            self._zoom_at(target, self._zoom_anchor)
            self._zoom_target = None
        else:
            self._zoom_at(self.zoom * ratio ** 0.38, self._zoom_anchor)      # 每一格走剩下距離的一部分：起步快、收尾緩
            self._zoom_job = self.after(14, self._zoom_step)
        self.request_redraw(fast=True)
        if self._zoom_target is None and self.on_view_change:
            self.on_view_change()

    def rotate_by(self, d_az=0.0, d_pitch=0.0):
        self.az = (self.az + d_az + 180.0) % 360.0 - 180.0
        self.pitch = max(12.0, min(89.0, self.pitch + d_pitch))
        self.request_redraw(fast=True)

    def set_exaggeration(self, zex):
        self.zex = float(zex)
        self.request_redraw()

    def set_quality(self, q):
        self.quality = max(1, int(q))
        self.request_redraw()

    # ------------------------------------------------------------------ 投影
    def _setup_projection(self):
        a, p = math.radians(self.az), math.radians(self.pitch)
        self._ca, self._sa = math.cos(a), math.sin(a)
        self._cp, self._sp = math.cos(p), math.sin(p)
        self._w2 = (self.winfo_width() + self._legend_inset()) / 2.0
        self._h2 = self.winfo_height() * 0.54

    def project(self, x, y, z):
        """世界座標 -> (螢幕 x, 螢幕 y, 深度)；深度越大越遠。"""
        dx, dy = x - self.tx, y - self.ty
        xr = dx * self._ca - dy * self._sa
        yr = dx * self._sa + dy * self._ca
        return (self._w2 + xr * self.zoom,
                self._h2 - (yr * self._sp + z * self._cp) * self.zoom,
                yr)

    def screen_to_latlng(self, sx, sy):
        """螢幕座標 -> 地面（z=0）的經緯度；project() 的反函數。"""
        a, p = math.radians(self.az), math.radians(self.pitch)
        ca, sa, sp = math.cos(a), math.sin(a), max(1e-3, math.sin(p))
        w2 = (self.winfo_width() + self._legend_inset()) / 2.0
        h2 = self.winfo_height() * 0.54
        xr = (sx - w2) / self.zoom
        yr = (h2 - sy) / (self.zoom * sp)
        x = self.tx + xr * ca + yr * sa
        y = self.ty - xr * sa + yr * ca
        return y / KM_PER_DEG_LAT + LAT0, x / KM_PER_DEG_LNG + LNG0

    def view_box(self):
        """目前畫面涵蓋的地面範圍 (west, east, north, south)。"""
        w, h = self.winfo_width(), self.winfo_height()
        pts = [self.screen_to_latlng(x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        lats, lngs = [q[0] for q in pts], [q[1] for q in pts]
        return min(lngs), max(lngs), max(lats), min(lats)

    def ground_z(self, lat, lng):
        if self.flat:
            return 0.0
        return self.terrain.elev(lat, lng) / 1000.0 * self.zex

    def _fit_zoom(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w > 50 and h > 50:
            self.zoom = max(3.0, min((w - self._legend_inset()) / 62.0, h / 45.0))

    # ------------------------------------------------------------------ 重繪排程
    def request_redraw(self, fast=False):
        if fast:
            self._fast = True
            if self._full_job:
                self.after_cancel(self._full_job)
            self._full_job = self.after(220, self._full_redraw)
        if self._pending is None:
            self._pending = self.after_idle(self._do_redraw)

    def _full_redraw(self):
        self._full_job = None
        if (self._drag and self._drag.get("moved")) or self._fly or self._zoom_target is not None:
            # 還在拖曳或動畫中：先不做完整重畫（比較花時間，會讓畫面頓一下），等停下來再畫
            self._full_job = self.after(160, self._full_redraw)
            return
        self._fast = False
        self.request_redraw()

    def _do_redraw(self):
        self._pending = None
        self.redraw(fast=getattr(self, "_fast", False))

    def _on_configure(self, _e):
        if self._auto_zoom:
            self._fit_zoom()
        self.request_redraw()

    # ------------------------------------------------------------------ 繪製
    def redraw(self, fast=False):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        self.delete("all")
        self._hit = []
        self._hover = None
        self._sync_legend()
        self._place_topbar(w)
        if self._auto_zoom:
            self._fit_zoom()
        self._setup_projection()
        if self.flat and self._draw_basemap(fast, w, h):
            pass
        else:
            step = self.quality if not fast else max(self.quality + 1, 3)
            self._draw_terrain(step, w, h)
        self._draw_rings()
        self._draw_roads(fast, w, h)
        if self.show["lines"]:
            self._draw_lines(fast)
        self._draw_objects(fast, w, h)
        self._draw_overlays(w, h)
        if self.pick_location:
            f = self.font(0, bold=True)
            text = "請在地圖上點一下要標示的位置（按右鍵取消）"
            tw = self.measure(f, text)
            self.create_rectangle(w / 2 - tw / 2 - 12, 8, w / 2 + tw / 2 + 12, 16 + self._line_height(f),
                                  fill="#1f2328", outline="")
            self.create_text(w / 2, 12, text=text, anchor="n", font=f, fill="#ffffff")
        if self.flat and not fast:
            self._settle_raster()

    def _draw_basemap(self, fast, w, h):
        """把衛星影像（含疊圖與高解析補丁）依目前視角做仿射變換後貼到畫布；失敗回傳 False（改畫地形）。"""
        try:
            P = (self.zoom, self._ca, self._sa, self._sp, self.tx, self.ty, self._w2, self._h2)
            img = self.raster.render((w, h), P, _rgb(BG), fast=fast, view_box=self.view_box())
            photo = self._photo
            if photo is None or (photo.width(), photo.height()) != (w, h):
                photo = self._photo = self._make_photo(img)
            elif hasattr(photo, "paste"):
                photo.paste(img)
            else:
                photo = self._photo = self._make_photo(img)
        except Exception:
            self.raster.base = None     # 這台裝置無法顯示影像，之後都用地形
            return False
        self.create_image(0, 0, anchor="nw", image=photo, tags="basemap")
        return True

    def _settle_raster(self):
        """視角停下來後：需要的話在背景抓高解析圖磚，抓到就重畫。"""
        if self.raster.request_detail(self.zoom, self.view_box()) or self.raster.loader and self.raster.loader.busy:
            if self._raster_job is None:
                self._raster_job = self.after(180, self._poll_raster)

    def _poll_raster(self):
        self._raster_job = None
        if self.raster.poll():
            self.request_redraw()
        loader = self.raster.loader
        if loader and loader.busy:
            self._raster_job = self.after(180, self._poll_raster)
        elif loader and loader.cert_error and self.on_status:
            loader.cert_error = False
            self.on_status("高解析影像：憑證驗證失敗，無法載入")

    def _make_photo(self, img):
        try:
            from PIL import ImageTk
            return ImageTk.PhotoImage(img, master=self)
        except Exception:
            # 沒有 ImageTk 時改用 Tk 內建的 PPM 解碼（較慢但不需額外元件）
            import io
            buf = io.BytesIO()
            img.save(buf, "PPM")
            return tk.PhotoImage(master=self, data=buf.getvalue())

    def _draw_terrain(self, step, w, h):
        t = self.terrain
        # 海面底板
        base = []
        for (i, j) in ((0, 0), (t.nx - 1, 0), (t.nx - 1, t.ny - 1), (0, t.ny - 1)):
            sx, sy, _ = self.project(self._xw[i], self._yw[j], 0.0)
            base.extend((sx, sy))
        self.create_polygon(base, fill=SEA, outline="#b9cbd8")

        I, J, cells = self._cells_for(step)
        ca, sa, cp, sp, zoom = self._ca, self._sa, self._cp, self._sp, self.zoom
        w2, h2, zex = self._w2, self._h2, self.zex
        xa = [(self._xw[i] - self.tx) * ca for i in I]
        xb = [(self._xw[i] - self.tx) * sa for i in I]
        ya = [(self._yw[j] - self.ty) * sa for j in J]
        yb = [(self._yw[j] - self.ty) * ca for j in J]
        SX, SY = [], []
        for b, j in enumerate(J):
            row_e = self._ekm[j]
            sxr, syr = [], []
            for a, i in enumerate(I):
                sxr.append(w2 + (xa[a] - ya[b]) * zoom)
                syr.append(h2 - ((xb[a] + yb[b]) * sp + row_e[i] * zex * cp) * zoom)
            SX.append(sxr)
            SY.append(syr)
        order = sorted(cells, key=lambda c: -(xb[c[0]] + yb[c[1]]))
        create = self.create_polygon
        m = 40 + zoom * 1.3 * step   # 邊界外保留量：至少一個網格的螢幕大小
        for a, b, color in order:
            x0, y0 = SX[b][a], SY[b][a]
            x2, y2 = SX[b + 1][a + 1], SY[b + 1][a + 1]
            if (x0 < -m and x2 < -m) or (x0 > w + m and x2 > w + m):
                continue
            if (y0 < -m and y2 < -m) or (y0 > h + m and y2 > h + m):
                continue
            create(x0, y0, SX[b][a + 1], SY[b][a + 1], x2, y2, SX[b + 1][a], SY[b + 1][a],
                   fill=color, outline=color)

    def _draw_rings(self):
        """距離圈：以某點為圓心、半徑若干公里，畫在地面上。"""
        for ring in self.rings:
            cx, cy = to_xy(ring["lat"], ring["lng"])
            pts = []
            for k in range(73):
                a = math.radians(k * 5)
                sx, sy, _ = self.project(cx + ring["km"] * math.cos(a), cy + ring["km"] * math.sin(a), 0.0)
                pts.extend((sx, sy))
            self.create_line(pts, fill="#ffffff", width=4)
            self.create_line(pts, fill=ring.get("color", "#1f2328"), width=2, dash=(7, 5))

    def _draw_roads(self, fast, w, h):
        """路段房價：道路依中位價上色；聚落式門牌畫成圓點。"""
        self._road_labels = []
        if not self.roads or not self.show.get("roads", True):
            return
        zoom, flat, zex = self.zoom, self.flat, self.zex
        project = self.project
        base_w = 2 if zoom < 12 else (3 if zoom < 40 else 5)
        show_lanes = zoom >= 45 and not fast
        for r in (self.roads[:120] if fast else self.roads):
            sel = self.selected == ("road", r["id"])
            color = r["color"]
            width = base_w + (2 if sel else 0)
            anchor = None
            n_main = len(r["_segs"])
            for k_seg, seg in enumerate(r["_segs"] + (r["_lanes"] if show_lanes or (sel and not fast) else [])):
                lane = k_seg >= n_main
                pts, xs, ys = [], [], []
                for x, y, e in seg:
                    sx, sy, d = project(x, y, 0.0 if flat else e * zex + 0.03)
                    pts.extend((sx, sy))
                    xs.append(sx)
                    ys.append(sy)
                if max(xs) < -20 or min(xs) > w + 20 or max(ys) < -20 or min(ys) > h + 20:
                    continue                                # 整段都在畫面外
                lw = max(2, width - 2) if lane else width
                if not fast and not lane:
                    self.create_line(pts, fill=INK if sel else "#ffffff", width=lw + 2, capstyle="round", joinstyle="round")
                self.create_line(pts, fill=color, width=lw, capstyle="round", joinstyle="round")
                if not fast:
                    lx = ly = -1e9                          # 沿線大約每 12 像素放一個可以點的小方框
                    for k in range(len(xs) - 1):
                        steps = max(1, int((abs(xs[k + 1] - xs[k]) + abs(ys[k + 1] - ys[k])) / 14.0))
                        for q in range(steps):
                            t = (q + 0.5) / steps
                            mx, my = xs[k] + (xs[k + 1] - xs[k]) * t, ys[k] + (ys[k + 1] - ys[k]) * t
                            if 0 <= mx <= w and 0 <= my <= h and abs(mx - lx) + abs(my - ly) >= 12:
                                self._hit.append(("road", r["id"], mx - 8, my - 8, mx + 8, my + 8, d - 800))
                                lx, ly = mx, my
            x, y, e = r["_pt"]
            sx, sy, d = project(x, y, 0.0 if flat else e * zex + 0.03)
            if not (-20 <= sx <= w + 20 and -20 <= sy <= h + 20):
                continue
            if r.get("dot"):
                rad = (6 if zoom < 30 else 9) + (2 if sel else 0)
                self.create_oval(sx - rad, sy - rad, sx + rad, sy + rad, fill=color,
                                 outline=INK if sel else "#ffffff", width=2)
                self._hit.append(("road", r["id"], sx - rad - 3, sy - rad - 3, sx + rad + 3, sy + rad + 3, d - 800))
                anchor = (sx, sy - rad - 2)
            else:
                anchor = (sx, sy - base_w - 3)
            if sel or zoom >= 22:
                self._road_labels.append((2 if sel else -1, 5 + r.get("n", 0), "road", r, anchor[0], anchor[1], d))

    def _draw_lines(self, fast):
        self._station_labels = []
        for ln in self.lines:
            sel = self.selected == ("line", ln["id"])
            width = (4 if sel else 3) if self.zoom > 7 else 2
            for seg in ln["segments"]:
                pts = []
                for lat, lng in seg:
                    x, y = to_xy(lat, lng)
                    sx, sy, _ = self.project(x, y, self.ground_z(lat, lng) + 0.04)
                    pts.extend((sx, sy))
                if len(pts) >= 4:
                    # 白色描邊讓路線在地形上更清楚
                    self.create_line(pts, fill="#ffffff", width=width + 2, capstyle="round", joinstyle="round")
                    opts = {"fill": ln["color"], "width": width, "capstyle": "round", "joinstyle": "round"}
                    if ln.get("dashed"):
                        opts["dash"] = (6, 4)
                        opts["capstyle"] = "butt"
                    self.create_line(pts, **opts)
            if fast or self.zoom < 14:
                continue
            r = 3 if self.zoom < 40 else 5
            for name, lat, lng in ln.get("stations", []):
                x, y = to_xy(lat, lng)
                sx, sy, d = self.project(x, y, self.ground_z(lat, lng) + 0.05)
                self.create_oval(sx - r, sy - r, sx + r, sy + r, fill="#ffffff", outline=ln["color"], width=2)
                self._hit.append(("station", (ln["id"], name), sx - 7, sy - 7, sx + 7, sy + 7, d))
                if self.zoom >= 48:
                    self._station_labels.append((-2, 0, "station", {"id": (ln["id"], name), "label": name.split("（")[0][:14]},
                                                 sx, sy - r - 2, d))

    def _bar_polys(self, bar):
        """計算一根房價柱的各面多邊形（螢幕座標）。"""
        x, y = to_xy(bar["lat"], bar["lng"])
        z0 = self.ground_z(bar["lat"], bar["lng"])
        # 柱子大小以螢幕像素為準並設上下限：放大地圖時柱子不會跟著變成巨塔
        hw = max(6.0, min(11.0, self.BAR_HALF_KM * self.zoom)) / self.zoom
        hmax = max(80.0, min(135.0, self.BAR_MAX_KM * self.zoom)) / self.zoom
        dim = bar.get("dim") and self.selected != ("district", bar["id"])
        if bar.get("value") is not None and not dim:
            hkm = max(0.02 * hmax, bar.get("frac", 0.0) * hmax)
        else:
            hkm = 0.02 * hmax               # 沒有資料、或不符合篩選條件：只留一塊貼地的小方塊
        corners = ((x - hw, y - hw), (x + hw, y - hw), (x + hw, y + hw), (x - hw, y + hw))
        bot = [self.project(cx, cy, z0) for cx, cy in corners]
        top = [self.project(cx, cy, z0 + hkm) for cx, cy in corners]
        faces = []
        shades = (0.70, 0.84, 0.70, 0.84)
        for k in range(4):
            k2 = (k + 1) % 4
            depth = (bot[k][2] + bot[k2][2]) / 2.0
            faces.append((depth, [bot[k][0], bot[k][1], bot[k2][0], bot[k2][1],
                                  top[k2][0], top[k2][1], top[k][0], top[k][1]], shades[k]))
        faces.sort(key=lambda f: -f[0])
        top_poly = []
        for p in top:
            top_poly.extend((p[0], p[1]))
        xs = [p[0] for p in bot + top]
        ys = [p[1] for p in bot + top]
        cx, cy, depth = self.project(x, y, z0 + hkm)
        return faces, top_poly, (min(xs), min(ys), max(xs), max(ys)), (cx, min(ys)), depth

    def _landmark_polys(self, lm):
        """地標模型投影後的各個面 [(深度, 螢幕多邊形, 顏色)]，以及外框與底部中心。"""
        x, y = to_xy(lm["lat"], lm["lng"])
        z0 = self.ground_z(lm["lat"], lm["lng"])
        size_px = max(42.0, min(88.0, 36.0 + self.zoom * 0.35)) * lm.get("size", 1.0)
        s = size_px / 2.2 / self.zoom                       # 模型一個單位相當於幾公里
        cp, sp, ca, sa = self._cp, self._sp, self._ca, self._sa
        cam = (-sa * cp, -ca * cp, sp)                      # 指向觀看者的方向
        out, xs, ys = [], [], []
        for pts, color, n in landmarks_mod.faces_for(lm):
            if n[0] * cam[0] + n[1] * cam[1] + n[2] * cam[2] <= 0.02:
                continue                                    # 背面不畫
            poly, depth = [], 0.0
            for px, py, pz in pts:
                sx, sy, yr = self.project(x + px * s, y + py * s, z0 + pz * s)
                poly.extend((sx, sy))
                xs.append(sx)
                ys.append(sy)
                depth += yr * cp - (z0 + pz * s) * sp
            out.append((depth / len(pts), poly, shade(color, landmarks_mod.brightness(n))))
        out.sort(key=lambda f: -f[0])
        cx, cy, d = self.project(x, y, z0)
        if not xs:
            return [], (cx, cy, cx, cy), (cx, cy, d), size_px
        return out, (min(xs), min(ys), max(xs), max(ys)), (cx, cy, d), size_px

    def _landmark_sprite(self, lm, sel):
        """地標圖案先畫成一張去背小圖（邊緣有反鋸齒），之後每一格只要貼圖；沒有 Pillow 時回傳 None 改畫多邊形。

        回傳 (圖, 圖的左上角相對於地標底部中心的位移 dx, dy, 圖案實際範圍 x0, y0, x1, y1（同樣相對於底部中心）)。
        """
        if self._sprites is None:
            return None
        size_px = max(42.0, min(88.0, 36.0 + self.zoom * 0.35)) * lm.get("size", 1.0)
        size_q = int(round(size_px / 4.0)) * 4                  # 大小、角度取整數格：轉動或縮放時不用每一格都重畫
        az_q, pitch_q = round(self.az / 2.0) * 2.0, round(self.pitch / 2.0) * 2.0
        params = lm.get("params") or {}
        key = (lm["model"], lm.get("state"), tuple(sorted(params.items())), size_q, az_q, pitch_q, bool(sel))
        hit = self._sprites.get(key)
        if hit is not None:
            return hit
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            self._sprites = None
            return None
        a, p = math.radians(az_q), math.radians(pitch_q)
        ca, sa, cp, sp = math.cos(a), math.sin(a), math.cos(p), math.sin(p)
        cam = (-sa * cp, -ca * cp, sp)
        unit = size_q / 2.2
        faces, us, vs = [], [], []
        for pts, color, n in landmarks_mod.faces_for(lm):
            if n[0] * cam[0] + n[1] * cam[1] + n[2] * cam[2] <= 0.02:
                continue
            poly, depth = [], 0.0
            for px, py, pz in pts:
                u = (px * ca - py * sa) * unit
                v = -((px * sa + py * ca) * sp + pz * cp) * unit
                poly.append((u, v))
                us.append(u)
                vs.append(v)
                depth += (px * sa + py * ca) * cp - pz * sp
            faces.append((depth / len(pts), poly, shade(color, landmarks_mod.brightness(n)), shade(color, 0.72)))
        if not faces:
            return None
        faces.sort(key=lambda f: -f[0])
        ss, pad = 3, 2                                          # 放大三倍畫再縮回來，邊緣才平滑
        x0, y0, x1, y1 = min(us), min(vs), max(us), max(vs)
        wpx, hpx = int(math.ceil(x1 - x0)) + 2 * pad, int(math.ceil(y1 - y0)) + 2 * pad
        try:
            img = Image.new("RGBA", (wpx * ss, hpx * ss), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            for _d, poly, fill, edge in faces:
                pts = [((u - x0 + pad) * ss, (v - y0 + pad) * ss) for u, v in poly]
                draw.polygon(pts, fill=_rgb(fill) + (255,))
                draw.line(pts + [pts[0]], fill=_rgb(INK if sel else edge) + (255,), width=ss if sel else 2)
            img = img.convert("RGBa").reduce(ss).convert("RGBA")     # 先乘上透明度再縮，邊緣才不會出現黑邊
            photo = ImageTk.PhotoImage(img, master=self)
        except Exception:
            self._sprites = None                                # 這台裝置畫不出來：之後都改畫多邊形
            return None
        if len(self._sprites) > 500:
            self._sprites.clear()
        out = self._sprites[key] = (photo, x0 - pad, y0 - pad, x0, y0, x1, y1)
        return out

    def _draw_objects(self, fast, w, h):
        items = []
        self._frame_sprites = []            # 這一格用到的圖案要留著參照，否則會被回收變成空白
        for bar in self.bars:
            faces, top_poly, bbox, anchor, depth = self._bar_polys(bar)
            if bbox[2] < -30 or bbox[0] > w + 30 or bbox[3] < -30 or bbox[1] > h + 30:
                continue
            items.append((depth, 0, bar, (faces, top_poly, bbox, anchor)))
        if self.show["markers"]:
            for mk in self.markers:
                x, y = to_xy(mk["lat"], mk["lng"])
                sx, sy, depth = self.project(x, y, self.ground_z(mk["lat"], mk["lng"]))
                if sx < -30 or sx > w + 30 or sy < -30 or sy > h + 60:
                    continue
                items.append((depth, 1, mk, (sx, sy)))
        if self.show.get("landmarks", True) and self.landmarks:
            placed = []
            for lm in sorted(self.landmarks, key=lambda m: (self.selected != (m.get("hit", "landmark"), m["id"]),
                                                            m.get("rank", 3))):
                x, y = to_xy(lm["lat"], lm["lng"])
                cx, cy, depth = self.project(x, y, self.ground_z(lm["lat"], lm["lng"]))
                if cx < -60 or cx > w + 60 or cy < -40 or cy > h + 90:
                    continue
                # 縮小時地標之間要留比較大的間隔才不會糊成一團；放大後間隔可以小一點，鄰近的地標才出得來
                k = 0.8 if self.zoom < 40 else (0.42 if self.zoom >= 150 else 0.8 - (self.zoom - 40) / 110.0 * 0.38)
                gap = max(42.0, min(88.0, 36.0 + self.zoom * 0.35)) * k
                if any((cx - px) ** 2 + (cy - py) ** 2 < gap * gap for px, py in placed):
                    continue                        # 縮小時地標擠在一起：只留比較知名的，放大後其他才出現
                placed.append((cx, cy))
                items.append((depth, 3, lm, None))
        for pin in self.pins:
            x, y = to_xy(pin["lat"], pin["lng"])
            sx, sy, depth = self.project(x, y, self.ground_z(pin["lat"], pin["lng"]))
            if -30 <= sx <= w + 30 and -30 <= sy <= h + 60:
                # 搜尋／點選的門牌圖釘永遠畫在最上面，不會被房價柱擋住
                items.append((-1e9 if pin.get("kind") == "search" else depth, 2, pin, (sx, sy)))
        items.sort(key=lambda it: -it[0])

        labels = []
        for depth, kind, obj, geo in items:
            if kind == 0:
                faces, top_poly, bbox, anchor = geo
                sel = self.selected == ("district", obj["id"])
                dim = obj.get("dim") and not sel
                color = "#d5d8dc" if dim else obj["color"]
                edge = INK if sel else ("#8d949c" if dim else shade(color, 0.55))
                for _d, poly, k in faces[2:]:             # 只畫朝向觀看者的兩個側面（另外兩面被擋住）
                    self.create_polygon(poly, fill=shade(color, k), outline=edge, width=1)
                self.create_polygon(top_poly, fill=color, outline=edge, width=2 if sel else 1)
                self._hit.append(("district", obj["id"], bbox[0] - 3, bbox[1] - 3, bbox[2] + 3, bbox[3] + 3, depth))
                if not dim:
                    labels.append((2 if sel else 0, obj.get("n", 0), "district", obj, anchor[0], anchor[1] - 3, depth))
            elif kind == 3:
                hk = obj.get("hit", "landmark")                 # 地標，或重大建設（project）
                sel = self.selected == (hk, obj["id"])
                sprite = self._landmark_sprite(obj, sel)
                if sprite:
                    photo, dx, dy, bx0, by0, bx1, by1 = sprite
                    x, y = to_xy(obj["lat"], obj["lng"])
                    cx, cy, _d = self.project(x, y, self.ground_z(obj["lat"], obj["lng"]))
                    self.create_image(round(cx + dx), round(cy + dy), anchor="nw", image=photo)
                    self._frame_sprites.append(photo)
                    bbox = (cx + bx0, cy + by0, cx + bx1, cy + by1)
                else:
                    faces, bbox, (cx, cy, _d), _size = self._landmark_polys(obj)
                    for _fd, poly, color in faces:
                        self.create_polygon(poly, fill=color, outline=INK if sel else shade(color, 0.72), width=1)
                # 點擊優先順序排在房價柱之後：地標和柱子疊在一起時，點到的是柱子
                self._hit.append((hk, obj["id"], bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2, depth + 500))
                if sel or (not fast and self.zoom >= (22 if hk == "project" else 26)):
                    labels.append((2 if sel else -1, 30 - obj.get("rank", 3), hk, obj, (bbox[0] + bbox[2]) / 2.0,
                                   bbox[1] - 2, depth))
            elif kind == 2:
                sx, sy = geo
                sel = self.selected == ("pin", obj["id"])
                big = obj.get("kind") == "search"              # 搜尋／點選的門牌：大一點、有落點
                r = 11 if big else (8 if sel else 7)
                ty = sy - (34 if big else 22)
                if big:
                    self.create_oval(sx - 6, sy - 3, sx + 6, sy + 3, fill=shade(obj["color"], 0.6), outline="#ffffff")
                self.create_line(sx, sy, sx, ty, fill=INK, width=3 if big else 2)
                self.create_oval(sx - r, ty - r, sx + r, ty + r, fill=obj.get("color", "#1f2328"),
                                 outline="#ffffff", width=2)
                if big:
                    self.create_oval(sx - 4, ty - 4, sx + 4, ty + 4, fill="#ffffff", outline="")
                elif obj.get("kind") == "work":
                    self.create_rectangle(sx - 3, ty - 3, sx + 3, ty + 3, fill="#ffffff", outline="")
                else:
                    self.create_oval(sx - 2.5, ty - 2.5, sx + 2.5, ty + 2.5, fill="#ffffff", outline="")
                self._hit.append(("pin", obj["id"], sx - r - 4, ty - r - 4, sx + r + 4, ty + r + 4, depth - 1500))
                labels.append((2 if obj.get("kind") == "search" else 1, 99, "pin", obj, sx, ty - r - 2, depth))
            else:
                sx, sy = geo
                sel = self.selected == ("marker", obj["id"])
                lvl = obj.get("level") or 3
                stem = 14 + 3 * lvl
                r = 4 + lvl * 0.8 + (2 if sel else 0)
                ty = sy - stem
                self.create_line(sx, sy, sx, ty, fill=INK_MUTED, width=1)
                self.create_polygon(sx, ty - r, sx + r, ty, sx, ty + r, sx - r, ty,
                                    fill=obj["color"], outline=INK if sel else "#ffffff", width=2 if sel else 1)
                self._hit.append(("marker", obj["id"], sx - r - 4, ty - r - 4, sx + r + 4, ty + r + 4, depth - 1000))
                if sel or (not fast and (lvl >= 5 or self.zoom >= 30)):
                    labels.append((2 if sel else -1, lvl, "marker", obj, sx, ty - r - 2, depth))

        if self.show["labels"] and not fast:
            self._draw_labels(labels + self._road_labels + getattr(self, "_station_labels", []), w, h)
        elif self.selected:
            self._draw_labels([lb for lb in labels + self._road_labels if lb[0] == 2], w, h)

    def _draw_labels(self, labels, w, h):
        labels.sort(key=lambda lb: (-lb[0], -lb[1]))
        placed = []
        f_norm, f_bold = self.font(0), self.font(0, bold=True)
        f_small = self.font(-1)
        line_h = self._line_height(f_bold)
        f_tiny = self.font(-2)
        left = self._legend_inset()
        reserved = self._reserved_boxes(w, h)
        for prio, _n, kind, obj, x, y, depth in labels:
            text = obj["label"]
            font = f_bold if kind == "district" else (f_tiny if kind == "station" else f_small)
            tw = self.measure(font, text)
            if x < left - 20 or x > w + 20 or y < 0 or y > h + line_h:
                continue                                    # 標的本身不在畫面內
            x = min(max(x, left + tw / 2 + 6), w - tw / 2 - 6)   # 靠邊時往內推，文字不被切掉
            x0, y0, x1, y1 = x - tw / 2 - 4, y - line_h - 2, x + tw / 2 + 4, y
            if prio < 1 and any(not (x1 < a or x0 > c or y1 < b or y0 > d) for a, b, c, d in placed + reserved):
                continue
            placed.append((x0, y0, x1, y1))
            sel = prio == 2
            self.create_rectangle(x0, y0, x1, y1, fill="#ffffff" if not sel else "#1f2328",
                                  outline=("#c9ced4" if kind != "station" else "") if not sel else "#1f2328")
            self.create_text(x, y - 1, text=text, anchor="s", font=font,
                             fill=(INK if kind != "station" else INK_MUTED) if not sel else "#ffffff")
            self._hit.append((kind, obj["id"], x0, y0, x1, y1, depth - 2000))

    def _legend_rows(self):
        """圖例內容 [(種類, 文字, ...)]；沒有圖例資料時回傳 None。"""
        if not self.legend:
            return None
        if "lh" not in self._measure:
            self._measure["lh"] = self.font(-1).metrics("linespace") + 3
        lh = self._measure["lh"]
        lg = self.legend
        rows = [("title", lg["title"])]
        for label, color in lg["stops"]:
            rows.append(("swatch", label, color))
        mrt, dev, over = [], [], []
        if self.show["lines"] and self.lines:
            mrt.append(("title", "捷運規劃路線"))
            for ln in self.lines:
                mrt.append(("line", ln["name"], ln["color"], ln.get("dashed")))
            if any(ln.get("dashed") for ln in self.lines):
                mrt.append(("note", "虛線：尚在研議、未核定"))
        if self.legend_projects and any(lm.get("hit") == "project" for lm in self.landmarks):
            dev.extend(self.legend_projects)
        if self.show["markers"] and self.markers and lg.get("marker_types"):
            present = set(m.get("type") for m in self.markers)
            dev.append(("title", "開發案（菱形標記）"))
            for label, color in lg["marker_types"]:
                if label in present:
                    dev.append(("diamond", label, color))
        if self.flat:
            for lid in self.raster.active_overlays():
                over.extend(lg.get("overlay_rows", {}).get(lid, []))
        if self.roads and self.show.get("roads", True):
            over = list(self.legend_extra) + over
        # 放不下時先省略開發案、再省略捷運的說明（疊圖的圖例是使用者剛打開的，優先保留）
        room = max(8, (self.winfo_height() - 30) // lh - 1)
        if len(rows) + len(mrt) + len(dev) + len(over) > room:
            dev = []
        if len(rows) + len(mrt) + len(over) > room:
            mrt = []
        return rows + mrt + dev + over

    def _legend_inset(self):
        """展開的圖例佔用的左側寬度；畫面夠寬時 3D 場景會往右讓開。"""
        if not (self.legend and self.show["legend"]) or self.winfo_width() < 620:
            return 0
        return self._legend_w + 14 if self._legend_w else 0

    def toggle_legend(self):
        self.show["legend"] = not self.show["legend"]
        if self.on_legend_toggle:
            self.on_legend_toggle(self.show["legend"])
        self.request_redraw()

    def _sync_legend(self):
        """圖例畫在疊在地圖左上角的子畫布上；內容有變才重畫（拖曳時每一格都重畫圖例很浪費）。"""
        rows = self._legend_rows()
        box = self._legend_box
        if rows is None:
            if box is not None:
                box.place_forget()
            self._legend_w = 0
            return
        expanded = bool(self.show["legend"])
        sig = (expanded, self.font_size, tuple(rows) if expanded else ())
        if sig == self._legend_sig:
            return
        self._legend_sig = sig
        if box is None:
            box = self._legend_box = tk.Canvas(self, bg="#ffffff", highlightthickness=1,
                                               highlightbackground="#c9ced4", cursor="hand2")
            box.bind("<ButtonRelease-1>", lambda e: self.toggle_legend())
        box.delete("all")
        f, fb = self.font(-1), self.font(-1, bold=True)
        lh = self._measure["lh"]
        head = "圖例 ▲" if expanded else "圖例 ▼"
        hw = self.measure(fb, head)
        if not expanded:
            width, height = hw + 20, lh + 8
            box.create_text(10, 4, text=head, anchor="nw", font=fb, fill=INK)
        else:
            width = max([self.measure(fb, r[1]) if r[0] == "title" else
                         self.measure(f, r[1]) + (0 if r[0] == "note" else 24) for r in rows] + [hw + 60]) + 16
            height = (len(rows) + 1) * lh + 12
            box.create_text(8, 4, text=head, anchor="nw", font=fb, fill=INK_MUTED)
            box.create_text(width - 8, 4, text="點一下收合", anchor="ne", font=f, fill="#9aa1a9")
            box.create_line(0, lh + 5, width, lh + 5, fill="#e3e6ea")
            x, cy = 0, lh + 9
            for r in rows:
                if r[0] == "title":
                    box.create_text(x + 8, cy, text=r[1], anchor="nw", font=fb, fill=INK)
                elif r[0] == "swatch":
                    box.create_rectangle(x + 8, cy + 3, x + 22, cy + lh - 4, fill=r[2], outline=shade(r[2], 0.6))
                    box.create_text(x + 30, cy, text=r[1], anchor="nw", font=f, fill=INK_MUTED)
                elif r[0] == "line":
                    opts = {"fill": r[2], "width": 3}
                    if r[3]:
                        opts["dash"] = (6, 4)
                    box.create_line(x + 6, cy + lh / 2, x + 24, cy + lh / 2, **opts)
                    box.create_text(x + 30, cy, text=r[1], anchor="nw", font=f, fill=INK_MUTED)
                elif r[0] == "note":
                    box.create_text(x + 8, cy, text=r[1], anchor="nw", font=f, fill=INK_MUTED)
                else:
                    mx, my = x + 15, cy + lh / 2 - 1
                    box.create_polygon(mx, my - 6, mx + 6, my, mx, my + 6, mx - 6, my, fill=r[2], outline="#ffffff")
                    box.create_text(x + 30, cy, text=r[1], anchor="nw", font=f, fill=INK_MUTED)
                cy += lh
        self._legend_w = width if expanded else 0
        box.config(width=width, height=height)
        box.place(x=10, y=10)

    def _topbar_box(self, w):
        """搜尋框要放的位置 (x, y, 寬, 高)：圖例（不論展開或收合）的右邊，右邊留給指北針。"""
        tb = self.topbar
        if tb is None:
            return None
        x = 10
        box = self._legend_box
        if box is not None and self._legend_rows() is not None:
            x += int(box.cget("width")) + 10
        width = max(140, min(self.topbar_max, w - x - 84))
        return x, 10, width, tb.winfo_reqheight()

    def _place_topbar(self, w):
        geom = self._topbar_box(w)
        if geom is not None and geom != self._topbar_geom:
            self._topbar_geom = geom
            self.topbar.place(x=geom[0], y=geom[1], width=geom[2])

    def _attribution_lines(self, w):
        """影像來源標示的排版：回傳 (左邊界, [每一行文字])。"""
        f = self.font(-1)
        parts = [t for t in self.raster.attribution().split(" | ") if t] if self.flat else []
        parts += [t for t in self.extra_attribution if t]
        x0 = self._legend_inset() + 6            # 圖例開著時排在圖例右邊，不要壓到圖例
        room = max(200, w - x0 - 190)            # 右下角留給比例尺
        packed = []
        for text in parts:                       # 放得下就併在同一行，少佔地圖
            if packed and self.measure(f, packed[-1] + "；" + text) <= room:
                packed[-1] += "；" + text
            else:
                packed.append(text)
        return x0, packed

    def _reserved_boxes(self, w, h):
        """標籤不要蓋到的區塊：指北針、比例尺、影像來源標示。"""
        f = self.font(-1)
        lh = self._line_height(f)
        boxes = [(w - 72, 0, w, 74), (w - 180, h - lh - 26, w, h)]
        tb = self._topbar_box(w)
        if tb is not None:
            boxes.append((tb[0] - 4, 0, tb[0] + tb[2] + 4, tb[1] + tb[3] + 4))
        x0, packed = self._attribution_lines(w)
        if packed:
            width = max(self.measure(f, t) for t in packed) + 12
            boxes.append((x0, h - 8 - len(packed) * (lh + 2), x0 + width, h))
        return boxes

    def _draw_overlays(self, w, h):
        f = self.font(-1)
        fb = self.font(-1, bold=True)
        # ---- 指北針（右上）
        cx, cy, r = w - 38, 40, 22
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffffff", outline="#c9ced4")
        # 北方在螢幕上的方向：世界 +y 投影後的方向
        nx, ny = -self._sa, -self._ca * self._sp
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln, ny / ln
        self.create_line(cx - nx * (r - 8), cy - ny * (r - 8), cx + nx * (r - 5), cy + ny * (r - 5),
                         fill="#c0392b", width=3, arrow="last", arrowshape=(9, 11, 4))
        self.create_text(cx + nx * (r + 9), cy + ny * (r + 9), text="北", font=fb, fill="#c0392b")
        # ---- 比例尺（右下）
        for km in (50, 20, 10, 5, 2, 1, 0.5):
            if km * self.zoom <= 150:
                break
        px = km * self.zoom
        x1, y1 = w - 14, h - 14
        self.create_rectangle(x1 - px - 8, y1 - self._line_height(f) - 8, x1 + 8, y1 + 7,
                              fill="#ffffff", outline="#c9ced4")
        self.create_line(x1 - px, y1, x1, y1, fill=INK, width=2)
        self.create_line(x1 - px, y1 - 5, x1 - px, y1, fill=INK, width=2)
        self.create_line(x1, y1 - 5, x1, y1, fill=INK, width=2)
        label = ("%g 公里" % km) if km >= 1 else ("%d 公尺" % (km * 1000))
        self.create_text(x1 - px / 2, y1 - 4, text=label, anchor="s", font=f, fill=INK)
        # ---- 資料來源標示（左下，每個來源一行）
        x0, packed = self._attribution_lines(w)
        lh = self._line_height(f)
        y = h - 6
        for text in reversed(packed):
            tw = self.measure(f, text)
            self.create_rectangle(x0, y - lh - 2, x0 + tw + 10, y, fill="#ffffff", outline="")
            self.create_text(x0 + 5, y - 1, text=text, anchor="sw", font=f, fill=INK_MUTED)
            y -= lh + 2

    # ------------------------------------------------------------------ 互動
    def pick(self, x, y):
        best = None
        for kind, ident, x0, y0, x1, y1, depth in self._hit:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if best is None or depth < best[2]:
                    best = (kind, ident, depth)
        return (best[0], best[1]) if best else None

    def _on_press(self, e, alt=False):
        # 左鍵照「拖曳」按鈕的模式（預設平移）；右鍵或按住 Shift 是另一種
        other = alt or bool(e.state & 0x0001)
        self._stop_motion()
        self._drag = {"x": e.x, "y": e.y, "x0": e.x, "y0": e.y, "moved": False,
                      "pan": (self.drag_mode == "pan") != other}
        self._set_hover(None)

    def _on_drag(self, e):
        d = self._drag
        if not d:
            return
        dx, dy = e.x - d["x"], e.y - d["y"]
        if not d["moved"] and abs(e.x - d["x0"]) + abs(e.y - d["y0"]) < 6:
            return
        d["moved"] = True
        d["x"], d["y"] = e.x, e.y
        if d["pan"]:
            # 螢幕位移 -> 世界位移（反推投影）
            xr = -dx / self.zoom
            yr = dy / (self.zoom * max(0.2, math.sin(math.radians(self.pitch))))
            a = math.radians(self.az)
            ca, sa = math.cos(a), math.sin(a)
            self.tx += xr * ca + yr * sa
            self.ty += -xr * sa + yr * ca
            self.tx = max(-45.0, min(45.0, self.tx))
            self.ty = max(-40.0, min(40.0, self.ty))
            self.request_redraw(fast=True)
        else:
            self.rotate_by(dx * 0.35, dy * 0.3)
        if self.on_view_change:
            self.on_view_change()

    def _on_release(self, e):
        d, self._drag = self._drag, None
        if d and not d["moved"] and self.pick_location:
            cb, self.pick_location = self.pick_location, None
            self.config(cursor="")
            if getattr(e, "num", 1) == 3:
                cb(None, None)          # 右鍵取消
            else:
                cb(*self.screen_to_latlng(e.x, e.y))
            self.request_redraw()
            return
        if d and not d["moved"]:
            hit = self.pick(e.x, e.y)
            if hit and self.on_pick:
                self.on_pick(*hit)

    def _on_wheel(self, e):
        # Windows 滑鼠一格是 120；觸控板與高解析滾輪會送比較小的數字，照比例縮放才不會一下跳太多
        notches = max(-3.0, min(3.0, (e.delta or 0) / 120.0)) if abs(e.delta or 0) >= 15 else (1 if e.delta > 0 else -1)
        self.zoom_by(1.2 ** notches, at=(e.x, e.y))

    def _on_motion(self, e):
        if self._drag:
            return
        self._set_hover(self.pick(e.x, e.y), e.x, e.y)

    def _set_hover(self, hit, x=0, y=0):
        if hit == self._hover:
            return
        self._hover = hit
        self.delete("tip")
        if not hit:
            self.config(cursor="")
            return
        self.config(cursor="hand2")
        text = self._tip_text(hit)
        if not text:
            return
        f = self.font(-1)
        lines = text.split("\n")
        tw = max(self.measure(f, s) for s in lines)
        th = f.metrics("linespace") * len(lines)
        px = min(max(8, x + 14), self.winfo_width() - tw - 20)
        py = min(max(8, y + 16), self.winfo_height() - th - 16)
        self.create_rectangle(px, py, px + tw + 12, py + th + 8, fill="#1f2328", outline="", tags="tip")
        self.create_text(px + 6, py + 4, text=text, anchor="nw", font=f, fill="#ffffff", tags="tip")

    def _tip_text(self, hit):
        kind, ident = hit
        if kind == "district":
            for b in self.bars:
                if b["id"] == ident:
                    return b.get("tip") or b["label"]
        elif kind == "marker":
            for m in self.markers:
                if m["id"] == ident:
                    return m.get("tip") or m["label"]
        elif kind == "station":
            for ln in self.lines:
                if ln["id"] == ident[0]:
                    return "%s\n%s" % (ln["name"], ident[1])
        elif kind == "pin":
            for p in self.pins:
                if p["id"] == ident:
                    return p.get("tip") or p["label"]
        elif kind == "road":
            for r in self.roads:
                if r["id"] == ident:
                    return r.get("tip") or r["label"]
        elif kind in ("landmark", "project"):
            for lm in self.landmarks:
                if lm["id"] == ident:
                    return lm.get("tip") or lm["name"]
        return None
