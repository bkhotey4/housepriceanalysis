"""找出內政部戶政司開放資料 API（ris.gov.tw）裡，各鄉鎮市區人口、年齡、遷入遷出的資料集代碼與欄位。

戶政司的 API 長這樣：https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP0xx/<民國年或年月>?page=1
但各資料集的代碼沒有統一的清單，所以先在 GitHub Actions 上逐一試，結果寫到
web/data/tw/pop_probe.json（網站上看得到），下一輪再依實際欄位做「人口成長與年齡結構」。

    python tools/probe_population.py
"""
import datetime
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "data", "tw", "pop_probe.json")
BASE = "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/%s/%s?page=1"


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "deep_tainan_house (github.com/bkhotey4/housepriceanalysis)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    today = datetime.date.today()
    roc = today.year - 1911
    periods = [str(roc - 1), str(roc - 2), "%d%02d" % (roc, max(1, today.month - 2)), "%d12" % (roc - 1)]
    found, tried, errors = [], 0, []
    for i in range(1, 61):
        code = "ODRP%03d" % i
        for p in periods:
            tried += 1
            try:
                d = get(BASE % (code, p))
            except Exception as e:                     # 連不上、格式不對：記下來，換下一個
                errors.append("%s/%s：%s" % (code, p, str(e)[:80]))
                if len(errors) > 30 and not found:
                    break
                continue
            rows = d.get("responseData") or []
            if rows:
                found.append({"code": code, "period": p, "total": d.get("totalDataSize"), "pages": d.get("totalPage"),
                              "keys": list(rows[0].keys()), "sample": rows[:2]})
                break
            time.sleep(0.2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "periods": periods, "tried": tried,
                   "found": found, "errors": errors[:40]}, f, ensure_ascii=False, indent=1)
    print("試了 %d 個網址，找到 %d 個有資料的資料集" % (tried, len(found)))
    for x in found:
        print("  %s/%s：%s 筆，欄位 %s" % (x["code"], x["period"], x["total"], "、".join(x["keys"][:12])))
    if not found:
        print("沒有找到（可能是 API 連不上或代碼不在 001～060），詳見 pop_probe.json 的 errors")


if __name__ == "__main__":
    main()
