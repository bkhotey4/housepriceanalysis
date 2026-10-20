// 選區小幫手：依使用者自己設定的條件與重要程度，替各區打分並列出加分／扣分理由（計算在 logic.js 的 rankDistricts）。
// 刻意不寫「推薦購買」：只整理公開資料，讓使用者決定要去哪幾區實地看。
import * as L from "./logic.js";
import { D, S, esc, isNation, minsTo, workPlace, modeName } from "./main.js";
import { rentYield } from "./finance.js";

const LEVELS = [[0, "不考慮"], [1, "一般"], [2, "重要"], [3, "很重要"]];
export function fitWeights() { return { ...L.FIT_DEFAULT, ...(S.settings.fitW || {}) }; }

// 各區的數字（沒有資料的是 null）
function fitRows() {
  const cat = S.cat === "presale" ? "all" : S.cat, w = workPlace();
  const code = D.county ? D.county.code : null;
  return D.districts.map(d => {
    const bu = D.book.best(d.name, cat, "u"), bt = D.book.best(d.name, cat, "t"), cell = D.book.cell(d.name, "all");
    if (bu.value == null && bt.value == null) return null;
    // 長期漲幅：5 年的資料不一定夠（要 22 季），依序試 5、4、3 年，評分時換算成「每 5 年」再比
    const ls = D.long ? L.longSeries(D.long, d.name, cat, "u") : [];
    const cl = ls.length ? (L.longChange(ls, 5) || L.longChange(ls, 4) || L.longChange(ls, 3)) : null;
    const p = L.popInfo(D.pop, d.name);
    // 重大建設：縣市裡是這一區中心 3 公里內；全台總覽是整個縣市（影響度 4 以上）
    const proj = (D.intel || []).filter(it => (it.impact_level || 0) >= 4 && it.lat != null &&
      (isNation() ? (it.county || "D") === d.code : (!code || (it.county || "D") === code) && L.distKm(d.lat, d.lng, it.lat, it.lng) <= 3)).length;
    return {
      name: d.name, t: bt.value, u: bu.value, n: cell && cell.y12 ? cell.y12[0] : bu.n,
      tr6: D.book.trend(d.name, cat, "u"), c5: cl ? cl.pct * 5 / cl.years : null, cl,
      pop: p ? p.chgAll : null, popSpan: p ? p.span : null, proj,
      yld: rentYield(d.name, cat === "house" ? "house" : "apt"), mins: w ? minsTo(d.lat, d.lng, w) : null,
    };
  }).filter(Boolean);
}

// 每一區的加分／扣分理由：只挑使用者有勾的條件（超出預算、樣本太少、漲幅過大不管有沒有勾都會提醒）
function reasons(r, weights, budget, all) {
  const pros = [], cons = [], on = k => (+weights[k] || 0) > 0, p = k => r.parts[k];
  const rankOf = (key, asc) => 1 + all.filter(x => x[key] != null && (asc ? x[key] < r[key] : x[key] > r[key])).length;
  const w = workPlace(), sgn = v => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
  if (budget > 0 && r.t != null) (r.t <= budget ? (on("budget") && pros.push(`中位總價 ${L.fmtNum(r.t)} 萬，在預算 ${L.fmtNum(budget)} 萬內`))
    : cons.push(`中位總價 ${L.fmtNum(r.t)} 萬，超過預算 ${L.fmtNum(budget)} 萬`));
  if (on("commute") && r.mins != null && w) {
    const txt = `到${w.name}${modeName()}約 ${r.mins} 分鐘`;
    if (r.mins >= 60 || (p("commute") <= 0.33 && r.mins > 30)) cons.push(txt);
    else if (p("commute") >= 0.66 && r.mins <= 45) pros.push(txt);
  }
  if (on("value") && r.u != null) {
    const k = rankOf("u", true), n = all.filter(x => x.u != null).length, unit = isNation() ? "個縣市" : "區";
    if (p("value") >= 0.66) pros.push(`中位單價 ${r.u.toFixed(1)} 萬/坪，${n} ${unit}裡第 ${k} 低`);
    else if (p("value") <= 0.33) cons.push(`中位單價 ${r.u.toFixed(1)} 萬/坪，${n} ${unit}裡第 ${n - k + 1} 高`);
  }
  const lt = r.cl ? `近 ${r.cl.years} 年 ${sgn(r.cl.pct)}` : "";
  if (r.c5 != null && r.c5 > 40) cons.push(`近 ${r.cl.years} 年單價已漲 ${r.cl.pct.toFixed(0)}%，追高風險較大`);
  else if (on("stable") && p("stable") >= 0.66) pros.push(`價格平穩（${[r.tr6 != null ? `近半年 ${sgn(r.tr6)}` : "", lt].filter(Boolean).join("、") || "近期沒有大漲大跌"}）`);
  else if (on("stable") && r.tr6 != null && Math.abs(r.tr6) >= 8) cons.push(`近半年價格波動大（${sgn(r.tr6)}）`);
  if (on("growth")) {
    if (r.pop != null && r.pop >= 2) pros.push(`近 ${r.popSpan} 年人口 ${sgn(r.pop)}`);
    else if (r.pop != null && r.pop <= -2) cons.push(`近 ${r.popSpan} 年人口 ${sgn(r.pop)}`);
    if (r.proj >= 2) pros.push(`${isNation() ? "縣市內" : "3 公里內"}有 ${r.proj} 項影響度高的重大建設`);
  }
  if (on("yield") && r.yld != null) (p("yield") >= 0.66 ? pros : p("yield") <= 0.33 ? cons : []).push(`毛租金報酬約 ${r.yld.toFixed(1)}%`);
  if (r.lowSample) cons.push(`近一年只有 ${r.n} 筆成交，行情參考性低`);
  else if (on("liquid") && r.n != null && p("liquid") >= 0.66) pros.push(`近一年 ${L.fmtNum(r.n)} 筆成交，好比價也比較好轉手`);
  return { pros: pros.slice(0, 4), cons: cons.slice(0, 4) };
}

