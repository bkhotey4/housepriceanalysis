"""檢查 data/intel.json 與 data/mrt.json 的格式。

手動或排程更新這兩個檔案後執行：

    python tools/check_data.py

每個檢查函式回傳「問題清單」（字串），空清單代表格式正確。只檢查格式與合理範圍，
不檢查內容是否屬實——內容的正確性要靠每一筆所附的來源連結。
"""
import math
import os
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
        if it.get("checked") is not None and not _DATE.match(str(it["checked"])):
            out.append("%s：checked（這一項的查證日）應為 YYYY-MM-DD" % where)
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


def check_loan(d):
    """data/loan.json：房貸試算用的參考利率與新青安條件（網頁啟動時載入，數字不合理的欄位網頁會改用預設）。"""
    out = []
    if not isinstance(d, dict):
        return ["loan.json：最外層必須是物件"]
    if not _DATE.match(str(d.get("checked") or "")):
        out.append("loan.json：checked（查證日）應為 YYYY-MM-DD")
    rules = {"normal": {"rate": (0, 15), "years": (1, 50)},
             "youth": {"rate": (0, 15), "years": (1, 50), "grace": (0, 10), "cap": (1, 100000)}}
    for part, fields in rules.items():
        sec = d.get(part)
        if not isinstance(sec, dict):
            out.append("loan.json：缺少 %s" % part)
            continue
        for k, (lo, hi) in fields.items():
            if not (_is_num(sec.get(k)) and lo <= sec[k] <= hi):
                out.append("loan.json：%s.%s 應為 %s～%s 的數字" % (part, k, lo, hi))
    y = d.get("youth") or {}
    if isinstance(y, dict) and not _DATE.match(str(y.get("until") or "")):
        out.append("loan.json：youth.until（申請期限）應為 YYYY-MM-DD")
    # 選填：新青安房價上限 {縣市代碼或 default: 萬}、央行信用管制 {second_ltv, second_grace, third_ltv, checked, source, note}
    pc = y.get("price_cap") if isinstance(y, dict) else None
    if pc is not None:
        if not isinstance(pc, dict) or not all((k == "default" or k in _COUNTY_KM or len(k) == 1) and _is_num(v) and 100 <= v <= 100000 for k, v in pc.items()):
            out.append("loan.json：youth.price_cap 應為 {縣市代碼或 default: 100～100000 的萬元}")
    cr = d.get("credit")
    if cr is not None:
        if not isinstance(cr, dict) or not (_is_num(cr.get("second_ltv")) and 0 <= cr["second_ltv"] <= 100):
            out.append("loan.json：credit.second_ltv（第二戶最高貸款成數 %）應為 0～100")
        elif cr.get("third_ltv") is not None and not (_is_num(cr["third_ltv"]) and 0 <= cr["third_ltv"] <= 100):
            out.append("loan.json：credit.third_ltv 應為 0～100")
        elif not _DATE.match(str(cr.get("checked") or "")):
            out.append("loan.json：credit.checked（查證日）應為 YYYY-MM-DD")
    return out


def check_schools(d):
    """data/schools.json：明星學區（地圖上的 🎓）。"""
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return ["schools.json：應為 {as_of, items: [...]}"]
    ids = set()
    for i, s in enumerate(d["items"]):
        tag = "schools.json 第 %d 筆（%s）" % (i + 1, s.get("name", "?") if isinstance(s, dict) else "?")
        if not isinstance(s, dict):
            out.append(tag + "：應為物件")
            continue
        for k in ("id", "name", "type", "county", "district", "status"):
            if not s.get(k):
                out.append(tag + "：缺少 %s" % k)
        if s.get("id") in ids:
            out.append(tag + "：id 重複")
        ids.add(s.get("id"))
        if not (_is_num(s.get("lat")) and _is_num(s.get("lng")) and 21.5 < s["lat"] < 26.5 and 118 < s["lng"] < 122.5):
            out.append(tag + "：座標不在台灣")
        if s.get("checked") and not _DATE.match(str(s["checked"])):
            out.append(tag + "：checked 應為 YYYY-MM-DD")
        for src in s.get("sources") or []:
            if not (isinstance(src, dict) and str(src.get("url", "")).startswith("http")):
                out.append(tag + "：sources 每筆要有 url")
    return out


