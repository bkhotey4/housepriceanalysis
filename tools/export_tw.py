"""把全台實價登錄整理成網頁版的檔案（web/data/tw/）。

    python tools/export_tw.py --update      # 先下載（或補齊）全國資料再整理（GitHub Actions 用）
    python tools/export_tw.py               # 用 data/cache/plvr_tw 裡已下載的資料
    python tools/export_tw.py --legacy-tainan   # 沒有全國資料時，只用台南的快取做出臺南市（測試用）

輸出：
    web/data/tw/index.json            22 縣市清單、各縣市是否有資料、資料日期、圖層設定
    web/data/tw/book.json             全台各縣市的每月統計（全台首頁的柱子）
    web/data/tw/<代碼>/book.json      該縣市各鄉鎮市區的每月統計
    web/data/tw/<代碼>/tx.json        該縣市逐筆成交（格式同台南版 web/data/tx.json）
    web/data/tw/<代碼>/districts.json 該縣市鄉鎮市區與位置
    web/data/tw/<代碼>/rent.json      該縣市各鄉鎮市區近一年的租金行情（實價登錄租賃檔）
    web/data/tw/rent.json             全台各縣市的租金行情
道路位置另由 tools/fetch_roads_tw.py 逐步下載到 web/data/tw/<代碼>/roads/。
"""
import argparse
import datetime
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

from core import address, geo, plvr_tw, prices, rent  # noqa: E402
from core.taiwan import COUNTIES, NATION, load_towns, norm  # noqa: E402

OUT = os.path.join(ROOT, "web", "data", "tw")
# 全台圖磚圖層（國土測繪中心 WMTS；斷層用地調所 WMS，依每張圖磚的範圍取圖）
LAYERS = {
    "photo": {"tiles": "https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}",
              "max_z": 19, "attribution": "影像：內政部國土測繪中心"},
    "town": {"tiles": "https://wmts.nlsc.gov.tw/wmts/TOWN/default/GoogleMapsCompatible/{z}/{y}/{x}",
             "max_z": 17, "attribution": "行政區界：內政部國土測繪中心"},
    "liq": {"tiles": "https://wmts.nlsc.gov.tw/wmts/SoilLiquefaction/default/GoogleMapsCompatible/{z}/{y}/{x}",
            "max_z": 15, "opacity": 0.55, "attribution": "土壤液化潛勢：經濟部地質調查及礦業管理中心（圖磚：國土測繪中心）"},
    "slide": {"tiles": "https://wmts.nlsc.gov.tw/wmts/GeoSensitive2/default/GoogleMapsCompatible/{z}/{y}/{x}",
              "max_z": 16, "opacity": 0.5, "attribution": "地質敏感區（山崩與地滑）：經濟部地質調查及礦業管理中心（圖磚：國土測繪中心）"},
    "fault": {"wms": ("https://geomap.gsmma.gov.tw/mapguide/mapagent/mapagent.fcgi?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
                      "&LAYERS=WMS/25K_Geomap_fault_2021,WMS/Sensitive_area_fault&STYLES=&SRS=EPSG:4326"
                      "&BBOX={w},{s},{e},{n}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE"),
              "max_z": 16, "attribution": "活動斷層：經濟部地質調查及礦業管理中心"},
}


def _dump(rel, obj):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def town_list(county, towns_osm, txs):
    """鄉鎮市區清單：OSM 抓到的位置為主；實價登錄裡有、OSM 沒有的，先放在縣市中心附近並標示約略位置。"""
    out, seen = [], set()
    for t in towns_osm:
        out.append(dict(t))
        seen.add(norm(t["name"]))
    names = {}
    for x in txs:
        names[x["dist"]] = names.get(x["dist"], 0) + 1
    extra = [n for n in names if n and norm(n) not in seen]
    for i, n in enumerate(sorted(extra, key=lambda n: -names[n])):
        a = i * 2.4
        out.append({"name": n, "lat": round(county["lat"] + 0.03 * math.sin(a) * (1 + i * 0.3), 5),
                    "lng": round(county["lng"] + 0.03 * math.cos(a) * (1 + i * 0.3), 5), "approx": True})
    # 名稱以實價登錄的寫法為準（臺／台），統計和門牌才對得起來
    tx_name = {norm(n): n for n in names}
    for t in out:
        t["name"] = tx_name.get(norm(t["name"]), t["name"])
    return out


def road_list(code):
    d = os.path.join(OUT, code, "roads")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []


