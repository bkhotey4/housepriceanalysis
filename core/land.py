"""純土地成交：從實價登錄買賣檔（*_lvr_land_a.csv）挑出「交易標的＝土地」的大面積成交。

建商推案前通常會先買地、整合土地；某一區短時間內出現多筆大面積住宅區或商業區土地成交，
往往一兩年後就有新建案。實價登錄不公開買方是誰，位置也只到「段、地號」（沒有座標），
所以網頁上以「區」為單位彙整，再列出每一筆的段名、面積、總價、使用分區。

口徑：
  * 只取交易標的為「土地」的買賣，排除備註含親友／特殊關係／持分／協議價購／公共設施保留地等特殊交易。
  * 大面積：土地移轉面積至少 MIN_PING 坪、總價至少 MIN_WAN 萬（小筆的自用或畸零地不列）。
  * 只留最近 MONTHS 個月。
"""
import csv
import io
import re

from .prices import (C_DIST, C_TARGET, C_ADDR, C_DATE, C_PIECES, C_TOTAL, C_NOTE, C_ID, PING_M2, _EXCL, _num,
                     dedupe, ym_add)
from .taiwan import strip_county

C_LAND_M2, C_URBAN, C_NONURBAN, C_NONURBAN_USE = 3, 4, 5, 6
MIN_PING, MIN_WAN, MONTHS = 150, 1000, 24
# 使用分區代碼：R 住宅、C 商業、I 工業、A 農業、N 非都市土地、O 其他（公共設施、特定專用區等）
ZONES = {"R": "住宅區", "C": "商業區", "I": "工業區", "A": "農業區", "N": "非都市土地", "O": "其他"}
_SEC = re.compile(r"^(.*?段(?:.*?小段)?)(.*?)地號")
_PIECES = re.compile(r"土地(\d+)")


def zone_of(urban, nonurban, nonurban_use):
    """(代碼, 原文)：都市土地看「都市土地使用分區」（住／商／工／農／其他:…），沒有就是非都市土地。"""
    # 原文有「住」「商」這種一個字的，也有「都市：其他:住宅區」「都市：其他:道路用地」這種
    urban = (urban or "").strip().replace("都市：", "").replace("其他:", "")
    if urban:
        short = {"住": "住宅區", "商": "商業區", "工": "工業區", "農": "農業區"}.get(urban, urban)
        code = next((c for c, k in (("R", "住宅"), ("C", "商業"), ("I", "工業"), ("A", "農業")) if short.startswith(k) or k in short[:6]), "O")
        if "道路" in short or "保留地" in short:
            code = "O"
        return code, short
    text = "、".join(p for p in ((nonurban or "").strip(), (nonurban_use or "").strip()) if p)
    return "N", text


def reduce_land_row(r):
    if len(r) <= C_ID or r[C_TARGET].strip() != "土地" or _EXCL.search(r[C_NOTE]):
        return None
    m2, total = _num(r[C_LAND_M2]), _num(r[C_TOTAL])
    if m2 <= 0 or total <= 0:
        return None
    d = r[C_DATE].strip()
    if len(d) != 7 or not d.isdigit():
        return None
    year, month, day = int(d[:3]) + 1911, int(d[3:5]), int(d[5:7])
    if not 1 <= month <= 12:
        return None
    dist = r[C_DIST].strip()
    addr = strip_county(r[C_ADDR].strip())
    if dist and addr.startswith(dist):
        addr = addr[len(dist):]
    m = _SEC.match(addr)
    sec, lot = (m.group(1), m.group(2)) if m else (addr, "")
    zc, zt = zone_of(r[C_URBAN], r[C_NONURBAN], r[C_NONURBAN_USE])
    pm = _PIECES.search(r[C_PIECES])
    ping, tw = m2 / PING_M2, total / 10000.0
    return {"id": r[C_ID], "dist": dist, "ym": "%04d-%02d" % (year, month),
            "date": "%04d-%02d-%02d" % (year, month, max(1, min(day, 28))),
            "sec": sec, "lot": lot, "ping": ping, "tw": tw, "u": tw / ping, "zone": zc, "zone_text": zt,
            "pieces": int(pm.group(1)) if pm else 1, "note": r[C_NOTE].strip()}


def parse_land_csv(text):
    """一份買賣檔 → 純土地成交（全部，不分大小）。"""
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\0", "")
    out = []
    for r in csv.reader(io.StringIO(text), quoting=csv.QUOTE_NONE):     # 打錯的引號當普通文字，見 prices.parse_csv_text
        if not r or r[0] == "鄉鎮市區" or r[0].startswith("The villages"):
            continue
        x = reduce_land_row(r)
        if x:
            out.append(x)
    return out


def big_deals(items, latest_ym, months=MONTHS, min_ping=MIN_PING, min_wan=MIN_WAN):
    """最近 months 個月（含 latest_ym）的大面積成交，新的在前。"""
    since = ym_add(latest_ym, -(months - 1))
    out = [x for x in dedupe(items) if since <= x["ym"] <= latest_ym and x["ping"] >= min_ping and x["tw"] >= min_wan]
    out.sort(key=lambda x: (x["date"], x["tw"]), reverse=True)
    return out, since


def build_land_book(items, district_names, latest_ym, county_name=""):
    """網頁版 land.json：各區彙整（近 12、24 個月的筆數、坪數、總價）＋逐筆清單。

    summary[區]：[近12月筆數, 坪數, 總價萬, 近24月筆數, 坪數, 總價萬, 近24月住宅區＋商業區筆數]
    rows：[區索引, 日期, 段名, 地號, 坪數, 總價（萬）, 單價（萬/坪）, 分區代碼, 分區原文, 土地筆數]"""
    deals, since = big_deals(items, latest_ym)
    since12 = ym_add(latest_ym, -11)
    dists = list(district_names)
    for x in deals:                         # 實價登錄有、鄉鎮清單沒有的（極少）也照列
        if x["dist"] and x["dist"] not in dists:
            dists.append(x["dist"])
    di = {n: i for i, n in enumerate(dists)}
    summary = {}
    for x in deals:
        if not x["dist"]:
            continue
        s = summary.setdefault(x["dist"], [0, 0.0, 0.0, 0, 0.0, 0.0, 0])
        if x["ym"] >= since12:
            s[0] += 1; s[1] += x["ping"]; s[2] += x["tw"]
        s[3] += 1; s[4] += x["ping"]; s[5] += x["tw"]
        if x["zone"] in ("R", "C"):
            s[6] += 1
    rows = [[di[x["dist"]], x["date"], x["sec"], x["lot"], round(x["ping"], 1), round(x["tw"]), round(x["u"], 1),
             x["zone"], x["zone_text"], x["pieces"]] for x in deals if x["dist"]]
    return {"county": county_name, "since": since, "since12": since12, "through": latest_ym,
            "min_ping": MIN_PING, "min_wan": MIN_WAN, "zones": ZONES, "dists": dists,
            "summary": {k: [v[0], round(v[1]), round(v[2]), v[3], round(v[4]), round(v[5]), v[6]] for k, v in summary.items()},
            "rows": rows}
