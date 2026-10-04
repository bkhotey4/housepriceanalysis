"""產生全台鄉鎮市區清單與位置（data/tw/towns.json），資料來自 OpenStreetMap（Overpass API）。

用法（需要網路；GitHub Actions 會自動跑）：
    python tools/build_towns.py            # 已有的縣市不重抓
    python tools/build_towns.py --force    # 全部重抓

每個縣市問一次 Overpass：縣市範圍內 admin_level 6~8 的行政區界線，取名稱與中心點。
臺南市沿用 data/districts.json（有人工校正的位置與「府城／南科」等分區說明）。
"""
import argparse
import datetime
import json
import os
import sys
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import geo, plvr, roads  # noqa: E402
from core.taiwan import COUNTIES, TOWNS_PATH  # noqa: E402

SUFFIX = ("區", "鄉", "鎮", "市")
# OpenStreetMap 界線中心不能用的區：旗津區的界線包含東沙、南沙，中心算到南海去了。改用本島上的位置。
FIXES = {"E": {"旗津區": (22.598, 120.278)}}


def apply_fixes(towns):
    for code, fixes in FIXES.items():
        for t in towns.get(code, []):
            if t["name"] in fixes:
                t["lat"], t["lng"] = fixes[t["name"]]


def query(county_name):
    return ('[out:json][timeout:120];area["name"="%s"]["admin_level"="4"]->.c;'
            'rel(area.c)["boundary"="administrative"]["admin_level"~"^[678]$"];out center tags;' % county_name)


def ask(ql):
    last = None
    for base in roads.ENDPOINTS:
        for attempt in range(2):
            try:
                hdr = dict(roads.HEADERS)
                hdr["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                body = plvr.fetch(base, timeout=180, agent=roads.AGENT, headers=hdr,
                                  data=("data=" + quote(ql)).encode("ascii"))
                raw = json.loads(body.decode("utf-8"))
                if isinstance(raw.get("elements"), list):
                    return raw
            except Exception as e:          # 忙線、逾時：換一台或稍後再試
                last = e
            time.sleep(5 + attempt * 10)
    raise RuntimeError("Overpass 查詢失敗：%s" % last)


def towns_of(raw):
    """從行政區界線挑出鄉鎮市區：名稱以 區/鄉/鎮/市 結尾，取出現最多的那個 admin_level。"""
    by_level = {}
    for e in raw.get("elements", []):
        t = e.get("tags") or {}
        name = (t.get("name") or t.get("name:zh") or "").strip()
        c = e.get("center") or {}
        if not name.endswith(SUFFIX) or "lat" not in c:
            continue
        by_level.setdefault(t.get("admin_level"), {})[name] = {"name": name, "lat": round(c["lat"], 5), "lng": round(c["lon"], 5)}
    if not by_level:
        return []
    best = max(by_level.values(), key=len)
    return sorted(best.values(), key=lambda x: (-x["lat"], x["lng"]))


def tainan_towns():
    return [{"name": d["name"], "lat": d["lat"], "lng": d["lng"], "zone": d.get("zone", "")} for d in geo.load_districts()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    try:
        with open(TOWNS_PATH, encoding="utf-8") as f:
            out = json.load(f)
    except (OSError, ValueError):
        out = {"source": "© OpenStreetMap 貢獻者（Overpass API）", "towns": {}}
    out["towns"]["D"] = tainan_towns()
    failed = []
    for c in COUNTIES:
        if c["code"] == "D" or (out["towns"].get(c["code"]) and not args.force):
            continue
        try:
            got = towns_of(ask(query(c["name"])))
        except RuntimeError as e:
            print("%s：%s" % (c["name"], e), flush=True)
            failed.append(c["name"])
            continue
        if got:
            out["towns"][c["code"]] = got
            print("%s：%d 個鄉鎮市區" % (c["name"], len(got)), flush=True)
        else:
            failed.append(c["name"])
            print("%s：沒有抓到鄉鎮市區" % c["name"], flush=True)
        time.sleep(3)
    apply_fixes(out["towns"])
    out["built"] = datetime.date.today().isoformat()
    os.makedirs(os.path.dirname(TOWNS_PATH), exist_ok=True)
    with open(TOWNS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    n = sum(len(v) for v in out["towns"].values())
    print("完成：%d 縣市、%d 個鄉鎮市區%s" % (len(out["towns"]), n, "；失敗：" + "、".join(failed) if failed else ""))


if __name__ == "__main__":
    main()
