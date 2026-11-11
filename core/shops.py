"""各區生活機能：財政部「全國營業（稅籍）登記資料集」按行業代號統計各鄉鎮市區的店家數。

資料：https://eip.fia.gov.tw/data/BGMOPEN1.zip（每天更新，UTF-8 CSV，約 170 萬筆營業中的營業人）
欄位：營業地址,統一編號,總機構統一編號,營業人名稱,資本額,設立日期,組織別名稱,使用統一發票,行業代號,名稱,行業代號1,名稱1,…
第 2 行是資料日期（例如 11-NOV-26），不是店家。

只看主要行業代號（第一個）；同一類裡同一個門牌只算一家（連鎖店的直營公司與加盟主常在同一個地址各登記一次）。
"""
import csv
import io
import re
import unicodedata
import zipfile

from .prices import road_of
from .taiwan import COUNTIES, norm

URL = "https://eip.fia.gov.tw/data/BGMOPEN1.zip"

# (鍵, 顯示名稱, 行業代號)：代號是財政部稅務行業標準分類（第 9 次修訂）
# 沒放診所（醫療免營業稅，稅籍資料裡幾乎沒有）與補習班（多數登記在教育局，稅籍只有一小部分）
CATS = [
    ("breakfast", "早餐店", ["561111"]),
    ("eat", "小吃、麵店、便當", ["561112", "561113", "561200"]),
    ("rest", "餐廳（含速食、吃到飽）", ["561114", "561115", "561116", "561117"]),
    ("drink", "手搖飲", ["563115", "563200"]),
    ("cafe", "咖啡館", ["563112"]),
    ("bakery", "麵包西點", ["472922"]),
    ("conv", "便利商店", ["471112", "471113"]),          # 471114（加盟、無進銷貨）多半是加盟主登記在自家的公司，不是店面
    ("mart", "超市、量販、百貨", ["471200", "471912", "471916"]),
    ("fresh", "蔬果肉品海鮮", ["472111", "472112", "472211", "472212", "472311"]),
    ("pharm", "藥局（西藥）", ["475112"]),
    ("bank", "銀行、郵局、農會信用部", ["641211", "641212", "641300", "641411", "641500"]),
    ("hair", "美髮、理髮", ["962111", "962112"]),
    ("laundry", "洗衣店", ["961012", "961099"]),
    ("gym", "健身、瑜珈、運動場館", ["931214", "931218", "931219", "859311"]),
    ("pet", "寵物店、寵物美容", ["485220", "485221", "485222", "969021"]),
    ("claw", "夾娃娃機店", ["932414"]),
]
CAT_OF = {code: i for i, (_, _, codes) in enumerate(CATS) for code in codes}
_COUNTY = {norm(c["name"]): c["code"] for c in COUNTIES}
_VILLAGE = re.compile(r"^(\D{1,4}?[里村])?(\d+鄰)?")
_DATE = re.compile(r"^\d{1,2}-[A-Z]{3}-\d{2}$")
_MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def split_address(addr, towns):
    """'臺南市永康區中華路１號二樓' → ('D', '永康區', '中華路1號')；對不上已知的區就回傳 None。

    towns: {縣市代碼: [區名, …]}（用最長的區名比對，避免「東區」配到「東區里」之類）。"""
    a = unicodedata.normalize("NFKC", addr or "").replace(" ", "")
    code = _COUNTY.get(norm(a[:3]))
    if not code:
        return None
    rest = a[3:]
    for t in sorted(towns.get(code, []), key=len, reverse=True):
        if norm(rest).startswith(norm(t)):
            door = _VILLAGE.sub("", rest[len(t):], count=1)
            i = door.find("號")
            return code, t, door[:i + 1] if i >= 0 else door
    return None


def as_of(cell):
    """'11-NOV-26' → '2026-11-11'"""
    m = _DATE.match(cell or "")
    if not m:
        return None
    d, mon, y = cell.split("-")
    return "20%s-%02d-%02d" % (y, _MON.get(mon, 0), int(d))


_CN = "零一二三四五六七八九十"


def road_name(door):
    """門牌（已去掉縣市、區、里鄰）→ 路段名稱，和實價登錄的路段同一套規則（core/prices.road_of）。
    稅籍地址多半寫「西門路2段」，實價登錄是「西門路二段」：先把段數換成國字。取不出來回傳 None。"""
    door = re.sub(r"(\d{1,2})段", lambda m: (_CN[int(m.group(1))] if int(m.group(1)) <= 10 else "十" + _CN[int(m.group(1)) - 10]) + "段", door)
    r = road_of(door, strip=False)
    return r if r and r != "其他" and re.search("(路|街|大道|段)$", r) else None


def count(lines, towns, roads=None):
    """逐行 CSV 文字 → ({縣市代碼: {區: [各類家數]}}, 資料日期, 對不上區的筆數)
    roads 給一個 dict 就順便填各路段的家數：{縣市代碼: {區: {路段: [各類家數]}}}"""
    seen, out, date, miss = set(), {}, None, 0
    for row in csv.reader(lines):
        if not row or row[0] == "營業地址":
            continue
        if date is None and as_of(row[0].strip()):
            date = as_of(row[0].strip())
            continue
        if len(row) < 9:
            continue
        k = CAT_OF.get(row[8].strip())
        if k is None:
            continue
        loc = split_address(row[0], towns)
        if not loc:
            miss += 1
            continue
        code, town, door = loc
        key = (code, town, door, k)
        if door and key in seen:
            continue
        seen.add(key)
        out.setdefault(code, {}).setdefault(town, [0] * len(CATS))[k] += 1
        if roads is not None:
            rd = road_name(door)
            if rd:
                roads.setdefault(code, {}).setdefault(town, {}).setdefault(rd, [0] * len(CATS))[k] += 1
    return out, date, miss


def parse_zip(data, towns, roads=None):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as f:
            return count(io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline=""), towns, roads)
