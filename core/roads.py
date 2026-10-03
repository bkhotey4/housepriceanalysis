"""路段位置：把實價登錄門牌上的路名，對到地圖上的道路。

實價登錄的開放資料只有門牌文字、沒有座標，所以道路的位置取自 OpenStreetMap
（© OpenStreetMap 貢獻者，ODbL 授權），透過公開的 Overpass API 一次抓一個行政區，
存在 data/cache/roads/，之後離線可用。

門牌上「路名」之外還有不少是聚落名稱（例如善化區的「茄拔」「小新營」），
這類沒有對應的道路，改用 OpenStreetMap 上的聚落地點，在地圖上畫成一個圓點。
"""
import json
import os
import queue
import re
import threading
import time
from urllib.parse import quote

from . import plvr
from .geo import DATA_DIR
from .prices import in_cat, median, road_of

ROAD_DIR = os.path.join(DATA_DIR, "cache", "roads")
ATTRIBUTION = "道路位置：© OpenStreetMap 貢獻者"
# 公開的 Overpass 伺服器要求程式說明自己是誰；沒有像樣的 User-Agent 會被直接拒絕
AGENT = "deep_tainan_house/1.0 (desktop app for personal Tainan house-price study)"
HEADERS = {"Accept": "application/json, */*;q=0.5", "Accept-Language": "zh-TW,zh;q=0.8,en;q=0.5"}
# 公開的 Overpass 伺服器（都是志願者維運，忙線很常見）：主站常回「too busy」，所以同時問兩台，誰先回就用誰
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
# 不當成「路段」的道路類型：國道、匝道、自行車道、步道、施工或規劃中
SKIP_HIGHWAY = {"motorway", "motorway_link", "cycleway", "footway", "path", "steps", "pedestrian", "track",
                "construction", "proposed", "bridleway", "corridor", "platform"}
_ROADLIKE = re.compile(r"(路|街|大道|巷|弄|段|新村|橋)$")
_LANE = re.compile(r"^\d+巷(\d+弄)?$|^.{1,6}巷(\d+弄)?$")
# 門牌與 OpenStreetMap 之間常見的異體字（只收確定是同一個地名的寫法；不做「差一個字就算」的模糊比對，
# 否則像「東勢寮」「東勢宅」這種相鄰的不同聚落會被配錯）
_VARIANTS = str.maketrans({"仔": "子", "臺": "台", "庄": "莊", "廍": "部", "份": "分", "磘": "窯", "衚": "衛"})


def query(district):
    """Overpass QL：臺南市某行政區內所有有名稱的道路，以及聚落地點。"""
    return ('[out:json][timeout:25];area["name"="臺南市"]["admin_level"="4"]->.c;'
            'rel(area.c)["boundary"="administrative"]["name"="%s"];map_to_area->.a;'
            '(way["highway"]["name"](area.a);node["place"]["name"](area.a););out tags geom qt;' % district)


def reduce(raw):
    """把 Overpass 的回應整理成 {"roads": {路名: [[[lat, lng], ...], ...]}, "places": {聚落: [lat, lng]}}。"""
    roads, places = {}, {}
    for e in raw.get("elements", []):
        tags = e.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        if e.get("type") == "way":
            hw = tags.get("highway")
            if hw in SKIP_HIGHWAY:
                continue
            if hw == "service" and not _ROADLIKE.search(name) and len(name) > 6:
                continue                    # 停車場、園區內部通道之類有名字的服務道路
            pts = [[round(p["lat"], 5), round(p["lon"], 5)] for p in e.get("geometry") or [] if "lat" in p]
            if len(pts) >= 2:
                roads.setdefault(name, []).append(pts)
        elif e.get("type") == "node" and "lat" in e:
            rank = {"village": 0, "hamlet": 1, "neighbourhood": 2, "quarter": 2, "locality": 3}.get(tags.get("place"), 9)
            if rank < 9 and (name not in places or rank < places[name][2]):
                places[name] = [round(e["lat"], 5), round(e["lon"], 5), rank]
    return {"roads": roads, "places": {k: v[:2] for k, v in places.items()}}


def _path(district):
    return os.path.join(ROAD_DIR, "%s.json" % district)


def cached(district):
    """這一區的道路位置是否已經下載過（只看檔案在不在，不讀內容）。"""
    return os.path.isfile(_path(district))


def load(district):
    """讀取快取的道路位置；沒有就回傳 None。"""
    try:
        with open(_path(district), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d.get("roads"), dict):
            return d
    except (OSError, ValueError):
        pass
    return None


