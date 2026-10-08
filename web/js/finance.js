// 房貸試算、交屋前現金、租金行情、買房還是租房（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, esc } from "./main.js";

// ---- 房貸試算：總價預設帶入這一區的中位總價，其他條件記在這台裝置
export const LOAN_DEFAULT = { price: "", down: 20, rate: L.NORMAL_LOAN.rate, years: L.NORMAL_LOAN.years, grace: 0, youth: false };
export function loanState() { return Object.assign({}, LOAN_DEFAULT, S.settings.loan || {}); }
// 依目前的條件試算；選了「新青安」時，超過 1,000 萬的部分用一般房貸的利率與年限另外算
function loanCalc(st, price) {
  if (!price) return null;
  if (st.youth) return L.mortgageCapped(price, +st.down, +st.rate, +st.years, +st.grace, L.YOUTH_LOAN.cap, LOAN_DEFAULT.rate, LOAN_DEFAULT.years);
  return L.mortgage(price, +st.down, +st.rate, +st.years, +st.grace);
}
export function loanResult(median) {
  const st = loanState(), price = +st.price || median;
  const m = loanCalc(st, price);
  if (!m) return `<p class="muted">輸入總價就能試算。</p>`;
  const yuan = v => Math.round(v).toLocaleString("zh-TW");
  let h = `<div class="summary">總價 ${L.fmtNum(price)} 萬：自備款 ${L.fmtNum(Math.round(m.down))} 萬、貸款 ${L.fmtNum(Math.round(m.loan))} 萬` +
    (m.rest ? `（其中 ${L.fmtNum(Math.round(m.rest))} 萬超過新青安上限，以一般房貸 ${LOAN_DEFAULT.rate}%、${LOAN_DEFAULT.years} 年試算）` : "") + `<br>` +
    (m.graceMonthly ? `寬限期每月只繳利息 <b>${yuan(m.graceMonthly)}</b> 元，之後` : "") + `每月約繳 <b>${yuan(m.monthly)}</b> 元<br>` +
    `總利息約 ${L.fmtNum(Math.round(m.totalInterest))} 萬｜月付控制在收入三分之一，家庭月收入約需 ${yuan(m.income)} 元</div>`;
  // 和另一種方案並排：選一般房貸時比新青安，選新青安時比一般房貸
  const y = L.YOUTH_LOAN, other = st.youth ? { ...st, ...LOAN_DEFAULT, price: st.price, down: st.down, youth: false }
    : { ...st, rate: y.rate, years: y.years, grace: y.grace, youth: true };
  const o = loanCalc(other, price);
  if (o) {
    const [a, b] = st.youth ? [o, m] : [m, o], col = (x, k) => x[k] ? yuan(x[k]) : "—";
    const diff = Math.round(b.totalInterest - a.totalInterest);
    h += `<table class="list loan-cmp"><thead><tr><th></th><th class="r">一般房貸<div class="muted">${st.youth ? `${LOAN_DEFAULT.rate}%・${LOAN_DEFAULT.years} 年` : `${+st.rate}%・${+st.years} 年`}</div></th>` +
      `<th class="r">新青安<div class="muted">${st.youth ? `${+st.rate}%・${+st.years} 年` : `${y.rate}%・${y.years} 年`}</div></th></tr></thead><tbody>` +
      `<tr><td>寬限期月付</td><td class="r">${col(a, "graceMonthly")}</td><td class="r">${col(b, "graceMonthly")}</td></tr>` +
      `<tr><td>攤還期月付</td><td class="r">${yuan(a.monthly)}</td><td class="r">${yuan(b.monthly)}</td></tr>` +
      `<tr><td>總利息（萬）</td><td class="r">${L.fmtNum(Math.round(a.totalInterest))}</td><td class="r">${L.fmtNum(Math.round(b.totalInterest))}</td></tr></tbody></table>` +
      `<p class="muted">新青安${diff > 0 ? `年限較長、加上寬限期，總利息反而多約 ${L.fmtNum(diff)} 萬` : `總利息少約 ${L.fmtNum(-diff)} 萬`}；寬限期結束後月付會明顯變高，要先確認那時繳得起。</p>`;
  }
  return h;
}
export function loanSection(median) {
  const st = loanState(), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-loan="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  const preset = (k, label) => `<button type="button" class="btn small${(k === "youth") === !!st.youth ? " primary" : ""}" data-act="loan-preset" data-preset="${k}" aria-pressed="${(k === "youth") === !!st.youth}">${label}</button>`;
  return `<h3>房貸試算</h3><div class="row loan-presets">${preset("normal", "一般房貸")}${preset("youth", "新青安")}</div>` +
    `<div class="loan">${num("price", "總價", 10, "萬", median ? String(Math.round(median)) : "")}${num("down", "自備款", 5, "%")}` +
    `${num("rate", "年利率", 0.05, "%")}${num("years", "年限", 5, "年")}${num("grace", "寬限期", 1, "年")}</div>` +
    `<div id="loan-out">${loanResult(median)}</div><p class="muted">本息平均攤還的估算，總價空白就用這一區的中位總價。新青安：貸款上限 ${L.YOUTH_LOAN.cap} 萬、最長 ${L.YOUTH_LOAN.years} 年、寬限期最長 ${L.YOUTH_LOAN.grace} 年，限名下無自有住宅者，利率會隨央行調整；` +
    `實際利率、成數、寬限期與申請資格以承辦銀行公告為準，這不是貸款建議。</p>`;
}
// ---- 交屋前要準備的現金：自備款＋買方稅費（契稅、印花稅、規費、代書、仲介…）
export const loanPrice = median => +loanState().price || median;
export function costState() { return Object.assign({}, L.COST_DEFAULT, S.settings.cost || {}); }
const wan = v => v >= 100 ? L.fmtNum(v) : v >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/0$/, "");
export function costResult(median) {
  const st = loanState(), price = loanPrice(median), c = price ? L.purchaseCosts(price, +st.down, costState()) : null;
  if (!c) return `<p class="muted">輸入總價就能試算。</p>`;
  const m = loanCalc(st, price);
  const reserve = m ? Math.max(m.monthly, m.graceMonthly || 0) * 6 / 10000 : 0;
  let h = `<table class="list cost"><tbody>` + c.items.filter(([k, , v]) => v > 0 || k === "agent")
    .map(([k, label, v, note]) => `<tr${k === "down" ? ' class="strong"' : ""}><td>${esc(label)}<div class="muted">${esc(note)}</div></td><td class="r">${wan(v)} 萬</td></tr>`).join("") +
    `<tr class="total"><td>合計（交屋前要準備）</td><td class="r">${L.fmtNum(c.total)} 萬</td></tr></tbody></table>`;
  h += `<div class="summary">頭期款以外的稅費與雜支約 <b>${wan(c.fees)} 萬</b>（總價的 ${(c.fees / price * 100).toFixed(1)}%）` +
    (reserve ? `<br>另外建議預留 6 個月房貸約 ${wan(reserve)} 萬，以免收入中斷時繳不出來` : "") + `</div>`;
  if (c.estimated) h += `<p class="muted">房屋評定現值、土地公告現值沒填，暫用總價的 ${L.COST_RATIO.house * 100}%、${L.COST_RATIO.land * 100}% 粗估（新大樓通常更低、老透天的土地比例更高）；實際數字看賣方的房屋稅單、地價稅單，或請代書查。</p>`;
  return h;
}
export function costSection(median) {
  const st = costState(), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-cost="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  const price = loanPrice(median);
  return `<details class="more" data-det="costOpen"${S.settings.costOpen ? " open" : ""}><summary>交屋前要準備多少現金</summary>` +
    `<div class="loan">${num("hv", "房屋現值", 1, "萬", price ? "約 " + Math.round(price * L.COST_RATIO.house) : "")}${num("lv", "土地現值", 1, "萬", price ? "約 " + Math.round(price * L.COST_RATIO.land) : "")}` +
    `${num("agent", "仲介費", 0.5, "%")}${num("reno", "裝潢搬家", 10, "萬")}</div><div id="cost-out">${costResult(median)}</div>` +
    `<p class="muted">總價、自備款比例沿用上面的房貸試算。稅率依現行法規（契稅 6%、印花稅與登記規費 0.1%、抵押權設定規費 0.1%）；房屋稅、地價稅依交屋日分算，不在這裡。這是估算，不是稅務建議。</p></details>`;
}

