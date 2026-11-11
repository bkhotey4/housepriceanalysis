// 各區生活機能（店家登記數）：財政部全國營業（稅籍）登記資料，tools/build_shops.py 整理成 data/tw/<代碼>/shops.json
// 每區各類店家數 ÷ 戶籍人口 → 每萬人幾家，跟全縣市（看全台時跟全台）平均比。
import * as L from "./logic.js";
import { D, S, esc, renderPanel } from "./main.js";

const CACHE = new Map();
let nationShops = null;
function fetchJSON(path) { return fetch(path).then(r => { if (!r.ok) throw Object.assign(new Error("HTTP " + r.status), { network: false }); return r.json(); }); }
// 進到縣市（或回全台）時呼叫：背景下載，下載好時如果正在看概況就重畫
export function loadShops(code) {
  D.shops = CACHE.get(code) || null;
  if (!nationShops) fetchJSON("data/tw/shops.json").then(j => { nationShops = j; if (S.tab === "overview") renderPanel(); }).catch(() => {});
  if (CACHE.has(code)) return;
  fetchJSON(code ? `data/tw/${code}/shops.json` : "data/tw/shops.json").then(j => {
    CACHE.set(code, j);
    if ((D.county ? D.county.code : "") === code) { D.shops = j; if (S.tab === "overview") renderPanel(); }
  }).catch(() => {});        // 沒有這個檔（資料流程還沒跑過）：不顯示這一段
}
const popOf = name => { const p = L.popInfo(D.pop, name); return p && p.now ? p.now : 0; };
// 把幾個區（或縣市）的人口加起來；pop.json 裡也有合計那一列，所以只加 shops.json 列出的名稱，免得重複算
const sumPop = (pd, names) => names.reduce((a, k) => { const p = L.popInfo(pd, k); return a + (p && p.now ? p.now : 0); }, 0);
// 全縣市（或全台）的人口：縣市 pop.json 裡有縣市合計，沒有就把各區加起來
function basePop() {
  return popOf(L.CITY) || (D.shops ? sumPop(D.pop, Object.keys(D.shops.data)) : 0);
}
const per10k = (n, pop) => pop ? n / pop * 1e4 : null;
const fmt = v => v == null ? "—" : v >= 10 ? v.toFixed(0) : v.toFixed(1);
// 餐飲＝早餐＋小吃＋餐廳（前三類）
export function shopsSection(name) {
  const sd = D.shops;
  if (!sd || !sd.data) return "";
  const isTop = name === L.CITY, row = isTop ? sd.total : sd.data[name] || sd.data[L.normTw(name)];
  if (!row) return "";
  const pop = isTop ? basePop() : popOf(name);
  // 比較基準：看一區時跟全縣市比；看縣市（或全台）總覽時跟全台比
  const cmpRow = isTop ? (D.county && nationShops ? nationShops.total : null) : sd.total;
  const cmpPop = isTop ? (nationShops ? sumPop(D.twPop, Object.keys(nationShops.data)) : 0) : basePop();
  const cmpName = isTop ? "全台" : L.CITY;
  const eat = r => r[0] + r[1] + r[2];
  let rows = sd.cats.map(([k, label], i) => ({ k, label, n: row[i], d: per10k(row[i], pop), b: cmpRow ? per10k(cmpRow[i], cmpPop) : null }));
  rows.unshift({ k: "food", label: "<b>餐飲合計</b>（早餐＋小吃＋餐廳）", raw: true, n: eat(row), d: per10k(eat(row), pop), b: cmpRow ? per10k(eat(cmpRow), cmpPop) : null });
  const vs = r => {
    if (r.d == null || r.b == null || !r.b) return "";
    const x = (r.d / r.b - 1) * 100;
    if (Math.abs(x) < 10) return `<span class="muted">差不多</span>`;
    return `<span class="${x > 0 ? "up" : "down"}">${x > 0 ? "多" : "少"} ${Math.abs(x).toFixed(0)}%</span>`;
  };
  let h = `<h3>生活機能（店家登記數）</h3><table class="list"><thead><tr><th>類別</th><th class="r">家數</th><th class="r">每萬人</th>${cmpRow ? `<th class="r">比${esc(cmpName)}平均</th>` : ""}</tr></thead><tbody>` +
    rows.map(r => `<tr><td>${r.raw ? r.label : esc(r.label)}</td><td class="r">${L.fmtNum(r.n)}</td><td class="r">${pop ? fmt(r.d) : "—"}</td>${cmpRow ? `<td class="r">${pop ? vs(r) : ""}</td>` : ""}</tr>`).join("") +
    `</tbody></table>`;
  // 縣市總覽：各區餐飲、超商密度排行（摺起來）
  if (isTop && D.county) {
    const ds = Object.keys(sd.data).map(n => { const p = popOf(n), r = sd.data[n]; return { n, p, eat: per10k(eat(r), p), conv: per10k(r[6], p), cnt: eat(r) }; })
      .filter(x => x.p).sort((a, b) => b.eat - a.eat);
    if (ds.length > 1) h += `<details class="more"><summary>各區餐飲、便利商店密度（每萬人）</summary><table class="list"><thead><tr><th>區</th><th class="r">餐飲</th><th class="r">便利商店</th><th class="r">餐飲家數</th></tr></thead><tbody>` +
      ds.map(x => `<tr><td>${esc(x.n)}</td><td class="r">${fmt(x.eat)}</td><td class="r">${fmt(x.conv)}</td><td class="r">${L.fmtNum(x.cnt)}</td></tr>`).join("") + `</tbody></table></details>`;
  }
  h += `<p class="muted">財政部全國營業（稅籍）登記資料（${esc(sd.as_of || "")}），依營業地址的行政區、主要行業代號統計；同一類同一門牌只算一家。` +
    `是「有登記的店家」：沒辦稅籍的小攤、診所（免營業稅）不在裡面，也可能有登記了但已經沒在營業的。每萬人用戶籍人口算，商圈、觀光區的店多半是服務外來客。要看某個地址附近有哪些店，請用「看周邊生活機能」。</p>`;
  return h;
}
