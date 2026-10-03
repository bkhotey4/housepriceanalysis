"""電腦版目前看的縣市：切換縣市時，一次把地圖原點、底圖範圍、道路快取、房價資料來源都換掉。

臺南市（D）沿用原本的資料與快取（地形高程、人工校正的行政區位置、只抓臺南的實價登錄），行為和以前完全一樣。
其他縣市：
  行政區位置   data/tw/towns.json（GitHub Actions 由 OpenStreetMap 產生，git pull 就有）；沒有的話由交易資料推估
  實價登錄     core/plvr_tw.py 下載全國檔（一次下載、22 縣市共用），再彙整成該縣市的統計，快取在 data/cache/county/<代碼>/
  道路位置     自己下載的放 data/cache/roads_tw/<代碼>/；也會直接用網頁版已抓好的 web/data/tw/<代碼>/roads/
  地形         沒有高程資料，地面以平面顯示
"""
import datetime
import json
import math
import os

from . import basemap, geo, plvr, plvr_tw, prices, roads
from .taiwan import BY_CODE, COUNTIES, load_towns, norm

DEFAULT = "D"
CODE = DEFAULT
COUNTY_CACHE = os.path.join(geo.DATA_DIR, "cache", "county")
WEB_TW = os.path.join(geo.BASE_DIR, "web", "data", "tw")
# 各縣市大致半徑（公里），沒有鄉鎮位置資料時用來決定地圖範圍（與 core/datacheck.py 相同）
_KM = {"U": 120, "V": 130, "M": 75, "F": 60, "G": 55, "E": 75, "T": 95, "Q": 60, "B": 60, "J": 50, "K": 50,
       "H": 45, "N": 45, "P": 50, "A": 18, "C": 15, "O": 15, "I": 10, "X": 50, "W": 25, "Z": 65}
_TAINAN_ORIGIN = (23.145, 120.34)
_SAVED = None          # 切到別的縣市前，臺南的底圖／道路設定


def info(code=None):
    return BY_CODE[code or CODE]


def is_tainan(code=None):
    return (code or CODE) == "D"


def city_label(code=None):
    """房價表裡代表「全縣市」的那一列名稱（臺南沿用「台南市」）。"""
    return info(code)["short"]


def _cache_dir(code=None):
    return os.path.join(COUNTY_CACHE, code or CODE)


def bounds(code=None, towns=None):
    """(west, east, north, south)：鄉鎮位置的外框再留一點邊；沒有鄉鎮資料就用縣市中心與半徑。"""
    code = code or CODE
    if code == "D":
        return basemap.TAINAN_BOUNDS
    c = BY_CODE[code]
    pts = [(t["lat"], t["lng"]) for t in (towns if towns is not None else load_towns().get(code, []))
           if t.get("lat") is not None and not t.get("approx")
           and geo.dist_km(t["lat"], t["lng"], c["lat"], c["lng"]) <= _KM.get(code, 40) * 1.2]   # 烏坵這種遠離本島的不撐大範圍
    if len(pts) >= 2:
        lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
        m = 0.07 if len(pts) > 4 else 0.04
        w, e, n, s = min(lngs) - m, max(lngs) + m, max(lats) + m, min(lats) - m
    else:
        r = _KM.get(code, 40) * 0.75
        dlat, dlng = r / 110.57, r / (111.32 * math.cos(math.radians(c["lat"])))
        w, e, n, s = c["lng"] - dlng, c["lng"] + dlng, c["lat"] + dlat, c["lat"] - dlat
    return round(w, 4), round(e, 4), round(n, 4), round(s, 4)


def activate(code):
    """切換到某縣市（只改模組狀態，不讀大檔）。未知代碼退回臺南。"""
    global CODE, _SAVED
    code = code if code in BY_CODE else DEFAULT
    if code == "D":
        CODE = code
        geo.set_origin(*_TAINAN_ORIGIN)
        if _SAVED:      # 從別的縣市切回來：還原臺南原本的設定（沒切換過就完全不動，測試可以自己改快取位置）
            basemap.set_region(*_SAVED["basemap"])
            roads.set_region(*_SAVED["roads"])
            _SAVED = None
        prices.CITY = "台南市"
        return code
    if CODE == "D" and _SAVED is None:
        _SAVED = {"basemap": ((basemap.WEST, basemap.EAST, basemap.NORTH, basemap.SOUTH), basemap.CACHE_DIR),
                  "roads": (roads.COUNTY, roads.ROAD_DIR, roads.WEB_DIR)}
    CODE = code
    w, e, n, s = bounds(code)
    geo.set_origin((n + s) / 2.0, (w + e) / 2.0)
    basemap.set_region((w, e, n, s), os.path.join(basemap.TAINAN_CACHE, "tw", code))
    roads.set_region(BY_CODE[code]["name"], os.path.join(geo.DATA_DIR, "cache", "roads_tw", code),
                     os.path.join(WEB_TW, code, "roads"))
    prices.CITY = city_label(code)
    return code


# ------------------------------------------------------------------ 地形與行政區
def terrain():
    if CODE == "D":
        return geo.Terrain()
    return geo.flat_terrain(*bounds())


