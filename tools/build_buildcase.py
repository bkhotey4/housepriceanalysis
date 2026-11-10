"""預售屋建案備查：下載內政部的全國備查 zip，產生網頁用的各縣市清單。

    python tools/build_buildcase.py

輸出 web/data/tw/<代碼>/buildcase.json：{"source", "url", "built", "fetched", "latest", "dists", "rows"}（格式見 core/buildcase.py）。
zip 每月 1 日更新、約 1 MB，每次都重抓；抓不到就用 data/cache/plvr_tw/buildcase.zip（上次成功的那份，跟著下載快取保存）。
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import buildcase, plvr, plvr_tw  # noqa: E402

URL = "https://plvr.land.moi.gov.tw/opendata/lvr_buildcasecsv.zip"
WEB_TW = os.path.join(ROOT, "web", "data", "tw")
STALE_DAYS = 45          # 每月更新：快取超過一個半月還抓不到新的，就提醒


def cached_path():
    return os.path.join(plvr_tw.CACHE, "buildcase.zip")


def get_zip(today):
    """回傳 (zip 內容, 取得日期 YYYY-MM-DD)；新的抓不到用快取，都沒有回傳 (None, None)。"""
    path = cached_path()
    try:
        z = plvr.fetch(URL, timeout=120)
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
        print("[提醒] 預售屋建案備查已經 %d 天沒有抓到新的（內政部網址可能改了）" % (today - day).days)
    with open(path, "rb") as f:
        return f.read(), day.isoformat()


def main():
    today = datetime.date.today()
    z, fetched = get_zip(today)
    if z is None:
        print("[提醒] 預售屋建案備查抓不到，也沒有上次的檔案，網站這次不會有預售屋報備清單")
        return 0
    books, fixed = buildcase.parse_zip(z)
    total = 0
    for code, book in sorted(books.items()):
        latest = max((r[6] for r in book["rows"] if r[6]), default="")
        out = {"source": "內政部地政司 預售屋建案備查", "url": URL, "built": today.isoformat(), "fetched": fetched,
               "latest": latest, **book}
        os.makedirs(os.path.join(WEB_TW, code), exist_ok=True)
        with open(os.path.join(WEB_TW, code, "buildcase.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        total += len(book["rows"])
        print("%s：%d 件（最新報備 %s%s）" % (code, len(book["rows"]), latest or "—",
                                          "，%d 列欄位夾逗號已修復" % fixed[code] if fixed.get(code) else ""))
    print("預售屋建案備查：%d 縣市、%d 件" % (len(books), total))
    if len(books) < 18:
        print("[提醒] 預售屋建案備查只有 %d 個縣市（平常有 21 個），zip 的格式可能改了" % len(books))
    return 0


if __name__ == "__main__":
    sys.exit(main())
