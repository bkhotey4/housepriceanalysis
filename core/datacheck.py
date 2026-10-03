"""檢查 data/intel.json 與 data/mrt.json 的格式。

手動或排程更新這兩個檔案後執行：

    python tools/check_data.py

每個檢查函式回傳「問題清單」（字串），空清單代表格式正確。只檢查格式與合理範圍，
不檢查內容是否屬實——內容的正確性要靠每一筆所附的來源連結。
"""
import math
import re

from .taiwan import BY_CODE
from . import geo

INTEL_TYPES = ["商辦", "商場", "科學園區", "產業園區", "重劃區", "公共建設", "交通建設", "住宅開發",
               "議會", "開發商", "市況"]
CONFIDENCE = ["高", "中", "低"]
# 台南市範圍（略放寬）
SOUTH, NORTH, WEST, EAST = 22.85, 23.45, 120.0, 120.70
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _in_tainan(lat, lng):
    return SOUTH <= lat <= NORTH and WEST <= lng <= EAST


# 各縣市座標合理範圍：離縣市中心的公里數（離島、花東、南投範圍大）
_COUNTY_KM = {"U": 120, "V": 130, "M": 75, "F": 60, "G": 55, "E": 75, "T": 95, "Q": 60, "B": 60, "J": 50, "K": 50,
              "H": 45, "N": 45, "P": 50, "A": 18, "C": 15, "O": 15, "I": 10, "X": 50, "W": 25, "Z": 65}


def _in_county(lat, lng, code):
    if code == "D":
        return _in_tainan(lat, lng)
    c = BY_CODE.get(code)
    if not c:
        return False
    dx = (lng - c["lng"]) * 111.32 * math.cos(math.radians(lat))
    dy = (lat - c["lat"]) * 110.57
    return math.hypot(dx, dy) <= _COUNTY_KM.get(code, 60)


def _check_sources(sources, where, out, required=True):
    if not isinstance(sources, list) or (required and not sources):
        out.append("%s：sources 必須是至少有一筆的清單" % where)
        return
    for k, s in enumerate(sources):
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            out.append("%s：第 %d 筆來源缺少 title" % (where, k + 1))
            continue
        if not re.match(r"^https?://\S+$", str(s.get("url") or "")):
            out.append("%s：第 %d 筆來源的 url 不是網址" % (where, k + 1))
        if s.get("date") not in (None, "", "未載明") and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(s["date"])):
            out.append("%s：第 %d 筆來源的 date 應為 YYYY-MM-DD 或「未載明」" % (where, k + 1))


def check_intel(d, min_items=40):
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return ["intel.json：最外層必須是 {\"as_of\": ..., \"items\": [...]}"]
    if not _DATE.match(str(d.get("as_of") or "")):
        out.append("intel.json：as_of 應為 YYYY-MM-DD")
    items = d["items"]
    if len(items) < min_items:
        out.append("intel.json：只有 %d 筆，少於下限 %d 筆（可能誤刪）" % (len(items), min_items))
    districts = set(x["name"] for x in geo.load_districts())
    seen = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            out.append("intel 第 %d 筆：不是物件" % (i + 1))
            continue
        name = str(it.get("name") or "").strip()
        where = "intel「%s」" % (name[:24] or "第 %d 筆" % (i + 1))
        if not name:
            out.append("%s：缺少 name" % where)
        elif name in seen:
            out.append("%s：名稱重複" % where)
        seen.add(name)
        if it.get("type") not in INTEL_TYPES:
            out.append("%s：type「%s」不在允許的類型內" % (where, it.get("type")))
        if not isinstance(it.get("district"), str):
            out.append("%s：district 必須是字串（不確定時用空字串）" % where)
        elif it.get("county", "D") not in BY_CODE:
            out.append("%s：county「%s」不是縣市代碼" % (where, it.get("county")))
        elif it.get("county", "D") == "D" and it["district"] and not any(n in it["district"] for n in districts) \
                and "台南" not in it["district"] and "全市" not in it["district"] and "臺南" not in it["district"]:
            out.append("%s：district「%s」不是台南的行政區" % (where, it["district"]))
        if not isinstance(it.get("status"), str) or not it["status"].strip():
            out.append("%s：缺少 status" % where)
        lat, lng = it.get("lat"), it.get("lng")
        if (lat is None) != (lng is None):
            out.append("%s：lat、lng 必須同時有值或同時為 null" % where)
        elif lat is not None and not (_is_num(lat) and _is_num(lng) and _in_county(lat, lng, it.get("county", "D"))):
            out.append("%s：座標 (%s, %s) 不在%s範圍內" % (where, lat, lng, BY_CODE.get(it.get("county", "D"), {}).get("short", "台灣")))
        lvl = it.get("impact_level")
        if lvl is not None and not (isinstance(lvl, int) and not isinstance(lvl, bool) and 1 <= lvl <= 5):
            out.append("%s：impact_level 應為 1~5 的整數或 null" % where)
        if it.get("confidence") not in CONFIDENCE:
            out.append("%s：confidence 應為 高／中／低" % where)
        if it.get("change_pct") is not None and not _is_num(it["change_pct"]):
            out.append("%s：change_pct 應為數字或 null" % where)
        for key in ("timeline", "developer", "scale", "impact"):
            if it.get(key) is not None and not isinstance(it[key], str):
                out.append("%s：%s 應為文字或 null" % (where, key))
        _check_sources(it.get("sources"), where, out)
        if it.get("build") is not None:
            _check_build(it["build"], it, where, out)
    return out