def check_workplaces(d):
    """data/workplaces.json：上班地點選單（科學園區、工業區、大型醫院等）。"""
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("places"), list):
        return ["workplaces.json：應為 {places: [...]}"]
    names = set()
    for i, p in enumerate(d["places"]):
        tag = "workplaces.json 第 %d 筆（%s）" % (i + 1, p.get("name", "?") if isinstance(p, dict) else "?")
        if not isinstance(p, dict) or not p.get("name"):
            out.append(tag + "：缺少 name")
            continue
        if (p["name"], p.get("county")) in names:
            out.append(tag + "：名稱重複")
        names.add((p["name"], p.get("county")))
        if not (_is_num(p.get("lat")) and _is_num(p.get("lng")) and 21.5 < p["lat"] < 26.5 and 118 < p["lng"] < 122.5):
            out.append(tag + "：座標不在台灣")
    if d.get("as_of") and not _DATE.match(str(d["as_of"])):
        out.append("workplaces.json：as_of 應為 YYYY-MM-DD")
    return out


LAND_DEALS = ["購地", "合建", "都更", "標售得標", "地上權", "其他"]
LAND_STATUS = ["取得土地", "規劃中", "申請建照", "已取得建照", "已開工", "預售中", "完工", "取消"]


def check_landbank(d):
    """data/landbank.json：建商、開發商取得土地的公開紀錄（可以是空清單）。"""
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return ["landbank.json：最外層必須是 {\"as_of\": ..., \"items\": [...]}"]
    if d.get("as_of") is not None and not _DATE.match(str(d["as_of"])):
        out.append("landbank.json：as_of 應為 YYYY-MM-DD 或 null")
    seen = set()
    for i, it in enumerate(d["items"]):
        if not isinstance(it, dict):
            out.append("landbank 第 %d 筆：必須是物件" % (i + 1))
            continue
        dev, loc = str(it.get("developer") or "").strip(), str(it.get("location") or "").strip()
        where = "landbank「%s %s」" % (dev[:12] or "第 %d 筆" % (i + 1), loc[:16])
        if not dev:
            out.append("%s：缺少 developer（建商名稱）" % where)
        if not loc:
            out.append("%s：缺少 location（地段或路名）" % where)
        key = (dev, it.get("county"), loc)
        if key in seen:
            out.append("%s：重複（同一建商、縣市、地點）" % where)
        seen.add(key)
        if it.get("county") not in BY_CODE:
            out.append("%s：county 不是縣市代碼" % where)
        if it.get("deal") not in LAND_DEALS:
            out.append("%s：deal 只能是 %s" % (where, "／".join(LAND_DEALS)))
        if it.get("status") not in LAND_STATUS:
            out.append("%s：status 只能是 %s" % (where, "／".join(LAND_STATUS)))
        if not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(it.get("date") or "")):
            out.append("%s：date（取得日期）應為 YYYY-MM-DD、YYYY-MM 或 YYYY" % where)
        for k, hi in (("area_ping", 1e6), ("amount_wan", 1e8)):
            v = it.get(k)
            if v is not None and not (_is_num(v) and 0 < v <= hi):
                out.append("%s：%s 應為正數或 null" % (where, k))
        lat, lng = it.get("lat"), it.get("lng")
        if (lat is None) != (lng is None):
            out.append("%s：lat、lng 要一起填或一起是 null" % where)
        elif lat is not None and not (_is_num(lat) and _is_num(lng) and _in_county(lat, lng, it.get("county"))):
            out.append("%s：座標 (%s, %s) 不在該縣市範圍內" % (where, lat, lng))
        if it.get("confidence") not in CONFIDENCE:
            out.append("%s：confidence 只能是 高／中／低" % where)
        _check_sources(it.get("sources"), where, out)
    return out


OPEN_CATS = ["餐飲", "超市量販", "百貨商場", "零售", "影城娛樂", "醫療", "其他"]
OPEN_STAGES = ["傳聞", "已確認", "申請建照", "已取得建照", "施工中", "徵才中", "已開幕", "取消"]


