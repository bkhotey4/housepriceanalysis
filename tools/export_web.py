"""把 data/ 與實價登錄快取整理成網頁版要用的檔案（web/data、web/img）。

網頁版完全在使用者的手機／平板瀏覽器裡執行，不需要伺服器；
這支程式負責把「重的」整理工作先做好：實價登錄統計、逐筆成交（含路名、巷、號拆好）、
各區道路位置、情資與捷運、地標與建設的 3D 模型、衛星底圖與疊圖。

用法（在專案資料夾）：
    python tools/export_web.py            # 用 data/cache 裡已下載的資料
    python tools/export_web.py --update   # 先更新實價登錄與缺少的道路位置，再匯出（GitHub Actions 用）
"""
import argparse
import datetime
import json
import math
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

from core import address, geo, landmarks, prices, roads  # noqa: E402

WEB = os.path.join(ROOT, "web")
OUT = os.path.join(WEB, "data")
IMG = os.path.join(WEB, "img")
CACHE = os.path.join(ROOT, "data", "cache")
BASEMAP = os.path.join(CACHE, "basemap")


def _dump(name, obj):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


# ------------------------------------------------------------------ 房價
def export_prices(book, txs):
    _dump("book.json", book.raw)
    dists = [d["name"] for d in geo.load_districts()]
    di = {n: i for i, n in enumerate(dists)}
    cats = {"house": 0, "apt": 1, "other": 2}
    rows = []
    for x in txs:
        if x["dist"] not in di:
            continue
        tail = address.normalize(x["addr"])
        if tail.startswith(x["dist"]):
            tail = tail[len(x["dist"]):]
        road, lane, alley, num, sub = address.tx_parts(x)
        if road is None:
            road = prices.road_of(x["addr"], x["dist"])
        rows.append([di[x["dist"]], x["date"], cats.get(x["cat"], 2), x.get("btype") or "", tail,
                     round(x["tw"], 1), round(x["u"], 2), round(x["ping"], 2), x.get("built") or 0,
                     1 if x.get("kind") == "presale" else 0, x.get("proj") or "",
                     road or "", lane if lane is not None else -1, alley if alley is not None else -1,
                     num if num is not None else -1] + prices.tx_extra(x))
    rows.sort(key=lambda r: r[1], reverse=True)
    fields = ["d", "date", "cat", "btype", "addr", "tw", "u", "ping", "built", "presale", "proj",
              "road", "lane", "alley", "num", "fl", "pk", "pka", "pkp", "pkt",
              "ps", "rp", "rm", "ev", "mg"]
    return _dump("tx.json", {"fields": fields, "cats": ["house", "apt", "other"], "dists": dists, "rows": rows}), len(rows)


# ------------------------------------------------------------------ 道路
def export_roads():
    names = [d["name"] for d in geo.load_districts()]
    done, total = [], 0
    for n in names:
        data = roads.load(n)
        if not data:
            if os.path.exists(os.path.join(OUT, "roads", "%s.json" % n)):
                done.append(n)                      # 這台電腦沒有快取，但網頁版已經有這一區：保留原檔
            continue
        merged = {}
        for name, segs in data["roads"].items():
            chains = roads.merge_chains(segs)
            merged[name] = [[c for p in chain for c in (round(p[0], 5), round(p[1], 5))] for chain in chains]
        total += _dump("roads/%s.json" % n, {"roads": merged, "places": data.get("places", {}),
                                              "fetched": data.get("fetched", "")})
        done.append(n)
    return done, total


# ------------------------------------------------------------------ 情資、捷運、地標
def export_static():
    intel = geo.load_json("intel.json")
    for i, it in enumerate(intel["items"]):
        it["id"] = i
    _dump("intel.json", intel)
    from mrt_data import AS_OF, MRT_LINES
    lines = []
    for short, d in MRT_LINES.items():
        lines.append({"name": short, "full_name": d["full_name"], "color": d["color"], "approved": d["approved"],
                      "status": d["status"], "stage": d["stage"], "construction_start": d["construction_start"],
                      "estimated_completion": d["estimated_completion"],
                      "segments": [[c for p in s["points"] for c in p] for s in d["segments"]],
                      "stations": [list(s) for s in d["stations"]], "sources": d["sources"][:3]})
    _dump("mrt.json", {"as_of": AS_OF, "lines": lines})
    _dump("landmarks.json", landmarks.load(county=None))
    models = {}
    for name in landmarks.MODELS:
        models[name] = [[[round(c, 3) for p in pts for c in p], color, [round(v, 4) for v in n]]
                        for pts, color, n in landmarks.faces_of(name)]
    _dump("models.json", models)
    _dump("districts.json", geo.load_districts())
    _dump("workplaces.json", geo.load_json("workplaces.json")["places"])


