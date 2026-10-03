"""地理工具：經緯度 <-> 公里座標、地形高程格網、行政區座標。"""
import json
import math
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 投影原點（台南市範圍中心）
LAT0, LNG0 = 23.145, 120.34
KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LNG = 111.32 * math.cos(math.radians(LAT0))


def to_xy(lat, lng):
    """經緯度 -> 以原點為中心的公里座標 (x 向東, y 向北)。"""
    return (lng - LNG0) * KM_PER_DEG_LNG, (lat - LAT0) * KM_PER_DEG_LAT


def dist_km(lat1, lng1, lat2, lng2):
    x1, y1 = to_xy(lat1, lng1)
    x2, y2 = to_xy(lat2, lng2)
    return math.hypot(x1 - x2, y1 - y2)


def load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


class Terrain:
    """台南地形高程格網（公尺）。rows[j][i]，j=0 為最北列，i=0 為最西行；-1 代表海面。"""

    def __init__(self, data=None):
        d = data or load_json("terrain_tainan.json")
        self.west, self.east = d["west"], d["east"]
        self.north, self.south = d["north"], d["south"]
        self.nx, self.ny = d["nx"], d["ny"]
        self.rows = d["rows"]
        self.source = d.get("source", "")
        self.dx = (self.east - self.west) / (self.nx - 1)
        self.dy = (self.north - self.south) / (self.ny - 1)
        self.max_elev = max(max(r) for r in self.rows)

    def node_latlng(self, i, j):
        return self.north - j * self.dy, self.west + i * self.dx

    def node_elev(self, i, j):
        """格點高程（海面回傳 0）。"""
        v = self.rows[j][i]
        return 0 if v < 0 else v

    def is_sea_node(self, i, j):
        return self.rows[j][i] < 0

    def elev(self, lat, lng):
        """雙線性內插取得任一點高程（公尺）；超出範圍取邊界值。"""
        fx = (lng - self.west) / self.dx
        fy = (self.north - lat) / self.dy
        fx = min(max(fx, 0.0), self.nx - 1.000001)
        fy = min(max(fy, 0.0), self.ny - 1.000001)
        i, j = int(fx), int(fy)
        tx, ty = fx - i, fy - j
        e00 = self.node_elev(i, j)
        e10 = self.node_elev(i + 1, j)
        e01 = self.node_elev(i, j + 1)
        e11 = self.node_elev(i + 1, j + 1)
        return (e00 * (1 - tx) + e10 * tx) * (1 - ty) + (e01 * (1 - tx) + e11 * tx) * ty

    def is_sea(self, lat, lng):
        fx = (lng - self.west) / self.dx
        fy = (self.north - lat) / self.dy
        i = min(max(int(round(fx)), 0), self.nx - 1)
        j = min(max(int(round(fy)), 0), self.ny - 1)
        return self.rows[j][i] < 0


def load_districts():
    return load_json("districts.json")["districts"]


def google_terrain_url(lat, lng, zoom=14):
    """Google 地圖「地形」圖層（官方 Maps URLs，免金鑰）。"""
    return ("https://www.google.com/maps/@?api=1&map_action=map"
            "&center=%.5f,%.5f&zoom=%d&basemap=terrain" % (lat, lng, zoom))


def google_satellite_url(lat, lng, zoom=15):
    return ("https://www.google.com/maps/@?api=1&map_action=map"
            "&center=%.5f,%.5f&zoom=%d&basemap=satellite" % (lat, lng, zoom))


def google_search_url(query):
    from urllib.parse import quote
    return "https://www.google.com/maps/search/?api=1&query=" + quote(query)


def google_directions_url(lat1, lng1, lat2, lng2):
    """Google 地圖開車路線（官方 Maps URLs，免金鑰）。"""
    return ("https://www.google.com/maps/dir/?api=1&origin=%.5f,%.5f&destination=%.5f,%.5f&travelmode=driving"
            % (lat1, lng1, lat2, lng2))
