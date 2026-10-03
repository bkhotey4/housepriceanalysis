"""地址搜尋：把使用者輸入的地址拆成「行政區、路段、巷、弄、號」，再到實價登錄的逐筆成交裡找同門牌、同巷、同路段的紀錄。

實價登錄的門牌是文字（例如「臺南市中西區大同路一段４６巷５０號五樓之３」），沒有座標，
所以地圖上只能定位到「那條路（或那條巷）」，不是門牌的精確位置。
"""
import re

from .prices import _ROAD, _VILLAGE, median, road_of
from .taiwan import strip_county

_FULL = str.maketrans("０１２３４５６７８９－（）", "0123456789-()")
_LANE = re.compile(r"(\d+)巷")
_ALLEY = re.compile(r"(\d+)弄")
_NUMBER = re.compile(r"(\d+)(?:之(\d+))?號")
_TAIL_NUMBER = re.compile(r"(\d+)(?:之(\d+))?$")


def normalize(text):
    """去掉空白、全形數字轉半形、去掉開頭的郵遞區號與縣市名稱（「臺南市」「台北市」…）。"""
    s = re.sub(r"\s+", "", (text or "")).translate(_FULL)
    s = re.sub(r"^\d{3,6}(?=[^\d號巷弄之])", "", s)
    rest = strip_county(s)
    return rest if rest else s


def _parts(rest):
    """行政區之後的部分 -> (路段, 巷, 弄, 號, 之幾)；沒有的項目是 None。"""
    rest = _VILLAGE.sub("", rest)
    road = road_of(rest)
    if road == "其他":
        return None, None, None, None, None
    tail = rest[len(road):] if rest.startswith(road) else rest
    lane = _LANE.search(tail)
    alley = _ALLEY.search(tail)
    after = tail[max(lane.end() if lane else 0, alley.end() if alley else 0):]
    num = _NUMBER.search(after) or _TAIL_NUMBER.search(after)
    return (road, int(lane.group(1)) if lane else None, int(alley.group(1)) if alley else None,
            int(num.group(1)) if num else None, int(num.group(2)) if num and num.group(2) else None)


def parse(text, district_names):
    """使用者輸入的地址 -> dict(district, road, lane, alley, num, sub, text)。

    行政區可以省略「區」字（「善化中山路」），但省略時後面必須是看得出來的路名，
    否則像「安平路」會被誤認成安平區。看不出路段時 road 是 None。
    """
    s = normalize(text)
    district, rest = None, s
    for name in sorted(district_names, key=len, reverse=True):
        if s.startswith(name):
            district, rest = name, s[len(name):]
            break
    else:
        for name in sorted(district_names, key=len, reverse=True):
            stem = name[:-1]
            if len(stem) >= 2 and s.startswith(stem) and _ROAD.match(_VILLAGE.sub("", s[len(stem):])) \
                    and len(_ROAD.match(_VILLAGE.sub("", s[len(stem):])).group(1)) >= 3:
                district, rest = name, s[len(stem):]
                break
    road, lane, alley, num, sub = _parts(rest) if rest else (None, None, None, None, None)
    return {"district": district, "road": road, "lane": lane, "alley": alley, "num": num, "sub": sub, "text": s}


def describe(q):
    """把拆好的地址寫回一行文字（不含行政區），例如「大同路一段 46 巷 50 號」。"""
    out = q["road"] or ""
    if q.get("lane") is not None:
        out += " %d 巷" % q["lane"]
    if q.get("alley") is not None:
        out += " %d 弄" % q["alley"]
    if q.get("num") is not None:
        out += " %d%s 號" % (q["num"], "之%d" % q["sub"] if q.get("sub") is not None else "")
    return out


def tx_parts(tx):
    """一筆成交的門牌 -> (路段, 巷, 弄, 號, 之幾)。"""
    s = normalize(tx["addr"])
    if tx.get("dist") and s.startswith(tx["dist"]):
        s = s[len(tx["dist"]):]
    return _parts(s)


def rank(rows, q):
    """把同一路段的成交依「離查詢門牌多近」排序。

    回傳 [(level, tx)]：level 3 = 同門牌（同一棟），2 = 同一條巷，1 = 同路段其他門牌。
    同一級裡門牌號碼越接近越前面（同單雙號優先，因為在路的同一側），再依日期新到舊。
    只輸入路名（沒有巷、號）時全部是 level 1，依日期排序。
    """
    out = []
    for tx in rows:
        _road, lane, alley, num, _sub = tx_parts(tx)
        same_lane = lane == q.get("lane") and (q.get("alley") is None or alley == q.get("alley"))
        level, gap = 1, 10 ** 6
        if q.get("num") is not None and same_lane and alley == q.get("alley") and num == q["num"]:
            level, gap = 3, 0
        elif q.get("lane") is not None and same_lane:
            level = 2
        if level < 3 and q.get("num") is not None and num is not None and same_lane:
            gap = abs(num - q["num"]) * 2 + (0 if (num - q["num"]) % 2 == 0 else 1)
        out.append((level, gap, tx))
    out.sort(key=lambda r: r[2]["date"], reverse=True)
    out.sort(key=lambda r: (-r[0], r[1]))
    return [(level, tx) for level, _gap, tx in out]


