"""租金行情：解析內政部實價登錄的「租賃」檔（*_lvr_land_c.csv），彙整各區月租中位數與租金報酬率。

資料口徑：
  * 只取有建物的住宅租賃（主要用途含「住」，或沒填用途但建物型態是住宅類）。
  * 排除備註含親友／員工／特殊關係等的案件；月租扣掉另計的車位租金。
  * 「整層住家」依建物型態分成大樓／華廈、公寓、透天；獨立套房、分租套房、雅房另成「套房／雅房」。
  * 以「租賃年月日」歸月；統計值一律取中位數。近一年＝和買賣統計同一個「完整月份」往前 12 個月。
租賃實價登錄主要來自租賃住宅服務業（代管、包租）與自行申報，房東自租的案件登錄比例較低，
所以租金行情偏向「透過業者出租」的物件，僅供參考。

欄位依表頭名稱找（內政部改版時欄位順序可能不同），找不到必要欄位就整份略過。
"""
import csv
import io
import math
import re

from .prices import PING_M2, category_of, median, ym_add

_EXCL = re.compile("親友|員工|特殊關係|二親等|關係人|公司宿舍|員工宿舍")
REQUIRED = ("鄉鎮市區", "租賃年月日", "總額元", "建物總面積平方公尺")
CATS = [("all", "全部"), ("apt", "大樓／華廈／公寓"), ("house", "透天"), ("room", "套房／雅房")]
CAT_LABEL = dict(CATS)
MIN_N = 5


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _col(header, *names):
    """依名稱找欄位（完全相同優先，其次「包含」）；找不到回傳 None。"""
    for n in names:
        if n in header:
            return header.index(n)
    for n in names:
        for i, h in enumerate(header):
            if n in h:
                return i
    return None


def rent_cat(btype, mode, use):
    """租賃類別：apt / house / room；不是住宅回傳 None。"""
    mode = mode or ""
    if re.search("套房|雅房", mode) or (btype or "").startswith("套房"):
        return "room"
    if use and "住" not in use:
        return None
    c = category_of(btype or "")
    if c in ("apt", "walkup"):
        return "apt"
    if c == "house":
        return "house"
    if c == "suite":
        return "room"
    return None


def parse_rent_csv(text):
    """一份租賃 CSV 文字 → 精簡租賃 list：{id, dist, ym, cat, rent(元/月), ping, unit(元/坪/月), rooms, built}。"""
    if text.startswith("﻿"):
        text = text[1:]
    rows = csv.reader(io.StringIO(text))
    header, idx, out = None, None, []
    for r in rows:
        if not r:
            continue
        if header is None:
            if r[0].strip() == "鄉鎮市區":
                header = [h.strip() for h in r]
                idx = {k: _col(header, k) for k in REQUIRED}
                if None in idx.values():
                    return []
                idx.update({
                    "target": _col(header, "交易標的"), "addr": _col(header, "土地位置建物門牌", "建物門牌"),
                    "btype": _col(header, "建物型態"), "use": _col(header, "主要用途"),
                    "built": _col(header, "建築完成年月"), "rooms": _col(header, "建物現況格局-房"),
                    "park": _col(header, "車位總額元", "車位總金額元"), "note": _col(header, "備註"),
                    "id": _col(header, "編號"), "mode": _col(header, "出租型態"),
                })
            continue
        if r[0].startswith("The villages") or len(r) < len(header) - 3:
            continue
        g = lambda k: (r[idx[k]].strip() if idx.get(k) is not None and idx[k] < len(r) else "")
        if g("target") and "建物" not in g("target") and "房地" not in g("target"):
            continue
        if _EXCL.search(g("note")):
            continue
        cat = rent_cat(g("btype"), g("mode"), g("use"))
        if not cat:
            continue
        d = g("租賃年月日")
        if not (len(d) == 7 and d.isdigit()):
            continue
        year, month = int(d[:3]) + 1911, int(d[3:5])
        if not 1 <= month <= 12:
            continue
        rent = _num(g("總額元")) - _num(g("park"))
        area = _num(g("建物總面積平方公尺"))
        if area <= 0:
            continue
        ping = area / PING_M2
        if not (1000 <= rent <= 400000) or not (1 <= ping <= 300):
            continue
        unit = rent / ping
        if not (50 <= unit <= 5000):
            continue
        built = g("built")
        rooms = int(_num(g("rooms")))
        out.append({"id": g("id"), "dist": g("鄉鎮市區"), "ym": "%04d-%02d" % (year, month), "cat": cat,
                    "rent": rent, "ping": ping, "unit": unit, "rooms": rooms,
                    "built": int(built[:3]) + 1911 if len(built) == 7 and built.isdigit() else None})
    return out


def dedupe(items):
    seen, out = set(), []
    for x in items:
        if x["id"] and x["id"] in seen:
            continue
        seen.add(x["id"])
        out.append(x)
    return out


def _r(v, nd=0):
    if v is None:
        return None
    f = 10 ** nd
    v = math.floor(v * f + 0.5) / f
    return int(round(v)) if nd <= 0 else v


def _stat(rows):
    """[件數, 月租中位(元), 每坪月租中位(元), 坪數中位]"""
    if not rows:
        return [0, None, None, None]
    return [len(rows), _r(median([x["rent"] for x in rows]), -2), _r(median([x["unit"] for x in rows]), 0),
            _r(median([x["ping"] for x in rows]), 1)]


def _rooms_key(x):
    if x["cat"] == "room":
        return "s"
    return str(min(4, max(1, x["rooms"]))) if x["rooms"] else None


def build_rent_book(items, names, end_ym, total):
    """各區近一年租金統計。

    回傳 {"window": [起, 迄], "prev": [起, 迄], "cats": [...], "data": {區: {類別: [n, 月租, 每坪, 坪],
           "rooms": {"s"|"1".."4": [n, 月租, 每坪, 坪]}, "chg": 每坪月租比前一年漲跌%（樣本夠才有）}}}
    """
    a, b = ym_add(end_ym, -11), end_ym
    pa, pb = ym_add(end_ym, -23), ym_add(end_ym, -12)
    by = {}
    for x in items:
        by.setdefault(x["dist"], []).append(x)
    data = {}
    for d in [total] + list(names):
        rows = items if d == total else by.get(d, [])
        cur = [x for x in rows if a <= x["ym"] <= b]
        prev = [x for x in rows if pa <= x["ym"] <= pb]
        if not cur:
            continue
        cell = {}
        for cat, _ in CATS:
            cell[cat] = _stat([x for x in cur if cat == "all" or x["cat"] == cat])
        rooms = {}
        for x in cur:
            k = _rooms_key(x)
            if k:
                rooms.setdefault(k, []).append(x)
        cell["rooms"] = {k: _stat(v) for k, v in sorted(rooms.items())}
        home_c = [x for x in cur if x["cat"] != "room"]
        home_p = [x for x in prev if x["cat"] != "room"]
        if len(home_c) >= 20 and len(home_p) >= 20:
            m0, m1 = median([x["unit"] for x in home_p]), median([x["unit"] for x in home_c])
            cell["chg"] = _r((m1 / m0 - 1) * 100, 1) if m0 else None
        data[d] = cell
    return {"window": [a, b], "prev": [pa, pb], "cats": [c for c, _ in CATS], "data": data}


def gross_yield(rent_unit, sale_unit_wan):
    """毛租金報酬率（%）：每坪月租 × 12 ÷ 每坪房價。sale_unit_wan 為萬/坪。"""
    if not rent_unit or not sale_unit_wan:
        return None
    return rent_unit * 12 / (sale_unit_wan * 10000) * 100
