// 土地分頁：建商買地的線索。兩種資料——
//  1. 大面積純土地成交（實價登錄，data/tw/<代碼>/land.json）：看得到哪一區、哪一段有大筆土地成交，看不到買方是誰。
//  2. 建商購地紀錄（data/landbank.json）：上市櫃建商重大訊息、標售得標、營造廠承攬合約與新聞整理，有建商名稱與來源。
import * as L from "./logic.js";
import { D, S, esc, isNation, needCounty, renderPanel } from "./main.js";

const LAND_CACHE = new Map(), BC_CACHE = new Map();
// 進到縣市時呼叫：背景下載那個縣市的 land.json 與 buildcase.json（預售屋建案報備），下載好時如果正在看土地分頁就重畫
export function loadLand(code) {
  D.land = LAND_CACHE.get(code) || null;
  D.buildcase = BC_CACHE.get(code) || null;
  if (!code) return;
  for (const [cache, file, key] of [[LAND_CACHE, "land", "land"], [BC_CACHE, "buildcase", "buildcase"]]) {
    if (cache.has(code)) continue;
    cache.set(code, null);
    fetch(`data/tw/${code}/${file}.json`).then(r => r.ok ? r.json() : null).then(lb => {
      cache.set(code, lb);
      if (D.county && D.county.code === code) { D[key] = lb; if (S.tab === "land") renderPanel(); }
    }).catch(() => cache.delete(code));          // 網路斷掉：下次進來再試，不要一直顯示「還沒產生」
  }
}

// 篩選：預設只看住宅區、商業區（蓋房子最相關）；可以切換成含工業區或全部
const FILTERS = [["rc", "住宅＋商業區", z => z === "R" || z === "C"], ["rci", "含工業區", z => z === "R" || z === "C" || z === "I"], ["all", "全部（含農地）", () => true]];
const zoneOk = z => (FILTERS.find(f => f[0] === (S.landf || "rc")) || FILTERS[0])[2](z);
const wan = v => v >= 10000 ? `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)} 億` : `${L.fmtNum(Math.round(v))} 萬`;

export function landClick(t) {
  const b = t.closest("[data-act='landf']");
  if (!b) return false;
  S.landf = b.dataset.v; renderPanel();
  return true;
}

// 建商購地紀錄：目前範圍內的（全台首頁＝全部；縣市＝那個縣市；區＝那一區）
function bankItems() {
  const items = (D.landbank && D.landbank.items) || [];
  const code = D.county ? D.county.code : (D.tw ? null : "D");
  return items.filter(it => (!code || it.county === code) && (!code || S.current === L.CITY || (it.district || "").includes(S.current)))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}
function bankSection() {
  const items = bankItems(), lb = D.landbank || {};
  let h = `<h3>建商購地紀錄</h3>`;
  if (!items.length) {
    return h + `<p class="empty">${(lb.items || []).length ? "這個範圍目前沒有收錄的建商購地紀錄。" : "建商購地紀錄還在整理中（每週更新時從公開資訊觀測站重大訊息、土地標售結果、營造廠承攬合約與新聞補進來）。"}</p>`;
  }
  h += `<table class="list"><thead><tr><th>日期</th><th>建商／地點</th><th class="r">面積</th><th class="r">金額</th></tr></thead><tbody>`;
  for (const it of items.slice(0, 80)) {
    const src = (it.sources || [])[0];
    const sub = [it.district, it.location, it.deal, it.status, it.plan].filter(Boolean).join("｜");
    h += `<tr><td>${esc(String(it.date || "").slice(0, 7))}</td><td><b>${esc(it.developer)}</b>${it.contractor ? `<span class="muted">（營造：${esc(it.contractor)}）</span>` : ""}${it.architect ? `<span class="muted">（設計：${esc(it.architect)}）</span>` : ""}` +
      `<div class="muted">${esc(sub)}${src ? `｜<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.title.slice(0, 18))}</a>` : ""}</div></td>` +
      `<td class="r">${it.area_ping ? L.fmtNum(Math.round(it.area_ping)) + " 坪" : "—"}</td><td class="r">${it.amount_wan ? wan(it.amount_wan) : "—"}</td></tr>`;
  }
  h += `</tbody></table>`;
  if (lb.as_of) h += `<p class="muted">整理到 ${esc(lb.as_of)}。只收公開資料（上市櫃公司重大訊息、政府標售公告、新聞報導）；未上市的建商買地多半不會公開，但發包給上市櫃營造廠時，營造廠的承攬公告常會帶出案子。</p>`;
  return h;
}