// 地圖上色用：各區的「符合我的條件」分數（0～100）；沒有選任何條件時回傳 null
export function fitScores() {
  const weights = fitWeights(), budget = parseFloat(S.settings.budget) || 0, w = workPlace();
  const eff = Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, (k === "budget" && !budget) || (k === "commute" && !w) ? 0 : v]));
  if (!Object.values(eff).some(v => +v > 0) || !D.districts || !D.districts.length) return null;
  return new Map(L.rankDistricts(fitRows(), eff, budget).map(r => [r.name, r.score]));
}
export function tabFit() {
  if (!D.districts || !D.districts.length) return `<p class="empty">資料載入中…</p>`;
  const weights = fitWeights(), budget = parseFloat(S.settings.budget) || 0, w = workPlace();
  const missing = { budget: !budget ? "先在 ☰ → 篩選填總價預算" : "", commute: !w ? "先在「通勤」設上班地點" : "" };
  let h = `<p class="muted">依你重視的條件，把${esc(isNation() ? "各縣市" : L.CITY + "各區")}排出來，並列出加分和扣分的理由。` +
    `這不是購買建議，只是幫你決定先去哪幾區實地看。</p>`;
  h += `<div class="fit-w">` + L.FIT_CRITERIA.map(c => {
    const v = missing[c.key] ? 0 : (+weights[c.key] || 0);
    return `<div class="fit-row"><div><b>${c.label}</b><div class="muted">${missing[c.key] ? esc(missing[c.key]) : c.hint}</div></div>` +
      `<div class="seg" role="radiogroup" aria-label="${c.label}的重要程度">${LEVELS.map(([lv, t]) =>
        `<button type="button" role="radio" data-act="fitw" data-k="${c.key}" data-v="${lv}" aria-checked="${v === lv}"${missing[c.key] ? " disabled" : ""}>${t}</button>`).join("")}</div></div>`;
  }).join("") + `</div>`;
  const eff = Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, missing[k] ? 0 : v]));
  if (!Object.values(eff).some(v => +v > 0)) return h + `<p class="empty">至少選一個條件。</p>`;
  const rows = fitRows(), ranked = L.rankDistricts(rows, eff, budget), shown = S.fitAll ? ranked : ranked.slice(0, 8);
  h += `<h3>排序結果（${L.CAT_LABEL[S.cat === "presale" ? "all" : S.cat]}）</h3>` +
    `<div class="row"><button type="button" class="btn small${S.settings.color === "fit" ? " primary" : ""}" data-act="fit-map" aria-pressed="${S.settings.color === "fit"}">` +
    `${S.settings.color === "fit" ? "✓ 地圖柱子顏色：符合程度" : "🗺️ 在地圖上用顏色標出符合程度"}</button></div>`;
  h += shown.map((r, i) => {
    const { pros, cons } = reasons(r, eff, budget, rows);
    const nums = [r.t != null ? `中位總價 ${L.fmtNum(r.t)} 萬` : "", r.u != null ? `${r.u.toFixed(1)} 萬/坪` : "", r.cl ? `近 ${r.cl.years} 年 ${r.cl.pct >= 0 ? "+" : ""}${r.cl.pct.toFixed(0)}%` : ""].filter(Boolean).join("｜");
    return `<div class="fit-card${r.overBudget ? " dim" : ""}"><div class="fit-head"><span class="fit-rank">${i + 1}</span>` +
      `<a href="#" data-goto="${esc(r.name)}"><b>${esc(r.name)}</b></a><span class="fit-score" title="符合你的條件的程度（0～100）">${r.score}</span></div>` +
      `<div class="fit-bar"><span style="width:${r.score}%"></span></div><div class="muted">${nums}</div>` +
      (pros.length ? `<ul class="fit-pros">${pros.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : "") +
      (cons.length ? `<ul class="fit-cons">${cons.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : "") + `</div>`;
  }).join("");
  if (ranked.length > shown.length) h += `<div class="row"><button type="button" class="btn small" data-act="fit-all">顯示全部 ${ranked.length} 區</button></div>`;
  h += `<p class="muted">分數是「在這些區裡，符合你所選條件的程度」，不是房價會不會漲的預測。資料：內政部實價登錄（中位價、成交件數、近 5 年走勢）、` +
    `戶政司人口統計、整理的重大建設情資（影響度 4 以上；台南整理得最完整，其他縣市的建設數可能偏少）、實價登錄租賃（毛租金報酬）、通勤時間（${w ? "依你設的上班地點" : "沒設上班地點時不算"}）。` +
    `沒有算進去的：屋況、樓層、學區、嫌惡設施、淹水與土壤液化——請看「周邊」與 ☰ 的風險圖層，並一定要實地走一趟。這不構成投資或購屋建議。</p>`;
  return h;
}
