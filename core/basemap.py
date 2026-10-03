"""衛星影像底圖與疊圖（需要 Pillow）。

圖資來源（都是免金鑰的政府開放圖資，2026-09-30 在使用者電腦的瀏覽器實測可用）：
  * 衛星影像、行政區界、道路地名、土壤液化潛勢：內政部國土測繪中心 WMTS
  * 活動斷層與斷層地質敏感區：經濟部地質調查及礦業管理中心 WMS

要把 Google 衛星圖放進 App 必須申請 Google Maps API 金鑰，沒有金鑰時條款不允許直接抓取圖磚，
因此 App 內改用國土測繪中心的航照影像；要看 Google 衛星圖仍可按「Google 衛星圖」按鈕。

運作方式：
  1. 每個圖層第一次使用時，下載涵蓋全台南的圖磚拼成一張圖，存到 data/cache/basemap/，之後離線可用。
  2. 放大超過拼圖解析度時，背景下載目前視野的高倍率圖磚（存到 data/cache/tiles/），貼在拼圖上。
  3. 每次重繪把影像依目前視角做仿射變換（正交投影下，地面到螢幕是線性關係）。
沒有 Pillow 時 App 會自動改用立體地形。
"""
import io
import json
import math
import os
import queue
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from . import plvr
from .geo import DATA_DIR, KM_PER_DEG_LAT, KM_PER_DEG_LNG, LAT0, LNG0

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:  # Pillow 未安裝
    Image = None
    HAVE_PIL = False

WMTS_URL = "https://wmts.nlsc.gov.tw/wmts/{name}/default/GoogleMapsCompatible/{z}/{y}/{x}"
FAULT_WMS = ("https://geomap.gsmma.gov.tw/mapguide/mapagent/mapagent.fcgi?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
             "&LAYERS=WMS/25K_Geomap_fault_2021,WMS/Sensitive_area_fault&STYLES=&SRS=EPSG:4326"
             "&BBOX={w},{s},{e},{n}&WIDTH={W}&HEIGHT={H}&FORMAT=image/png&TRANSPARENT=TRUE")

LAYERS = OrderedDict([
    ("photo", {"name": "衛星影像", "sources": ["PHOTO2"], "rgba": False, "max_z": 19, "detail": True,
               "attribution": "影像：內政部國土測繪中心"}),
    ("liq", {"name": "土壤液化潛勢", "sources": ["SoilLiquefaction", "SoilLiquefaction2"], "rgba": True,
             "max_z": 15, "detail": False, "opacity": 0.55,
             "attribution": "土壤液化潛勢：經濟部地質調查及礦業管理中心、臺南市政府（圖磚：國土測繪中心）"}),
    ("fault", {"name": "活動斷層", "wms": True, "rgba": True, "detail": False,
               "attribution": "活動斷層：經濟部地質調查及礦業管理中心"}),
    ("town", {"name": "行政區界", "sources": ["TOWN"], "rgba": True, "max_z": 17, "detail": True,
              "attribution": "行政區界：內政部國土測繪中心"}),
    ("roads", {"name": "道路與地名", "sources": ["EMAP2"], "rgba": True, "max_z": 19, "detail": True,
               "attribution": "電子地圖：內政部國土測繪中心"}),
])
OVERLAY_ORDER = ["liq", "fault", "town", "roads"]      # 由下往上的繪製順序
PROVIDER = {"id": "nlsc_photo2", "name": "國土測繪中心正射影像",
            "url": WMTS_URL.replace("{name}", "PHOTO2"), "attribution": LAYERS["photo"]["attribution"]}

CACHE_DIR = os.path.join(DATA_DIR, "cache", "basemap")
TILE_DIR = os.path.join(DATA_DIR, "cache", "tiles")
TILE = 256
# 涵蓋範圍（與地形格網相同）
WEST, EAST, NORTH, SOUTH = 120.02, 120.66, 23.42, 22.87
EARTH_KM = 40075.017