# ------------------------------------------------------------------ 底圖：重投影成「緯度線性」，網頁上用仿射變換就能精準貼圖
def _merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _to_linear(im, meta, out_w):
    """網格圖磚（Web Mercator）-> 緯度線性的影像，寬 out_w。"""
    import numpy as np
    from PIL import Image
    w, h = im.size
    out_h = int(round(out_w * h / w))
    north, south = meta["north"], meta["south"]
    yn, ys = _merc_y(north), _merc_y(south)
    lats = north - (np.arange(out_h) + 0.5) / out_h * (north - south)
    src_y = np.array([(yn - _merc_y(la)) / (yn - ys) * h for la in lats])
    src_y = np.clip(src_y.astype(int), 0, h - 1)
    arr = np.asarray(im.resize((out_w, h), Image.LANCZOS))
    return Image.fromarray(arr[src_y])


def export_images():
    from PIL import Image
    os.makedirs(IMG, exist_ok=True)
    layers = {}
    specs = [("photo", "nlsc_photo2_z13", [("basemap.jpg", 2048), ("basemap_hi.jpg", 3840)]),
             ("town", "layer_town_z13", [("town.png", 3072)]),
             ("liq", "layer_liq_z13", [("liq.png", 2048)]),
             ("fault", "layer_fault", [("fault.png", 2048)])]
    for key, stem, outs in specs:
        src, meta_path = os.path.join(BASEMAP, stem + (".jpg" if key == "photo" else ".png")), os.path.join(BASEMAP, stem + ".json")
        if not (os.path.exists(src) and os.path.exists(meta_path)):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        im = Image.open(src)
        im = im.convert("RGB" if key == "photo" else "RGBA")
        files = []
        for name, width in outs:
            if meta.get("z"):                       # 圖磚拼成的：Web Mercator
                out = _to_linear(im, meta, min(width, im.size[0]))
            else:                                   # WMS 以經緯度取圖：本來就是線性
                out = im.resize((min(width, im.size[0]), int(round(min(width, im.size[0]) * im.size[1] / im.size[0]))),
                                Image.LANCZOS)
            path = os.path.join(IMG, name)
            if key == "photo":
                out.save(path, "JPEG", quality=78, optimize=True, progressive=True)
            else:
                out.save(path, "PNG", optimize=True)
            files.append({"file": "img/" + name, "width": out.size[0], "height": out.size[1],
                          "bytes": os.path.getsize(path)})
        layers[key] = {"west": meta["west"], "east": meta["east"], "north": meta["north"], "south": meta["south"],
                       "attribution": meta.get("attribution", ""), "files": files}
    return layers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="先下載新一期實價登錄與缺少的道路位置")
    ap.add_argument("--no-images", action="store_true", help="不重新產生底圖（底圖很少變）")
    args = ap.parse_args()
    if args.update:
        from core import plvr
        try:
            book, n = plvr.update(progress=lambda d, t, m: print("  ", m))
            print("實價登錄更新完成：%d 筆" % n)
        except Exception as e:                      # 抓不到就用手上的資料繼續匯出
            print("實價登錄更新失敗（沿用原有資料）：%s" % e)
        for d in geo.load_districts():
            if roads.load(d["name"]) is None and not os.path.exists(os.path.join(OUT, "roads", "%s.json" % d["name"])):
                try:
                    roads.download(d["name"])
                    print("道路位置：%s 下載完成" % d["name"])
                except Exception as e:
                    print("道路位置：%s 下載失敗：%s" % (d["name"], e))
    os.makedirs(OUT, exist_ok=True)
    book = prices.load_book()
    txs = prices.load_transactions() if book.source == "live" else []
    old_meta = {}
    try:
        with open(os.path.join(OUT, "meta.json"), encoding="utf-8") as f:
            old_meta = json.load(f)
    except (OSError, ValueError):
        pass
    if txs:
        size_tx, n_tx = export_prices(book, txs)
    elif os.path.exists(os.path.join(OUT, "tx.json")):
        # 這台電腦（或 GitHub Actions）沒有逐筆成交的快取：保留網頁版現有的房價資料，只更新情資、捷運等
        print("沒有逐筆成交快取，保留 web/data 現有的房價資料")
        size_tx, n_tx = os.path.getsize(os.path.join(OUT, "tx.json")), old_meta.get("tx_count", 0)
        book = None
    else:
        size_tx, n_tx = export_prices(book, txs)
    road_dists, size_roads = export_roads()
    export_static()
    layers = None
    if not args.no_images:
        layers = export_images()
    else:
        try:
            with open(os.path.join(OUT, "meta.json"), encoding="utf-8") as f:
                layers = json.load(f).get("layers")
        except (OSError, ValueError):
            layers = {}
    if book is None:
        keep = {k: old_meta.get(k) for k in ("source", "describe", "as_of", "complete_through")}
    else:
        keep = {"source": book.source, "describe": book.describe_source(), "as_of": book.as_of,
                "complete_through": book.complete_through}
    meta = {"built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), **keep,
            "tx_count": n_tx, "road_districts": road_dists, "layers": layers or {},
            "roads_attribution": roads.ATTRIBUTION}
    _dump("meta.json", meta)
    print("匯出完成：成交 %d 筆（%.1f MB）、道路 %d 區（%.1f MB）" % (n_tx, size_tx / 1e6, len(road_dists), size_roads / 1e6))


if __name__ == "__main__":
    main()