def save(district, data):
    os.makedirs(ROAD_DIR, exist_ok=True)
    tmp = _path(district) + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, _path(district))


def _log(line):
    """下載紀錄（成功、失敗都記），出問題時看 data/cache/roads/_log.txt 就知道卡在哪。"""
    try:
        os.makedirs(ROAD_DIR, exist_ok=True)
        with open(os.path.join(ROAD_DIR, "_log.txt"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except OSError:
        pass


def _rounds():
    """每一輪同時問哪幾台（伺服器, 送法, 等多久）。第一輪兩台都沒成功才有第二輪；最壞情況大約一分半鐘。"""
    return [[(ENDPOINTS[0], "POST", 25), (ENDPOINTS[1], "POST", 45)],
            [(ENDPOINTS[0], "GET", 25), (ENDPOINTS[1], "GET", 45), (ENDPOINTS[2], "POST", 30)]]


def _ask(district, ql, base, method, timeout, insecure):
    """問一台伺服器；成功回傳整理好的資料，失敗丟出 DownloadError / ValueError / CertError。"""
    if method == "POST":
        hdr = dict(HEADERS)
        hdr["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        body = plvr.fetch(base, timeout=timeout, insecure=insecure, agent=AGENT, headers=hdr,
                          data=("data=" + quote(ql)).encode("ascii"))
    else:
        body = plvr.fetch(base + "?data=" + quote(ql), timeout=timeout, insecure=insecure, agent=AGENT,
                          headers=HEADERS)
    try:
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw.get("elements"), list):
            raise ValueError
    except (ValueError, AttributeError):                # 忙線時會回一頁 HTML 錯誤訊息
        hint = re.sub(r"<[^>]+>|\s+", " ", body[:600].decode("utf-8", "replace")).strip()
        raise ValueError("伺服器回的不是資料（多半是忙線的錯誤頁）：%s" % hint[:200])
    data = reduce(raw)
    if not data["roads"]:
        raise ValueError("這個行政區沒有抓到任何道路")
    return data


def download(district, insecure=False, progress=None):
    """從 Overpass API 抓某行政區的道路位置並存檔。

    公開伺服器忙線很常見，所以每一輪同時問幾台、誰先回就用誰；都失敗再試第二輪。
    progress(文字) 會在每一輪開始時被呼叫（從背景執行緒）。原因都記在 data/cache/roads/_log.txt。
    """
    ql = query(district)
    errors, certs = [], []
    rounds = _rounds()
    for n, plan in enumerate(rounds):
        if progress:
            progress("下載%s的道路位置（OpenStreetMap，第 %d/%d 輪，約需 10~40 秒）…" % (district, n + 1, len(rounds)))
        results = queue.Queue()

        def work(base, method, timeout):
            host, t0 = base.split("/")[2], time.time()
            try:
                data = _ask(district, ql, base, method, timeout, insecure)
                results.put((host, method, time.time() - t0, data, None))
            except Exception as e:                      # 交給主流程記錄與判斷
                results.put((host, method, time.time() - t0, None, e))

        for base, method, timeout in plan:
            threading.Thread(target=work, args=(base, method, timeout), daemon=True).start()
        deadline = time.time() + max(t for _b, _m, t in plan) + 10
        for _ in plan:
            try:
                host, method, secs, data, err = results.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                break
            if data is not None:
                data.update({"district": district, "fetched": time.strftime("%Y-%m-%d"), "attribution": ATTRIBUTION})
                save(district, data)
                _log("%s 成功 %s %s %.1f 秒，%d 條路" % (district, host, method, secs, len(data["roads"])))
                return data
            if isinstance(err, plvr.CertError):
                certs.append(err)
            errors.append("%s：%s" % (host, err))
            _log("%s 失敗 %s %s %.1f 秒：%s" % (district, host, method, secs, err))
        if n + 1 < len(rounds):
            time.sleep(2.0)
    if certs and len(certs) == len(errors):             # 每一台都是憑證驗證失敗：是這台電腦的憑證問題，不是伺服器忙線
        raise certs[0]
    busy = any("too busy" in e or "504" in e or "429" in e or "timed out" in e for e in errors)
    raise plvr.DownloadError("OpenStreetMap 的公開伺服器%s（%s）" % (
        "現在都在忙線，過幾分鐘再試" if busy else "沒有回應", "；".join(e[:70] for e in errors[-2:])))


def _norm(name):
    return name.translate(_VARIANTS)


def merge_chains(segs):
    """把頭尾相接的折線接成一條（OSM 會在每個路口把道路切成一小段，接起來畫比較快）。"""
    segs = [list(map(tuple, seg)) for seg in segs if len(seg) >= 2]
    merged = True
    while merged and len(segs) > 1:
        merged = False
        ends = {}
        for i, seg in enumerate(segs):
            ends.setdefault(seg[0], []).append(i)
            ends.setdefault(seg[-1], []).append(i)
        for pt, idx in ends.items():
            idx = sorted(set(idx))
            if len(idx) != 2:               # 只接「剛好兩條在這裡相接」的點；三岔以上保持分開
                continue
            a, b = segs[idx[0]], segs[idx[1]]
            if a[-1] != pt:
                a = a[::-1]
            if b[0] != pt:
                b = b[::-1]
            if a[-1] != pt or b[0] != pt or a[0] == b[-1] and len(a) + len(b) < 4:
                continue
            segs = [s for k, s in enumerate(segs) if k not in idx] + [a + b[1:]]
            merged = True
            break
    return [[list(p) for p in seg] for seg in segs]


def locate(data, name):
    """路名（或聚落名）在地圖上的位置。

    回傳 {"segments": 主要道路的折線, "lanes": 同路名的巷弄折線, "point": 聚落或代表點 [lat, lng]}；
    完全找不到回傳 None。
    """
    roads, places = data["roads"], data.get("places", {})
    segments = list(roads.get(name, []))
    lanes = []
    if segments or _ROADLIKE.search(name):
        for other, segs in roads.items():
            if other != name and other.startswith(name) and _LANE.match(other[len(name):]):
                lanes.extend(segs)
    if not segments and not lanes:
        # 聚落式門牌（例如「北子店」）：先看有沒有以它開頭的巷道，再找聚落地點
        for other, segs in roads.items():
            if other.startswith(name) and re.match(r"^\d+巷", other[len(name):]):
                lanes.extend(segs)
    point = None
    if not segments:
        target = _norm(name)
        for pname, pos in places.items():
            if _norm(pname) == target:
                point = pos
                break
    if not segments and not lanes and point is None:
        return None
    if point is None:
        longest = max(segments or lanes, key=len)
        point = longest[len(longest) // 2]
    return {"segments": merge_chains(segments), "lanes": merge_chains(lanes), "point": point}


def road_prices(txs, district, cat, since_ym):
    """某區某房型各路段的件數與中位價（1 件也列，low=True 表示樣本少）。"""
    groups = {}
    for x in txs:
        if x["dist"] != district or x["ym"] < since_ym or not in_cat(x, cat):
            continue
        groups.setdefault(road_of(x["addr"], district), []).append(x)
    out = []
    for name, rows in groups.items():
        if name == "其他":
            continue
        out.append({"name": name, "n": len(rows), "u": round(median([x["u"] for x in rows]), 1),
                    "t": int(round(median([x["tw"] for x in rows]))), "last": max(x["date"] for x in rows),
                    "low": len(rows) < 3})
    out.sort(key=lambda r: (-r["n"], r["name"]))
    return out


def layer(txs, district, cat, since_ym, data):
    """地圖上要畫的路段：road_prices 的每一筆加上位置；找不到位置的另外回傳名稱清單。"""
    found, missing = [], []
    for r in road_prices(txs, district, cat, since_ym):
        loc = locate(data, r["name"]) if data else None
        if loc is None:
            missing.append(r["name"])
            continue
        r = dict(r)
        r.update(loc)
        found.append(r)
    return found, missing


def search(txs, keyword, cat, since_ym, limit=200):
    """全市搜尋路名：回傳 [{dist, name, n, u, t, last}]，依件數排序。"""
    kw = keyword.strip()
    if not kw:
        return []
    groups = {}
    for x in txs:
        if x["ym"] < since_ym or not in_cat(x, cat):
            continue
        road = road_of(x["addr"], x["dist"])
        if kw in road:
            groups.setdefault((x["dist"], road), []).append(x)
    out = []
    for (dist, name), rows in groups.items():
        out.append({"dist": dist, "name": name, "n": len(rows), "u": round(median([x["u"] for x in rows]), 1),
                    "t": int(round(median([x["tw"] for x in rows]))), "last": max(x["date"] for x in rows),
                    "low": len(rows) < 3})
    out.sort(key=lambda r: (-r["n"], r["dist"], r["name"]))
    return out[:limit]