# ------------------------------------------------------------------ 圖磚座標（Web Mercator）
def lng_to_x(lng, z):
    return (lng + 180.0) / 360.0 * (2 ** z)


def lat_to_y(lat, z):
    r = math.radians(lat)
    return (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * (2 ** z)


def x_to_lng(x, z):
    return x / float(2 ** z) * 360.0 - 180.0


def y_to_lat(y, z):
    n = math.pi - 2.0 * math.pi * y / float(2 ** z)
    return math.degrees(math.atan(math.sinh(n)))


def tile_range(z, west=WEST, east=EAST, north=NORTH, south=SOUTH):
    """回傳涵蓋範圍所需的圖磚 (x0, x1, y0, y1)，兩端皆含。"""
    return (int(math.floor(lng_to_x(west, z))), int(math.floor(lng_to_x(east, z))),
            int(math.floor(lat_to_y(north, z))), int(math.floor(lat_to_y(south, z))))


def px_per_km(z, lat=LAT0):
    """該縮放層級的圖磚在地面上每公里有幾個像素。"""
    return TILE * (2 ** z) / (EARTH_KM * math.cos(math.radians(lat)))


def _paths(z, layer="photo"):
    if layer == "photo":
        base = os.path.join(CACHE_DIR, "%s_z%d" % (PROVIDER["id"], z))      # 沿用舊檔名，既有快取可直接用
        return base + ".jpg", base + ".json"
    if layer == "fault":
        base = os.path.join(CACHE_DIR, "layer_fault")
    else:
        base = os.path.join(CACHE_DIR, "layer_%s_z%d" % (layer, z))
    return base + ".png", base + ".json"


class Basemap:
    """一張影像與它的經緯度範圍；RGB（底圖）或 RGBA（疊圖）皆可。"""

    def __init__(self, image, west, east, north, south, z, attribution="", pyramid=True):
        self.image = image
        self.west, self.east, self.north, self.south = west, east, north, south
        self.z = z
        self.attribution = attribution
        self.rgba = image.mode == "RGBA"
        self.width, self.height = image.size
        # 每公里幾個影像像素（x、y 方向）
        self.px_per_km_x = self.width / ((east - west) * KM_PER_DEG_LNG)
        self.px_per_km_y = self.height / ((north - south) * KM_PER_DEG_LAT)
        self.levels = [(1.0, image)]
        s, im = 1.0, image
        while pyramid and min(im.size) > 600:
            s /= 2.0
            try:
                im = im.reduce(2)
            except AttributeError:      # 舊版 Pillow 沒有 reduce
                im = im.resize((im.size[0] // 2, im.size[1] // 2))
            self.levels.append((s, im))

    def level_for(self, screen_px_per_km):
        """挑一個解析度不超過螢幕需求太多的層級，回傳 (縮放比例, 影像)。"""
        ratio = self.px_per_km_x / float(screen_px_per_km)   # 每個螢幕像素對應幾個原圖像素
        best = self.levels[0]
        for s, im in self.levels:
            if ratio * s >= 0.85:
                best = (s, im)
        return best

    def affine(self, zoom, ca, sa, sp, tx, ty, w2, h2, scale=1.0):
        """回傳 PIL AFFINE 係數：螢幕像素 (sx, sy) -> 影像像素。

        與 View3D.project() 在 z=0 平面的反函數一致：
            xr = (sx - w2) / zoom,  yr = (h2 - sy) / (zoom * sp)
            X = tx + xr*ca + yr*sa, Y = ty - xr*sa + yr*ca
        """
        sp = max(sp, 1e-3)
        ax, ay = self.px_per_km_x, self.px_per_km_y
        bx = (LNG0 - self.west) / (self.east - self.west) * self.width
        by = (self.north - LAT0) / (self.north - self.south) * self.height
        a = ax * ca / zoom
        b = -ax * sa / (zoom * sp)
        c = ax * (tx - w2 * ca / zoom + h2 * sa / (zoom * sp)) + bx
        d = ay * sa / zoom
        e = ay * ca / (zoom * sp)
        f = -ay * (ty + w2 * sa / zoom + h2 * ca / (zoom * sp)) + by
        return tuple(v * scale for v in (a, b, c, d, e, f))

    def render(self, size, zoom, ca, sa, sp, tx, ty, w2, h2, fill=None, fast=False):
        if fill is None:
            fill = (0, 0, 0, 0) if self.rgba else (238, 241, 244)
        scale, im = self.level_for(zoom)
        coeffs = self.affine(zoom, ca, sa, sp, tx, ty, w2, h2, scale)
        resample = Image.NEAREST if fast else Image.BILINEAR
        try:
            return im.transform(size, Image.AFFINE, coeffs, resample=resample, fillcolor=fill)
        except TypeError:               # 舊版 Pillow 沒有 fillcolor
            return im.transform(size, Image.AFFINE, coeffs, resample=resample)

    def pixel_of(self, lat, lng):
        """經緯度 -> 原圖像素（與 affine 相同的線性近似）。"""
        return ((lng - self.west) / (self.east - self.west) * self.width,
                (self.north - lat) / (self.north - self.south) * self.height)

    def intersects(self, west, east, north, south):
        return not (self.east < west or self.west > east or self.north < south or self.south > north)


# ------------------------------------------------------------------ 快取讀取
def cached_zooms(layer="photo"):
    out = []
    if os.path.isdir(CACHE_DIR):
        for z in range(10, 17):
            img, meta = _paths(z, layer)
            if os.path.exists(img) and os.path.exists(meta):
                out.append(z)
                if layer == "fault":
                    break
    return out


def load(z=None, layer="photo"):
    """讀取快取的影像拼圖；沒有快取或沒有 Pillow 回傳 None。"""
    if not HAVE_PIL:
        return None
    zs = cached_zooms(layer)
    if not zs:
        return None
    z = z if z in zs else max(zs)
    img_path, meta_path = _paths(z, layer)
    try:
        with open(meta_path, encoding="utf-8") as f:
            m = json.load(f)
        im = Image.open(img_path)
        im.load()
        im = im.convert("RGBA" if LAYERS[layer]["rgba"] else "RGB")
        if im.size != (m["width"], m["height"]):
            return None
        # 疊圖會先合成到底圖上再顯示，不需要自己的縮圖層級（省記憶體）
        return Basemap(im, m["west"], m["east"], m["north"], m["south"], m["z"], m.get("attribution", ""),
                       pyramid=(layer == "photo"))
    except Exception:
        return None


# ------------------------------------------------------------------ 下載
def _decode(data, rgba):
    tile = Image.open(io.BytesIO(data))
    tile.load()
    return tile.convert("RGBA" if rgba else "RGB")


def _merge_sources(tiles):
    """多個來源疊成一張：後面的來源在有資料的地方「取代」前面的（例如中級液化圖取代初級）。"""
    out = tiles[0]
    for t in tiles[1:]:
        mask = t.getchannel("A").point(lambda a: 255 if a else 0)
        out.paste(t, (0, 0), mask)
    return out


def _save(bm, layer, z, extra=None):
    os.makedirs(CACHE_DIR, exist_ok=True)
    img_path, meta_path = _paths(z, layer)
    part = img_path + ".part"
    if bm.rgba:
        bm.image.save(part, "PNG")
    else:
        bm.image.save(part, "JPEG", quality=86)
    os.replace(part, img_path)
    meta = {"layer": layer, "provider": PROVIDER["id"] if layer == "photo" else layer,
            "attribution": bm.attribution, "z": z, "west": bm.west, "east": bm.east,
            "north": bm.north, "south": bm.south, "width": bm.width, "height": bm.height}
    meta.update(extra or {})
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def download(z=13, progress=None, insecure=False, workers=4, layer="photo"):
    """下載某個圖層涵蓋全台南的圖磚並拼成一張影像，存入快取後回傳 Basemap。progress(done, total, message)。"""
    if not HAVE_PIL:
        raise plvr.DownloadError("需要先安裝 Pillow（pip install pillow）才能使用衛星影像底圖。")
    cfg = LAYERS[layer]
    if cfg.get("wms"):
        return download_fault(progress=progress, insecure=insecure)
    rgba, sources, label = cfg["rgba"], cfg["sources"], cfg["name"]
    x0, x1, y0, y1 = tile_range(z)
    jobs = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    total = len(jobs)
    size = ((x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE)
    mosaic = Image.new("RGBA", size, (0, 0, 0, 0)) if rgba else Image.new("RGB", size, (200, 205, 210))
    lock = threading.Lock()
    state = {"done": 0, "failed": 0, "cert": None}

    def one(job):
        x, y = job
        tile = None
        for _attempt in range(3):
            if state["cert"]:
                break
            try:
                parts = [_decode(plvr.fetch(WMTS_URL.format(name=name, z=z, x=x, y=y), timeout=30, insecure=insecure),
                                 rgba) for name in sources]
                tile = _merge_sources(parts) if len(parts) > 1 else parts[0]
                break
            except plvr.CertError as e:
                state["cert"] = e
                break
            except Exception:
                tile = None
        with lock:
            if tile is not None and tile.size == (TILE, TILE):
                mosaic.paste(tile, ((x - x0) * TILE, (y - y0) * TILE))
            else:
                state["failed"] += 1
            state["done"] += 1
            if progress:
                progress(state["done"], total, "下載%s %d/%d …" % (label if layer != "photo" else "衛星底圖",
                                                                state["done"], total))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    if state["cert"]:
        raise plvr.CertError(str(state["cert"]))
    if state["failed"] > total * 0.1:
        raise plvr.DownloadError("%s下載不完整（%d/%d 張失敗），請確認網路後再試。" % (
            label if layer != "photo" else "衛星底圖", state["failed"], total))

    bm = Basemap(mosaic, x_to_lng(x0, z), x_to_lng(x1 + 1, z), y_to_lat(y0, z), y_to_lat(y1 + 1, z), z,
                 cfg["attribution"], pyramid=(layer == "photo"))
    _save(bm, layer, z, {"failed_tiles": state["failed"]})
    return bm


def download_fault(progress=None, insecure=False):
    """活動斷層：向地礦中心 WMS 要一張涵蓋全台南的透明 PNG。"""
    if not HAVE_PIL:
        raise plvr.DownloadError("需要先安裝 Pillow（pip install pillow）才能使用疊圖。")
    if progress:
        progress(0, 1, "下載活動斷層圖（地質中心的伺服器要算一下，大約半分鐘）…")
    last = None
    for W, H in ((2048, 1760), (1024, 880)):       # 伺服器若不接受大圖就改要小一點的
        url = FAULT_WMS.format(w=WEST, s=SOUTH, e=EAST, n=NORTH, W=W, H=H)
        try:
            data = plvr.fetch(url, timeout=90, insecure=insecure)
            if data[:4] != b"\x89PNG":
                last = plvr.DownloadError("活動斷層圖服務沒有回傳影像。")
                continue
            im = _decode(data, True)
            bm = Basemap(im, WEST, EAST, NORTH, SOUTH, 0, LAYERS["fault"]["attribution"], pyramid=False)
            _save(bm, "fault", 0)
            if progress:
                progress(1, 1, "活動斷層圖完成")
            return bm
        except plvr.CertError:
            raise
        except plvr.DownloadError as e:
            last = e
    raise last or plvr.DownloadError("活動斷層圖下載失敗。")


# ------------------------------------------------------------------ 放大時的高解析圖磚
class DetailLoader:
    """在背景執行緒下載目前視野的高倍率圖磚，組成「補丁」影像；主執行緒用 poll() 取回結果。"""

    MEM_MAX = 260

    def __init__(self):
        self.queue = queue.Queue()
        self.tokens = {}
        self.pending = 0
        self.insecure = False
        self.cert_error = False
        self._jobs = ThreadPoolExecutor(max_workers=2)
        self._pool = ThreadPoolExecutor(max_workers=6)
        self._mem = OrderedDict()
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self.pending > 0

    def request(self, layer, z, x0, x1, y0, y1):
        token = self.tokens.get(layer, 0) + 1
        self.tokens[layer] = token
        self.pending += 1
        self._jobs.submit(self._job, layer, token, z, x0, x1, y0, y1)

    def _tile(self, name, z, x, y, rgba):
        key = (name, z, x, y)
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                return self._mem[key]
        ext = "png" if rgba else "jpg"
        path = os.path.join(TILE_DIR, name, str(z), "%d_%d.%s" % (y, x, ext))
        tile = None
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    tile = _decode(f.read(), rgba)
            except Exception:
                tile = None
        if tile is None:
            try:
                data = plvr.fetch(WMTS_URL.format(name=name, z=z, x=x, y=y), timeout=25, insecure=self.insecure)
                tile = _decode(data, rgba)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".part", "wb") as f:
                    f.write(data)
                os.replace(path + ".part", path)
            except plvr.CertError:
                self.cert_error = True
                return None
            except Exception:
                return None
        with self._lock:
            self._mem[key] = tile
            while len(self._mem) > self.MEM_MAX:
                self._mem.popitem(last=False)
        return tile

    def _job(self, layer, token, z, x0, x1, y0, y1):
        try:
            cfg = LAYERS[layer]
            name, rgba = cfg["sources"][0], cfg["rgba"]
            tiles = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]

            def one(xy):
                if self.tokens.get(layer) != token:
                    return xy, None
                return xy, self._tile(name, z, xy[0], xy[1], rgba)

            patch = Image.new("RGBA", ((x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE), (0, 0, 0, 0))
            got = 0
            for (x, y), tile in self._pool.map(one, tiles):
                if tile is not None:
                    patch.paste(tile.convert("RGBA"), ((x - x0) * TILE, (y - y0) * TILE))
                    got += 1
            if got and self.tokens.get(layer) == token:
                bm = Basemap(patch, x_to_lng(x0, z), x_to_lng(x1 + 1, z), y_to_lat(y0, z), y_to_lat(y1 + 1, z), z,
                             cfg["attribution"], pyramid=False)
                self.queue.put((layer, bm, (z, x0, x1, y0, y1)))
        except Exception:
            pass
        finally:
            self.queue.put(("__done__", None, None))

    def poll(self):
        out = []
        try:
            while True:
                layer, bm, key = self.queue.get_nowait()
                if layer == "__done__":
                    self.pending = max(0, self.pending - 1)
                else:
                    out.append((layer, bm, key))
        except queue.Empty:
            pass
        return out


def plan_detail(zoom, west, east, north, south, base_z, max_z, max_tiles=60):
    """決定要抓哪一層、哪些圖磚。回傳 (z, x0, x1, y0, y1)；不需要高解析時回傳 None。"""
    west, east = max(west, WEST - 0.03), min(east, EAST + 0.03)
    south, north = max(south, SOUTH - 0.03), min(north, NORTH + 0.03)
    if west >= east or south >= north:
        return None
    if zoom <= px_per_km(base_z) * 1.2:
        return None
    z = base_z + 1
    while z < max_z and px_per_km(z) < 0.75 * zoom:
        z += 1
    while z > base_z:
        x0, x1, y0, y1 = tile_range(z, west, east, north, south)
        if (x1 - x0 + 1) * (y1 - y0 + 1) <= max_tiles:
            return z, x0, x1, y0, y1
        z -= 1
    return None


def with_opacity(img, k):
    """把 RGBA 影像的透明度整體乘上 k（0~1）；k 接近 1 時直接回傳原圖。"""
    if k >= 0.995:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda a: int(a * k + 0.5)))
    return out


def resample_to(src, dst):
    """把 src（Basemap）的影像重新取樣到 dst（Basemap）的像素格線上，回傳與 dst 同尺寸的影像。

    兩者都把經緯度當成與像素呈線性關係（和畫面上的仿射貼圖用同一個近似），所以是單純的平移加縮放。
    """
    if (src.image.size == dst.image.size and abs(src.west - dst.west) < 1e-9 and abs(src.east - dst.east) < 1e-9
            and abs(src.north - dst.north) < 1e-9 and abs(src.south - dst.south) < 1e-9):
        return src.image
    a = (dst.east - dst.west) / dst.width / (src.east - src.west) * src.width
    c = (dst.west - src.west) / (src.east - src.west) * src.width
    e = (dst.north - dst.south) / dst.height / (src.north - src.south) * src.height
    f = (src.north - dst.north) / (src.north - src.south) * src.height
    fill = (0, 0, 0, 0) if src.rgba else (238, 241, 244)
    try:
        return src.image.transform(dst.image.size, Image.AFFINE, (a, 0.0, c, 0.0, e, f),
                                   resample=Image.BILINEAR, fillcolor=fill)
    except TypeError:               # 舊版 Pillow 沒有 fillcolor
        return src.image.transform(dst.image.size, Image.AFFINE, (a, 0.0, c, 0.0, e, f), resample=Image.BILINEAR)


class RasterStack:
    """底圖＋疊圖＋高解析補丁，負責把它們依視角合成一張影像。

    為了讓拖曳順暢，疊圖不是每一格畫面都各自轉一次，而是在「開關疊圖、調整濃淡、補丁更新」時
    先合成好一張「已疊好的底圖」（以及一張「已疊好的補丁」），之後每一格只需要做一到兩次仿射變換。
    """

    def __init__(self):
        self.base = None            # 衛星影像拼圖
        self.overlays = {}          # 圖層 id -> Basemap（RGBA 拼圖）
        self.enabled = set()        # 目前開啟的疊圖 id
        self.patches = {}           # 圖層 id -> (Basemap 補丁, key)
        self.opacity = {}           # 圖層 id -> 濃淡（0~1，乘在圖層本身的透明度上）
        self.detail = True
        self._last_plan = {}
        self._flat = (None, None)   # (key, Basemap)：底圖＋疊圖
        self._flat_patch = (None, None)
        self.loader = DetailLoader() if HAVE_PIL else None

    def active_overlays(self):
        return [lid for lid in OVERLAY_ORDER if lid in self.enabled and lid in self.overlays]

    def opacity_of(self, lid):
        return float(self.opacity.get(lid, LAYERS[lid].get("opacity", 1.0)))

    def set_opacity(self, lid, value):
        self.opacity[lid] = max(0.1, min(1.0, float(value)))

    def attribution(self):
        parts = [self.base.attribution] if self.base and self.base.attribution else []
        for lid in self.active_overlays():
            parts.append(LAYERS[lid]["attribution"])
        return " | ".join(parts)

    def _overlay_key(self):
        return tuple((lid, id(self.overlays[lid]), round(self.opacity_of(lid), 3)) for lid in self.active_overlays())

    def flattened(self):
        """底圖加上目前開啟的疊圖（依濃淡）合成後的 Basemap；沒有疊圖時就是底圖本身。"""
        active = self.active_overlays()
        if not active:
            self._flat = (None, None)
            return self.base
        key = (id(self.base), self._overlay_key())
        if self._flat[0] != key:
            img = self.base.image.convert("RGB")       # convert 會複製，不動到原圖
            for lid in active:
                ov = with_opacity(resample_to(self.overlays[lid], self.base), self.opacity_of(lid))
                img.paste(ov, (0, 0), ov)
            b = self.base
            self._flat = (key, Basemap(img, b.west, b.east, b.north, b.south, b.z, b.attribution))
        return self._flat[1]

    def _patch(self, layer, zoom, view_box):
        entry = self.patches.get(layer)
        if not entry or not self.detail:
            return None
        bm = entry[0]
        if px_per_km(bm.z) > zoom * 3.2:        # 已經縮得很小，補丁解析度過高反而有雜訊
            return None
        if view_box and not bm.intersects(*view_box):
            return None
        return bm

    def flattened_patch(self, zoom, view_box):
        """高解析影像補丁加上疊圖後的 Basemap（RGBA）；目前視野用不到補丁時回傳 None。"""
        photo = self._patch("photo", zoom, view_box)
        if photo is None:
            return None
        active = self.active_overlays()
        if not active:
            return photo
        sources = []
        for lid in active:
            src = self.overlays[lid]
            entry = self.patches.get(lid)
            if entry:                               # 疊圖自己的高解析補丁要完整蓋住影像補丁才用，否則用全區拼圖
                p = entry[0]
                if (p.west <= photo.west + 1e-9 and p.east >= photo.east - 1e-9
                        and p.north >= photo.north - 1e-9 and p.south <= photo.south + 1e-9):
                    src = p
            sources.append((lid, src))
        key = (id(photo), tuple((lid, id(src), round(self.opacity_of(lid), 3)) for lid, src in sources))
        if self._flat_patch[0] != key:
            img = photo.image.copy()
            alpha = img.getchannel("A")             # 影像補丁沒有圖磚的地方保持透明，露出下面的底圖
            for lid, src in sources:
                ov = with_opacity(resample_to(src, photo), self.opacity_of(lid))
                img.paste(ov, (0, 0), ov)
            img.putalpha(alpha)
            self._flat_patch = (key, Basemap(img, photo.west, photo.east, photo.north, photo.south, photo.z,
                                             photo.attribution, pyramid=False))
        return self._flat_patch[1]

    def render(self, size, P, fill, fast=False, view_box=None):
        """P = (zoom, ca, sa, sp, tx, ty, w2, h2)。回傳 RGB 影像。"""
        frame = self.flattened().render(size, *P, fill=fill, fast=fast)
        patch = self.flattened_patch(P[0], view_box)
        if patch is not None:
            over = patch.render(size, *P, fast=fast)
            frame.paste(over, (0, 0), over)
        return frame

    def request_detail(self, zoom, view_box):
        """視角停下來後呼叫：需要的話開始抓高解析圖磚。回傳是否有送出請求。"""
        if not (self.detail and self.loader and self.base):
            return False
        sent = False
        for lid in ["photo"] + self.active_overlays():
            cfg = LAYERS[lid]
            if not cfg.get("detail"):
                continue
            base_z = self.base.z if lid == "photo" else self.overlays[lid].z
            plan = plan_detail(zoom, view_box[0], view_box[1], view_box[2], view_box[3], base_z, cfg["max_z"])
            if plan is None:
                continue
            cur = self.patches.get(lid)
            if cur:
                z, x0, x1, y0, y1 = cur[1]
                if z == plan[0] and x0 <= plan[1] and x1 >= plan[2] and y0 <= plan[3] and y1 >= plan[4]:
                    continue        # 現有補丁已涵蓋
            if self._last_plan.get(lid) == plan:
                continue            # 同一個請求已送出（可能還在下載，或該處沒有圖磚）
            self._last_plan[lid] = plan
            self.loader.request(lid, *plan)
            sent = True
        return sent

    def poll(self):
        """取回背景下載完成的補丁；有新東西回傳 True。"""
        if not self.loader:
            return False
        got = False
        for lid, bm, key in self.loader.poll():
            self.patches[lid] = (bm, key)
            got = True
        return got