// ---- 租金行情：實價登錄租賃（近一年），加上毛租金報酬率
export function rentYield(name, cat) {
  const rc = L.rentCell(D.rent, name, cat), su = D.book.best(name, cat, "u").value;
  return rc && rc.n >= 5 ? L.grossYield(rc.unit, su) : null;
}
export function rentSection(name) {
  if (!D.tw) return "";
  const rb = D.rent;
  let h = `<h3>租金行情</h3>`;
  if (!rb) return h + `<p class="muted">這個縣市的租金資料還在準備中（每次自動更新會補上）。</p>`;
  const cell = rb.data[name];
  if (!cell) return h + `<p class="muted">近一年沒有這一區的租賃登錄。</p>`;
  const rows = L.RENT_ROOMS.map(([k, label]) => [label + (k === "s" ? "" : "（整層）"), cell.rooms && cell.rooms[k]])
    .concat([["透天（整棟）", cell.house]]).filter(([, v]) => v && v[0]);
  h += `<table class="list"><thead><tr><th>類型</th><th class="r">件</th><th class="r">月租中位</th><th class="r">每坪月租</th><th class="r">坪數</th></tr></thead><tbody>` +
    rows.map(([k, v]) => `<tr${v[0] < L.RENT_MIN_N ? ' class="low"' : ""}><td>${esc(k)}</td><td class="r">${v[0]}</td><td class="r">${L.fmtNum(v[1])}</td><td class="r">${L.fmtNum(v[2])}</td><td class="r">${v[3] == null ? "—" : v[3].toFixed(0)}</td></tr>`).join("") + `</tbody></table>`;
  const bits = [];
  for (const [cat, label] of [["apt", "大樓／華廈"], ["house", "透天"]]) {
    const y = rentYield(name, cat), rc = L.rentCell(rb, name, cat);
    if (y != null) bits.push(`${label}：每坪月租 ${L.fmtNum(rc.unit)} 元，毛租金報酬率約 <b>${y.toFixed(1)}%</b>`);
  }
  if (cell.chg != null) bits.push(`每坪月租比前一年${cell.chg >= 0 ? "漲" : "跌"} ${Math.abs(cell.chg).toFixed(1)}%`);
  if (bits.length) h += `<div class="summary">${bits.join("<br>")}</div>`;
  h += `<p class="muted">內政部實價登錄租賃資料，${esc(rb.window[0])}～${esc(rb.window[1])}，灰字不到 5 件。租賃登錄多來自代管、包租業者，房東自己出租的登錄較少，行情可能偏高。毛租金報酬率＝每坪月租 × 12 ÷ 每坪中位房價，未扣稅費、空租期與管理維修。</p>`;
  return h;
}

