"""全台營運中的捷運、輕軌、高鐵與台鐵路線（OpenStreetMap），給網頁版與電腦版畫在地圖上。

用法（需要網路；GitHub Actions 會自動跑，已有的檔案超過 30 天才重抓）：
    python tools/build_transit.py            # 檔案太舊或不存在才抓
    python tools/build_transit.py --force    # 一定重抓

輸出 data/tw/transit.json（也複製到 web/data/tw/transit.json）：
  {"as_of", "source", "lines": [{"name", "full_name", "network", "color", "operating": true, "approved": true,
     "status", "counties": [代碼…], "segments": [[lat, lng, lat, lng, …], …], "stations": [[站名, lat, lng], …]}]}
OSM 的一條路線會依行駛方向拆成好幾個 relation（例如「淡水信義線：象山→淡水」「淡水→象山」），這裡依路線名稱合併。
台鐵的 relation 是一班一班的列車，太多也不完整，所以直接抓軌道（railway=rail，排除高鐵、糖鐵、側線）與車站，合成一條「台鐵」。
台鐵那幾區查不到時，沿用上一次的台鐵資料，捷運照常更新。
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
VERSION = 4          # 格式或抓法改了就加 1：舊檔案即使還沒滿 30 天也會重抓（4：加台鐵）
REPORT = os.path.join(ROOT, "web", "data", "tw", "transit_report.json")   # 每條 relation 的明細（網站上看得到，方便查漏抓）
# 一次查全台太大，Overpass 會中途停掉（回傳一部分＋remark 錯誤訊息）：分區、分類各查一次再合併
AREAS = [("北部", "24.55,120.9,25.35,122.1"), ("中部", "23.75,120.2,24.55,121.4"), ("南部", "21.8,120.0,23.75,121.0"),
         ("東部與離島", "21.8,118.0,26.5,122.2")]
_Q = '[out:json][timeout:180][bbox:%s];%s->.r;.r out geom;node(r.r)["name"];out;'
QUERIES = [("%s捷運輕軌" % n, _Q % (b, 'rel["route"~"^(subway|light_rail|monorail)$"]')) for n, b in AREAS[:3]] + [
    ("高鐵", _Q % ("21.8,118.0,26.5,122.2", 'rel["route"="train"]["name"~"高鐵|高速鐵路|High Speed"]'))]
# 台鐵：軌道＋車站，分四區（區域可以重疊，依 id 去重）
TRA_AREAS = [("台鐵北部", "24.4,120.6,25.35,122.1"), ("台鐵中部", "23.4,120.1,24.45,121.2"),
             ("台鐵南部", "21.8,120.0,23.45,121.0"), ("台鐵東部", "21.8,120.8,24.95,122.0")]
_QT = ('[out:json][timeout:180][bbox:%s];way["railway"="rail"]["service"!~"."];out geom tags;'
       'node["railway"~"^(station|halt)$"];out tags;')
TRA_QUERIES = [(n, _QT % b) for n, b in TRA_AREAS]
TRA_COLOR = "#5b6b7c"
_TRA_OP = re.compile("臺鐵|台鐵|臺灣鐵路|台灣鐵路|Taiwan Railway")
_NOT_TRA = re.compile("高鐵|高速鐵路|High Speed|糖|捷運|Metro|MRT|林鐵|阿里山|森林|輕軌")
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
                remark = str(raw.get("remark") or "")
                if "error" in remark.lower() or "runtime" in remark.lower():
                    raise RuntimeError("Overpass 中途停止：%s" % remark[:200])    # 只回了一部分，不能用
                if isinstance(raw.get("elements"), list):
                    return raw
            except Exception as e:          # 忙線、逾時：換一台或稍後再試
                last = e
                print("  %s 第 %d 次：%s" % (base.split("/")[2], attempt + 1, str(e)[:160]), flush=True)
            time.sleep(10 + attempt * 20)
    raise RuntimeError("Overpass 查詢失敗：%s" % last)


# 已知路線：OSM 上同一條線常拆成好幾個 relation（各方向、各班次、支線、普通車／直達車，名稱寫法也不統一），
# 依關鍵字直接歸到同一條。順序有意義（先比對較特定的）。
CANON = [
    (r"新北投", "新北投支線"), (r"小碧潭", "小碧潭支線"), (r"文湖", "文湖線"), (r"淡水|信義線", "淡水信義線"),
    (r"松山|新店|台電大樓", "松山新店線"), (r"中和|新蘆", "中和新蘆線"), (r"板南|南港-板橋-土城", "板南線"),
    (r"三鶯", "三鶯線"), (r"機場捷運|機場第二航廈", "桃園機場捷運"), (r"淡海輕軌", "淡海輕軌"), (r"安坑", "安坑輕軌"),
    (r"(臺北|台北|新北)捷運環狀線|新北捷運環狀|^臺北捷運環狀線", "環狀線"),
    (r"(臺中|台中)捷運綠線", "臺中捷運綠線"), (r"高雄捷運紅線", "高雄捷運紅線"), (r"高雄捷運橘線", "高雄捷運橘線"),
    (r"環狀輕軌", "高雄環狀輕軌"), (r"台灣高鐵|臺灣高鐵|高速鐵路", "台灣高鐵"),
]
CANONICAL = {c for _, c in CANON}


def canon_name(name):
    for pat, c in CANON:
        if re.search(pat, name or ""):
            return c
    return None


def line_key(tags):
    """同一條線不同方向的 relation 合併用：先比對已知路線，其餘去掉「：起站→迄站」與方向字樣。"""
    name = tags.get("name") or tags.get("name:zh") or tags.get("ref") or ""
    c = canon_name(name)
    if c:
        return c
    name = re.split(r"[：:]", name)[0].strip()
    # 方向、支線的括號：「(順向)」「(蘆洲逆向)」「（往淡水）」…都去掉，同一條線的各個方向、分支合成一條
    name = re.sub(r"\s*[（(][^）)]*(往|下行|上行|北上|南下|順行|逆行|順向|逆向|方向|direction)[^）)]*[）)]\s*$", "", name).strip()
    name = re.sub(r"\s*[（(][^）)]*(南向|北向|東向|西向|->|→)[^）)]*[）)]\s*$", "", name).strip()
    net = (tags.get("network") or "").strip()
    if net and name and not name.replace("臺", "台").startswith(net[:2].replace("臺", "台")):     # 只寫「綠線」的：補上路網名稱，免得台北、台中的綠線被併成一條
        name = net + name
    return name


ALIASES = {"南港-板橋-土城線": "板南線"}
# OSM 沒標顏色時用官方路線色（依名稱比對）
KNOWN_COLORS = {"文湖線": "#c48c31", "淡水信義線": "#e3002c", "新北投支線": "#f8a5b8", "松山新店線": "#008659",
                "小碧潭支線": "#cedc00", "中和新蘆線": "#f8b61c", "板南線": "#0070bd", "環狀線": "#ffdb00",
                "桃園機場捷運": "#8246af", "高雄捷運紅線": "#e20b65", "高雄捷運橘線": "#faa73f", "臺中捷運綠線": "#8ec31f",
                "台灣高鐵": "#e36f1e"}


def short_name(full):
    """「臺北捷運淡水信義線」→「淡水信義線」；「高雄捷運紅線」→「紅線」（網路名稱另外存在 network）。"""
    if full in ALIASES:
        return ALIASES[full]
    if full in CANONICAL:
        return full
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
        if t.get("route") == "train" and key != "台灣高鐵":
            continue                                   # 觀光小火車（例如糖廠五分車）不算
        if key not in CANONICAL and not any(str(m.get("role", "")).startswith("stop") for m in e.get("members") or []):
            continue                                   # 不認得、又沒有車站的路線（多半是調車或未完工路段）
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
        if key in KNOWN_COLORS:
            color = KNOWN_COLORS[key]                  # 已知路線一律用官方路線色（各 relation 標的顏色常不一致）
        elif not (t.get("colour") or t.get("color")):
            color = next((c for k, c in KNOWN_COLORS.items() if k in key or k in short_name(key)), color)
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


def _merge_fast(segs):
    """頭尾相接（而且那一點只有這兩段）的折線接起來；每一輪接很多對，比 roads.merge_chains 快很多（台鐵有好幾千段）。"""
    segs = [list(s) for s in segs if len(s) >= 2]
    changed = True
    while changed and len(segs) > 1:
        changed = False
        ends = {}
        for i, sg in enumerate(segs):
            ends.setdefault(sg[0], set()).add(i)
            ends.setdefault(sg[-1], set()).add(i)
        used, out = set(), []
        for pt, idx in ends.items():
            if len(idx) != 2:
                continue
            i, j = sorted(idx)
            if i in used or j in used:
                continue
            a, b = segs[i], segs[j]
            if a[-1] != pt:
                a = a[::-1]
            if b[0] != pt:
                b = b[::-1]
            if a[-1] != pt or b[0] != pt or a[0] == b[-1]:
                continue
            used.update((i, j))
            out.append(a + b[1:])
            changed = True
        segs = [s for k, s in enumerate(segs) if k not in used] + out
    return segs


def is_tra_way(t):
    """台鐵的軌道：排除高鐵（標準軌、名稱）、糖鐵與林鐵（窄軌、觀光）、工業線。"""
    if t.get("highspeed") == "yes" or t.get("railway:preserved") == "yes":
        return False
    if t.get("usage") in ("industrial", "military", "tourism", "test"):
        return False
    gauge = str(t.get("gauge") or "")
    if gauge and gauge != "1067":
        return False
    text = " ".join(str(t.get(k) or "") for k in ("name", "operator", "network"))
    return not _NOT_TRA.search(text)


def build_tra(elements, towns=None):
    """Overpass 回傳（台鐵軌道 way＋車站 node）→ 一條「台鐵」路線；沒有軌道回傳 None。"""
    towns = towns if towns is not None else load_towns()
    ways, nodes = {}, {}
    for e in elements:
        t = e.get("tags") or {}
        if e.get("type") == "way" and e.get("geometry") and is_tra_way(t):
            pts = [(round(p["lat"], 4), round(p["lon"], 4)) for p in e["geometry"] if "lat" in p]
            if len(pts) >= 2:
                ways[e["id"]] = pts
        elif e.get("type") == "node" and t.get("name") and "lat" in e:
            nodes[e["id"]] = e
    if not ways:
        return None
    # 車站：有台鐵的營運者標記，或在台鐵軌道（的節點）300 公尺內、又不是捷運／高鐵／輕軌的站
    grid = {}
    for pts in ways.values():
        for la, lo in pts:
            grid.setdefault((int(la * 100), int(lo * 100)), []).append((la, lo))

    def near_track(la, lo):
        gx, gy = int(la * 100), int(lo * 100)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for p in grid.get((gx + dx, gy + dy), ()):
                    if math.hypot((p[0] - la) * 110.57, (p[1] - lo) * 101.8) < 0.3:
                        return True
        return False
    stations, seen = [], set()
    for e in nodes.values():
        t = e["tags"]
        if t.get("station") in ("subway", "light_rail", "monorail") or t.get("subway") == "yes" or t.get("light_rail") == "yes":
            continue
        text = " ".join(str(t.get(k) or "") for k in ("name", "operator", "network"))
        if _NOT_TRA.search(text):
            continue
        if not (_TRA_OP.search(text) or near_track(e["lat"], e["lon"])):
            continue
        name = t["name"].split(";")[0].strip()
        name = name if name.endswith("站") else name + "站"
        if name in seen:
            continue
        seen.add(name)
        stations.append([name, round(e["lat"], 5), round(e["lon"], 5)])
    chains = _merge_fast(list(ways.values()))
    segs = [[c for p in _thin(ch, 0.08) for c in p] for ch in chains if len(ch) >= 2]
    counties = sorted({_nearest_county(la, lo, towns) for _n, la, lo in stations}) if stations else []
    stations.sort(key=lambda s: (-s[1], s[2]))
    return {"name": "台鐵", "full_name": "臺灣鐵路", "network": "臺鐵", "kind": "台鐵", "color": TRA_COLOR,
            "operating": True, "approved": True, "status": "營運中（台鐵）", "counties": counties,
            "segments": segs, "stations": stations}


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
        if old and old.get("lines") and old.get("v") == VERSION and age is not None and age < MAX_AGE_DAYS:
            os.makedirs(os.path.dirname(WEB_OUT), exist_ok=True)
            shutil.copyfile(OUT, WEB_OUT)
            print("路線資料 %d 天前更新過，這次不重抓" % age)
            return
    elements, seen, report, failed = [], set(), [], []
    tra_elements, tra_seen, tra_failed = [], set(), []
    for label, ql in TRA_QUERIES:
        try:
            raw = ask(ql)
        except RuntimeError as e:
            print("%s：查詢失敗（%s）" % (label, str(e)[:200]), flush=True)
            tra_failed.append(label)
            continue
        n = 0
        for e in raw["elements"]:
            k = (e.get("type"), e.get("id"))
            if k not in tra_seen:
                tra_seen.add(k)
                tra_elements.append(e)
                n += 1
        print("%s：%d 個軌道與車站" % (label, n), flush=True)
        time.sleep(5)
    for label, ql in QUERIES:
        try:
            raw = ask(ql)
        except RuntimeError as e:
            print("%s：查詢失敗（%s）" % (label, str(e)[:200]), flush=True)
            failed.append(label)
            continue
        n_rel = 0
        for e in raw["elements"]:
            k = (e.get("type"), e.get("id"))
            if k in seen:
                continue
            seen.add(k)
            elements.append(e)
            if e.get("type") == "relation":
                n_rel += 1
                t = e.get("tags") or {}
                ms = e.get("members") or []
                report.append({"query": label, "id": e["id"], "name": t.get("name", ""), "route": t.get("route", ""),
                               "network": t.get("network", ""), "key": line_key(t),
                               "ways": sum(1 for m in ms if m.get("type") == "way" and m.get("geometry")),
                               "stops": sum(1 for m in ms if m.get("type") == "node" and str(m.get("role", "")).startswith("stop"))})
        print("%s：%d 個 relation" % (label, n_rel), flush=True)
        time.sleep(5)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump({"as_of": datetime.date.today().isoformat(), "relations": report}, f, ensure_ascii=False, indent=0)
    if failed:
        # 有一區沒抓到：這次不覆蓋，網站繼續用上一次的路線（避免路線突然少一大半），結束代碼 1 讓紀錄看得到
        if os.path.exists(OUT):
            os.makedirs(os.path.dirname(WEB_OUT), exist_ok=True)
            shutil.copyfile(OUT, WEB_OUT)
        raise SystemExit("有 %d 區查詢失敗（%s），沿用上一次的路線資料，下次更新再試" % (len(failed), "、".join(failed)))
    lines = build({"elements": elements})
    if not lines:
        raise SystemExit("沒有抓到任何路線")
    tra = None if tra_failed else build_tra(tra_elements)
    if tra is None:
        # 台鐵這次沒抓齊：沿用上一次的（如果有）
        try:
            with open(OUT, encoding="utf-8") as f:
                tra = next((ln for ln in json.load(f).get("lines") or [] if ln.get("kind") == "台鐵"), None)
        except (OSError, ValueError):
            tra = None
        print("台鐵：%s" % ("查詢失敗（%s），沿用上一次的資料" % "、".join(tra_failed) if tra_failed else "沒有抓到軌道")
              + ("" if tra else "，這次沒有台鐵"), flush=True)
    if tra:
        lines.append(tra)
    out = {"as_of": datetime.date.today().isoformat(), "v": VERSION, "source": "© OpenStreetMap 貢獻者（Overpass API）",
           "lines": lines}
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
