"""行情報告：選一個行政區（或搜尋的地址），產生一頁可以直接列印成 PDF 的 HTML 報告。

給房仲拿給客戶看，或自己存檔比較用。內容全部來自程式裡已有的資料：
實價登錄統計與逐筆成交、重大建設時程、上班地點距離；不連網、不需要額外套件。
"""
import datetime
import html
import os

from . import address, landmarks, prices
from .geo import BASE_DIR, dist_km

REPORT_DIR = os.path.join(BASE_DIR, "reports")
NEAR_KM = 5.0          # 列出幾公里內的重大建設
MAX_TX = 30            # 報告裡最多列幾筆成交


def _e(text):
    return html.escape("" if text is None else str(text))


def _num(v, digits=0):
    if v is None:
        return "—"
    return ("{:,.%df}" % digits).format(v)


def _trend_svg(series, width=640, height=180):
    """每月中位單價的折線圖＋件數長條（inline SVG，列印也清楚）。"""
    pts = [(i, v, n, partial) for i, (_m, v, n, partial) in enumerate(series)]
    vals = [v for _i, v, _n, _p in pts if v is not None]
    if len(vals) < 2:
        return "<p class='muted'>這一區近一年的成交太少，畫不出走勢。</p>"
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1.0
    lo, hi = lo - pad, hi + pad
    nmax = max(n for _i, _v, n, _p in pts) or 1
    left, right, top, bottom = 46, 26, 12, 40
    w, h = width - left - right, height - top - bottom
    step = w / max(1, len(pts) - 1)

    def x(i):
        return left + i * step

    def y(v):
        return top + (hi - v) / (hi - lo) * h * 0.72
    out = ["<svg viewBox='0 0 %d %d' width='100%%' role='img' aria-label='每月中位單價走勢'>" % (width, height)]
    for i, _v, n, partial in pts:
        bh = n / nmax * h * 0.22
        out.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'/>" % (
            x(i) - step * 0.3, top + h - bh, step * 0.6, bh, "#d9dde2" if partial else "#b9c0c8"))
    for frac in (0.0, 0.5, 1.0):
        v = hi - (hi - lo) * frac
        yy = y(v)
        out.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#e6e9ec'/>" % (left, width - right, yy, yy))
        out.append("<text x='%d' y='%.1f' font-size='11' text-anchor='end' fill='#5b6168'>%.1f</text>" % (left - 6, yy + 4, v))
    line = [(x(i), y(v)) for i, v, _n, partial in pts if v is not None and not partial]
    if len(line) >= 2:
        out.append("<polyline fill='none' stroke='#2a78d6' stroke-width='2.5' points='%s'/>" %
                   " ".join("%.1f,%.1f" % p for p in line))
    for i, v, _n, partial in pts:
        if v is not None:
            out.append("<circle cx='%.1f' cy='%.1f' r='3.5' fill='%s' stroke='#2a78d6'/>" % (
                x(i), y(v), "#ffffff" if partial else "#2a78d6"))
    for i, (m, _v, _n, _p) in enumerate(series):
        if i % 2 == 0 or i == len(series) - 1:
            out.append("<text x='%.1f' y='%d' font-size='11' text-anchor='middle' fill='#5b6168'>%s</text>" % (
                x(i), height - 22, _e(m[2:].replace("-", "/"))))
    out.append("<text x='%d' y='%d' font-size='11' fill='#5b6168'>線：每月中位單價（萬/坪），空心點是資料還沒到齊的月份；灰色長條：每月件數</text>" % (
        left, height - 4))
    out.append("</svg>")
    return "".join(out)


def nearby_projects(intel, lat, lng, district, year, km=NEAR_KM):
    """附近（或同一區）的重大建設：[(距離公里或 None, 項目, 該年狀態)]，近的在前。"""
    out = []
    for it in intel:
        b = it.get("build")
        if not b or it.get("lat") is None:
            continue
        d = dist_km(lat, lng, it["lat"], it["lng"]) if lat is not None else None
        same = district and district in (it.get("district") or "")
        if (d is not None and d <= km) or same:
            out.append((d, it, landmarks.build_state(b, year)))
    out.sort(key=lambda r: (r[0] is None, r[0] or 0, -(r[1].get("impact_level") or 0)))
    return out