function dealsSection() {
  const lb = D.land;
  if (!lb) return `<h3>大面積土地成交</h3><p class="empty">${D.county ? "這個縣市的土地成交資料還沒產生（下次資料更新後就會有）。" : ""}</p>`;
  const rows = lb.rows.filter(r => zoneOk(r[7])), atCity = S.current === L.CITY;
  const seg = `<div class="row"><div class="seg">${FILTERS.map(([k, t]) => `<button data-act="landf" data-v="${k}" aria-checked="${(S.landf || "rc") === k}">${t}</button>`).join("")}</div></div>`;
  let h = `<h3>大面積土地成交</h3>${seg}`;
  const note = `<p class="muted">實價登錄「只買土地」的成交（${L.fmtNum(lb.min_ping)} 坪、${L.fmtNum(lb.min_wan)} 萬以上，${esc(lb.since)}～${esc(lb.through)}，已排除親友、持分等特殊交易）。` +
    `實價登錄不公開買方，位置也只到段、地號；同一區短時間內有多筆住宅區或商業區的大筆土地成交，常是建商在買地、整合土地，一兩年後可能推出新建案。這只是線索，不構成投資或購屋建議。</p>`;
  if (atCity) {
    const by = new Map();
    for (const r of rows) {
      const name = lb.dists[r[0]], s = by.get(name) || { n12: 0, n: 0, ping: 0, tw: 0 };
      s.n++; s.ping += r[4]; s.tw += r[5]; if (r[1].slice(0, 7) >= lb.since12) s.n12++;
      by.set(name, s);
    }
    const list = [...by.entries()].sort((a, b) => b[1].ping - a[1].ping);
    if (!list.length) return h + `<p class="empty">近兩年沒有符合條件的大筆土地成交。</p>` + note;
    h += `<table class="list"><thead><tr><th>區</th><th class="r">近一年</th><th class="r">兩年筆數</th><th class="r">兩年坪數</th><th class="r">兩年總價</th></tr></thead><tbody>`;
    for (const [name, s] of list) h += `<tr class="click" data-dist="${esc(name)}"><td>${esc(name)}</td><td class="r">${s.n12}</td><td class="r">${s.n}</td><td class="r">${L.fmtNum(Math.round(s.ping))}</td><td class="r">${wan(s.tw)}</td></tr>`;
    return h + `</tbody></table><p class="muted">依兩年成交坪數排序，點一區看每一筆。</p>` + note;
  }
  const mine = rows.filter(r => lb.dists[r[0]] === S.current);
  if (!mine.length) return h + `<p class="empty">${esc(S.current)}近兩年沒有符合條件的大筆土地成交。</p>` + note;
  // 同一段的成交擺在一起看：一段裡多筆成交，比較像是在整合土地
  const secN = new Map(); for (const r of mine) secN.set(r[2], (secN.get(r[2]) || 0) + 1);
  h += `<p class="muted">${esc(S.current)}近兩年 ${mine.length} 筆，總面積約 ${L.fmtNum(Math.round(mine.reduce((s, r) => s + r[4], 0)))} 坪、總價約 ${wan(mine.reduce((s, r) => s + r[5], 0))}。</p>`;
  h += `<table class="list"><thead><tr><th>日期</th><th>地段</th><th class="r">坪數</th><th class="r">總價</th><th class="r">萬/坪</th></tr></thead><tbody>`;
  for (const r of mine.slice(0, 200)) {
    const many = secN.get(r[2]) >= 3 ? ` <span class="pill">同段 ${secN.get(r[2])} 筆</span>` : "";
    h += `<tr><td>${esc(r[1])}</td><td>${esc(r[2])}${r[3] ? " " + esc(r[3]) + " 地號" : ""}${many}<div class="muted">${esc(r[8] || lb.zones[r[7]] || "")}${r[9] > 1 ? `｜${r[9]} 筆土地` : ""}</div></td>` +
      `<td class="r">${L.fmtNum(Math.round(r[4]))}</td><td class="r">${wan(r[5])}</td><td class="r">${r[6].toFixed(1)}</td></tr>`;
  }
  return h + `</tbody></table>` + note;
}

