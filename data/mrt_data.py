"""
台南捷運（臺南先進運輸系統）與鐵路立體化資料。

實際內容放在同資料夾的 mrt.json（2026-09-30 依市府捷運工程處、交通部、新聞報導查證，
每條線都附來源）。本檔負責載入並提供與舊版相容的 MRT_LINES / MRT_PHASE2 介面。
所有站位經緯度都是依路口與地標估算，僅供地圖示意，誤差可能達數百公尺。
"""
import json
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(DATA_DIR, "mrt.json"), encoding="utf-8") as _f:
    MRT_META = json.load(_f)


def _txt(v, default="未定"):
    return default if v in (None, "") else str(v)


def _stations(raw):
    out = []
    for s in raw or []:
        if s and s[1] is not None and s[2] is not None:
            out.append((s[0], s[1], s[2]))
    return out


MRT_LINES = {}
for _l in MRT_META["lines"]:
    _st = _stations(_l.get("stations"))
    _segs = []
    for _seg in _l.get("segments") or []:
        _pts = _stations(_seg.get("stations"))
        if len(_pts) >= 2:
            _segs.append({"name": _seg.get("name", ""), "points": [(p[1], p[2]) for p in _pts]})
    if not _segs and len(_st) >= 2:
        _segs = [{"name": "", "points": [(p[1], p[2]) for p in _st]}]
    MRT_LINES[_l["short"]] = {
        "id": _l.get("id", _l["short"]),
        "full_name": _l["name"],
        "color": _l["color"],
        "phase": "第一期路網" if "構想" not in _l["short"] else "構想階段",
        "route": _txt(_l.get("route"), ""),
        "length_km": _l.get("length_km"),
        "stations_count": _l.get("stations_count") or 0,
        "depot": _txt(_l.get("depot"), ""),
        "system": _txt(_l.get("system"), ""),
        "cost": _txt(_l.get("cost"), ""),
        "status": _txt(_l.get("status")),
        "stage": _txt(_l.get("stage")),
        "progress_detail": _txt(_l.get("progress_detail"), ""),
        "feasibility": _txt(_l.get("feasibility"), "未查證"),
        "comprehensive_plan": _txt(_l.get("comprehensive_plan"), "未查證"),
        "eia": _txt(_l.get("eia"), "未查證"),
        "design": _txt(_l.get("design"), "未查證"),
        "construction_start": _txt(_l.get("construction_start")),
        "estimated_completion": _txt(_l.get("estimated_completion")),
        "council_resolution": _txt(_l.get("council_resolution"), "未查證"),
        "stations": _st,
        "segments": _segs,
        "stations_note": _txt(_l.get("stations_note") or _l.get("station_code_note"), ""),
        "sources": _l.get("sources") or [],
        # 只有已核定綜合規劃的路線畫實線，其餘（可行性研究中）畫虛線
        "approved": _txt(_l.get("comprehensive_plan"), "").startswith("已核定"),
    }

RAIL_PROJECTS = [p for p in MRT_META.get("rail_projects", []) if p.get("status") and not str(p["status"]).startswith("未查證")]
MRT_NOTES = MRT_META.get("notes", [])
AS_OF = MRT_META.get("as_of", "")

# 舊版的「二期路網」清單：官方 2026 年進度表已不再列出，保留空字典以維持相容。
MRT_PHASE2 = {}


def export_mrt_geojson():
    features = []
    for line_name, d in MRT_LINES.items():
        for seg in d["segments"]:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lng, lat] for lat, lng in seg["points"]]},
                "properties": {"type": "mrt_line", "name": line_name, "color": d["color"], "status": d["status"],
                               "stage": d["stage"], "completion": d["estimated_completion"]},
            })
        for name, lat, lng in d["stations"]:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {"type": "mrt_station", "name": name, "line": line_name},
            })
    return {"type": "FeatureCollection", "features": features}


if __name__ == "__main__":
    geojson = export_mrt_geojson()
    with open(os.path.join(DATA_DIR, "tainan_geojson.json"), "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    print("GeoJSON exported: %d features" % len(geojson["features"]))