def build(book, txs, intel, district, cat, q=None, point=None, agent=None, works=None, today=None):
    """產生報告 HTML。

    district：行政區名稱；cat：房型（prices.CATS 的鍵）；q：address.parse() 的結果（搜尋地址時才有）；
    point：(lat, lng) 報告的中心點（地址圖釘或行政區中心）；agent：{"name", "phone", "client", "note"}；
    works：[(名稱, 距離公里)] 到上班地點的距離。
    """
    today = today or datetime.date.today()
    agent = agent or {}
    cat_label = prices.CAT_LABEL.get(cat, cat)
    bu, bt = book.best(district, cat, "u"), book.best(district, cat, "t")
    tr = book.trend(district, cat, "u")
    title = district if not (q and q.get("road")) else "%s %s" % (district, address.describe(q))
    parts = []
    parts.append("<header><div><h1>%s 房價行情報告</h1><p class='muted'>%s｜%s｜製作日期 %s</p></div>" % (
        _e(title), _e(cat_label), _e(book.describe_source()), today.isoformat()))
    who = [x for x in (agent.get("name"), agent.get("phone")) if x]
    if who or agent.get("client"):
        parts.append("<div class='agent'>%s%s</div>" % (
            ("<b>%s</b><br>" % _e(" ".join(who))) if who else "",
            ("給 %s" % _e(agent["client"])) if agent.get("client") else ""))
    parts.append("</header>")

    # ---- 重點數字
    def kpi(label, value, unit, note=""):
        return "<div class='kpi'><div class='k'>%s</div><div class='v'>%s<small> %s</small></div><div class='n'>%s</div></div>" % (
            _e(label), _e(value), _e(unit), _e(note))
    win = {"h6": "近半年", "y12": "近一年"}.get(bu["window"], "")
    parts.append("<section class='kpis'>")
    parts.append(kpi("%s 中位單價" % district, _num(bu["value"], 1), "萬/坪", "%s %d 件%s" % (win, bu["n"], "，樣本少" if bu["low"] else "")))
    parts.append(kpi("中位總價", _num(bt["value"]), "萬", win))
    parts.append(kpi("近半年起伏", ("%+.1f%%" % tr) if tr is not None else "—", "", "後 3 個月對前 3 個月" if tr is not None else "樣本不足"))
    gap = book.presale_gap(district)
    parts.append(kpi("預售比中古大樓", ("%+.0f%%" % gap) if gap is not None else "—", "", "單價差距"))
    parts.append("</section>")
    if cat == "house" or cat == "all":
        parts.append("<p class='muted'>透天厝的單價含土地，跟大樓單價不能直接比，看透天請以總價為主。</p>")

    # ---- 地址：同門牌／同巷／整條路
    rows = []
    if txs:
        rows = [x for x in txs if x["dist"] == district and prices.in_cat(x, cat)]
    ranked = None
    if q and q.get("road") and rows:
        on_road = [x for x in rows if prices.road_of(x["addr"], district) == q["road"]]
        ranked = address.rank(on_road, q)
        st = address.summary(ranked)
        parts.append("<h2>%s 附近的成交</h2><table class='mini'><tr><th></th><th>件數</th><th>中位單價（萬/坪）</th><th>中位總價（萬）</th></tr>" %
                     _e(address.describe(q)))
        for label, key in (("同門牌（同一棟）", "exact"), ("同一條巷", "lane"), ("整條路", "road")):
            g = st[key]
            if key == "exact" and q.get("num") is None:
                continue
            if key == "lane" and q.get("lane") is None:
                continue
            parts.append("<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (
                label, g["n"], _num(g["u"], 1), _num(g["t"])))
        parts.append("</table>")

    # ---- 走勢
    parts.append("<h2>%s 每月行情</h2>" % _e(district))
    parts.append(_trend_svg(book.series(district, cat, "u")))

    # ---- 成交明細
    if rows:
        if ranked is not None:
            listing = [x for _lv, x in ranked][:MAX_TX]
            head = "這條路的成交（依門牌遠近）"
        else:
            listing = sorted(rows, key=lambda x: x["date"], reverse=True)[:MAX_TX]
            head = "%s 最近的成交" % district
        parts.append("<h2>%s</h2><table><tr><th>日期</th><th>類型</th><th>地址／建案</th><th class='r'>總價（萬）</th>"
                     "<th class='r'>單價（萬/坪）</th><th class='r'>建坪</th><th class='r'>屋齡</th></tr>" % _e(head))
        for x in listing:
            age = "" if not x.get("built") else str(max(0, int(x["date"][:4]) - x["built"]))
            where = address.normalize(x["addr"])
            if x.get("proj"):
                where = "%s（%s）" % (x["proj"], where[:16])
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='r'>%s</td><td class='r'>%.1f</td><td class='r'>%.1f</td><td class='r'>%s</td></tr>" % (
                _e(x["date"]), _e(x.get("btype")), _e(where), _num(x["tw"]), x["u"], x["ping"], _e(age)))
        parts.append("</table><p class='muted'>已排除親友、持分、急買急賣等特殊交易。共 %d 筆，列出 %d 筆。</p>" % (
            len(rows) if ranked is None else len(ranked), len(listing)))
    else:
        parts.append("<p class='muted'>沒有逐筆成交資料（在 App 按「更新實價登錄」下載後，報告會列出逐筆成交）。</p>")

    # ---- 重大建設
    lat, lng = point if point else (None, None)
    near = nearby_projects(intel, lat, lng, district, today.year)
    parts.append("<h2>附近的重大建設</h2>")
    if near:
        parts.append("<table><tr><th>建設</th><th class='r'>距離</th><th>現況</th><th>預計完工</th><th>時程依據</th></tr>")
        for d, it, state in near[:12]:
            b = it["build"]
            parts.append("<tr><td>%s</td><td class='r'>%s</td><td>%s</td><td>%s</td><td class='muted'>%s</td></tr>" % (
                _e(it["name"]), ("%.1f 公里" % d) if d is not None else "同區", _e(state),
                _e(b.get("done") or "未定"), _e(b.get("note"))))
        parts.append("</table><p class='muted'>時程依報導與官方說法整理，常會延後；距離為直線距離。</p>")
    else:
        parts.append("<p class='muted'>%.0f 公里內沒有收錄的重大建設。</p>" % NEAR_KM)

    # ---- 通勤
    if works:
        parts.append("<h2>到上班地點</h2><ul>")
        for name, km in works:
            parts.append("<li>%s：約 %.1f 公里（直線）</li>" % (_e(name), km))
        parts.append("</ul>")

    if agent.get("note"):
        parts.append("<h2>備註</h2><p>%s</p>" % _e(agent["note"]).replace("\n", "<br>"))
    parts.append("<footer>資料來源：內政部不動產交易實價查詢服務網開放資料（由 deep_tainan_house 整理）；"
                 "重大建設整理自新聞與官方公告。統計值為中位數，僅供參考，不構成投資或購屋建議。</footer>")
    return PAGE % {"title": _e(title + " 房價行情報告"), "body": "\n".join(parts)}