def check_openings(d):
    """data/openings.json：即將開幕的連鎖店與大型商場（新聞、徵才、建照等公開線索；可以是空清單）。"""
    out = []
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return ["openings.json：最外層必須是 {\"as_of\": ..., \"items\": [...]}"]
    if d.get("as_of") is not None and not _DATE.match(str(d["as_of"])):
        out.append("openings.json：as_of 應為 YYYY-MM-DD 或 null")
    seen = set()
    for i, it in enumerate(d["items"]):
        if not isinstance(it, dict):
            out.append("openings 第 %d 筆：必須是物件" % (i + 1))
            continue
        name = str(it.get("name") or "").strip()
        where = "openings「%s」" % (name[:20] or "第 %d 筆" % (i + 1))
        if not name:
            out.append("%s：缺少 name（店名，例如「壽司郎 南科店」）" % where)
        if not str(it.get("brand") or "").strip():
            out.append("%s：缺少 brand（品牌）" % where)
        key = (name, it.get("county"))
        if key in seen:
            out.append("%s：重複（同一店名、縣市）" % where)
        seen.add(key)
        if it.get("county") not in BY_CODE:
            out.append("%s：county 不是縣市代碼" % where)
        if it.get("category") not in OPEN_CATS:
            out.append("%s：category 只能是 %s" % (where, "／".join(OPEN_CATS)))
        if it.get("stage") not in OPEN_STAGES:
            out.append("%s：stage 只能是 %s" % (where, "／".join(OPEN_STAGES)))
        if it.get("expected") and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", str(it["expected"])):
            out.append("%s：expected（預計開幕）應為 YYYY-MM-DD、YYYY-MM、YYYY 或空字串" % where)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(it.get("updated") or "")):
            out.append("%s：updated（最後查證日）應為 YYYY-MM-DD" % where)
        pm = it.get("permit")
        if pm is not None and not (isinstance(pm, dict) and pm.get("no") and pm.get("date")):
            out.append("%s：permit 應為 {no, date, owner, use} 或省略" % where)
        lat, lng = it.get("lat"), it.get("lng")
        if (lat is None) != (lng is None):
            out.append("%s：lat、lng 要一起填或一起是 null" % where)
        elif lat is not None and not (_is_num(lat) and _is_num(lng) and _in_county(lat, lng, it.get("county"))):
            out.append("%s：座標 (%s, %s) 不在該縣市範圍內" % (where, lat, lng))
        if it.get("confidence") not in CONFIDENCE:
            out.append("%s：confidence 只能是 高／中／低" % where)
        _check_sources(it.get("sources"), where, out)
    return out


def check_all():
    """檢查目前 data/ 裡的情資、捷運、房貸參考條件，回傳問題清單。"""
    out = []
    for name, fn in (("intel.json", check_intel), ("mrt.json", check_mrt), ("loan.json", check_loan), ("landbank.json", check_landbank),
                     ("openings.json", check_openings), ("schools.json", check_schools), ("workplaces.json", check_workplaces)):
        try:
            d = geo.load_json(name)
        except (OSError, ValueError) as e:
            out.append("%s：讀取失敗（%s）" % (name, e))
            continue
        out.extend(fn(d))
    return out


def check_tw_output(tw_dir, prev_report=None, today=None):
    """全台網頁資料（tools/export_tw.py 產生）的合理性檢查：回傳提醒文字的 list（不擋部署，但會寫進更新紀錄並開 Issue）。

    - 實價登錄資料日期太舊（下載可能一直失敗）、「資料到齊」月份落後太多
    - 和上一次更新相比：有資料的縣市變少、某縣市成交筆數掉超過 15%
    - 有資料的縣市少了租金、土地檔"""
    import datetime
    import json
    import re
    today = today or datetime.date.today()
    out = []
    try:
        with open(os.path.join(tw_dir, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return ["全台網頁資料的 index.json 讀不到"]
    try:
        age = (today - datetime.date.fromisoformat(str(idx.get("as_of", ""))[:10])).days
        if age > 20:
            out.append("實價登錄資料日期是 %s，已經 %d 天沒有新資料（內政部大約每 10 天發布一次，下載可能一直失敗）" % (idx["as_of"], age))
    except ValueError:
        out.append("全台網頁資料沒有資料日期（as_of）")
    ct = idx.get("complete_through") or ""
    if re.match(r"^\d{4}-\d{2}$", ct):
        lag = (today.year - int(ct[:4])) * 12 + today.month - int(ct[5:])
        if lag > 4:
            out.append("房價統計到 %s，比現在落後 %d 個月（正常約 2～3 個月）" % (ct, lag))
    counts = {c["code"]: c.get("tx_count", 0) for c in idx.get("counties", []) if c.get("has_data")}
    for c in idx.get("counties", []):
        if not c.get("has_data"):
            continue
        for f in ("rent.json", "land.json"):
            if not os.path.exists(os.path.join(tw_dir, c["code"], f)):
                out.append("%s 沒有 %s" % (c.get("short", c["code"]), f))
    prev = None
    if prev_report and os.path.exists(prev_report):
        with open(prev_report, encoding="utf-8") as f:
            m = re.search(r"^- 資料：(\{.*\})\s*$", f.read(), re.M)
        if m:
            try:
                prev = json.loads(m.group(1))
            except ValueError:
                prev = None
    if prev:
        if prev.get("counties_with_data") and len(counts) < prev["counties_with_data"]:
            out.append("有資料的縣市從 %d 個變成 %d 個" % (prev["counties_with_data"], len(counts)))
        names = {c["code"]: c.get("short", c["code"]) for c in idx.get("counties", [])}
        for code, n0 in (prev.get("counts") or {}).items():
            n1 = counts.get(code, 0)
            if n0 >= 200 and n1 < n0 * 0.85:
                out.append("%s 的成交筆數從 %d 掉到 %d（少了 %.0f%%）" % (names.get(code, code), n0, n1, (1 - n1 / n0) * 100))
    return out