// 預售屋建案報備：建商開賣預售屋前要向縣市政府報備（內政部全國備查清單，每月更新）。
// 列：[行政區索引, 建案名稱, 坐落街道, 起造人, 戶數, 主要用途, 報備日期, 建照核發日期, 第一次成交登記日期, 第一筆地號, 地號筆數]
function buildcaseSection() {
  const bc = D.buildcase;
  if (!bc) return `<h3>預售屋建案報備</h3><p class="empty">${D.county ? "這個縣市的預售屋報備清單還沒產生（下次資料更新後就會有）。" : ""}</p>`;
  const ago = days => new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
  const day = r => r[6] || r[7], since = ago(365), old = ago(730);
  const note = `<p class="muted">建商開賣預售屋前要向縣市政府報備，這是內政部的全國備查清單（110 年 7 月起，最新報備 ${esc(bc.latest || "—")}，${esc(bc.fetched || "")} 取得）。` +
    `「尚無成交」表示還沒有登錄過第一筆成交，多半是剛報備、即將或剛開始銷售；報備超過兩年還沒有成交紀錄的，可能延後推出或停售。戶數是報備的總戶數，個人起造人不顯示姓名。</p>`;
  let h = `<h3>預售屋建案報備</h3>`;
  if (S.current === L.CITY) {
    const by = new Map();
    for (const r of bc.rows) {
      const s = by.get(r[0]) || { n12: 0, u12: 0, n: 0, last: "" };
      s.n++; if (day(r) >= since) { s.n12++; s.u12 += r[4]; } if (day(r) > s.last) s.last = day(r);
      by.set(r[0], s);
    }
    const list = [...by.entries()].sort((a, b) => b[1].u12 - a[1].u12 || b[1].n - a[1].n);
    if (!list.length) return h + `<p class="empty">這個縣市沒有預售屋報備紀錄。</p>` + note;
    h += `<table class="list"><thead><tr><th>區</th><th class="r">近一年件數</th><th class="r">近一年戶數</th><th class="r">累計件數</th><th>最新報備</th></tr></thead><tbody>`;
    for (const [i, s] of list) h += `<tr class="click" data-dist="${esc(bc.dists[i])}"><td>${esc(bc.dists[i])}</td><td class="r">${s.n12}</td><td class="r">${L.fmtNum(s.u12)}</td><td class="r">${s.n}</td><td>${esc(s.last.slice(0, 7))}</td></tr>`;
    return h + `</tbody></table><p class="muted">依近一年報備戶數排序，點一區看每個建案。</p>` + note;
  }
  const di = bc.dists.indexOf(S.current), mine = bc.rows.filter(r => r[0] === di);
  if (!mine.length) return h + `<p class="empty">${esc(S.current)}沒有預售屋報備紀錄。</p>` + note;
  const recent = mine.filter(r => day(r) >= since);
  h += `<p class="muted">${esc(S.current)}共 ${mine.length} 件，近一年 ${recent.length} 件、${L.fmtNum(recent.reduce((s, r) => s + r[4], 0))} 戶。</p>`;
  h += `<table class="list"><thead><tr><th>報備</th><th>建案／起造人</th><th class="r">戶數</th></tr></thead><tbody>`;
  for (const r of mine.slice(0, 120)) {
    const sub = [r[2], r[5], r[9] ? r[9] + (r[10] > 1 ? ` 等 ${r[10]} 筆` : "") : ""].filter(Boolean).join("｜");
    const tag = r[8] ? `<span class="pill done">${esc(r[8].slice(0, 7))} 起有成交</span>`
      : day(r) && day(r) < old ? `<span class="pill plan">未見成交紀錄</span>` : `<span class="pill new">尚無成交</span>`;
    h += `<tr><td>${esc((day(r) || "").slice(0, 7))}</td><td><b>${esc(r[1])}</b> ${tag}<div class="muted">${esc(r[3])}${sub ? "｜" + esc(sub) : ""}</div></td><td class="r">${r[4] ? L.fmtNum(r[4]) : "—"}</td></tr>`;
  }
  h += `</tbody></table>`;
  if (mine.length > 120) h += `<p class="muted">只列最近 120 件。</p>`;
  return h + note;
}

export function tabLand() {
  if (isNation()) return bankSection() + `<h3>預售屋建案報備</h3>` + needCounty() + `<h3>大面積土地成交</h3>` + needCounty();
  return (D.tw ? buildcaseSection() + dealsSection() : "") + bankSection();
}
