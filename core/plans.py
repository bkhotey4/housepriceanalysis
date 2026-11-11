"""規劃中的公共建設：從政府電子採購網的公告（開放資料鏡像 pcc-api.openfun.app）找出大型建設的早期訊號。

機關要蓋大型建設，通常好幾年前就會先發包「可行性評估」「先期規劃」「綜合規劃」「環境影響評估」這類委託案，
接著是「規劃設計」「新建工程（統包）」「促參招商」。這些公告比新聞早，也比建照早很多。

每天的公告清單：/api/listbydate?date=YYYYMMDD → {"records": [{date, brief: {type, title, category}, unit_id, unit_name, job_number, tender_api_url}, …]}
單一標案的細節：/api/tender?unit_id=…&job_number=… → {"records": [{date, brief, detail: {"採購資料:預算金額": "2,000,000元", "其他:履約地點（含地區）": "新北市－八里區", …}}, …]}
"""
import re

from .taiwan import COUNTIES, norm

API = "https://pcc-api.openfun.app/api/"
SITE = "https://pcc-api.openfun.app"

# 要看的公告種類：招標（最早）、公開閱覽、徵求參考資料（促參常用）、決標（確定有人接）
TYPES = {"公開招標公告", "經公開評選或公開徵求之限制性招標公告", "公開徵求廠商提供參考資料公告",
         "招標文件公開閱覽公告資料公告", "決標公告"}
# 階段（名稱裡有這些字才算），順序＝顯示的階段名稱
STAGES = [
    ("可行性評估", re.compile("可行性(評估|研究)|可行性及|先期(規劃|作業)|整體(規劃|開發)|開發計畫|綜合規劃|都市計畫(變更|擬定|通盤)")),
    ("環評", re.compile("環境影響(評估|說明書)|環評")),
    ("招商", re.compile("促參|招商|民間參與|地上權")),
    ("規劃設計", re.compile("規劃設計|基本設計|細部設計|設計及監造|委託設計")),
    ("新建工程", re.compile("新建工程|興建工程|統包|闢建工程|開闢工程|建設工程")),
]
# 建設的種類（名稱裡要有其一，才不會收到一般設備、活動）
THING = re.compile("捷運|輕軌|鐵路|車站|高鐵|園區|快速道路|快速公路|道路|聯絡道|交流道|橋|轉運|停車場|運動中心|體育館|運動園區|"
                   "圖書館|美術館|博物館|藝術中心|文化中心|醫院|長照|社會住宅|公共住宅|焚化|垃圾|掩埋|污水|水資源|再生水|市場|"
                   "公園|綠園道|重劃|區段徵收|都市計畫|行政中心|行政大樓|會展|商場|產業|工業區|機場|港|國民小學|國中|高中|大學|校舍|"
                   "變電|電廠|淨水|滯洪|堤防")
# 不收：維護修繕、變更設計、小型設施
EXCLUDE = re.compile("變更設計|契約變更|第.次變更|維護|維修|修繕|整修|修建|改善|改建工程|保養|租賃|清潔|監造(?!.*新建)|補強|耐震|設備|"
                     "勘驗|測量|鑽探|檢測|拆除|代辦|管理|宣導|活動|舖面|鋪面|人行道|公廁|廁所|路燈|號誌|標線|植栽|綠美化|景觀優化|"
                     "遮雨棚|停車棚|風雨球場|圍牆|候車亭|監測|指標系統|標示|招牌|污染防治|燈節|燈會|節慶|展演活動|碳足跡|盤查|"
                     "教育訓練|研習|宣傳")
# 預算門檻（萬元）：委託規劃、環評等勞務 100 萬以上；工程 5,000 萬以上
MIN_SERVICE_WAN, MIN_WORKS_WAN = 100, 5000

_CODE = {norm(c["name"]): c["code"] for c in COUNTIES}
_COUNTY_RE = re.compile("(%s)" % "|".join(sorted({norm(c["name"]) for c in COUNTIES} | {c["name"] for c in COUNTIES}, key=len, reverse=True)))


def stage_of(title):
    for name, rx in STAGES:
        if rx.search(title):
            return name
    return None