BUILD_PHASES = ("完工", "施工中", "規劃中")


def _check_build(b, it, where, out):
    """重大建設的 build 欄位：{model, phase, start, done, note}，地圖上畫成 3D 小圖。"""
    from . import landmarks
    if not isinstance(b, dict):
        out.append("%s：build 應為物件" % where)
        return
    if it.get("lat") is None:
        out.append("%s：有 build 就要有座標（地圖上要畫 3D 圖案）" % where)
    if b.get("model") not in landmarks.MODELS:
        out.append("%s：build.model「%s」不是已知的圖案" % (where, b.get("model")))
    if b.get("phase") not in BUILD_PHASES:
        out.append("%s：build.phase 應為 完工／施工中／規劃中" % where)
    for key in ("start", "done"):
        v = b.get(key)
        if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and 1950 <= v <= 2060):
            out.append("%s：build.%s 應為西元年（整數）或 null" % (where, key))
    if b.get("start") and b.get("done") and b["start"] > b["done"]:
        out.append("%s：build.start 晚於 build.done" % where)
    if not isinstance(b.get("note"), str) or not b["note"].strip():
        out.append("%s：build.note 要寫時程的依據（例如「2028 年竣工（報導）」）" % where)


def _check_stations(stations, where, out):
    n = 0
    if not isinstance(stations, list):
        out.append("%s：stations 必須是清單" % where)
        return 0
    for s in stations:
        if not (isinstance(s, list) and len(s) == 3 and isinstance(s[0], str)):
            out.append("%s：車站格式應為 [名稱, 緯度, 經度]" % where)
            continue
        if s[1] is None and s[2] is None:
            continue
        if not (_is_num(s[1]) and _is_num(s[2]) and _in_tainan(s[1], s[2])):
            out.append("%s：車站「%s」座標不在台南範圍內" % (where, s[0]))
        else:
            n += 1
    return n


def check_mrt(d, min_lines=5):
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("lines"), list):
        return ["mrt.json：最外層必須有 lines 清單"]
    if not _DATE.match(str(d.get("as_of") or "")):
        out.append("mrt.json：as_of 應為 YYYY-MM-DD")
    if len(d["lines"]) < min_lines:
        out.append("mrt.json：只有 %d 條路線，少於下限 %d 條（可能誤刪）" % (len(d["lines"]), min_lines))
    shorts = set()
    for i, ln in enumerate(d["lines"]):
        if not isinstance(ln, dict):
            out.append("mrt 第 %d 條路線：不是物件" % (i + 1))
            continue
        where = "mrt「%s」" % (ln.get("short") or ln.get("name") or "第 %d 條" % (i + 1))
        for key in ("id", "name", "short", "status"):
            if not isinstance(ln.get(key), str) or not ln[key].strip():
                out.append("%s：缺少 %s" % (where, key))
        if ln.get("short") in shorts:
            out.append("%s：short 重複" % where)
        shorts.add(ln.get("short"))
        if not _COLOR.match(str(ln.get("color") or "")):
            out.append("%s：color 應為 #RRGGBB" % where)
        if ln.get("length_km") is not None and not _is_num(ln["length_km"]):
            out.append("%s：length_km 應為數字或 null" % where)
        if ln.get("stations_count") is not None and not isinstance(ln["stations_count"], int):
            out.append("%s：stations_count 應為整數或 null" % where)
        _check_stations(ln.get("stations") or [], where, out)
        segs = ln.get("segments") or []
        if not isinstance(segs, list):
            out.append("%s：segments 必須是清單或 null" % where)
            segs = []
        for seg in segs:
            if not isinstance(seg, dict):
                out.append("%s：segments 的每一段必須是物件" % where)
            else:
                _check_stations(seg.get("stations") or [], where + " 的分段", out)
        _check_sources(ln.get("sources"), where, out)
    rails = d.get("rail_projects", [])
    if not isinstance(rails, list):
        out.append("mrt.json：rail_projects 必須是清單")
        rails = []
    for i, p in enumerate(rails):
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            out.append("鐵路計畫第 %d 筆：缺少 name" % (i + 1))
            continue
        where = "鐵路「%s」" % p["name"][:20]
        for st in p.get("new_stations") or []:
            if not isinstance(st, dict) or not st.get("name"):
                out.append("%s：new_stations 的每一站必須是有 name 的物件" % where)
            elif st.get("lat") is not None and not (_is_num(st["lat"]) and _is_num(st.get("lng")) and _in_tainan(st["lat"], st["lng"])):
                out.append("%s：車站「%s」座標不在台南範圍內" % (where, st["name"]))
        _check_sources(p.get("sources"), where, out, required=False)
    if not isinstance(d.get("notes", []), list):
        out.append("mrt.json：notes 必須是清單")
    return out


def check_all():
    """檢查目前 data/ 裡的兩個檔案，回傳問題清單。"""
    out = []
    for name, fn in (("intel.json", check_intel), ("mrt.json", check_mrt)):
        try:
            d = geo.load_json(name)
        except (OSError, ValueError) as e:
            out.append("%s：讀取失敗（%s）" % (name, e))
            continue
        out.extend(fn(d))
    return out
