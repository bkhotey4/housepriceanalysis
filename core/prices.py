"""房價資料：解析內政部實價登錄 CSV、彙整各區每月行情、計算近半年起伏。

資料口徑（離線快照與線上更新完全相同）：
  * 只取「房地(土地+建物)」及「房地(土地+建物)+車位」的住宅交易
    （透天厝、住宅大樓、華廈、公寓、套房）。
  * 排除備註含親友／特殊關係／急買急賣／持分／瑕疵等特殊交易。
  * 單價採實價登錄「單價元平方公尺」欄位（有拆分車位價時已扣除車位），換算為 萬元/坪。
  * 以「交易年月日」歸月，統計值一律取中位數。
  * 預售屋另成一類（實價登錄的預售屋檔），已解約的案件不計；「全部合併」只含成屋買賣，不含預售。
"""
import csv
import io
import json
import math
import os
import re

from .geo import DATA_DIR
from .taiwan import strip_county

CACHE_DIR = os.path.join(DATA_DIR, "cache")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "price_snapshot.json")
BOOK_CACHE_PATH = os.path.join(CACHE_DIR, "pricebook.json")
TX_CACHE_PATH = os.path.join(CACHE_DIR, "transactions.json")

PING_M2 = 3.305785
CITY = "台南市"
CATS = [("all", "全部合併"), ("house", "透天厝"), ("apt", "大樓／華廈"), ("presale", "預售屋")]
CAT_LABEL = dict(CATS)
METRICS = [("u", "單價（萬/坪）"), ("t", "總價（萬）")]
MIN_N = 5         # 低於這個件數就標示「樣本少」
TREND_MIN_N = 10  # 前後兩個 3 個月區間都至少要這麼多件，才計算漲跌

_EXCL = re.compile("親友|員工|特殊關係|二親等|急買急賣|債權債務|瑕疵|持分|地上權|協議價購|向政府機關承購|公共設施保留地|毛胚")
_TYPE_CAT = (("透天厝", "house"), ("住宅大樓", "apt"), ("華廈", "apt"), ("公寓", "walkup"), ("套房", "suite"))

# CSV 欄位索引（33 欄，順序固定）
C_DIST, C_TARGET, C_ADDR, C_DATE = 0, 1, 2, 7
C_FLOORS, C_BTYPE, C_BUILT, C_AREA = 10, 11, 14, 15
C_TOTAL, C_UNIT, C_NOTE, C_ID = 21, 22, 26, 27
# 預售屋檔（31 欄）前 28 欄相同，後面是 建案名稱、棟及號、解約情形
C_PROJ, C_CANCEL = 28, 30


def _r1(x):
    return math.floor(x * 10 + 0.5) / 10


def _r0(x):
    return int(math.floor(x + 0.5))


def median(values):
    if not values:
        return 0
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def category_of(btype):
    for prefix, cat in _TYPE_CAT:
        if btype.startswith(prefix):
            return cat
    return None


def reduce_row(r, presale=False):
    """把一列實價登錄原始資料轉成精簡交易 dict；不符口徑回傳 None。"""
    if len(r) < (31 if presale else 28):
        return None
    if not r[C_TARGET].startswith("房地"):
        return None
    cat = category_of(r[C_BTYPE])
    if not cat:
        return None
    d = r[C_DATE].strip()
    if not (len(d) == 7 and d.isdigit()):
        return None
    year, month, day = int(d[:3]) + 1911, int(d[3:5]), int(d[5:7])
    if not 1 <= month <= 12:
        return None
    total, area = _num(r[C_TOTAL]), _num(r[C_AREA])
    if total <= 0 or area <= 0:
        return None
    if _EXCL.search(r[C_NOTE]):
        return None
    if presale and r[C_CANCEL].strip():
        return None                     # 已解約
    unit = _num(r[C_UNIT])
    if unit <= 0:
        unit = total / area
    u = unit * PING_M2 / 10000.0
    tw = total / 10000.0
    if u < 3 or u > 200 or tw < 50:
        return None
    built = r[C_BUILT].strip()
    built_year = int(built[:3]) + 1911 if len(built) == 7 and built.isdigit() else None
    return {
        "id": r[C_ID], "dist": r[C_DIST], "ym": "%04d-%02d" % (year, month),
        "date": "%04d-%02d-%02d" % (year, month, max(1, min(day, 31))),
        "cat": cat, "btype": r[C_BTYPE].split("(")[0], "addr": r[C_ADDR],
        "tw": tw, "u": u, "ping": area / PING_M2, "built": built_year,
        "floors": r[C_FLOORS], "note": r[C_NOTE],
        "kind": "presale" if presale else "sale", "proj": r[C_PROJ].strip() if presale else "",
    }


