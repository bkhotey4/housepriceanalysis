"""全台 22 縣市的基本資料：實價登錄的縣市代碼、名稱、地圖中心。

實價登錄開放資料以英文字母代表縣市（檔名 A_lvr_land_A.csv 的第一個字母）。
鄉鎮市區的清單與位置由 tools/build_towns.py 從 OpenStreetMap 產生（data/tw/towns.json）。
"""
import json
import os

from .geo import DATA_DIR

# (代碼, 實價登錄／OSM 用的正式名稱, 顯示名稱, 地區, 中心緯度, 中心經度, 預設縮放)
_ROWS = [
    ("A", "臺北市", "台北市", "北部", 25.050, 121.550, 46),
    ("F", "新北市", "新北市", "北部", 25.012, 121.465, 26),
    ("C", "基隆市", "基隆市", "北部", 25.128, 121.740, 50),
    ("H", "桃園市", "桃園市", "北部", 24.950, 121.230, 28),
    ("O", "新竹市", "新竹市", "北部", 24.800, 120.968, 52),
    ("J", "新竹縣", "新竹縣", "北部", 24.800, 121.100, 26),
    ("G", "宜蘭縣", "宜蘭縣", "北部", 24.700, 121.740, 24),
    ("K", "苗栗縣", "苗栗縣", "中部", 24.540, 120.850, 24),
    ("B", "臺中市", "台中市", "中部", 24.160, 120.660, 26),
    ("N", "彰化縣", "彰化縣", "中部", 24.020, 120.480, 28),
    ("M", "南投縣", "南投縣", "中部", 23.910, 120.700, 20),
    ("P", "雲林縣", "雲林縣", "中部", 23.700, 120.420, 26),
    ("I", "嘉義市", "嘉義市", "南部", 23.480, 120.450, 56),
    ("Q", "嘉義縣", "嘉義縣", "南部", 23.460, 120.380, 22),
    ("D", "臺南市", "台南市", "南部", 23.145, 120.340, 22),
    ("E", "高雄市", "高雄市", "南部", 22.680, 120.360, 22),
    ("T", "屏東縣", "屏東縣", "南部", 22.600, 120.550, 20),
    ("U", "花蓮縣", "花蓮縣", "東部", 23.900, 121.550, 16),
    ("V", "臺東縣", "台東縣", "東部", 22.850, 121.130, 16),
    ("X", "澎湖縣", "澎湖縣", "離島", 23.570, 119.580, 30),
    ("W", "金門縣", "金門縣", "離島", 24.440, 118.370, 40),
    ("Z", "連江縣", "連江縣", "離島", 26.160, 119.950, 40),
]
COUNTIES = [{"code": c, "name": n, "short": s, "region": r, "lat": la, "lng": lo, "zoom": z}
            for c, n, s, r, la, lo, z in _ROWS]
BY_CODE = {c["code"]: c for c in COUNTIES}
NATION = "全台"
TOWNS_PATH = os.path.join(DATA_DIR, "tw", "towns.json")


def norm(name):
    """臺／台 視為同一字，比對用。"""
    return (name or "").replace("臺", "台").strip()


_BY_NAME = {}
for _c in COUNTIES:
    for _n in (_c["name"], _c["short"], norm(_c["name"])):
        _BY_NAME[norm(_n)] = _c
_PREFIXES = sorted({p for c in COUNTIES for p in (c["name"], c["short"])}, key=len, reverse=True)


def county_by_name(name):
    return _BY_NAME.get(norm(name))


def split_county(addr):
    """門牌開頭若是縣市名稱，回傳 (縣市 dict, 去掉縣市後的字串)；沒有就回傳 (None, 原字串)。"""
    s = (addr or "").strip()
    for p in _PREFIXES:
        if s.startswith(p):
            return county_by_name(p), s[len(p):]
    # 「台南善化區…」這種省略「市／縣」的寫法（後面緊接著是行政區名稱才算，避免把「基隆路」「桃園區」誤認成縣市）
    for c in COUNTIES:
        for head in {c["short"][:2], c["name"][:2]}:
            if s.startswith(head) and len(s) > 3 and s[2] not in "市縣區鄉鎮路街巷大里村":
                return c, s[2:]
    return None, s


def strip_county(addr):
    return split_county(addr)[1]


def load_towns():
    """{代碼: [{"name", "lat", "lng"}, ...]}；還沒產生過就回傳 {}。"""
    try:
        with open(TOWNS_PATH, encoding="utf-8") as f:
            return json.load(f).get("towns", {})
    except (OSError, ValueError):
        return {}
