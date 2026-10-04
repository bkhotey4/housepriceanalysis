"""全台營運中的捷運、輕軌與高鐵路線（OpenStreetMap），給網頁版與電腦版畫在地圖上。

用法（需要網路；GitHub Actions 會自動跑，已有的檔案超過 30 天才重抓）：
    python tools/build_transit.py            # 檔案太舊或不存在才抓
    python tools/build_transit.py --force    # 一定重抓

輸出 data/tw/transit.json（也複製到 web/data/tw/transit.json）：
  {"as_of", "source", "lines": [{"name", "full_name", "network", "color", "operating": true, "approved": true,
     "status", "counties": [代碼…], "segments": [[lat, lng, lat, lng, …], …], "stations": [[站名, lat, lng], …]}]}
OSM 的一條路線會依行駛方向拆成好幾個 relation（例如「淡水信義線：象山→淡水」「淡水→象山」），這裡依路線名稱合併。
臺南捷運還在規劃，仍以 data/mrt.json（人工整理的規劃線與進度）為準。
"""
import argparse
import datetime
import json
import math
import os
import re
import shutil
import sys
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import plvr, roads  # noqa: E402
from core.taiwan import COUNTIES, load_towns  # noqa: E402

OUT = os.path.join(ROOT, "data", "tw", "transit.json")
WEB_OUT = os.path.join(ROOT, "web", "data", "tw", "transit.json")
MAX_AGE_DAYS = 30
QUERY = ('[out:json][timeout:240][bbox:21.8,118.0,26.5,122.2];'
         '(rel["route"~"^(subway|light_rail|monorail)$"];'
         'rel["route"="train"]["name"~"高鐵|高速鐵路|High Speed"];)->.r;'
         '.r out geom;node(r.r)["name"];out;')
DEFAULT_COLORS = {"subway": "#2a78d6", "light_rail": "#2ea36b", "monorail": "#8e5bd0", "train": "#e36f1e"}


def ask(ql):
    last = None
    for base in roads.ENDPOINTS:
        for attempt in range(2):
            try:
                hdr = dict(roads.HEADERS)
                hdr["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                body = plvr.fetch(base, timeout=300, agent=roads.AGENT, headers=hdr,
                                  data=("data=" + quote(ql)).encode("ascii"))
                raw = json.loads(body.decode("utf-8"))
                if isinstance(raw.get("elements"), list) and raw["elements"]:
                    return raw
            except Exception as e:          # 忙線、逾時：換一台或稍後再試
                last = e
            time.sleep(10 + attempt * 20)
    raise RuntimeError("Overpass 查詢失敗：%s" % last)


def line_key(tags):
    """同一條線不同方向的 relation 合併用：去掉「：起站→迄站」與方向字樣。"""
    name = tags.get("name") or tags.get("name:zh") or tags.get("ref") or ""
    name = re.split(r"[：:]", name)[0].strip()
    name = re.sub(r"[（(](往|下行|上行|北上|南下|順行|逆行)[^）)]*[）)]$", "", name).strip()
    net = (tags.get("network") or "").strip()
    if net and name and not name.startswith(net[:2]):     # 只寫「綠線」的：補上路網名稱，免得台北、台中的綠線被併成一條
        name = net + name
    return name


def short_name(full):
    """「臺北捷運淡水信義線」→「淡水信義線」；「高雄捷運紅線」→「紅線」（網路名稱另外存在 network）。"""
    for pre in ("臺北捷運", "台北捷運", "新北捷運", "桃園捷運", "臺中捷運", "台中捷運", "高雄捷運", "高雄輕軌", "淡海輕軌",
                "安坑輕軌", "臺北都會區大眾捷運系統", "台北都會區大眾捷運系統"):
        if full.startswith(pre) and len(full) > len(pre) + 1:
            return full[len(pre):].strip(" -")
    return full


def _thin(pts, min_km=0.03):
    """去掉彼此太近的點（30 公尺內），檔案小很多、畫出來看不出差別。"""
    out = [pts[0]]
    for p in pts[1:-1]:
        q = out[-1]
        if math.hypot((p[0] - q[0]) * 110.57, (p[1] - q[1]) * 101.8) >= min_km:
            out.append(p)
    out.append(pts[-1])
    return out


