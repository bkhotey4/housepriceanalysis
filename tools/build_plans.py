"""規劃中的公共建設：讀政府電子採購網每天的公告（開放資料鏡像），留下大型建設的可行性評估、環評、規劃設計、新建工程、招商。

    python tools/build_plans.py                # 從上次看到的那天接著抓到昨天（第一次往回抓 120 天）
    python tools/build_plans.py --days 30      # 只重抓最近 30 天

整理結果存在 data/tw/plans.json（存回專案，下次接著抓）：
    {"through": 已看過的最後一天 YYYYMMDD, "missing": [抓不到、下次再試的平日], "pending": [細節還沒抓到的], "items": [...]}
網頁用：web/data/tw/<代碼>/plans.json {"built", "through", "items"}（格式見 core/plans.py 的 item_from）
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import plans, plvr, taiwan  # noqa: E402

STATE = os.path.join(ROOT, "data", "tw", "plans.json")
WEB_TW = os.path.join(ROOT, "web", "data", "tw")
BACKFILL_DAYS = 90
MAX_DAYS = 90           # 一次最多補幾天（太久沒跑時分好幾次補完）
KEEP_DAYS = 3 * 365      # 三年前最後一次公告的案子就不留了
PAUSE = 2.0              # 每次請求間隔（秒）：鏡像對訪客有頻率限制（HTTP 429）
MAX_DETAILS = 250        # 一次最多查幾案細節（其餘留到下次）
RETRY_DAYS = 14          # 抓不到的平日（國定假日也會）兩週內每次再試


class RateLimited(Exception):
    pass


def get_json(path, sleep=time.sleep, **params):
    """被限流（429）或連線被切斷：等 60 秒再試，最多 3 次；還是不行就丟 RateLimited"""
    url = plans.API + path + "?" + urllib.parse.urlencode(params)
    for i in range(3):
        try:
            return json.loads(plvr.fetch(url, timeout=90).decode("utf-8"))
        except plvr.DownloadError as e:
            if "429" not in str(e) and "closed connection" not in str(e):
                raise
            sleep(60)
    raise RateLimited(url)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"through": None, "pending": [], "items": []}


def days_to_fetch(state, today, days=None):
    end = today - datetime.timedelta(days=1)
    if days:
        start = today - datetime.timedelta(days=days)
    elif state.get("through"):
        start = datetime.datetime.strptime(state["through"], "%Y%m%d").date() + datetime.timedelta(days=1)
    else:
        start = today - datetime.timedelta(days=BACKFILL_DAYS)
    start = max(start, end - datetime.timedelta(days=MAX_DAYS - 1))
    out = []
    while start <= end:
        if start.weekday() < 5:                     # 週末沒有公告（鏡像回 HTTP 500），跳過
            out.append(start)
        start += datetime.timedelta(days=1)
    return out


def run(state, today, towns, days=None, sleep=time.sleep):
    """回傳 (新的 state, 統計)"""
    # 上次抓不到的平日（國定假日也會抓不到）：兩週內每次再試，之後放棄
    recent = (today - datetime.timedelta(days=RETRY_DAYS)).strftime("%Y%m%d")
    retry = sorted(d for d in state.get("missing", []) if d >= recent)
    todo = retry + [d.strftime("%Y%m%d") for d in days_to_fetch(state, today, days)]
    # 上次細節沒抓到的：兩個月內的再試（篩選條件改過的話照新的條件重篩）
    old = (today - datetime.timedelta(days=60)).strftime("%Y%m%d")
    missing, ok = [], 0
    cands = [r for r in state.get("pending", []) if str(r.get("date")) >= old and plans.candidate(r)]
    through = state.get("through")
    for ds in todo:
        try:
            recs = get_json("listbydate", sleep=sleep, date=ds).get("records", [])
            ok += 1
        except Exception as e:
            print("  %s 的公告清單抓不到：%s" % (ds, e))
            missing.append(ds)
            recs = []
        cands += [r for r in recs if plans.candidate(r)]
        if ds not in retry:
            through = max(through or ds, ds)
        sleep(PAUSE)
    new, pending = [], []
    seen, limited = set(), False
    for r in cands:
        k = (r.get("unit_id"), r.get("job_number"), r.get("date"))
        if k in seen:
            continue
        seen.add(k)
        if limited or len(seen) > MAX_DETAILS:
            pending.append(r)
            continue
        try:
            t = get_json("tender", sleep=sleep, unit_id=r["unit_id"], job_number=r["job_number"])
        except RateLimited:
            print("  一直被限流，其餘的留到下次")
            limited = True
            pending.append(r)
            continue
        except Exception as e:
            print("  標案細節抓不到（下次再試）：%s %s" % (r.get("brief", {}).get("title", "")[:30], e))
            pending.append(r)
            continue
        it = plans.item_from(r, t, towns)
        if it:
            new.append(it)
        sleep(PAUSE)
    cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    # 篩選條件改過時，已經收的也照新條件重篩（例如後來才排除的燈節、碳足跡盤查）
    items = [it for it in plans.merge(state.get("items", []), new) if it["last"] >= cutoff and not plans.EXCLUDE.search(it["title"])]
    st = {"through": through, "missing": sorted(set(missing)), "pending": pending[-300:], "items": items}
    return st, {"days": len(todo), "ok": ok, "missing": missing, "cands": len(seen), "new": len(new), "pending": len(pending)}


def write_web(state, today):
    by = {}
    for it in state["items"]:
        by.setdefault(it["county"], []).append(it)
    for c in taiwan.COUNTIES:
        out = {"built": today.isoformat(), "through": state.get("through"), "source": "政府電子採購網公告（開放資料鏡像 pcc-api.openfun.app）",
               "items": by.get(c["code"], [])}
        path = os.path.join(WEB_TW, c["code"], "plans.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return by


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args(argv)
    today = datetime.date.today()
    towns = {c: [t["name"] for t in v] for c, v in taiwan.load_towns().items()}
    state = load_state()
    state, s = run(state, today, towns, a.days)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0)
    by = write_web(state, today)
    print("採購公告：看了 %d 天（%d 天有資料，到 %s），候選 %d 案，新增或更新 %d 案；目前共 %d 案（%s）" % (
        s["days"], s["ok"], state.get("through"), s["cands"], s["new"], len(state["items"]),
        "、".join("%s %d" % (c["short"], len(by[c["code"]])) for c in taiwan.COUNTIES if by.get(c["code"]))))
    if s["days"] >= 3 and not s["ok"]:
        print("[提醒] 採購公告清單 %d 天全部抓不到（pcc-api.openfun.app 可能停了或改版）" % s["days"])
    if state.get("through"):
        lag = (today - datetime.datetime.strptime(state["through"], "%Y%m%d").date()).days
        if lag > 20:
            print("[提醒] 採購公告已經 %d 天沒有接著抓到（pcc-api.openfun.app 可能停了或改版）" % lag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