def save(html_text, title, today=None):
    """存到 reports/ 資料夾，回傳檔案路徑。"""
    today = today or datetime.date.today()
    os.makedirs(REPORT_DIR, exist_ok=True)
    safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|').replace(" ", "")[:40] or "report"
    path = os.path.join(REPORT_DIR, "%s_%s.html" % (today.strftime("%Y%m%d"), safe))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return path


PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
  body { font-family: "Microsoft JhengHei", "Noto Sans TC", "PingFang TC", sans-serif; color: #1f2328; background: #fff;
         max-width: 820px; margin: 24px auto; padding: 0 16px; line-height: 1.55; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px;
           border-bottom: 3px solid #0b5d57; padding-bottom: 8px; }
  h1 { font-size: 24px; margin: 0; color: #0b5d57; }
  h2 { font-size: 17px; margin: 22px 0 6px; border-left: 4px solid #0b5d57; padding-left: 8px; }
  .muted { color: #5b6168; font-size: 13px; }
  .agent { text-align: right; font-size: 14px; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; }
  .kpi { border: 1px solid #d9dde2; border-radius: 6px; padding: 8px 10px; }
  .kpi .k { font-size: 12px; color: #5b6168; } .kpi .v { font-size: 22px; font-weight: bold; }
  .kpi small { font-size: 12px; font-weight: normal; color: #5b6168; } .kpi .n { font-size: 11px; color: #5b6168; }
  table { width: 100%%; border-collapse: collapse; font-size: 13px; }
  th, td { border-bottom: 1px solid #e3e6ea; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f3f5f7; } .r { text-align: right; white-space: nowrap; }
  table.mini { width: auto; } footer { margin-top: 26px; font-size: 12px; color: #5b6168; border-top: 1px solid #d9dde2; padding-top: 8px; }
  .bar { text-align: right; margin-bottom: 8px; } .print { padding: 6px 12px; font-size: 14px; }
  @media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
  @media print { .bar { display: none; } body { margin: 0; } h2 { break-after: avoid; } tr { break-inside: avoid; } }
</style></head>
<body><div class="bar"><button class="print" onclick="window.print()">列印／存成 PDF</button></div>
%(body)s
</body></html>
"""