// ---- 買房還是租房：同一間房子，N 年後兩邊的資產
export function rvbState() { return Object.assign({ rent: "" }, L.RVB_DEFAULT, S.settings.rvb || {}); }
export function rvbDefaultRent(name, median) {
  const price = loanPrice(median), y = rentYield(name, S.cat === "house" ? "house" : "apt") ?? rentYield(name, "apt");
  return price && y ? Math.round(price * 10000 * y / 100 / 12 / 100) * 100 : null;
}
function rvbSVG(years) {
  const W = 360, H = 150, l = 44, r = 10, t = 10, b = 22, vals = years.flatMap(p => [p.buy, p.rent]);
  let lo = Math.min(0, ...vals), hi = Math.max(...vals); if (hi <= lo) hi = lo + 1;
  const x = i => l + (W - l - r) * (i + 1) / years.length, y = v => t + (hi - v) / (hi - lo) * (H - t - b);
  let s = `<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="買房與租房的資產比較">`;
  for (const f of [0, 0.5, 1]) { const v = hi - (hi - lo) * f; s += `<line x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}" stroke="#eceff2"/><text x="${l - 5}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#5b6168">${L.fmtNum(v)}</text>`; }
  for (const [k, c] of [["buy", "#e3542c"], ["rent", "#2a78d6"]])
    s += `<polyline fill="none" stroke="${c}" stroke-width="2.2" points="${years.map((p, i) => `${x(i)},${y(p[k])}`).join(" ")}"/>`;
  years.forEach((p, i) => { if ((i + 1) % 5 === 0 || i === 0) s += `<text x="${x(i)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#5b6168">${p.y}年</text>`; });
  return s + `</svg><p class="muted"><span style="color:#e3542c">━</span> 買房的資產　<span style="color:#2a78d6">━</span> 租房的資產（萬）</p>`;
}
export function rvbResult(name, median) {
  const st = loanState(), rv = rvbState(), price = loanPrice(median);
  const rent = +rv.rent || rvbDefaultRent(name, median);
  if (!price) return `<p class="muted">輸入總價就能比較。</p>`;
  if (!rent) return `<p class="muted">這一區沒有足夠的租金資料，請自己填同樣房子的月租。</p>`;
  const c = L.purchaseCosts(price, +st.down, costState());
  const res = L.rentVsBuy({ price, down: +st.down, rate: +st.rate, loanYears: +st.years, grace: +st.grace, rent, cash: c.total,
    years: +rv.years, g: +rv.g, rg: +rv.rg, inv: +rv.inv, hold: +rv.hold, sell: +rv.sell });
  if (!res) return `<p class="muted">條件不完整。</p>`;
  const e = res.end, diff = e.buy - e.rent, yuan = v => Math.round(v).toLocaleString("zh-TW");
  let h = `<div class="summary">一開始兩邊都有 ${L.fmtNum(res.cash0)} 萬現金：買方付頭期與稅費，租方拿去投資。<br>` +
    `每月：房貸 ${yuan(res.monthly)} 元＋持有成本 vs 房租 ${yuan(rent)} 元（每年調 ${rv.rg}%）<br>` +
    `<b>${rv.years} 年後：買房約 ${L.fmtNum(e.buy)} 萬、租房約 ${L.fmtNum(e.rent)} 萬</b>（${diff >= 0 ? "買房多" : "租房多"} ${L.fmtNum(Math.abs(diff))} 萬）<br>` +
    (res.breakeven != null ? `住滿約 <b>${res.breakeven} 年</b>以後，買房開始比租房划算` : `${rv.years} 年內租房都比較划算（假設條件下）`) + `</div>`;
  return h + rvbSVG(res.years);
}
export function rvbSection(name, median) {
  const st = rvbState(), def = rvbDefaultRent(name, median), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-rvb="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  return `<details class="more" data-det="rvbOpen"${S.settings.rvbOpen ? " open" : ""}><summary>買房還是租房比較划算</summary>` +
    `<div class="loan">${num("rent", "月租", 500, "元", def ? String(def) : "")}${num("years", "比較", 1, "年")}${num("g", "房價年漲", 0.5, "%")}` +
    `${num("rg", "租金年漲", 0.5, "%")}${num("inv", "投資報酬", 0.5, "%")}</div><div id="rvb-out">${rvbResult(name, median)}</div>` +
    `<p class="muted">月租空白時用這一區的毛租金報酬率推算同總價房子的租金。房貸條件沿用上面的試算；持有成本（房屋稅、地價稅、管理費、修繕）以每年房價 ${L.RVB_DEFAULT.hold}% 估，賣屋時扣 ${L.RVB_DEFAULT.sell}% 仲介與稅費，未計房地合一稅。結果對「房價年漲」與「投資報酬」很敏感，請多試幾組；這不是投資建議。</p></details>`;
}
// 上班地點選單：依縣市分組，目前看的縣市排最前面

