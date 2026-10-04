// 行情報告：產生一頁可以直接列印／存成 PDF 的 HTML（給房仲拿給客戶看，或自己存檔）。全部在裝置上產生，不上傳任何資料。
import * as L from "./logic.js";

const NEAR_KM = 5, MAX_TX = 30;
const e = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 0) => v == null ? "—" : d ? v.toFixed(d) : L.fmtNum(v);

function trendSvg(series, width = 640, height = 180) {
  const pts = series.map((p, i) => ({ ...p, i })), vals = pts.filter(p => p.v != null).map(p => p.v);
  if (vals.length < 2) return "<p class='muted'>成交太少，畫不出走勢。</p>";
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.15 || 1; lo -= pad; hi += pad;
  const nmax = Math.max(1, ...pts.map(p => p.n)), left = 46, right = 26, top = 12, bottom = 40;
  const w = width - left - right, h = height - top - bottom, step = w / Math.max(1, pts.length - 1);
  const x = i => left + i * step, y = v => top + (hi - v) / (hi - lo) * h * 0.72;
  let s = `<svg viewBox='0 0 ${width} ${height}' width='100%' role='img' aria-label='每月中位單價走勢'>`;
  for (const p of pts) { const bh = p.n / nmax * h * 0.22; s += `<rect x='${(x(p.i) - step * 0.3).toFixed(1)}' y='${(top + h - bh).toFixed(1)}' width='${(step * 0.6).toFixed(1)}' height='${bh.toFixed(1)}' fill='${p.partial ? "#d9dde2" : "#b9c0c8"}'/>`; }
  for (const f of [0, 0.5, 1]) { const v = hi - (hi - lo) * f, yy = y(v); s += `<line x1='${left}' x2='${width - right}' y1='${yy.toFixed(1)}' y2='${yy.toFixed(1)}' stroke='#e6e9ec'/><text x='${left - 6}' y='${(yy + 4).toFixed(1)}' font-size='11' text-anchor='end' fill='#5b6168'>${v.toFixed(1)}</text>`; }
  const line = pts.filter(p => p.v != null && !p.partial).map(p => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`);
  if (line.length >= 2) s += `<polyline fill='none' stroke='#2a78d6' stroke-width='2.5' points='${line.join(" ")}'/>`;
  for (const p of pts) if (p.v != null) s += `<circle cx='${x(p.i).toFixed(1)}' cy='${y(p.v).toFixed(1)}' r='3.5' fill='${p.partial ? "#fff" : "#2a78d6"}' stroke='#2a78d6'/>`;
  pts.forEach(p => { if (p.i % 2 === 0 || p.i === pts.length - 1) s += `<text x='${x(p.i).toFixed(1)}' y='${height - 22}' font-size='11' text-anchor='middle' fill='#5b6168'>${e(p.m.slice(2).replace("-", "/"))}</text>`; });
  return s + `<text x='${left}' y='${height - 4}' font-size='11' fill='#5b6168'>線：每月中位單價（萬/坪），空心點是資料還沒到齊的月份；灰色長條：每月件數</text></svg>`;
}

// ctx: { book, txs, intel, district, cat, q, point:[lat,lng], agent:{name,phone,client,note}, work:{name,lat,lng}, mode, poi, meta }
export function buildReport(ctx) {
  const { book, txs, intel, district, cat, q, point, work, poi } = ctx, agent = ctx.agent || {};
  const today = new Date(), ymd = today.toISOString().slice(0, 10), year = today.getFullYear();
  const bu = book.best(district, cat, "u"), bt = book.best(district, cat, "t"), tr = book.trend(district, cat, "u");
  const title = q && q.road ? `${district} ${L.describe(q)}` : district;
  const p = [];
  p.push(`<header><div><h1>${e(title)} 房價行情報告</h1><p class='muted'>${e(L.CAT_LABEL[cat])}｜${e(ctx.meta?.describe || "")}｜製作日期 ${ymd}</p></div>`);
  const who = [agent.name, agent.phone].filter(Boolean);
  if (who.length || agent.client) p.push(`<div class='agent'>${who.length ? `<b>${e(who.join(" "))}</b><br>` : ""}${agent.client ? "給 " + e(agent.client) : ""}</div>`);
  p.push("</header>");
  const kpi = (k, v, u, n = "") => `<div class='kpi'><div class='k'>${e(k)}</div><div class='v'>${e(v)}<small> ${e(u)}</small></div><div class='n'>${e(n)}</div></div>`;
  const win = bu.window === "h6" ? "近半年" : bu.window === "y12" ? "近一年" : "";
  const gap = book.presaleGap(district);
  p.push("<section class='kpis'>" +
    kpi(`${district} 中位單價`, num(bu.value, 1), "萬/坪", `${win} ${bu.n} 件${bu.low ? "，樣本少" : ""}`) +
    kpi("中位總價", num(bt.value), "萬", win) +
    kpi("近半年起伏", tr == null ? "—" : `${tr >= 0 ? "+" : ""}${tr.toFixed(1)}%`, "", tr == null ? "樣本不足" : "後 3 個月對前 3 個月") +
    kpi("預售比中古大樓", gap == null ? "—" : `${gap >= 0 ? "+" : ""}${gap.toFixed(0)}%`, "", "單價差距") + "</section>");
  if (cat === "house" || cat === "all") p.push("<p class='muted'>透天厝的單價含土地，跟大樓單價不能直接比，看透天請以總價為主。</p>");

  const rows = (txs || []).filter(x => x.dist === district && L.inCat(x, cat));
  let ranked = null;
  if (q && q.road && rows.length) {
    ranked = L.rankByAddress(rows.filter(x => x.road === q.road), q);
    const st = L.addressSummary(ranked);
    p.push(`<h2>${e(L.describe(q))} 附近的成交</h2><table class='mini'><tr><th></th><th>件數</th><th>中位單價（萬/坪）</th><th>中位總價（萬）</th></tr>`);
    for (const [label, key] of [["同門牌（同一棟）", "exact"], ["同一條巷", "lane"], ["整條路", "road"]]) {
      if (key === "exact" && q.num == null) continue;
      if (key === "lane" && q.lane == null) continue;
      const g = st[key]; p.push(`<tr><td>${label}</td><td>${g.n}</td><td>${num(g.u, 1)}</td><td>${num(g.t)}</td></tr>`);
    }
    p.push("</table>");
  }
  p.push(`<h2>${e(district)} 每月行情</h2>` + trendSvg(book.series(district, cat, "u")));
  if (rows.length) {
    const listing = ranked ? ranked.map(r => r.x).slice(0, MAX_TX) : [...rows].sort((a, b) => a.date < b.date ? 1 : -1).slice(0, MAX_TX);
    p.push(`<h2>${ranked ? "這條路的成交（依門牌遠近）" : e(district) + " 最近的成交"}</h2><table><tr><th>日期</th><th>類型</th><th>地址／建案</th><th class='r'>總價（萬）</th><th class='r'>單價（萬/坪）</th><th class='r'>建坪</th><th class='r'>屋齡</th></tr>`);
    for (const x of listing) {
      const age = x.built ? Math.max(0, +x.date.slice(0, 4) - x.built) : "";
      const where = x.proj ? `${x.proj}（${x.addr.slice(0, 16)}）` : x.addr;
      p.push(`<tr><td>${e(x.date)}</td><td>${e(x.btype)}</td><td>${e(where)}</td><td class='r'>${num(x.tw)}</td><td class='r'>${x.u.toFixed(1)}</td><td class='r'>${x.ping.toFixed(1)}</td><td class='r'>${age}</td></tr>`);
    }
    p.push(`</table><p class='muted'>已排除親友、持分、急買急賣等特殊交易。共 ${ranked ? ranked.length : rows.length} 筆，列出 ${listing.length} 筆。</p>`);
  }
  const [lat, lng] = point || [null, null];
  const near = (intel || []).filter(it => it.build && it.lat != null).map(it => ({ it, d: lat != null ? L.distKm(lat, lng, it.lat, it.lng) : null }))
    .filter(r => (r.d != null && r.d <= NEAR_KM) || ((r.it.county || "D") === (ctx.county || "D") && (r.it.district || "").includes(district)))
    .sort((a, b) => (a.d ?? 1e9) - (b.d ?? 1e9)).slice(0, 12);
  p.push("<h2>附近的重大建設</h2>");
  if (near.length) {
    p.push("<table><tr><th>建設</th><th class='r'>距離</th><th>現況</th><th>預計完工</th><th>時程依據</th></tr>");
    for (const { it, d } of near) p.push(`<tr><td>${e(it.name)}</td><td class='r'>${d != null ? d.toFixed(1) + " 公里" : "同區"}</td><td>${e(L.buildState(it.build, year))}</td><td>${e(it.build.done || "未定")}</td><td class='muted'>${e(it.build.note)}</td></tr>`);
    p.push("</table><p class='muted'>時程依報導與官方說法整理，常會延後；距離為直線距離。</p>");
  } else p.push(`<p class='muted'>${NEAR_KM} 公里內沒有收錄的重大建設。</p>`);
  if (work && lat != null) {
    const km = L.distKm(lat, lng, work.lat, work.lng), mode = L.MODES[ctx.mode] || L.MODES.car;
    p.push(`<h2>到上班地點</h2><p>${e(work.name)}：${mode[0]}約 ${L.commuteMin(km, ctx.mode)} 分鐘（直線 ${km.toFixed(1)} 公里，估計；尖峰可能多 3～5 成）</p>`);
  }
  if (poi && poi.res) {
    p.push("<h2>周邊生活機能與嫌惡設施</h2><table><tr><th>項目</th><th class='r'>範圍內</th><th>最近</th></tr>");
    for (const c of L.POI_CATS) {
      const b = poi.res.byCat[c.key], r = c.r >= 1000 ? (c.r / 1000).toFixed(1) + " 公里" : c.r + " 公尺";
      p.push(`<tr><td>${c.group === "bad" ? "⚠ " : ""}${e(c.label)}</td><td class='r'>${r}內 ${b.n}</td><td>${b.nearest ? e(b.nearest.name) + "，" + b.nearest.d + " 公尺" : "—"}</td></tr>`);
    }
    p.push("</table><p class='muted'>周邊資料來自 OpenStreetMap，可能有缺漏，請以實地查看為準。</p>");
  }
  if (agent.note) p.push(`<h2>備註</h2><p>${e(agent.note).replace(/\n/g, "<br>")}</p>`);
  p.push("<footer>資料來源：內政部不動產交易實價查詢服務網開放資料；重大建設整理自新聞與官方公告；周邊設施 © OpenStreetMap 貢獻者。統計值為中位數，僅供參考，不構成投資或購屋建議。<br>程式與設計 © 全台房價即時動態分析，保留所有權利。 bkhotey4.github.io/housepriceanalysis</footer>");
  return PAGE.replace("%TITLE%", e(title + " 房價行情報告")).replace("%BODY%", p.join("\n"));
}

const PAGE = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
  body { font-family: system-ui, -apple-system, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif; color: #1f2328; background: #fff;
         max-width: 820px; margin: 24px auto; padding: 0 16px; line-height: 1.55; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; border-bottom: 3px solid #0b5d57; padding-bottom: 8px; }
  h1 { font-size: 24px; margin: 0; color: #0b5d57; }
  h2 { font-size: 17px; margin: 22px 0 6px; border-left: 4px solid #0b5d57; padding-left: 8px; }
  .muted { color: #5b6168; font-size: 13px; } .agent { text-align: right; font-size: 14px; }
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; }
  .kpi { border: 1px solid #d9dde2; border-radius: 6px; padding: 8px 10px; }
  .kpi .k { font-size: 12px; color: #5b6168; } .kpi .v { font-size: 22px; font-weight: bold; }
  .kpi small { font-size: 12px; font-weight: normal; color: #5b6168; } .kpi .n { font-size: 11px; color: #5b6168; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { border-bottom: 1px solid #e3e6ea; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f3f5f7; } .r { text-align: right; white-space: nowrap; } table.mini { width: auto; }
  footer { margin-top: 26px; font-size: 12px; color: #5b6168; border-top: 1px solid #d9dde2; padding-top: 8px; }
  .bar { text-align: right; margin-bottom: 8px; } .print { padding: 6px 12px; font-size: 14px; }
  @media (max-width: 640px) { .kpis { grid-template-columns: repeat(2, 1fr); } header { flex-direction: column; } .agent { text-align: left; } }
  @media print { .bar { display: none; } body { margin: 0; } h2 { break-after: avoid; } tr { break-inside: avoid; } }
</style></head>
<body><div class="bar"><button class="print" onclick="window.print()">列印／存成 PDF</button></div>
%BODY%
</body></html>`;
