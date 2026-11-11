"""各區生活機能：下載財政部全國營業（稅籍）登記資料，統計各鄉鎮市區的餐飲、超商、銀行等店家數。

    python tools/build_shops.py

輸出：
    web/data/tw/<代碼>/shops.json   {"source", "url", "built", "as_of", "cats": [[鍵, 名稱], …], "data": {區: [各類家數]}, "total": [縣市合計],
                                     "roads": {區: {路段: [各類家數]}}}（路段名稱和實價登錄同一套規則，路段分頁與成交分頁用）
    web/data/tw/shops.json          全台：data 以縣市名稱（台南市…）為鍵
zip 每天更新、約 66 MB；抓不到就用 data/cache/plvr_tw/shops.zip（上次成功的那份，跟著下載快取保存）。
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import plvr, plvr_tw, shops, taiwan  # noqa: E402

WEB_TW = os.path.join(ROOT, "web", "data", "tw")
STALE_DAYS = 20          # 每天更新：快取超過 20 天還抓不到新的，就提醒
SOURCE = "財政部 全國營業（稅籍）登記資料"


def cached_path():
    return os.path.join(plvr_tw.CACHE, "shops.zip")


def get_zip(today):
    """回傳 (zip 內容, 取得日期)；新的抓不到用快取，都沒有回傳 (None, None)。"""
    path = cached_path()
    try:
        z = plvr.fetch(shops.URL, timeout=300)
        if z[:2] != b"PK":
            raise plvr.DownloadError("回傳的不是 zip")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(z)
        os.replace(path + ".tmp", path)
        return z, today.isoformat()
    except Exception as e:
        print("下載失敗：%s" % e, flush=True)
    if not os.path.exists(path):
        return None, None
    day = datetime.date.fromtimestamp(os.path.getmtime(path))
    print("改用上次下載的檔案（%s）" % day.isoformat())
    if (today - day).days > STALE_DAYS:
        print("[提醒] 稅籍登記資料已經 %d 天沒有抓到新的（財政部網址可能改了）" % (today - day).days)
    with open(path, "rb") as f:
        return f.read(), day.isoformat()


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main():
    today = datetime.date.today()
    z, fetched = get_zip(today)
    if z is None:
        print("[提醒] 稅籍登記資料抓不到，也沒有上次的檔案，網站這次不會有各區生活機能統計")
        return 0
    towns = {c: [t["name"] for t in v] for c, v in taiwan.load_towns().items()}
    roads = {}
    counts, as_of, miss = shops.parse_zip(z, towns, roads)
    meta = {"source": SOURCE, "url": shops.URL, "built": today.isoformat(), "as_of": as_of or fetched,
            "cats": [[k, label] for k, label, _ in shops.CATS]}
    nation = {}
    for c in taiwan.COUNTIES:
        data = counts.get(c["code"])
        if not data:
            continue
        total = [sum(v[i] for v in data.values()) for i in range(len(shops.CATS))]
        write(os.path.join(WEB_TW, c["code"], "shops.json"), dict(meta, data=data, total=total, roads=roads.get(c["code"], {})))
        nation[c["short"]] = total
        print("%s：%d 區，餐飲 %d 家、便利商店 %d 家" % (c["short"], len(data), sum(total[:3]), total[6]))
    write(os.path.join(WEB_TW, "shops.json"), dict(meta, data=nation, total=[sum(v[i] for v in nation.values()) for i in range(len(shops.CATS))]))
    print("稅籍登記（%s）：%d 縣市，%d 筆地址對不上行政區" % (meta["as_of"], len(nation), miss))
    if len(nation) < 20:
        print("[提醒] 稅籍登記資料只對上 %d 個縣市（平常 22 個），檔案格式可能改了" % len(nation))
    return 0


if __name__ == "__main__":
    sys.exit(main())
