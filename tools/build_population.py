"""各鄉鎮市區的人口成長與年齡結構（內政部戶政司開放資料 API，ris.gov.tw）。

用到的資料集（代碼由 tools/probe_population.py 在 GitHub Actions 上找出來）：
    ODRP048  各鄉鎮市區人口密度（每年）            statistic_yyy, site_id, people_total, area, population_density
    ODRP014  村里戶數、單一年齡人口（每月）        statistic_yyymm, site_id, village, household_no, people_total, people_age_000_m … people_age_100up_f
    ODRP011  村里遷入遷出統計（每月）              statistic_yyymm, site_id, village, in_total_m/f, out_total_m/f …

    python tools/build_population.py           # 資料超過 25 天才重抓（GitHub Actions 用），每次都重新產生網頁檔
    python tools/build_population.py --force

輸出：
    data/tw/population.json          全台各區的整理結果（存回專案）
    web/data/tw/<代碼>/pop.json       該縣市各區 {區: {...}}，另有縣市合計
    web/data/tw/pop.json              全台各縣市合計
每區：{"pop": {民國年: 人口}, "now": 最新月人口, "hh": 戶數, "age": [0-14, 15-24, 25-44, 45-64, 65+], "in12", "out12"}
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.taiwan import COUNTIES, NATION, norm  # noqa: E402

OUT = os.path.join(ROOT, "data", "tw", "population.json")
WEB_TW = os.path.join(ROOT, "web", "data", "tw")
API = "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/%s/%s?page=%d"
MAX_AGE_DAYS = 25
YEARS = 5
BANDS = [(0, 14), (15, 24), (25, 44), (45, 64), (65, 200)]
_AGE = re.compile(r"^people_age_(\d{3})(up)?_[mf]$")
CODE_OF = {norm(c["name"]): c["code"] for c in COUNTIES}


def get(url, timeout=40, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "deep_tainan_house (github.com/bkhotey4/housepriceanalysis)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:            # 忙線、逾時：等一下再試
            last = e
            time.sleep(3 + i * 5)
    raise RuntimeError("戶政司 API 連不上：%s（%s）" % (url, last))


def fetch_all(code, period, fetch=get):
    """一個資料集一期的所有列（自動翻頁）；沒有資料回傳 []。"""
    rows, page, pages = [], 1, 1
    while page <= pages:
        d = fetch(API % (code, period, page))
        data = (d.get("responseData") or []) if isinstance(d, dict) else []
        if not isinstance(data, list) or not data:
            break
        rows.extend(r for r in data if isinstance(r, dict))
        try:
            pages = min(50, int(d.get("totalPage") or 1))
        except (TypeError, ValueError):
            pages = page
        page += 1
    return rows


def split_site(site_id):
    """「臺南市善化區」→ ("D", "善化區")；認不得回傳 (None, None)。"""
    s = norm(site_id)
    code = CODE_OF.get(s[:3])
    return (code, s[3:]) if code and len(s) > 3 else (None, None)


def _int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def months_back(roc, month, n):
    out = []
    for _ in range(n):
        out.append("%d%02d" % (roc, month))
        month -= 1
        if month == 0:
            roc, month = roc - 1, 12
    return out


def collect(today, fetch=get, log=print):
    roc = today.year - 1911
    data = {}

    def cell(site):
        code, dist = split_site(site)
        if not code:
            return None
        return data.setdefault(code, {}).setdefault(dist, {"pop": {}, "hh": 0, "now": 0, "age": [0] * len(BANDS), "in12": 0, "out12": 0})

    # 1. 每年人口（近 YEARS+1 年；最新一年可能還沒發布）
    years = []
    for y in range(roc - YEARS - 1, roc):
        rows = fetch_all("ODRP048", str(y), fetch)
        if not rows:
            continue
        years.append(y)
        for r in rows:
            c = cell(r.get("site_id"))
            if c is not None:
                c["pop"][str(y)] = _int(r.get("people_total"))
        log("人口 %d 年：%d 區" % (y, len(rows)))
    # 2. 最新一個月的年齡結構與戶數（村里加總到鄉鎮市區）
    month = None
    for p in months_back(roc, today.month, 6):
        rows = fetch_all("ODRP014", p, fetch)
        if not rows:
            continue
        month = p
        for r in rows:
            c = cell(r.get("site_id"))
            if c is None:
                continue
            c["hh"] += _int(r.get("household_no"))
            c["now"] += _int(r.get("people_total"))
            for k, v in r.items():
                m = _AGE.match(k)
                if m:
                    age = int(m.group(1))
                    for i, (a, b) in enumerate(BANDS):
                        if a <= age <= b:
                            c["age"][i] += _int(v)
                            break
        log("年齡結構 %s：%d 個村里" % (p, len(rows)))
        break
    # 3. 近 12 個月的遷入、遷出
    mig_months = []
    if month:
        for p in months_back(int(month[:3]), int(month[3:]), 12):
            rows = fetch_all("ODRP011", p, fetch)
            if not rows:
                continue
            mig_months.append(p)
            for r in rows:
                c = cell(r.get("site_id"))
                if c is not None:
                    c["in12"] += _int(r.get("in_total_m")) + _int(r.get("in_total_f"))
                    c["out12"] += _int(r.get("out_total_m")) + _int(r.get("out_total_f"))
        log("遷入遷出：%d 個月" % len(mig_months))
    return {"built": today.isoformat(), "years": years, "month": month, "mig_months": sorted(mig_months), "counties": data}


def total(cells):
    t = {"pop": {}, "hh": 0, "now": 0, "age": [0] * len(BANDS), "in12": 0, "out12": 0}
    for c in cells:
        for y, v in c["pop"].items():
            t["pop"][y] = t["pop"].get(y, 0) + v
        for k in ("hh", "now", "in12", "out12"):
            t[k] += c[k]
        t["age"] = [a + b for a, b in zip(t["age"], c["age"])]
    return t


def write_web(pop):
    meta = {"years": pop["years"], "month": pop["month"], "mig_months": pop["mig_months"],
            "source": "內政部戶政司開放資料（ris.gov.tw）", "bands": ["0-14", "15-24", "25-44", "45-64", "65+"]}
    nation = {}
    for c in COUNTIES:
        cells = pop["counties"].get(c["code"])
        if not cells:
            continue
        out = dict(cells)
        out[c["short"]] = total(cells.values())
        nation[c["short"]] = out[c["short"]]
        os.makedirs(os.path.join(WEB_TW, c["code"]), exist_ok=True)
        with open(os.path.join(WEB_TW, c["code"], "pop.json"), "w", encoding="utf-8") as f:
            json.dump(dict(meta, data=out), f, ensure_ascii=False, separators=(",", ":"))
    if nation:
        nation[NATION] = total(nation.values())
        with open(os.path.join(WEB_TW, "pop.json"), "w", encoding="utf-8") as f:
            json.dump(dict(meta, data=nation), f, ensure_ascii=False, separators=(",", ":"))
    print("pop.json：%d 縣市" % (len(nation) - 1 if nation else 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    today = datetime.date.today()
    old = None
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        pass
    fresh = old and (today - datetime.date.fromisoformat(old["built"])).days < MAX_AGE_DAYS
    pop = old
    if args.force or not fresh:
        try:
            pop = collect(today)
            if not pop["counties"]:
                raise RuntimeError("API 沒有回傳任何資料")
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(pop, f, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:                  # API 掛掉、格式變了：沿用上一次的資料，網頁檔照樣產生
            print("人口資料更新失敗：%s%s" % (e, "，沿用上一次的資料" if old else ""))
            pop = old
    else:
        print("人口資料 %s 更新過，這次不重抓" % old["built"])
    if pop:
        write_web(pop)


if __name__ == "__main__":
    main()