// ---- 賣屋／換屋試算：賣掉現在的房子能拿回多少，接到「交屋前要準備多少現金」，算出換屋要補多少
export function sellState() { return Object.assign({}, L.SELL_DEFAULT, S.settings.sell || {}); }
export function sellResult(median) {
  const st = sellState(), r = L.sellHouse(st);
  if (!r) return `<p class="muted">填入舊房子預計賣多少，就能試算。</p>`;
  const row = (label, v, note, cls) => `<tr${cls ? ` class="${cls}"` : ""}><td>${esc(label)}${note ? `<div class="muted">${esc(note)}</div>` : ""}</td><td class="r">${v}</td></tr>`;
  const w = v => `${v < 0 ? "−" : ""}${wan(Math.abs(v))} 萬`;
  let h = `<table class="list cost"><tbody>` + row("賣價", w(r.sell), "", "strong") +
    row("還清剩餘房貸", "−" + w(r.loan), "", "") +
    row("仲介服務費（賣方）", "−" + w(r.agent), `賣價 ${+st.agent || 0}%（行情約 2～4%，可議價）`) +
    row("代書、塗銷抵押、雜費", "−" + w(r.fees), "") +
    row("房地合一稅（或舊制所得稅）", "−" + w(r.tax), r.rule + (r.taxable != null ? `；課稅所得約 ${wan(r.taxable)} 萬` : "")) +
    row("土地增值稅", r.missingLandTax ? "未填" : "−" + w(r.landTax), "依公告土地現值的漲幅計算；自用住宅（一生一次）稅率 10%，請代書或地方稅務局試算") +
    `<tr class="total"><td>賣掉後實際拿回</td><td class="r">${w(r.net)}</td></tr></tbody></table>`;
  // 換屋：接到交屋前現金
  const lst = loanState(), price = loanPrice(median), c = price ? L.purchaseCosts(price, +lst.down, costState()) : null;
  if (c) {
    const gap = r.net - c.total, refund = st.self ? L.rebuyRefund(r.tax, r.sell, price) : 0;
    h += `<div class="summary">換到總價 ${L.fmtNum(price)} 萬的房子（自備 ${+lst.down}%），交屋前要準備 ${L.fmtNum(c.total)} 萬：<br>` +
      (gap >= 0 ? `賣舊屋拿回的錢付完還<b>多出約 ${wan(gap)} 萬</b>` : `賣舊屋拿回的錢還<b>不夠約 ${wan(-gap)} 萬</b>，要另外準備`) +
      (refund > 0 ? `<br>如果 2 年內重購並自住，房地合一稅可申請「重購退稅」約 ${wan(refund)} 萬（新屋價格低於舊屋時按比例退）` : "") + `</div>`;
  }
  if (r.missingLandTax) h += `<p class="muted">土地增值稅沒填，上面「拿回」的金額會偏高。老房子、土地持分大的透天，土增稅可能是幾十萬以上。</p>`;
  return h;
}
export function sellSection(median) {
  const st = sellState(), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-sell="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  return `<details class="more" data-det="sellOpen"${S.settings.sellOpen ? " open" : ""}><summary>賣屋／換屋試算</summary>` +
    `<p class="muted">要賣掉現在的房子再買這一區的房子嗎？填入舊房子的資料，算出賣掉能拿回多少、換屋要補多少。新房子的總價與自備款沿用上面的房貸試算。</p>` +
    `<div class="loan">${num("sell", "預計賣價", 10, "萬")}${num("buy", "當初買價", 10, "萬")}${num("bought", "買進年份", 1, "西元", "例 2018")}${num("years", "持有", 1, "年")}` +
    `${num("loan", "剩餘房貸", 10, "萬", "0")}${num("agent", "仲介費", 0.5, "%")}${num("landTax", "土增稅", 1, "萬", "請代書試算")}${num("landInc", "土地漲價", 10, "萬", "可空白")}</div>` +
    `<label class="row" style="gap:6px;font-size:14px"><input type="checkbox" data-sell="self"${st.self ? " checked" : ""}> 自住：本人、配偶或未成年子女設籍並住滿 6 年，期間沒有出租或營業</label>` +
    `<div class="loan" id="sell-old"${+st.bought && +st.bought < 2016 ? "" : " hidden"}>${num("oldHouseVal", "房屋現值", 1, "萬", "看房屋稅單")}${num("oldStd", "所得標準", 1, "%")}${num("oldRate", "綜所稅率", 1, "%")}</div>` +
    `<div id="sell-out">${sellResult(median)}</div>` +
    `<p class="muted">房地合一稅 2.0（2021 年 7 月起）：持有 2 年內 45%、2～5 年 35%、5～10 年 20%、超過 10 年 15%；自住滿 6 年 400 萬以下免稅、超過 10%。費用沒有單據時按賣價 3%（最多 30 萬）計。2015 年底前買的適用舊制。這是粗估，實際以國稅局核定為準，不是稅務建議。</p></details>`;
}
