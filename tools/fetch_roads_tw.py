"""逐步下載全台各鄉鎮市區的道路位置（OpenStreetMap），存成網頁版用的格式。

    python tools/fetch_roads_tw.py --minutes 25     # 最多跑 25 分鐘，已下載的不重抓

輸出：web/data/tw/<縣市代碼>/roads/<鄉鎮市區>.json（和台南版 web/data/roads 相同格式）。
公開的 Overpass 伺服器是志工維運，所以一次只問一區、每區之間休息幾秒；
全台 368 區要分好幾次（GitHub Actions 每次自動續抓），沒抓到的區網頁上就只是沒有路段線條。
"""
import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import roads  # noqa: E402
from core.taiwan import COUNTIES, load_towns  # noqa: E402

OUT = os.path.join(ROOT, "web", "data", "tw")


def out_path(code, town):
    return os.path.join(OUT, code, "roads", "%s.json" % town)


def to_web(data):
    merged = {}
    for name, segs in data["roads"].items():
        chains = roads.merge_chains(segs)
        merged[name] = [[c for p in chain for c in (round(p[0], 5), round(p[1], 5))] for chain in chains]
    return {"roads": merged, "places": data.get("places", {}), "fetched": data.get("fetched", time.strftime("%Y-%m-%d"))}


def fetch_one(county, town):
    ql = roads.query(town, county, timeout=90)
    last = None
    for base in roads.ENDPOINTS:
        try:
            data = roads._ask(town, ql, base, "POST", 120, False)
            data["fetched"] = time.strftime("%Y-%m-%d")
            return data
        except Exception as e:
            last = e
            time.sleep(8)
    raise RuntimeError(str(last)[:200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--only", help="只抓某些縣市代碼，例如 A,F")
    args = ap.parse_args()
    t_end = time.time() + args.minutes * 60
    # 台南沿用已經整理好的 web/data/roads
    legacy = os.path.join(ROOT, "web", "data", "roads")
    if os.path.isdir(legacy):
        os.makedirs(os.path.join(OUT, "D", "roads"), exist_ok=True)
        for f in os.listdir(legacy):
            dst = os.path.join(OUT, "D", "roads", f)
            if f.endswith(".json") and not os.path.exists(dst):
                shutil.copyfile(os.path.join(legacy, f), dst)
    towns = load_towns()
    only = set((args.only or "").upper().split(",")) - {""}
    todo = [(c, t["name"]) for c in COUNTIES if (not only or c["code"] in only)
            for t in towns.get(c["code"], []) if not os.path.exists(out_path(c["code"], t["name"]))]
    print("待下載 %d 區" % len(todo), flush=True)
    done = fail = 0
    for c, town in todo:
        if time.time() > t_end:
            break
        try:
            data = to_web(fetch_one(c["name"], town))
            os.makedirs(os.path.dirname(out_path(c["code"], town)), exist_ok=True)
            with open(out_path(c["code"], town), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            done += 1
            print("  %s%s：%d 條路" % (c["short"], town, len(data["roads"])), flush=True)
        except Exception as e:
            fail += 1
            print("  %s%s 失敗：%s" % (c["short"], town, e), flush=True)
        time.sleep(4)
    print("本次完成 %d 區、失敗 %d 區、剩 %d 區" % (done, fail, len(todo) - done))


if __name__ == "__main__":
    main()