def summary(ranked):
    """各層級的件數與中位價：{"exact": {...}, "lane": {...}, "road": {...}}，每個是 dict(n, u, t)（n=0 時 u、t 為 None）。"""
    def stat(rows):
        if not rows:
            return {"n": 0, "u": None, "t": None}
        return {"n": len(rows), "u": round(median([x["u"] for x in rows]), 1),
                "t": int(round(median([x["tw"] for x in rows])))}
    exact = [tx for level, tx in ranked if level == 3]
    lane = [tx for level, tx in ranked if level >= 2]
    return {"exact": stat(exact), "lane": stat(lane), "road": stat([tx for _l, tx in ranked])}


# ---------------------------------------------------------------------- 門牌在地圖上的大概位置
# 實價登錄沒有座標，免費的地理編碼服務（Nominatim）對台灣門牌也只認得到路名，
# 所以位置是用 OpenStreetMap 的道路自己推估的：
#   1. 「N 巷」的巷口就在這條路的 N 號附近，用一條路上好幾個巷口當刻度，內插出門牌號碼的位置；
#   2. 地址在巷子裡、而且 OpenStreetMap 有那條巷：沿著巷子從巷口往裡走，每個號碼約 2.5 公尺（單雙號各在一邊）；
#   3. 聚落式門牌（例如「小新營 102 之 15 號」）只能標在聚落的大概位置；
#   4. 都不行就標在那條路的中段。
METERS_PER_NUMBER = 2.5     # 巷內每一個門牌號碼大約幾公尺（兩邊各一排、每戶面寬約 5 公尺）
LANE_SNAP_KM = 0.12         # 巷口離主要道路多近才算接在這條路上

PRECISION_NOTE = {
    "lane": "依巷內門牌號碼推估，誤差約數十公尺",
    "interp": "依這條路上各巷口的號碼推估，誤差約一兩百公尺",
    "lane_mouth": "標在這條巷的巷口附近（OpenStreetMap 上沒有這條巷）",
    "alley_mouth": "標在這條弄的弄口附近（OpenStreetMap 上沒有這條弄），誤差約數十公尺",
    "near_lane": "標在附近一個巷口，只能當大概位置",
    "settlement": "聚落式門牌，只能標在聚落的大概位置",
    "road": "只知道在這條路上，圖釘在路的中段",
}
PRECISION_RADIUS_KM = {"alley_mouth": 0.08, "lane": 0.05, "interp": 0.15, "lane_mouth": 0.1, "near_lane": 0.3, "settlement": 0.4, "road": None}


def _xy(p):
    from .geo import to_xy
    return to_xy(p[0], p[1])


def _latlng(x, y):
    from .geo import KM_PER_DEG_LAT, KM_PER_DEG_LNG, LAT0, LNG0
    return [round(y / KM_PER_DEG_LAT + LAT0, 6), round(x / KM_PER_DEG_LNG + LNG0, 6)]


def _chain_xy(chain):
    pts = [_xy(p) for p in chain]
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    return pts, cum


def _project(pts, cum, p):
    """點 p 投影到折線上：回傳 (沿線距離, 與折線的距離)。"""
    px, py = p
    best = (0.0, float("inf"))
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        dx, dy = x1 - x0, y1 - y0
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg2))
        qx, qy = x0 + dx * t, y0 + dy * t
        d = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
        if d < best[1]:
            best = (cum[i] + (cum[i + 1] - cum[i]) * t, d)
    return best


def _point_at(pts, cum, s):
    s = max(0.0, min(cum[-1], s))
    for i in range(len(pts) - 1):
        if cum[i + 1] >= s:
            span = cum[i + 1] - cum[i]
            t = 0.0 if span == 0 else (s - cum[i]) / span
            return _latlng(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)
    return _latlng(*pts[-1])


def _merged(data, name):
    from .roads import merge_chains
    return merge_chains(data["roads"].get(name, []))


def lane_anchors(data, road):
    """這條路上的巷口刻度：[(巷號, 主要道路第幾段, 沿線距離, 巷子的折線（從巷口往裡）)]。"""
    chains = [_chain_xy(c) for c in _merged(data, road)]
    if not chains:
        return chains, []
    pat = re.compile("^" + re.escape(road) + r"(\d+)巷$")
    anchors = []
    for name in data["roads"]:
        m = pat.match(name)
        if not m:
            continue
        best = None
        for lane in _merged(data, name):
            for end, oriented in ((lane[0], lane), (lane[-1], lane[::-1])):
                p = _xy(end)
                for ci, (pts, cum) in enumerate(chains):
                    s, d = _project(pts, cum, p)
                    if d <= LANE_SNAP_KM and (best is None or d < best[0]):
                        best = (d, ci, s, oriented)
        if best:
            anchors.append((int(m.group(1)), best[1], best[2], best[3]))
    return chains, anchors