def export_tx(code, txs, dists, cancels=()):
    di = {n: i for i, n in enumerate(dists)}
    cats = {"house": 0, "apt": 1, "other": 2}
    rows = []
    for x in txs:
        if x["dist"] not in di:
            continue
        tail = address.normalize(x["addr"])
        if tail.startswith(x["dist"]):
            tail = tail[len(x["dist"]):]
        road, lane, alley, num, _sub = address.tx_parts(x)
        if road is None:
            road = prices.road_of(x["addr"], x["dist"])
        rows.append([di[x["dist"]], x["date"], cats.get(x["cat"], 2), x.get("btype") or "", tail,
                     round(x["tw"], 1), round(x["u"], 2), round(x["ping"], 2), x.get("built") or 0,
                     1 if x.get("kind") == "presale" else 0, x.get("proj") or "",
                     road or "", lane if lane is not None else -1, alley if alley is not None else -1,
                     num if num is not None else -1] + prices.tx_extra(x))
    rows.sort(key=lambda r: r[1], reverse=True)
    fields = ["d", "date", "cat", "btype", "addr", "tw", "u", "ping", "built", "presale", "proj",
              "road", "lane", "alley", "num", "fl", "pk", "pka", "pkp", "pkt"]
    return _dump("%s/tx.json" % code, {"fields": fields, "cats": ["house", "apt", "other"], "dists": dists, "rows": rows,
                                       "cancel": prices.cancel_counts(cancels, dists)}), len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="先下載全國實價登錄")
    ap.add_argument("--legacy-tainan", action="store_true", help="只用台南快取做出臺南市（測試用）")
    ap.add_argument("--refresh-roads", action="store_true", help="只更新 index.json 裡各縣市已有道路位置的清單")
    args = ap.parse_args()
    if args.refresh_roads:
        with open(os.path.join(OUT, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        for c in index["counties"]:
            c["roads"] = road_list(c["code"])
        _dump("index.json", index)
        print("道路清單：%d 區" % sum(len(c["roads"]) for c in index["counties"]))
        return
    today = datetime.date.today()
    if args.update:
        try:
            plvr_tw.update()
        except Exception as e:                      # 下載失敗：用上次留下的快取照樣產生，不要讓網站掉成只剩台南
            print("下載全台實價登錄失敗：%s；改用已下載的資料。" % e, flush=True)
            if not plvr_tw.folders():
                raise SystemExit("沒有任何已下載的全台資料可用。")
    towns = load_towns()
    if not towns.get("D"):           # 還沒跑過 build_towns：臺南市用內建的行政區位置
        towns["D"] = [{"name": d["name"], "lat": d["lat"], "lng": d["lng"], "zone": d.get("zone", "")} for d in geo.load_districts()]
    as_of = plvr_tw.as_of()
    all_tx, all_rent, counties, books = [], [], [], {}
    for c in COUNTIES:
        if args.legacy_tainan:
            txs, cancels = (prices.load_transactions() if c["code"] == "D" else []), []
        else:
            cancels = []
            txs = plvr_tw.load_county(c["code"], cancels)
        entry = {k: c[k] for k in ("code", "name", "short", "region", "lat", "lng", "zoom")}
        entry["has_data"] = bool(txs)
        dl = town_list(c, towns.get(c["code"], []), txs) if (txs or towns.get(c["code"])) else []
        entry["towns"] = len(dl)
        entry["town_names"] = [t["name"] for t in dl]
        if dl:
            _dump("%s/districts.json" % c["code"], {"districts": dl})
        raw = None
        if txs:
            names = [t["name"] for t in dl]
            try:
                raw = prices.build_book(txs, names, as_of=as_of, source="live", total=c["short"],
                                        note="內政部不動產交易實價查詢服務網開放資料", today_ym=today.strftime("%Y-%m"))
            except ValueError as e:                 # 例如只有預售屋、沒有一般買賣：這個縣市先當作沒有資料
                print("%s：%s，略過" % (c["short"], e), flush=True)
                entry["has_data"] = False
        if raw:
            _dump("%s/book.json" % c["code"], raw)
            books[c["code"]] = raw
            size, n = export_tx(c["code"], txs, names, cancels)
            entry["tx_count"] = n
            entry["complete_through"] = raw["complete_through"]
            print("%s：%d 筆、%d 區（%.1f MB）" % (c["short"], n, len(names), size / 1e6), flush=True)
            for x in txs:
                all_tx.append(dict(x, dist=c["short"]))
            rents = [] if args.legacy_tainan else plvr_tw.load_county_rent(c["code"])
            if rents:
                rb = rent.build_rent_book(rents, names, raw["complete_through"], c["short"])
                _dump("%s/rent.json" % c["code"], rb)
                n_rent = rb["data"].get(c["short"], {}).get("all", [0])[0]
                entry["rent_n"] = n_rent
                print("  租賃：近一年 %d 筆" % n_rent, flush=True)
                for x in rents:
                    all_rent.append(dict(x, dist=c["short"]))
        entry["roads"] = road_list(c["code"])
        counties.append(entry)
    if not all_tx:
        raise SystemExit("沒有任何縣市有交易資料")
    nat = prices.build_book(all_tx, [c["short"] for c in counties if c["has_data"]], as_of=as_of, source="live",
                            total=NATION, note="內政部不動產交易實價查詢服務網開放資料", today_ym=today.strftime("%Y-%m"))
    _dump("book.json", nat)
    if all_rent:
        _dump("rent.json", rent.build_rent_book(all_rent, [c["short"] for c in counties if c.get("rent_n")],
                                                nat["complete_through"], NATION))
    pb = prices.PriceBook(nat)
    index = {"built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "as_of": as_of,
             "complete_through": nat["complete_through"], "describe": pb.describe_source(),
             "tx_count": len(all_tx), "nation": NATION, "counties": counties, "layers": LAYERS,
             "roads_attribution": "道路位置：© OpenStreetMap 貢獻者"}
    _dump("index.json", index)
    print("完成：%d 縣市有資料、共 %d 筆" % (sum(c["has_data"] for c in counties), len(all_tx)))


if __name__ == "__main__":
    main()