def parse_csv_text(text, presale=None):
    """解析一份實價登錄 CSV 文字（含中文表頭與英文表頭兩列），回傳精簡交易 list。

    presale=None 時由表頭自動判斷是不是預售屋檔（第 29 欄為「建案名稱」）。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    for r in csv.reader(io.StringIO(text)):
        if not r:
            continue
        if r[0] == "鄉鎮市區":
            if presale is None:
                presale = len(r) > C_PROJ and r[C_PROJ] == "建案名稱"
            continue
        if r[0].startswith("The villages"):
            continue
        x = reduce_row(r, presale=bool(presale))
        if x:
            out.append(x)
    return out


def in_cat(x, cat):
    """交易是否屬於某個房型類別。"""
    if cat == "presale":
        return x.get("kind") == "presale"
    if x.get("kind") == "presale":
        return False
    return cat == "all" or x["cat"] == cat


def dedupe(txs):
    seen, out = set(), []
    for x in txs:
        k = x["id"]
        if k and k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


# ------------------------------------------------------------------ 月份工具
def ym_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    n = y * 12 + (m - 1) + k
    return "%04d-%02d" % (n // 12, n % 12 + 1)


def ym_range(a, b):
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur = ym_add(cur, 1)
    return out


def ym_label(ym):
    return "%d/%d" % (int(ym[2:4]), int(ym[5:7]))


def find_complete_through(counts, today_ym=None):
    """找出「資料大致到齊」的最後一個月。

    實價登錄有 1~2 個月的登記與申報時間差，最近的月份件數會偏少。
    規則：由最新月份往回找，第一個件數 >= 前 6 個月件數中位數一半的月份。
    """
    months = sorted(m for m, n in counts.items() if n > 0 and (today_ym is None or m <= today_ym))
    if not months:
        return None
    for back in range(0, 6):
        if back >= len(months):
            break
        m = months[-1 - back]
        prev = [counts.get(ym_add(m, -k), 0) for k in range(1, 7)]
        base = median([p for p in prev if p > 0])
        if base == 0 or counts[m] >= 0.5 * base:
            return m
    return months[-1]


def _stat(rows):
    return [len(rows), _r1(median([x["u"] for x in rows])), _r0(median([x["tw"] for x in rows]))]


def build_book(txs, district_names, as_of, source="live", note="", today_ym=None, total=CITY):
    """由交易清單彙整成 PriceBook 的 dict（格式與 price_snapshot.json 相同）。"""
    counts = {}
    for x in txs:
        if x.get("kind") != "presale":          # 以成屋買賣的件數判斷哪個月資料已到齊
            counts[x["ym"]] = counts.get(x["ym"], 0) + 1
    ct = find_complete_through(counts, today_ym)
    if ct is None:
        raise ValueError("沒有可用的交易資料")
    latest = max(m for m in counts if today_ym is None or m <= today_ym)
    months = ym_range(ym_add(ct, -11), ct)
    if latest > ct:
        months.append(ym_add(ct, 1))
    windows = {"r3": [ym_add(ct, -2), ct], "p3": [ym_add(ct, -5), ym_add(ct, -3)],
               "h6": [ym_add(ct, -5), ct], "y12": [ym_add(ct, -11), ct]}
    by_dist = {}
    for x in txs:
        by_dist.setdefault(x["dist"], []).append(x)
    data = {}
    for d in [total] + list(district_names):
        rows = txs if d == total else by_dist.get(d, [])
        data[d] = {}
        for cat, _ in CATS:
            rc = [x for x in rows if in_cat(x, cat)]
            by_m = {}
            for x in rc:
                by_m.setdefault(x["ym"], []).append(x)
            cell = {"n": [], "u": [], "t": []}
            for m in months:
                s = _stat(by_m.get(m, []))
                cell["n"].append(s[0])
                cell["u"].append(s[1])
                cell["t"].append(s[2])
            for key, (a, b) in windows.items():
                cell[key] = _stat([x for x in rc if a <= x["ym"] <= b])
            data[d][cat] = cell
    return {"source": source, "as_of": as_of, "note": note, "months": months, "total": total,
            "complete_through": ct, "windows": windows, "data": data}


class PriceBook:
    """各區行情查詢介面。"""

    def __init__(self, raw):
        self.raw = raw
        self.source = raw.get("source", "snapshot")
        self.as_of = raw.get("as_of", "")
        self.note = raw.get("note", "")
        self.months = raw["months"]
        self.complete_through = raw["complete_through"]
        self.windows = raw["windows"]
        self.data = raw["data"]

    # -- 基本查詢
    def cell(self, district, cat):
        return self.data.get(district, {}).get(cat)

    def window_label(self, key):
        a, b = self.windows[key]
        return "%s~%s" % (ym_label(a), ym_label(b))

    def half_year_months(self):
        a, b = self.windows["h6"]
        return ym_range(a, b)

    def best(self, district, cat, metric="u"):
        """回傳最適合當「目前行情」的數值。

        優先用近半年；件數太少則退到近一年；都沒有則 value=None。
        回傳 dict: value, n, window('h6'|'y12'|None), low(樣本是否偏少)
        """
        c = self.cell(district, cat)
        idx = 1 if metric == "u" else 2
        if not c:
            return {"value": None, "n": 0, "window": None, "low": True}
        for key in ("h6", "y12"):
            n = c[key][0]
            if n >= (MIN_N if key == "h6" else 1):
                return {"value": c[key][idx], "n": n, "window": key, "low": n < MIN_N}
        return {"value": None, "n": 0, "window": None, "low": True}

    def trend(self, district, cat, metric="u"):
        """近半年起伏：後 3 個月中位數相對前 3 個月中位數的變動（%）。樣本不足回傳 None。"""
        c = self.cell(district, cat)
        if not c:
            return None
        idx = 1 if metric == "u" else 2
        r3, p3 = c["r3"], c["p3"]
        if r3[0] < TREND_MIN_N or p3[0] < TREND_MIN_N or not p3[idx]:
            return None
        return (r3[idx] - p3[idx]) / p3[idx] * 100.0

    def series(self, district, cat, metric="u"):
        """回傳 [(月份, 數值或 None, 件數, 是否資料未齊)]。"""
        c = self.cell(district, cat)
        out = []
        for i, m in enumerate(self.months):
            n = c["n"][i] if c else 0
            v = (c["u"][i] if metric == "u" else c["t"][i]) if c and n else None
            out.append((m, v, n, m > self.complete_through))
        return out

    def districts(self):
        return [d for d in self.data if d != self.raw.get("total", CITY)]

    def presale_gap(self, district):
        """預售屋單價比區內中古大樓／華廈高多少（%）；任一邊樣本不足回傳 None。"""
        p, a = self.best(district, "presale", "u"), self.best(district, "apt", "u")
        if p["value"] is None or a["value"] is None or p["low"] or a["low"] or not a["value"]:
            return None
        return (p["value"] - a["value"]) / a["value"] * 100.0

    def describe_source(self):
        if self.source == "none":
            return "%s：還沒有實價登錄資料，按右下角「更新實價登錄」下載全國檔（下載一次，22 縣市共用）" % (
                self.note.replace("尚未下載", "").replace("的實價登錄", "") or "這個縣市")
        if self.source == "snapshot":
            return "內建快照 | 資料截至 %s 發布 | 完整月份到 %s" % (self.as_of, self.complete_through)
        return "已更新資料 | %s 下載 | 完整月份到 %s" % (self.as_of, self.complete_through)


# ------------------------------------------------------------------ 讀寫
def load_book():
    """優先讀取線上更新後的快取，否則讀內建快照。

    舊版快取若缺少某個房型（例如預售屋），且月份與快照一致，就從快照補上。
    """
    snap = None
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        snap = None
    try:
        with open(BOOK_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("months") and raw.get("data"):
            if snap and raw["months"] == snap["months"]:
                for d, cells in snap["data"].items():
                    for cat, cell in cells.items():
                        raw["data"].setdefault(d, {}).setdefault(cat, cell)
            return PriceBook(raw)
    except (OSError, ValueError, KeyError):
        pass
    if snap and snap.get("months") and snap.get("data"):
        return PriceBook(snap)
    raise RuntimeError("找不到房價資料（data/price_snapshot.json 遺失）")


_TX_FIELDS = ["id", "dist", "date", "cat", "btype", "addr", "tw", "u", "ping", "built", "floors", "note", "kind", "proj"]


def save_transactions(txs, path=TX_CACHE_PATH):
    rows = []
    for x in txs:
        rows.append([x["id"], x["dist"], x["date"], x["cat"], x["btype"], x["addr"], round(x["tw"], 1),
                     round(x["u"], 2), round(x["ping"], 1), x["built"], x["floors"], x["note"][:60],
                     x.get("kind", "sale"), x.get("proj", "")])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fields": _TX_FIELDS, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))


def load_transactions(path=TX_CACHE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    fields = d["fields"]
    out = []
    for r in d["rows"]:
        x = dict(zip(fields, r))
        x["ym"] = x["date"][:7]
        x.setdefault("kind", "sale")
        x.setdefault("proj", "")
        out.append(x)
    return out


def save_book(raw, path=BOOK_CACHE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ 路段行情
_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_ROAD = re.compile("^(.+?(?:大道|路|街)(?:[一二三四五六七八九十]+段)?)")
_VILLAGE = re.compile("^[\u4e00-\u9fff]{1,4}里(?=[\u4e00-\u9fff])")


def road_of(addr, dist=""):
    """由門牌取出路段名稱，例如「臺南市善化區中山路１２３號」->「中山路」。取不出來回傳「其他」。"""
    s = (addr or "").translate(_FULLWIDTH).strip()
    s = strip_county(s)
    if dist and s.startswith(dist):
        s = s[len(dist):]
    s = _VILLAGE.sub("", s)
    m = _ROAD.match(s)
    if m and len(m.group(1)) <= 12:
        return m.group(1)
    head = re.split("[0-9]", s)[0].strip()
    return head[:10] if 2 <= len(head) <= 10 else "其他"


def road_stats(txs, district, cat, since_ym, min_n=2):
    """某區某房型各路段（預售屋則為各建案）的件數與中位價，依件數由多到少排序。"""
    groups = {}
    for x in txs:
        if x["dist"] != district or x["ym"] < since_ym or not in_cat(x, cat):
            continue
        key = (x.get("proj") or "未命名建案") if cat == "presale" else road_of(x["addr"], district)
        groups.setdefault(key, []).append(x)
    out = []
    for name, rows in groups.items():
        if len(rows) < min_n:
            continue
        out.append({"name": name, "n": len(rows), "u": _r1(median([x["u"] for x in rows])),
                    "t": _r0(median([x["tw"] for x in rows])), "last": max(x["date"] for x in rows)})
    out.sort(key=lambda r: (-r["n"], r["name"]))
    return out


# ------------------------------------------------------------------ 房貸試算
def monthly_payment(loan_wan, annual_rate_pct, years):
    """本息平均攤還的每月應繳金額（元）。loan_wan 為貸款金額（萬元）。"""
    principal = loan_wan * 10000.0
    n = int(round(years * 12))
    if principal <= 0 or n <= 0:
        return 0.0
    r = annual_rate_pct / 100.0 / 12.0
    if r <= 0:
        return principal / n
    return principal * r / (1.0 - (1.0 + r) ** -n)


# ------------------------------------------------------------------ 交屋前要準備的現金（與網頁版 logic.purchaseCosts 相同）
COST_RATIO = {"house": 0.10, "land": 0.25}     # 沒填時粗估：房屋評定現值≈總價 10%、土地公告現值≈總價 25%


def purchase_costs(price_wan, down_pct, house_val=None, land_val=None, agent_pct=2.0, reno=0.0,
                   scrivener=2.0, bank_fee=1.0):
    """買方交屋前要準備的現金（萬元）。回傳 {items: [(代號, 名稱, 萬, 說明)], down, loan, fees, total, estimated}。

    契稅＝房屋評定現值 × 6%；印花稅、登記規費＝（房屋評定現值＋土地公告現值）× 0.1%；
    抵押權設定規費＝貸款 × 1.2 × 0.1%；履約保證費＝總價 0.06% 由買賣雙方各半。
    """
    if not price_wan or price_wan <= 0:
        return None
    est = house_val is None or land_val is None
    hv = house_val if house_val is not None else price_wan * COST_RATIO["house"]
    lv = land_val if land_val is not None else price_wan * COST_RATIO["land"]
    loan = max(0.0, price_wan * (1 - down_pct / 100.0))
    down = price_wan - loan
    agent_pct = agent_pct or 0.0
    items = [
        ("down", "自備款（頭期款）", down, "總價 %g%%" % down_pct),
        ("deed", "契稅", hv * 0.06, "房屋評定現值 × 6%"),
        ("stamp", "印花稅", (hv + lv) * 0.001, "（房屋評定現值＋土地公告現值）× 0.1%"),
        ("reg", "產權登記規費", (hv + lv) * 0.001 + 0.016, "申報價值 × 0.1%＋書狀費"),
        ("mort", "抵押權設定規費", loan * 1.2 * 0.001, "貸款 × 1.2 × 0.1%"),
        ("scrivener", "代書費", scrivener, "行情約 1.5～2.5 萬"),
        ("escrow", "履約保證費", price_wan * 0.0003, "總價 0.06%，買賣雙方各半"),
        ("agent", "仲介服務費", price_wan * agent_pct / 100.0, "總價 %g%%（行情約 1～2%%，可議價；跟建商買免付）" % agent_pct),
        ("bank", "貸款開辦費、火險地震險", bank_fee if loan > 0 else 0.0, "依銀行而定"),
        ("reno", "裝潢、家具、搬家", reno or 0.0, "自己估"),
    ]
    fees = sum(it[2] for it in items if it[0] != "down")
    return {"items": items, "down": down, "loan": loan, "fees": fees, "total": down + fees, "estimated": est,
            "hv": hv, "lv": lv}
