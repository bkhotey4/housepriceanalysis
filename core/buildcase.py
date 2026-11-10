"""預售屋建案備查（內政部地政司開放資料）：建商開賣預售屋前要向縣市政府報備，這份是全國累計的備查清單。

來源 https://plvr.land.moi.gov.tw/opendata/lvr_buildcasecsv.zip（每月 1 日重新產生，110-07-01 起累計，沒有連江縣）。
zip 裡每個縣市三個 CSV，檔名開頭是小寫縣市代碼：
    <代碼>_lvr_buildcase.csv       鄉鎮市區、建案名稱、坐落街道、起造人、層棟戶數、使用分區、主要用途、主要建材、
                                   申報備查日期、銷售期間、坐落基地、建照核發日期、建造執照、第1次登記日期、編號（15 欄）
    <代碼>_lvr_buildingland.csv    編號、土地位置（一個建案多筆地號）
    <代碼>_lvr_buildingpermit.csv  編號、建照核發日期、建造執照
日期是民國年 YYYMMDD。CSV 不用引號包欄位，但使用分區、主要用途等欄位裡偶爾夾逗號（約 1%），
前 5 欄與最後 4 欄的位置不受影響，報備日期從中間找第一個 7 位數日期。
"""
import csv
import io
import re
import zipfile

from .taiwan import COUNTIES

N_COLS = 15
_ROC = re.compile(r"^\d{6,7}$")
_COMPANY = re.compile("公司|股份|有限|建設|開發|營造|機構|合作社|基金會|法人|銀行|人壽|保險|政府|公所|學校|醫院|寺|教會|宮|廟|協會")
_BOSS = re.compile(r"\s*負責人.*$")


def roc_date(s):
    """1151008 → 2026-10-08；不是日期回傳空字串。"""
    s = (s or "").strip()
    if not _ROC.match(s):
        return ""
    y, m, d = int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return ""
    return "%04d-%02d-%02d" % (y, m, d)


def owner_of(s):
    """起造人：公司去掉負責人姓名；個人不公開姓名。"""
    s = _BOSS.sub("", (s or "").strip()).strip()
    return s if _COMPANY.search(s) else "個人"


def _rows(text):
    if text.startswith("﻿"):
        text = text[1:]
    out = []
    for r in csv.reader(io.StringIO(text.replace("\0", "")), quoting=csv.QUOTE_NONE):
        if not r or r[0] in ("鄉鎮市區", "編號") or re.match(r"^[A-Za-z ]+$", r[0]):     # 中文表頭、英文表頭（TOWN、serial number…）
            continue
        out.append(r)
    return out


def parse_cases(text):
    """buildcase.csv → [{dist, name, street, owner, units, zone, use, date, permit_date, permit, reg, id}]，另回傳修復的列數。"""
    out, fixed = [], 0
    for r in _rows(text):
        if len(r) < N_COLS:
            continue
        if len(r) == N_COLS:
            zone, use, date = r[5], r[6], r[8]
        else:                                   # 中間欄位夾了逗號：頭尾照抓，報備日期找中間第一個日期
            fixed += 1
            mid = r[5:-4]
            date = next((x for x in mid if _ROC.match(x.strip())), "")
            zone, use = "", ""
        units = r[4].strip()
        out.append({"dist": r[0].strip(), "name": r[1].strip(), "street": r[2].strip(), "owner": owner_of(r[3]),
                    "units": int(units) if units.isdigit() else 0, "zone": zone.strip(), "use": use.strip(),
                    "date": roc_date(date), "permit_date": roc_date(r[-4]), "permit": r[-3].strip(),
                    "reg": roc_date(r[-2]), "id": r[-1].strip()})
    return out, fixed


def parse_lands(text):
    """buildingland.csv → {編號: [地號…]}。"""
    out = {}
    for r in _rows(text):
        if len(r) >= 2 and r[0].strip():
            out.setdefault(r[0].strip(), []).append(",".join(r[1:]).strip())
    return out


def county_book(cases, lands):
    """一個縣市的網頁格式：行政區編號、每筆一列，報備日期新的在前。
    列：[行政區索引, 建案名稱, 坐落街道, 起造人, 戶數, 主要用途, 報備日期, 建照核發日期, 第一次成交登記日期, 第一筆地號, 地號筆數]"""
    dists = sorted({c["dist"] for c in cases if c["dist"]})
    di = {d: i for i, d in enumerate(dists)}
    rows = []
    for c in sorted(cases, key=lambda c: (c["date"] or c["permit_date"], c["id"]), reverse=True):
        if c["dist"] not in di:
            continue
        ls = lands.get(c["id"], [])
        rows.append([di[c["dist"]], c["name"], c["street"], c["owner"], c["units"], c["use"],
                     c["date"], c["permit_date"], c["reg"], ls[0] if ls else "", len(ls)])
    return {"dists": dists, "rows": rows}


def parse_zip(z_bytes):
    """整個 zip → {縣市代碼: county_book(...)}，另回傳 {代碼: 修復列數}。"""
    out, fixed = {}, {}
    with zipfile.ZipFile(io.BytesIO(z_bytes)) as z:
        names = {n.split("/")[-1].lower(): n for n in z.namelist()}
        for c in COUNTIES:
            code = c["code"].lower()
            m = names.get("%s_lvr_buildcase.csv" % code)
            if not m:
                continue
            cases, fx = parse_cases(z.read(m).decode("utf-8-sig", "replace"))
            lm = names.get("%s_lvr_buildingland.csv" % code)
            lands = parse_lands(z.read(lm).decode("utf-8-sig", "replace")) if lm else {}
            out[c["code"]] = county_book(cases, lands)
            fixed[c["code"]] = fx
    return out, fixed