def candidate(rec):
    """每日清單的一筆 → 值得查細節嗎（只看公告種類與標案名稱）"""
    b = rec.get("brief") or {}
    t = b.get("title") or ""
    return b.get("type") in TYPES and bool(stage_of(t)) and bool(THING.search(t)) and not EXCLUDE.search(t)


def money_wan(s):
    """'2,442,042元' → 244.2（萬元）；沒有數字回傳 None"""
    m = re.search(r"[\d,]+", s or "")
    if not m or not m.group(0).replace(",", ""):
        return None
    return round(int(m.group(0).replace(",", "")) / 1e4, 1)


def _field(detail, *names):
    for k, v in detail.items():
        if any(k.endswith(n) for n in names) and v:
            return v
    return ""


def place(detail, unit_name, title, towns):
    """→ (縣市代碼, 行政區)；縣市看履約地點，沒有就看機關名稱、標案名稱；行政區看「履約地點（含地區）」或名稱裡的區名"""
    loc = _field(detail, "履約地點（含地區）", "履約地點")
    code = None
    for text in (loc, unit_name, title):
        m = _COUNTY_RE.search(norm(text or ""))
        if m:
            code = _CODE.get(norm(m.group(1)))
            break
    if not code:
        return None, ""
    dist = ""
    m = re.search("－(.+?[區鄉鎮市])", loc or "")
    if m and m.group(1) in towns.get(code, []):
        dist = m.group(1)
    else:
        dist = town_in(title, towns.get(code, []))
    return code, dist


def town_in(title, names):
    """名稱裡提到的鄉鎮市區：先找全名，再找去掉「區鄉鎮市」的簡稱（後面接路、街的不算，例如「中正路」不是中正區）。
    「東區」「北區」這種兩個字的太容易誤判，名稱裡不認。"""
    names = sorted((t for t in names if len(t) >= 3), key=len, reverse=True)
    for t in names:
        if t in title:
            return t
    for t in names:
        if re.search(re.escape(t[:-1]) + "(?![路街巷道])", title):
            return t
    return ""


def item_from(rec, tender, towns):
    """每日清單的一筆＋標案細節 → 網站用的一筆；不夠大或找不到縣市就回傳 None"""
    b = rec["brief"]
    detail = {}
    for r in (tender or {}).get("records", []):          # 同一案的公告由舊到新，後面的覆蓋前面的
        detail.update(r.get("detail") or {})
    title = b.get("title", "")
    budget = money_wan(_field(detail, "預算金額"))
    award = money_wan(_field(detail, "總決標金額"))
    works = (b.get("category") or _field(detail, "標的分類")).startswith("工程")
    amount = award or budget
    if amount is None or amount < (MIN_WORKS_WAN if works else MIN_SERVICE_WAN):
        return None
    code, dist = place(detail, rec.get("unit_name") or "", title, towns)
    if not code:
        return None
    winner = _field(detail, "得標廠商1:得標廠商", "投標廠商1:廠商名稱") if b.get("type") == "決標公告" else ""
    return {
        "key": "%s|%s" % (rec.get("unit_id"), re.sub(r"-\d+$", "", rec.get("job_number") or "")),
        "title": title, "unit": rec.get("unit_name") or "", "county": code, "district": dist,
        "stage": stage_of(title), "works": works, "status": "已決標" if b.get("type") == "決標公告" else "招標中",
        "first": str(rec["date"]), "last": str(rec["date"]), "budget_wan": budget, "award_wan": award, "winner": winner,
        "url": SITE + rec["url"] if rec.get("url", "").startswith("/") else rec.get("url", ""),
    }


def merge(items, new):
    """同一案（機關＋案號，去掉 -1 之類的重新招標尾碼）只留一筆：保留最早看到的日期，其他用最新的公告"""
    by = {it["key"]: it for it in items}
    for it in new:
        old = by.get(it["key"])
        if old:
            newer = it["last"] >= old["last"]
            m = dict(old)
            if newer:
                m.update({k: v for k, v in it.items() if v not in (None, "")})
            m["first"], m["last"] = min(old["first"], it["first"]), max(old["last"], it["last"])
            if "已決標" in (old["status"], it["status"]) and old["last"] == it["last"]:
                m["status"] = "已決標"
            it = m
        by[it["key"]] = it
    return sorted(by.values(), key=lambda x: x["last"], reverse=True)
