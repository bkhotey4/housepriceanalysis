"""長期房價走勢（近 5 年）：補抓舊季檔的摘要，並產生網頁用的 long.json。

    python tools/build_long.py              # 每次最多補 4 季（GitHub Actions 用，幾次更新後就補齊 5 年）
    python tools/build_long.py --max 20     # 一次補齊
    python tools/build_long.py --no-fetch   # 只用已有的摘要重新產生 long.json

已經在 data/cache/plvr_tw 裡的季檔直接用，不重抓。摘要存在 data/tw/long/<季別>.json（存回專案），
原始季檔用完就丟，不佔快取空間。格式見 core/longterm.py。
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import longterm, plvr, plvr_tw, prices  # noqa: E402
from core.taiwan import COUNTIES  # noqa: E402

LONG_DIR = os.path.join(ROOT, "data", "tw", "long")
WEB_TW = os.path.join(ROOT, "web", "data", "tw")
YEARS = 5
SEASONS = YEARS * 4 + 1          # 多一季：最早那幾個月才湊得齊


def wanted_seasons(today):
    """最近 SEASONS 季（最新的可能還沒釋出，抓不到就跳過）。"""
    return [plvr.season_name(r, q) for r, q in plvr.season_candidates(today, SEASONS + 1)]


def fetch_season(name, insecure=False):
    """一季的全國摘要；尚未釋出回傳 None。"""
    cached = os.path.join(plvr_tw.CACHE, "season_" + name)
    if plvr_tw.is_done("season_" + name) or os.path.exists(os.path.join(cached, "_done")):
        summ, counts = longterm.season_summary_from_dir(cached)
        return summ, counts, "cache"
    url = "%s/DownloadSeason?season=%s&type=zip&fileName=lvr_landcsv.zip" % (plvr.BASE_URL, name)
    z = plvr.fetch(url, timeout=600, insecure=insecure)
    if z[:2] != b"PK":
        return None
    summ, counts = longterm.season_summary_from_zip(z)
    return summ, counts, "download"


def write_web(today):
    files = longterm.load_season_files(LONG_DIR)
    if not files:
        print("還沒有任何季檔摘要，略過 long.json")
        return 0
    end = today.strftime("%Y-%m")
    start = prices.ym_add(end, -(YEARS * 12 + 2))
    n = 0
    nation_merged = {}
    for c in COUNTIES:
        code = c["code"]
        merged = longterm.merge(files, code)
        if not merged:
            continue
        recent = None
        bp = os.path.join(WEB_TW, code, "book.json")
        if os.path.exists(bp):
            with open(bp, encoding="utf-8") as f:
                recent = json.load(f)
        last = max((m for cats in merged.values() for ms in cats.values() for m in ms), default=start)
        months_end = max(last, (recent or {}).get("complete_through") or last)
        months = prices.ym_range(start, months_end)
        recent_from = (recent or {}).get("months", [None])[0]
        book = longterm.long_book(merged, months, recent, recent_from)
        os.makedirs(os.path.join(WEB_TW, code), exist_ok=True)
        with open(os.path.join(WEB_TW, code, "long.json"), "w", encoding="utf-8") as f:
            json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
        n += 1
        if c["short"] in merged:
            nation_merged[c["short"]] = merged[c["short"]]
    if nation_merged:
        months = prices.ym_range(start, max(m for cats in nation_merged.values() for ms in cats.values() for m in ms))
        nat = None
        bp = os.path.join(WEB_TW, "book.json")
        if os.path.exists(bp):
            with open(bp, encoding="utf-8") as f:
                nat = json.load(f)
        book = longterm.long_book(nation_merged, months, nat, (nat or {}).get("months", [None])[0])
        with open(os.path.join(WEB_TW, "long.json"), "w", encoding="utf-8") as f:
            json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    print("long.json：%d 縣市" % n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=4, help="這次最多下載幾季")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()
    today = datetime.date.today()
    os.makedirs(LONG_DIR, exist_ok=True)
    want = wanted_seasons(today)
    have = {n[:-5] for n in os.listdir(LONG_DIR) if n.endswith(".json")}
    missing = [s for s in want if s not in have]
    fetched, failed = 0, []
    if not args.no_fetch:
        for name in missing:                       # 新的先補：近 3 年的漲跌會先出來
            if fetched >= args.max:
                break
            try:
                r = fetch_season(name, args.insecure)
            except plvr.DownloadError as e:
                print("%s：下載失敗（%s）" % (name, e), flush=True)
                failed.append(name)
                continue
            if r is None:
                print("%s：尚未釋出或沒有檔案" % name, flush=True)
                continue
            summ, counts, how = r
            with open(os.path.join(LONG_DIR, name + ".json"), "w", encoding="utf-8") as f:
                json.dump({"season": name, "built": today.isoformat(), "counts": counts, "counties": summ},
                          f, ensure_ascii=False, separators=(",", ":"))
            fetched += how == "download"
            print("%s：%s，%d 筆" % (name, "快取" if how == "cache" else "下載", sum(counts.values())), flush=True)
    # 超過 5 年的舊摘要刪掉，專案不會越來越大
    for name in sorted(have - set(want)):
        os.remove(os.path.join(LONG_DIR, name + ".json"))
        print("刪除過舊的摘要 %s" % name)
    left = [s for s in want if not os.path.exists(os.path.join(LONG_DIR, s + ".json"))]
    print("季檔摘要：%d / %d 季%s" % (len(want) - len(left), len(want), "（還缺 %s）" % "、".join(left) if left else ""))
    write_web(today)
    if failed:
        print("有 %d 季下載失敗：%s（下次更新再補）" % (len(failed), "、".join(failed)))


if __name__ == "__main__":
    main()