def load_districts(txs=None):
    """[{"name", "lat", "lng", "zone"}]。名稱以實價登錄的寫法為準（臺／台），統計才對得起來。"""
    if CODE == "D":
        return geo.load_districts()
    c = info()
    tx_names = {}
    for x in txs or []:
        if x.get("dist"):
            tx_names[x["dist"]] = tx_names.get(x["dist"], 0) + 1
    by_norm = {norm(n): n for n in tx_names}
    out, seen = [], set()
    for t in load_towns().get(CODE, []):
        if t.get("lat") is None:
            continue
        name = by_norm.get(norm(t["name"]), t["name"])
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "lat": t["lat"], "lng": t["lng"], "zone": "位置約略" if t.get("approx") else ""})
    # 交易資料裡有、位置清單沒有的區：先排在縣市中心附近，標示位置約略
    extra = sorted((n for n in tx_names if n not in seen), key=lambda n: -tx_names[n])
    for i, n in enumerate(extra):
        a = i * 2.4
        out.append({"name": n, "lat": round(c["lat"] + 0.03 * math.sin(a) * (1 + i * 0.3), 5),
                    "lng": round(c["lng"] + 0.03 * math.cos(a) * (1 + i * 0.3), 5), "zone": "位置約略"})
    return out


# ------------------------------------------------------------------ 實價登錄
def _book_path():
    return os.path.join(_cache_dir(), "pricebook.json")


def _tx_path():
    return os.path.join(_cache_dir(), "transactions.json")


def empty_book(names=(), today=None):
    """還沒下載實價登錄的縣市：一本全部空白的帳（地圖照樣畫行政區，只是沒有房價柱）。"""
    today = today or datetime.date.today()
    ct = prices.ym_add(today.strftime("%Y-%m"), -2)
    months = prices.ym_range(prices.ym_add(ct, -11), ct)
    windows = {"r3": [prices.ym_add(ct, -2), ct], "p3": [prices.ym_add(ct, -5), prices.ym_add(ct, -3)],
               "h6": [prices.ym_add(ct, -5), ct], "y12": [prices.ym_add(ct, -11), ct]}
    data = {d: {} for d in [city_label()] + list(names)}
    return prices.PriceBook({"source": "none", "as_of": "", "note": "尚未下載%s的實價登錄" % info()["short"],
                             "months": months, "total": city_label(), "complete_through": ct,
                             "windows": windows, "data": data})


def _build_from_cache(today=None):
    """由全國下載快取彙整出目前縣市的統計並存檔；沒有資料回傳 (None, [])。"""
    today = today or datetime.date.today()
    txs = plvr_tw.load_county(CODE)
    if not txs:
        return None, []
    names = [d["name"] for d in load_districts(txs)]
    raw = prices.build_book(txs, names, as_of=plvr_tw.as_of(), source="live",
                            note="內政部不動產交易實價查詢服務網開放資料（全國檔），由本程式下載彙整。",
                            today_ym=today.strftime("%Y-%m"), total=city_label())
    os.makedirs(_cache_dir(), exist_ok=True)
    prices.save_book(raw, path=_book_path())
    prices.save_transactions(txs, path=_tx_path())
    return prices.PriceBook(raw), txs


def _stamp():
    """全國下載快取的版本（下載完成的日期）；用來判斷縣市統計要不要重算。"""
    folders = plvr_tw.folders()
    return "%s|%d" % (plvr_tw.as_of(), len(folders)) if folders else ""


def load_book_and_txs():
    """(PriceBook, 交易清單)。臺南沿用原本的快取／內建快照。"""
    if CODE == "D":
        book = prices.load_book()
        return book, (prices.load_transactions() if book.source == "live" else [])
    stamp = _stamp()
    try:
        with open(_book_path(), encoding="utf-8") as f:
            raw = json.load(f)
        if stamp and raw.get("stamp") == stamp and raw.get("months") and raw.get("data"):
            return prices.PriceBook(raw), prices.load_transactions(path=_tx_path())
    except (OSError, ValueError):
        pass
    if stamp:
        book, txs = _build_from_cache()
        if book:
            book.raw["stamp"] = stamp
            prices.save_book(book.raw, path=_book_path())
            return book, txs
    return empty_book([d["name"] for d in load_districts()]), []


def has_live_cache():
    return plvr.has_live_cache() if CODE == "D" else bool(plvr_tw.folders())


def needs_update(today=None):
    if CODE == "D":
        return plvr.needs_update(today)
    if not plvr_tw.folders():
        return False
    try:
        got = datetime.date.fromisoformat(plvr_tw.as_of())
    except ValueError:
        return True
    return got < plvr.last_release(today)


def update(progress=None, insecure=False):
    """下載最新實價登錄並重算目前縣市；回傳 (PriceBook, 交易筆數)。"""
    if CODE == "D":
        return plvr.update(progress=progress, insecure=insecure)
    plvr_tw.update(progress=progress, insecure=insecure)
    book, txs = _build_from_cache()
    if not book:
        raise plvr.DownloadError("全國檔裡找不到%s的交易資料。" % info()["short"])
    book.raw["stamp"] = _stamp()
    prices.save_book(book.raw, path=_book_path())
    return book, len(txs)


def choices():
    """下拉選單用：[(代碼, 顯示名稱)]。"""
    return [(c["code"], c["short"]) for c in COUNTIES]


def strip_city(addr):
    """門牌去掉開頭的縣市名稱（交易明細表用）。"""
    from .taiwan import strip_county
    return strip_county(addr or "")
