"""長期房價走勢（近 5 年）：把實價登錄的舊季檔濃縮成「每區、每房型、每月」的統計，存進專案，不必保留原始檔。

一季的季檔（DownloadSeason?season=111S2）裡是那一季「登錄」的成交，交易月份可能落在前一兩季，
所以同一個月會分散在兩三個季檔裡。每個季檔各自算 [件數, 中位單價, 中位總價]，合併時用件數加權平均。
這樣算出來的中位數是近似值（不是全部成交合在一起的真正中位數），畫長期走勢足夠。

檔案：
    data/tw/long/<季別>.json       {"season", "built", "counties": {代碼: {區或縣市名: {房型: {"YYYY-MM": [n, u, t]}}}}}
    web/data/tw/<代碼>/long.json   {"months": [...], "data": {區: {房型: {"n": [...], "u": [...], "t": [...]}}}}
    web/data/tw/long.json          全台各縣市（同上格式，區＝縣市簡稱）
"""
import io
import json
import os
import zipfile

from . import prices
from .taiwan import COUNTIES

CATS = [c for c, _ in prices.CATS]          # all / house / apt / presale


def summarize(txs, total):
    """一批交易（同一縣市）→ {區: {房型: {ym: [n, u, t]}}}，另加 total（全縣市）。"""
    groups = {}
    for x in txs:
        for d in (x["dist"], total):
            for cat in CATS:
                if prices.in_cat(x, cat):
                    groups.setdefault(d, {}).setdefault(cat, {}).setdefault(x["ym"], []).append(x)
    out = {}
    for d, cats in groups.items():
        out[d] = {cat: {ym: prices._stat(rows) for ym, rows in sorted(ms.items())} for cat, ms in cats.items()}
    return out


def season_summary_from_zip(z_bytes):
    """全國季檔 zip → {代碼: summarize(...)}，另回傳各縣市解析筆數。"""
    out, counts = {}, {}
    with zipfile.ZipFile(io.BytesIO(z_bytes)) as z:
        names = {n.split("/")[-1].lower(): n for n in z.namelist()}
        for c in COUNTIES:
            code = c["code"].lower()
            txs = []
            for kind in ("a", "b"):
                member = names.get("%s_lvr_land_%s.csv" % (code, kind))
                if member:
                    text = z.read(member).decode("utf-8-sig", "replace")
                    txs.extend(prices.parse_csv_text(text, presale=(kind == "b")))
            txs = prices.dedupe(txs)
            counts[c["code"]] = len(txs)
            if txs:
                out[c["code"]] = summarize(txs, c["short"])
    return out, counts


def season_summary_from_dir(path):
    """已展開的季檔資料夾（data/cache/plvr_tw/season_xxx）→ 同上。"""
    out, counts = {}, {}
    for c in COUNTIES:
        code = c["code"].lower()
        txs = []
        for kind in ("a", "b"):
            p = os.path.join(path, "%s_lvr_land_%s.csv" % (code, kind))
            if os.path.exists(p):
                with open(p, "rb") as f:
                    txs.extend(prices.parse_csv_text(f.read().decode("utf-8-sig", "replace"), presale=(kind == "b")))
        txs = prices.dedupe(txs)
        counts[c["code"]] = len(txs)
        if txs:
            out[c["code"]] = summarize(txs, c["short"])
    return out, counts


def merge(season_files, code):
    """多個季檔摘要 → 某縣市 {區: {房型: {ym: [n, u, t]}}}（同一個月件數加權平均）。"""
    acc = {}
    for sf in season_files:
        for d, cats in (sf.get("counties", {}).get(code) or {}).items():
            for cat, ms in cats.items():
                for ym, (n, u, t) in ms.items():
                    if not n:
                        continue
                    a = acc.setdefault(d, {}).setdefault(cat, {}).setdefault(ym, [0, 0.0, 0.0])
                    a[0] += n
                    a[1] += n * (u or 0)
                    a[2] += n * (t or 0)
    out = {}
    for d, cats in acc.items():
        out[d] = {cat: {ym: [n, round(su / n, 1), round(st / n)] for ym, (n, su, st) in ms.items()} for cat, ms in cats.items()}
    return out


def combine(cells_list):
    """好幾個 {房型: {ym: [n, u, t]}} 合成一個（件數加權），例如各縣市合計 → 全台。"""
    acc = {}
    for cells in cells_list:
        for cat, ms in (cells or {}).items():
            for ym, (n, u, t) in ms.items():
                if not n:
                    continue
                a = acc.setdefault(cat, {}).setdefault(ym, [0, 0.0, 0.0])
                a[0] += n
                a[1] += n * (u or 0)
                a[2] += n * (t or 0)
    return {cat: {ym: [n, round(su / n, 1), round(st / n)] for ym, (n, su, st) in ms.items()} for cat, ms in acc.items()}


def long_book(merged, months, recent_raw=None, recent_from=None):
    """合併後的摘要 → 網頁用的格式。recent_raw（近期 PriceBook 的 dict）在 recent_from 之後的月份以近期統計為準
    （近期資料含本期與前期檔，比季檔完整）。"""
    rdata = (recent_raw or {}).get("data") or {}
    rmonths = (recent_raw or {}).get("months") or []
    data = {}
    for d in sorted(set(merged) | set(rdata)):
        cells = {}
        for cat in CATS:
            ms = (merged.get(d) or {}).get(cat) or {}
            rc = (rdata.get(d) or {}).get(cat)
            n, u, t = [], [], []
            for m in months:
                v = None
                if rc and recent_from and m >= recent_from and m in rmonths:
                    i = rmonths.index(m)
                    v = [rc["n"][i], rc["u"][i], rc["t"][i]]
                elif m in ms:
                    v = ms[m]
                ok = bool(v and v[0])
                n.append(v[0] if ok else 0)
                u.append(v[1] if ok else None)
                t.append(v[2] if ok else None)
            if any(n):
                cells[cat] = {"n": n, "u": u, "t": t}
        if cells:
            data[d] = cells
    return {"months": months, "data": data}


def load_season_files(folder):
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out.append(json.load(f))
            except ValueError:                # 壞掉的檔案略過（下次會重抓）
                print("略過壞掉的摘要 %s" % name)
    return out