def _fit(anchors):
    """巷號 -> 沿線距離的直線 s = a + b·N；刻度太少或彼此矛盾時回傳 None。"""
    pts = sorted({(n, s) for n, s in anchors})
    ns = sorted({n for n, _s in pts})
    if len(ns) < 2:
        return None
    k = len(pts)
    mn, ms = sum(n for n, _ in pts) / k, sum(s for _, s in pts) / k
    sxx = sum((n - mn) ** 2 for n, _ in pts)
    sxy = sum((n - mn) * (s - ms) for n, s in pts)
    syy = sum((s - ms) ** 2 for _, s in pts)
    if sxx == 0 or syy == 0:
        return None
    b = sxy / sxx
    r = sxy / (sxx * syy) ** 0.5
    # 號碼和巷口位置要大致成正比（同一條路，號碼不會忽前忽後）；每號平均間距也要合理（0.5~30 公尺）
    if abs(r) < 0.8 or not 0.0005 <= abs(b) <= 0.03:
        return None
    return ms - b * mn, b


def position(data, q, places=None):
    """門牌的大概位置：dict(lat, lng, precision, note, radius_km, spot)；連路都找不到回傳 None。

    q 是 parse() 或 tx_parts() 的結果（要有 road，可有 lane、alley、num）。
    """
    from .roads import locate
    road, lane, num = q.get("road"), q.get("lane"), q.get("num")
    if not road or not data:
        return None

    def out(latlng, precision, spot):
        return {"lat": latlng[0], "lng": latlng[1], "precision": precision, "note": PRECISION_NOTE[precision],
                "radius_km": PRECISION_RADIUS_KM[precision], "spot": spot}

    chains, anchors = lane_anchors(data, road)
    if not chains:
        loc = locate(data, road)                    # 聚落式門牌，或只有巷子沒有主要道路
        if loc is None:
            return None
        if not loc["segments"] and not loc["lanes"]:
            return out(loc["point"], "settlement", road)
        return out(loc["point"], "road", road)
    alley = q.get("alley")
    if lane is not None:
        for n, _ci, _s, lane_line in anchors:
            if n != lane:
                continue
            pts, cum = _chain_xy(lane_line)
            if alley is not None:
                # 在「弄」裡：OpenStreetMap 有那條弄就沿著弄走；沒有就標在弄口（巷子裡第 M 號附近）
                aname = "%s%d巷%d弄" % (road, lane, alley)
                for a_line in _merged(data, aname):
                    a_pts, a_cum = _chain_xy(a_line)
                    s0, _d0 = _project(pts, cum, a_pts[0])
                    s1, _d1 = _project(pts, cum, a_pts[-1])
                    if _d1 < _d0:                   # 從接在巷子上的那一端往裡走
                        a_pts, a_cum = _chain_xy(a_line[::-1])
                    walk = (num or 0) * METERS_PER_NUMBER / 1000.0 if num is not None else min(a_cum[-1] / 2.0, 0.05)
                    return out(_point_at(a_pts, a_cum, walk), "lane", aname)
                return out(_point_at(pts, cum, alley * METERS_PER_NUMBER / 1000.0), "alley_mouth",
                           "%s%d巷%d弄口" % (road, lane, alley))
            if num is not None:
                return out(_point_at(pts, cum, num * METERS_PER_NUMBER / 1000.0), "lane", "%s%d巷" % (road, lane))
            return out(_point_at(pts, cum, min(cum[-1] / 2.0, 0.08)), "lane", "%s%d巷" % (road, lane))
    target = lane if lane is not None else num
    if target is not None and anchors:
        by_chain = {}
        for n, ci, s, _l in anchors:
            by_chain.setdefault(ci, []).append((n, s))

        def score(item):
            # 先挑巷號範圍涵蓋這個門牌的那一段路，其次挑巷號最接近的，再其次挑刻度最多的
            _ci, group = item
            ns = [n for n, _s in group]
            outside = 0 if min(ns) <= target <= max(ns) else min(abs(target - min(ns)), abs(target - max(ns)))
            return (outside, -len(group))
        for ci, group in sorted(by_chain.items(), key=score):
            pts, cum = chains[ci]
            fit = _fit(group)
            if not fit:
                continue
            a, b = fit
            s = a + b * target
            if -0.15 <= s <= cum[-1] + 0.15:        # 推出這段路的範圍太多，就不相信這個推估
                return out(_point_at(pts, cum, s), "lane_mouth" if lane is not None else "interp",
                           "%s%s" % (road, "%d巷口" % lane if lane is not None else ""))
        ci, n0, s0 = min(((ci, n, s) for ci, g in by_chain.items() for n, s in g), key=lambda t: abs(t[1] - target))
        if abs(n0 - target) <= 30:
            pts, cum = chains[ci]
            return out(_point_at(pts, cum, s0), "near_lane", "%s%d巷口" % (road, n0))
    pts, cum = max(chains, key=lambda c: c[1][-1])
    return out(_point_at(pts, cum, cum[-1] / 2.0), "road", road)