def _nearest_county(lat, lng, towns):
    best, bd = None, 1e9
    for code, ts in towns.items():
        for t in ts:
            d = (t["lat"] - lat) ** 2 + ((t["lng"] - lng) * 0.92) ** 2
            if d < bd:
                best, bd = code, d
    if best is None:
        c = min(COUNTIES, key=lambda c: (c["lat"] - lat) ** 2 + (c["lng"] - lng) ** 2)
        best = c["code"]
    return best


def build(raw, towns=None):
    """Overpass 回傳 → 路線清單。"""
    towns = towns if towns is not None else load_towns()
    node_names = {}
    for e in raw.get("elements", []):
        if e.get("type") == "node" and (e.get("tags") or {}).get("name"):
            node_names[e["id"]] = e["tags"]["name"]
    groups = {}
    for e in raw.get("elements", []):
        if e.get("type") != "relation":
            continue
        t = e.get("tags") or {}
        key = line_key(t)
        if not key:
            continue
        g = groups.setdefault(key, {"tags": t, "ways": {}, "stops": {}})
        for m in e.get("members") or []:
            if m.get("type") == "way" and m.get("geometry") and m.get("role", "") in ("", "route", "forward", "backward"):
                pts = [(round(p["lat"], 5), round(p["lon"], 5)) for p in m["geometry"] if "lat" in p]
                if len(pts) >= 2:
                    g["ways"][m["ref"]] = pts
            elif m.get("type") == "node" and str(m.get("role", "")).startswith("stop") and "lat" in m:
                name = node_names.get(m["ref"])
                if name:
                    name = name if name.endswith("站") else name + "站"
                    g["stops"].setdefault(name, (round(m["lat"], 5), round(m["lon"], 5)))
    lines = []
    for key, g in groups.items():
        if not g["ways"]:
            continue
        t = g["tags"]
        chains = roads.merge_chains(list(g["ways"].values()))
        segs = [[c for p in _thin(ch) for c in p] for ch in chains]
        stations = [[n, la, lo] for n, (la, lo) in g["stops"].items()]
        pts = [(s[1], s[2]) for s in stations] or [tuple(ch[0]) for ch in chains]
        counties = sorted({_nearest_county(la, lo, towns) for la, lo in pts})
        color = t.get("colour") or t.get("color") or DEFAULT_COLORS.get(t.get("route"), "#2a78d6")
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            color = DEFAULT_COLORS.get(t.get("route"), "#2a78d6")
        kind = {"subway": "捷運", "light_rail": "輕軌", "monorail": "單軌", "train": "高鐵"}.get(t.get("route"), "軌道")
        lines.append({"name": short_name(key), "full_name": key, "network": t.get("network") or t.get("operator") or "",
                      "kind": kind, "color": color.lower(), "operating": True, "approved": True,
                      "status": "營運中（%s）" % kind, "counties": counties, "segments": segs, "stations": stations})
    # 不同路網撞名（例如兩個城市都有「綠線」）：加上路網名稱區分
    seen = {}
    for ln in lines:
        seen.setdefault(ln["name"], []).append(ln)
    for name, same in seen.items():
        if len(same) > 1:
            for ln in same:
                ln["name"] = ln["full_name"]
    lines.sort(key=lambda ln: (ln["counties"][0] if ln["counties"] else "", ln["name"]))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not args.force:
        try:
            with open(OUT, encoding="utf-8") as f:
                old = json.load(f)
            age = (datetime.date.today() - datetime.date.fromisoformat(old["as_of"])).days   # 不看檔案時間：git checkout 會改掉
        except (OSError, ValueError, KeyError):
            old, age = None, None
        if old and old.get("lines") and age is not None and age < MAX_AGE_DAYS:
            os.makedirs(os.path.dirname(WEB_OUT), exist_ok=True)
            shutil.copyfile(OUT, WEB_OUT)
            print("路線資料 %d 天前更新過，這次不重抓" % age)
            return
    lines = build(ask(QUERY))
    if not lines:
        raise SystemExit("沒有抓到任何路線")
    out = {"as_of": datetime.date.today().isoformat(), "source": "© OpenStreetMap 貢獻者（Overpass API）", "lines": lines}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(os.path.dirname(WEB_OUT), exist_ok=True)
    shutil.copyfile(OUT, WEB_OUT)
    print("完成：%d 條路線、%d 個車站" % (len(lines), sum(len(ln["stations"]) for ln in lines)))
    for ln in lines:
        print("  %s %s（%s）%d 站" % (ln["kind"], ln["name"], "、".join(ln["counties"]), len(ln["stations"])))


if __name__ == "__main__":
    main()
