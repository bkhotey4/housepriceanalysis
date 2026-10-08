// 資料與計算：房價統計、逐筆成交、路段、地址解析與門牌位置推估。
// 和 Python 的 core/prices.py、core/roads.py、core/address.py 邏輯一致（測試會比對結果）。

// 投影原點：台南版用台南中心；全台版啟動時改成台灣中心（setOrigin）。import 的變數是「活的」，改了大家都看得到。
export let LAT0 = 23.145, LNG0 = 120.34;
export const KM_LAT = 110.57;
export let KM_LNG = 111.32 * Math.cos(LAT0 * Math.PI / 180);
export function setOrigin(lat, lng) { LAT0 = lat; LNG0 = lng; KM_LNG = 111.32 * Math.cos(lat * Math.PI / 180); }
// 目前範圍的「總計」名稱：台南版是「台南市」；全台版在首頁是「全台」，進到縣市後是那個縣市（setCity）
export let CITY = "台南市";
export let COUNTY_NAME = "台南市";      // 搜尋其他平台、Google 地圖時加在地名前面
export function setCity(name, county = name) { CITY = name; COUNTY_NAME = county; }

// ------------------------------------------------------------------ 全台縣市（和 core/taiwan.py 相同）
export const COUNTIES = [
  ["A", "臺北市", "台北市"], ["F", "新北市", "新北市"], ["C", "基隆市", "基隆市"], ["H", "桃園市", "桃園市"], ["O", "新竹市", "新竹市"],
  ["J", "新竹縣", "新竹縣"], ["G", "宜蘭縣", "宜蘭縣"], ["K", "苗栗縣", "苗栗縣"], ["B", "臺中市", "台中市"], ["N", "彰化縣", "彰化縣"],
  ["M", "南投縣", "南投縣"], ["P", "雲林縣", "雲林縣"], ["I", "嘉義市", "嘉義市"], ["Q", "嘉義縣", "嘉義縣"], ["D", "臺南市", "台南市"],
  ["E", "高雄市", "高雄市"], ["T", "屏東縣", "屏東縣"], ["U", "花蓮縣", "花蓮縣"], ["V", "臺東縣", "台東縣"], ["X", "澎湖縣", "澎湖縣"],
  ["W", "金門縣", "金門縣"], ["Z", "連江縣", "連江縣"]].map(([code, name, short]) => ({ code, name, short }));
const PREFIXES = COUNTIES.flatMap(c => [[c.name, c], [c.short, c]]).sort((a, b) => b[0].length - a[0].length);
export const normTw = s => (s || "").replace(/臺/g, "台");
export function countyByName(name) { const n = normTw(name); return COUNTIES.find(c => c.short === n || normTw(c.name) === n) || null; }
// 開頭是縣市名稱就拆開：「台北市大安區…」→ [台北市, 大安區…]；「台南善化區…」（省略市）也可以
export function splitCounty(text) {
  const s = (text || "").trim();
  for (const [p, c] of PREFIXES) if (s.startsWith(p)) return [c, s.slice(p.length)];
  for (const c of COUNTIES) for (const head of new Set([c.short.slice(0, 2), c.name.slice(0, 2)]))
    if (s.startsWith(head) && s.length > 3 && !"市縣區鄉鎮路街巷大里村".includes(s[2])) return [c, s.slice(2)];
  return [null, s];
}
export const CATS = [["all", "全部合併"], ["house", "透天厝"], ["apt", "大樓／華廈"], ["presale", "預售屋"]];
export const CAT_LABEL = Object.fromEntries(CATS);
const MIN_N = 5, TREND_MIN_N = 10;

export function toXY(lat, lng) { return [(lng - LNG0) * KM_LNG, (lat - LAT0) * KM_LAT]; }
export function toLatLng(x, y) { return [y / KM_LAT + LAT0, x / KM_LNG + LNG0]; }
export function distKm(lat1, lng1, lat2, lng2) {
  const [x1, y1] = toXY(lat1, lng1), [x2, y2] = toXY(lat2, lng2);
  return Math.hypot(x1 - x2, y1 - y2);
}
export function median(a) {
  if (!a.length) return null;
  const s = [...a].sort((p, q) => p - q), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
// 分位數（線性內插，和 numpy 預設一樣）；s 必須已由小到大排序
export function quantile(s, q) {
  if (!s.length) return null;
  const i = (s.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}
// 價格分佈：切成 bins 格；最便宜 2%、最貴 5% 併進頭尾兩格，少數豪宅或怪價不會把圖拉得很扁
export function priceHistogram(values, bins = 14) {
  const s = values.filter(v => v > 0).sort((a, b) => a - b);
  if (s.length < 8) return null;
  const lo = quantile(s, 0.02), hi = quantile(s, 0.95), w = (hi - lo) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of s) counts[Math.max(0, Math.min(bins - 1, Math.floor((v - lo) / w)))]++;
  return { lo, hi, w, n: s.length, counts, p25: quantile(s, 0.25), p50: quantile(s, 0.5), p75: quantile(s, 0.75),
    below: b => s.filter(v => v <= b).length / s.length };
}
// 和 Python 的 round() 一樣：剛好在中間時取偶數（統計值才會和 Python 產生的資料完全一致）
export function pyRound(x, nd = 0) {
  if (x == null) return x;
  // 用精確的十進位展開判斷是不是「剛好一半」；是的話取偶數，否則照一般四捨五入（toFixed 依精確值處理）
  const exact = Math.abs(x).toPrecision(100).replace(/0+$/, "");
  const dot = exact.indexOf("."), frac = dot < 0 ? "" : exact.slice(dot + 1);
  if (frac.length === nd + 1 && frac[nd] === "5") {
    const k = 10 ** nd, f = Math.floor(Math.abs(x) * k), r = (f % 2 === 0 ? f : f + 1) / k;
    return x < 0 ? -r : r;
  }
  return Number(x.toFixed(nd));
}
export const fmtNum = v => v == null ? "—" : Math.round(v).toLocaleString("en-US");

// ------------------------------------------------------------------ 房價統計（PriceBook）
export class Book {
  constructor(raw) { Object.assign(this, raw); }
  cell(d, cat) { return (this.data[d] || {})[cat] || null; }
  best(d, cat, metric = "u") {
    const c = this.cell(d, cat), idx = metric === "u" ? 1 : 2;
    if (!c) return { value: null, n: 0, window: null, low: true };
    for (const key of ["h6", "y12"]) {
      const n = c[key][0];
      if (n >= (key === "h6" ? MIN_N : 1)) return { value: c[key][idx], n, window: key, low: n < MIN_N };
    }
    return { value: null, n: 0, window: null, low: true };
  }
  trend(d, cat, metric = "u") {
    const c = this.cell(d, cat), idx = metric === "u" ? 1 : 2;
    if (!c) return null;
    const r3 = c.r3, p3 = c.p3;
    if (r3[0] < TREND_MIN_N || p3[0] < TREND_MIN_N || !p3[idx]) return null;
    return (r3[idx] - p3[idx]) / p3[idx] * 100;
  }
  series(d, cat, metric = "u") {
    const c = this.cell(d, cat);
    return this.months.map((m, i) => {
      const n = c ? c.n[i] : 0;
      return { m, v: c && n ? (metric === "u" ? c.u[i] : c.t[i]) : null, n, partial: m > this.complete_through };
    });
  }
  presaleGap(d) {
    const p = this.best(d, "presale", "u"), a = this.best(d, "apt", "u");
    if (p.value == null || a.value == null || p.low || a.low || !a.value) return null;
    return (p.value - a.value) / a.value * 100;
  }
  windowLabel(key) {
    const [a, b] = this.windows[key], f = s => s.slice(2).replace("-", "/");
    return `${f(a)}~${f(b)}`;
  }
}

export function trendText(pct) {
  if (pct == null) return "樣本不足";
  if (Math.abs(pct) < 0.5) return `持平 ${Math.abs(pct).toFixed(1)}%`;
  return (pct > 0 ? "▲ 漲 " : "▼ 跌 ") + Math.abs(pct).toFixed(1) + "%";
}

// ------------------------------------------------------------------ 逐筆成交
export function decodeTx(raw) {
  const out = [];
  const cats = raw.cats, dists = raw.dists;
  for (const r of raw.rows) {
    out.push({ dist: dists[r[0]], date: r[1], ym: r[1].slice(0, 7), cat: cats[r[2]], btype: r[3], addr: r[4],
               tw: r[5], u: r[6], ping: r[7], built: r[8] || null, presale: r[9] === 1, proj: r[10],
               road: r[11], lane: r[12] < 0 ? null : r[12], alley: r[13] < 0 ? null : r[13], num: r[14] < 0 ? null : r[14],
               // 舊資料沒有下面四欄：樓層（null 不明）、車位數、車位坪數、車位價（萬）
               fl: r[15] == null || r[15] < 0 ? null : r[15], pk: r[16] || 0, pka: r[17] || 0, pkp: r[18] || 0, pkt: r[19] || 0,
               // 公設比（%，null 不明）、實坪（坪）、房數（0 不明）、電梯與管理組織（0 不明、1 有、2 無）
               ps: r[20] == null || r[20] < 0 ? null : r[20], rp: r[21] || 0, rm: r[22] || 0, ev: r[23] || 0, mg: r[24] || 0 });
  }
  return out;
}
// 已解約的預售屋筆數："區|建案" → 筆數（tx.json 的 cancel 欄；舊資料沒有就是空的）
export function decodeCancel(raw) {
  const m = new Map();
  for (const [d, proj, n] of raw.cancel || []) m.set(raw.dists[d] + "|" + proj, n);
  return m;
}
export function inCat(x, cat) {
  if (cat === "presale") return x.presale;
  if (x.presale) return false;
  return cat === "all" || x.cat === cat;
}

function groupStats(rows) {
  return { n: rows.length, u: pyRound(median(rows.map(x => x.u)), 1),
           t: pyRound(median(rows.map(x => x.tw))), last: rows.reduce((m, x) => x.date > m ? x.date : m, ""),
           low: rows.length < 3 };
}
// 某區某房型各路段的件數與中位價（預售屋以建案分組）
export function roadPrices(txs, district, cat, sinceYm) {
  const groups = new Map();
  for (const x of txs) {
    if (x.dist !== district || x.ym < sinceYm || !inCat(x, cat)) continue;
    const key = cat === "presale" ? (x.proj || "未命名建案") : x.road;
    if (!key || key === "其他") continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(x);
  }
  const out = [];
  for (const [name, rows] of groups) out.push({ name, dist: district, ...groupStats(rows) });
  out.sort((a, b) => b.n - a.n || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return out;
}
export function searchRoads(txs, kw, cat, sinceYm, limit = 200) {
  kw = kw.trim();
  if (!kw) return [];
  const groups = new Map();
  for (const x of txs) {
    if (x.ym < sinceYm || !inCat(x, cat) || !x.road.includes(kw)) continue;
    const key = x.dist + "|" + x.road;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(x);
  }
  const out = [];
  for (const [key, rows] of groups) {
    const [dist, name] = key.split("|");
    out.push({ dist, name, ...groupStats(rows) });
  }
  out.sort((a, b) => b.n - a.n || a.dist.localeCompare(b.dist) || a.name.localeCompare(b.name));
  return out.slice(0, limit);
}

// ------------------------------------------------------------------ 地址解析（core/address.py）
const FULL = { "０": "0", "１": "1", "２": "2", "３": "3", "４": "4", "５": "5", "６": "6", "７": "7", "８": "8", "９": "9", "－": "-", "（": "(", "）": ")" };
const ROAD_RE = /^(.+?(?:大道|路|街)(?:[一二三四五六七八九十]+段)?)/u;
const VILLAGE_RE = /^[一-鿿]{1,4}里(?=[一-鿿])/u;

export function normalize(text) {
  let s = (text || "").replace(/\s+/g, "").replace(/[０-９－（）]/g, c => FULL[c]);
  s = s.replace(/^\d{3,6}(?=[^\d號巷弄之])/u, "");
  const rest = splitCounty(s)[1];
  return rest || s;
}
export function roadOf(s) {
  s = s.replace(VILLAGE_RE, "");
  const m = s.match(ROAD_RE);
  if (m && [...m[1]].length <= 12) return m[1];
  const head = s.split(/[0-9]/)[0].trim();
  const n = [...head].length;
  return n >= 2 && n <= 10 ? head : "其他";
}
function parts(rest) {
  rest = rest.replace(VILLAGE_RE, "");
  const road = roadOf(rest);
  if (road === "其他") return [null, null, null, null, null];
  const tail = rest.startsWith(road) ? rest.slice(road.length) : rest;
  const lane = tail.match(/(\d+)巷/), alley = tail.match(/(\d+)弄/);
  const cut = Math.max(lane ? lane.index + lane[0].length : 0, alley ? alley.index + alley[0].length : 0);
  const after = tail.slice(cut);
  const num = after.match(/(\d+)(?:之(\d+))?號/) || after.match(/(\d+)(?:之(\d+))?$/);
  return [road, lane ? +lane[1] : null, alley ? +alley[1] : null, num ? +num[1] : null, num && num[2] ? +num[2] : null];
}
export function parseAddress(text, districtNames) {
  const s = normalize(text);
  let district = null, rest = s;
  const names = [...districtNames].sort((a, b) => b.length - a.length);
  for (const n of names) if (s.startsWith(n)) { district = n; rest = s.slice(n.length); break; }
  if (!district) {
    for (const n of names) {
      const stem = n.slice(0, -1);
      if (stem.length >= 2 && s.startsWith(stem)) {
        const m = s.slice(stem.length).replace(VILLAGE_RE, "").match(ROAD_RE);
        if (m && m[1].length >= 3) { district = n; rest = s.slice(stem.length); break; }
      }
    }
  }
  const [road, lane, alley, num, sub] = rest ? parts(rest) : [null, null, null, null, null];
  return { district, road, lane, alley, num, sub, text: s };
}
export function describe(q) {
  let out = q.road || "";
  if (q.lane != null) out += ` ${q.lane} 巷`;
  if (q.alley != null) out += ` ${q.alley} 弄`;
  if (q.num != null) out += ` ${q.num}${q.sub != null ? "之" + q.sub : ""} 號`;
  return out;
}
// 依門牌遠近排序：level 3 同門牌、2 同巷、1 同路段
export function rankByAddress(rows, q) {
  const out = rows.map(x => {
    const sameLane = x.lane === q.lane && (q.alley == null || x.alley === q.alley);
    let level = 1, gap = 1e6;
    if (q.num != null && sameLane && x.alley === q.alley && x.num === q.num) { level = 3; gap = 0; }
    else if (q.lane != null && sameLane) level = 2;
    if (level < 3 && q.num != null && x.num != null && sameLane) {
      const d = x.num - q.num;
      gap = Math.abs(d) * 2 + (((d % 2) + 2) % 2 === 0 ? 0 : 1);
    }
    return { level, gap, x };
  });
  out.sort((a, b) => (b.level - a.level) || (a.gap - b.gap) || (a.x.date < b.x.date ? 1 : a.x.date > b.x.date ? -1 : 0));
  return out;
}
export function addressSummary(ranked) {
  const stat = rows => rows.length ? { n: rows.length, u: pyRound(median(rows.map(x => x.u)), 1),
                                       t: pyRound(median(rows.map(x => x.tw))) } : { n: 0, u: null, t: null };
  return { exact: stat(ranked.filter(r => r.level === 3).map(r => r.x)),
           lane: stat(ranked.filter(r => r.level >= 2).map(r => r.x)),
           road: stat(ranked.map(r => r.x)) };
}

// ------------------------------------------------------------------ 道路位置（core/roads.py 的 locate）
const ROADLIKE = /(路|街|大道|巷|弄|段|新村|橋)$/u;
const LANE_NAME = /^\d+巷(\d+弄)?$|^.{1,6}巷(\d+弄)?$/u;
const VARIANTS = { "仔": "子", "臺": "台", "庄": "莊", "廍": "部", "份": "分", "磘": "窯", "衚": "衛" };
const variant = s => s.replace(/[仔臺庄廍份磘衚]/g, c => VARIANTS[c]);
// data.roads[name] = [扁平 [lat, lng, lat, lng, ...], ...]（已接成連續的折線）
export function locate(data, name) {
  const roads = data.roads, places = data.places || {};
  const segments = roads[name] ? [...roads[name]] : [];
  const lanes = [];
  if (segments.length || ROADLIKE.test(name)) {
    for (const other in roads) if (other !== name && other.startsWith(name) && LANE_NAME.test(other.slice(name.length))) lanes.push(...roads[other]);
  }
  if (!segments.length && !lanes.length) {
    for (const other in roads) if (other.startsWith(name) && /^\d+巷/.test(other.slice(name.length))) lanes.push(...roads[other]);
  }
  let point = null;
  if (!segments.length) {
    const t = variant(name);
    for (const p in places) if (variant(p) === t) { point = places[p]; break; }
  }
  if (!segments.length && !lanes.length && !point) return null;
  if (!point) {
    const longest = (segments.length ? segments : lanes).reduce((a, b) => b.length > a.length ? b : a);
    const k = Math.floor(longest.length / 4) * 2;
    point = [longest[k], longest[k + 1]];
  }
  return { segments, lanes, point };
}

// ------------------------------------------------------------------ 門牌位置推估（core/address.py 的 position）
const METERS_PER_NUMBER = 2.5, LANE_SNAP_KM = 0.12;
export const PRECISION = {
  lane: ["依巷內門牌號碼推估，誤差約數十公尺", 0.05],
  interp: ["依這條路上各巷口的號碼推估，誤差約一兩百公尺", 0.15],
  lane_mouth: ["標在這條巷的巷口附近（OpenStreetMap 上沒有這條巷）", 0.1],
  alley_mouth: ["標在這條弄的弄口附近（OpenStreetMap 上沒有這條弄），誤差約數十公尺", 0.08],
  near_lane: ["標在附近一個巷口，只能當大概位置", 0.3],
  settlement: ["聚落式門牌，只能標在聚落的大概位置", 0.4],
  road: ["只知道在這條路上，圖釘在路的中段", null],
};
function chainXY(flat) {
  const pts = [];
  for (let i = 0; i < flat.length; i += 2) pts.push(toXY(flat[i], flat[i + 1]));
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return { pts, cum };
}
function project(c, p) {
  let best = [0, Infinity];
  for (let i = 0; i < c.pts.length - 1; i++) {
    const [x0, y0] = c.pts[i], [x1, y1] = c.pts[i + 1], dx = x1 - x0, dy = y1 - y0, s2 = dx * dx + dy * dy;
    const t = s2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - x0) * dx + (p[1] - y0) * dy) / s2));
    const d = Math.hypot(p[0] - (x0 + dx * t), p[1] - (y0 + dy * t));
    if (d < best[1]) best = [c.cum[i] + (c.cum[i + 1] - c.cum[i]) * t, d];
  }
  return best;
}
function pointAt(c, s) {
  s = Math.max(0, Math.min(c.cum[c.cum.length - 1], s));
  for (let i = 0; i < c.pts.length - 1; i++) {
    if (c.cum[i + 1] >= s) {
      const span = c.cum[i + 1] - c.cum[i], t = span === 0 ? 0 : (s - c.cum[i]) / span;
      return toLatLng(c.pts[i][0] + (c.pts[i + 1][0] - c.pts[i][0]) * t, c.pts[i][1] + (c.pts[i + 1][1] - c.pts[i][1]) * t);
    }
  }
  const last = c.pts[c.pts.length - 1];
  return toLatLng(last[0], last[1]);
}
const reverseFlat = f => { const o = []; for (let i = f.length - 2; i >= 0; i -= 2) o.push(f[i], f[i + 1]); return o; };
export function laneAnchors(data, road) {
  const chains = (data.roads[road] || []).map(chainXY);
  if (!chains.length) return { chains, anchors: [] };
  const re = new RegExp("^" + road.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(\\d+)巷$", "u");
  const anchors = [];
  for (const name in data.roads) {
    const m = name.match(re);
    if (!m) continue;
    let best = null;
    for (const lane of data.roads[name]) {
      for (const [end, oriented] of [[[lane[0], lane[1]], lane], [[lane[lane.length - 2], lane[lane.length - 1]], reverseFlat(lane)]]) {
        const p = toXY(end[0], end[1]);
        chains.forEach((c, ci) => {
          const [s, d] = project(c, p);
          if (d <= LANE_SNAP_KM && (!best || d < best.d)) best = { d, ci, s, line: oriented };
        });
      }
    }
    if (best) anchors.push({ n: +m[1], ci: best.ci, s: best.s, line: best.line });
  }
  return { chains, anchors };
}
function fit(group) {
  const seen = new Set(), pts = [];
  for (const g of group) { const k = g.n + "|" + g.s; if (!seen.has(k)) { seen.add(k); pts.push(g); } }
  if (new Set(pts.map(p => p.n)).size < 2) return null;
  const k = pts.length, mn = pts.reduce((a, p) => a + p.n, 0) / k, ms = pts.reduce((a, p) => a + p.s, 0) / k;
  let sxx = 0, sxy = 0, syy = 0;
  for (const p of pts) { sxx += (p.n - mn) ** 2; sxy += (p.n - mn) * (p.s - ms); syy += (p.s - ms) ** 2; }
  if (!sxx || !syy) return null;
  const b = sxy / sxx, r = sxy / Math.sqrt(sxx * syy);
  if (Math.abs(r) < 0.8 || Math.abs(b) < 0.0005 || Math.abs(b) > 0.03) return null;
  return [ms - b * mn, b];
}
export function position(data, q) {
  const { road, lane, num, alley } = q;
  if (!road || !data) return null;
  const out = (ll, precision, spot) => ({ lat: ll[0], lng: ll[1], precision, note: PRECISION[precision][0],
                                          radius: PRECISION[precision][1], spot });
  const { chains, anchors } = laneAnchors(data, road);
  if (!chains.length) {
    const loc = locate(data, road);
    if (!loc) return null;
    return out(loc.point, !loc.segments.length && !loc.lanes.length ? "settlement" : "road", road);
  }
  if (lane != null) {
    for (const a of anchors) {
      if (a.n !== lane) continue;
      const c = chainXY(a.line);
      if (alley != null) {
        const aname = `${road}${lane}巷${alley}弄`;
        for (const line of data.roads[aname] || []) {
          let ac = chainXY(line);
          const [, d0] = project(c, ac.pts[0]), [, d1] = project(c, ac.pts[ac.pts.length - 1]);
          if (d1 < d0) ac = chainXY(reverseFlat(line));
          const walk = num != null ? num * METERS_PER_NUMBER / 1000 : Math.min(ac.cum[ac.cum.length - 1] / 2, 0.05);
          return out(pointAt(ac, walk), "lane", aname);
        }
        return out(pointAt(c, alley * METERS_PER_NUMBER / 1000), "alley_mouth", `${road}${lane}巷${alley}弄口`);
      }
      if (num != null) return out(pointAt(c, num * METERS_PER_NUMBER / 1000), "lane", `${road}${lane}巷`);
      return out(pointAt(c, Math.min(c.cum[c.cum.length - 1] / 2, 0.08)), "lane", `${road}${lane}巷`);
    }
  }
  const target = lane != null ? lane : num;
  if (target != null && anchors.length) {
    const by = new Map();
    for (const a of anchors) { if (!by.has(a.ci)) by.set(a.ci, []); by.get(a.ci).push(a); }
    const items = [...by.entries()].sort((A, B) => {
      const score = g => { const ns = g.map(x => x.n), lo = Math.min(...ns), hi = Math.max(...ns);
                           return lo <= target && target <= hi ? 0 : Math.min(Math.abs(target - lo), Math.abs(target - hi)); };
      return score(A[1]) - score(B[1]) || B[1].length - A[1].length;
    });
    for (const [ci, group] of items) {
      const f = fit(group);
      if (!f) continue;
      const c = chains[ci], s = f[0] + f[1] * target;
      if (s >= -0.15 && s <= c.cum[c.cum.length - 1] + 0.15)
        return out(pointAt(c, s), lane != null ? "lane_mouth" : "interp", road + (lane != null ? `${lane}巷口` : ""));
    }
    let best = null;
    for (const a of anchors) if (!best || Math.abs(a.n - target) < Math.abs(best.n - target)) best = a;
    if (Math.abs(best.n - target) <= 30) return out(pointAt(chains[best.ci], best.s), "near_lane", `${road}${best.n}巷口`);
  }
  const c = chains.reduce((a, b) => b.cum[b.cum.length - 1] > a.cum[a.cum.length - 1] ? b : a);
  return out(pointAt(c, c.cum[c.cum.length - 1] / 2), "road", road);
}

// ------------------------------------------------------------------ 重大建設的狀態
export function buildState(b, year) {
  if (b.done && b.done <= year) return "完工";
  if (b.phase === "完工") return "完工";
  if (b.start && b.start <= year) return "施工中";
  if (b.phase === "施工中") return "施工中";
  return "規劃中";
}

// ------------------------------------------------------------------ 社區／大樓（實價登錄沒有社區名稱：中古屋以「同門牌」歸成一棟，預售屋以建案名稱）
export function bldgKey(x) {
  if (x.presale) return x.proj ? "P|" + x.proj : null;
  if (!x.road || x.road === "其他" || x.num == null) return null;
  return ["A", x.road, x.lane ?? "", x.alley ?? "", x.num].join("|");
}
export function buildings(txs, district, cat, sinceYm) {
  const g = new Map();
  for (const x of txs) {
    if (x.dist !== district || !inCat(x, cat)) continue;
    const key = bldgKey(x);
    if (!key) continue;
    if (!g.has(key)) g.set(key, []);
    g.get(key).push(x);
  }
  const out = [];
  for (const [key, rows] of g) {
    if (rows.length < 2) continue;
    const x0 = rows[0], recent = rows.filter(x => x.ym >= sinceYm);
    const types = new Map();
    for (const x of rows) types.set(x.btype, (types.get(x.btype) || 0) + 1);
    const built = rows.map(x => x.built).filter(Boolean);
    out.push({
      key, dist: district, presale: x0.presale,
      name: x0.presale ? x0.proj : describe({ road: x0.road, lane: x0.lane, alley: x0.alley, num: x0.num }).replace(/ /g, ""),
      road: x0.road, lane: x0.lane, alley: x0.alley, num: x0.num,
      n: rows.length, u: pyRound(median(rows.map(x => x.u)), 1), t: pyRound(median(rows.map(x => x.tw))),
      n12: recent.length, u12: recent.length ? pyRound(median(recent.map(x => x.u)), 1) : null,
      last: rows.reduce((m, x) => x.date > m ? x.date : m, ""),
      built: built.length ? Math.round(median(built)) : null,
      btype: [...types].sort((a, b) => b[1] - a[1])[0][0] || "",
    });
  }
  return out.sort((a, b) => b.n - a.n || (b.last > a.last ? 1 : -1));
}

// 同一個建案／社區每一季的成交：預售屋看得出開賣以來單價怎麼走（首批 vs 最近）
export function quarterSeries(rows) {
  const g = new Map();
  for (const x of rows) {
    const q = x.ym.slice(0, 4) + "Q" + (((+x.ym.slice(5, 7)) - 1) / 3 + 1 | 0);
    if (!g.has(q)) g.set(q, []);
    g.get(q).push(x.u);
  }
  const out = [...g].sort((a, b) => a[0] < b[0] ? -1 : 1).map(([q, us]) => ({ q, n: us.length, u: pyRound(median(us), 1) }));
  if (out.length < 2) return null;
  const solid = out.filter(r => r.n >= 3);
  const first = solid[0] || out[0], last = solid[solid.length - 1] || out[out.length - 1];
  return { rows: out, first, last, pct: solid.length >= 2 && first.u ? (last.u - first.u) / first.u * 100 : null };
}

// ------------------------------------------------------------------ 進階行情：樓層價差、屋齡折舊、車位、市場冷熱
const monthsBack = (ym, n) => { const i = +ym.slice(0, 4) * 12 + (+ym.slice(5, 7)) - 1 - n; return `${Math.floor(i / 12)}-${String(i % 12 + 1).padStart(2, "0")}`; };
export const FLOOR_BANDS = [[1, 1, "1 樓"], [2, 3, "2～3 樓"], [4, 6, "4～6 樓"], [7, 9, "7～9 樓"], [10, 14, "10～14 樓"], [15, 19, "15～19 樓"], [20, 99, "20 樓以上"]];
// 樓層價差：同一棟（同門牌或同建案）裡，每一筆的單價 ÷ 這一棟的中位單價，再依樓層分組取中位數。
// 用「同棟比同棟」才不會被地段、屋齡混在一起；透天沒有樓層的問題，不算。
export function floorPremium(txs, district, sinceYm, minN = 8) {
  const g = new Map();
  for (const x of txs) {
    if (x.dist !== district || x.ym < sinceYm || x.cat === "house" || x.fl == null) continue;
    const k = bldgKey(x);
    if (!k) continue;
    if (!g.has(k)) g.set(k, []);
    g.get(k).push(x);
  }
  const ratios = FLOOR_BANDS.map(() => []);
  let bldgs = 0;
  for (const rows of g.values()) {
    if (rows.length < 4 || new Set(rows.map(x => x.fl)).size < 2) continue;
    const m = median(rows.map(x => x.u));
    if (!m) continue;
    bldgs++;
    for (const x of rows) { const i = FLOOR_BANDS.findIndex(([a, b]) => x.fl >= a && x.fl <= b); if (i >= 0) ratios[i].push(x.u / m); }
  }
  const bands = FLOOR_BANDS.map(([a, b, label], i) => ({ label, n: ratios[i].length, pct: ratios[i].length >= minN ? pyRound((median(ratios[i]) - 1) * 100, 1) : null }));
  return bands.some(b => b.pct != null) ? { bands, bldgs } : null;
}
// 同一棟每層的中位單價（社區明細用）
export function floorProfile(rows) {
  const g = new Map();
  for (const x of rows) if (x.fl != null) { if (!g.has(x.fl)) g.set(x.fl, []); g.get(x.fl).push(x.u); }
  if (g.size < 2) return null;
  return [...g].sort((a, b) => a[0] - b[0]).map(([fl, us]) => ({ fl, n: us.length, u: pyRound(median(us), 1) }));
}
export const AGE_BANDS = [[0, 5, "5 年內"], [6, 10, "6～10 年"], [11, 20, "11～20 年"], [21, 30, "21～30 年"], [31, 200, "30 年以上"]];
// 屋齡和單價：近兩年的中古成交（不含預售）依屋齡分組；pct 是相對「5 年內」（樣本不夠就用下一組）的差距
export function ageCurve(txs, district, cat, endYm, minN = 5) {
  const since = monthsBack(endYm, 23), groups = AGE_BANDS.map(() => []);
  for (const x of txs) {
    if (x.dist !== district || x.presale || x.ym < since || !x.built || !inCat(x, cat === "presale" ? "all" : cat)) continue;
    const age = +x.date.slice(0, 4) - x.built, i = AGE_BANDS.findIndex(([a, b]) => age >= a && age <= b);
    if (i >= 0) groups[i].push(x.u);
  }
  const bands = AGE_BANDS.map(([, , label], i) => ({ label, n: groups[i].length, u: groups[i].length >= minN ? pyRound(median(groups[i]), 1) : null }));
  const base = bands.find(b => b.u != null);
  if (!base || bands.filter(b => b.u != null).length < 2) return null;
  for (const b of bands) b.pct = b.u != null ? pyRound((b.u - base.u) / base.u * 100, 0) : null;
  return { bands, base: base.label, since };
}
// 車位行情：只看「一個車位、而且有分開登錄車位價」的成交，依平面／機械分
export function parkingStats(txs, district, endYm) {
  const since = monthsBack(endYm, 23), out = { flat: [], mech: [], other: [] };
  for (const x of txs) {
    if (x.dist !== district || x.ym < since || x.pk !== 1 || !(x.pkp > 0)) continue;
    (x.pkt === 1 ? out.flat : x.pkt === 2 ? out.mech : out.other).push(x);
  }
  const st = rows => rows.length >= 3 ? { n: rows.length, price: pyRound(median(rows.map(x => x.pkp)), 0), area: pyRound(median(rows.map(x => x.pka).filter(a => a > 0)) || 0, 1),
    lo: pyRound(quantile(rows.map(x => x.pkp).sort((a, b) => a - b), 0.25), 0), hi: pyRound(quantile(rows.map(x => x.pkp).sort((a, b) => a - b), 0.75), 0) } : null;
  const r = { flat: st(out.flat), mech: st(out.mech), other: st(out.other), since };
  return r.flat || r.mech || r.other ? r : null;
}
// 市場冷熱：價格（近 3 個月 vs 前 3 個月）＋成交量（近 6 個月 vs 前 6 個月，只算資料到齊的月份）
export function marketHeat(book, name, cat = "all") {
  const c = book.cell(name, cat);
  if (!c) return null;
  const done = book.months.map((m, i) => [m, i]).filter(([m]) => m <= book.complete_through).map(([, i]) => i);
  if (done.length < 12) return null;
  const sum = idx => idx.reduce((a, i) => a + (c.n[i] || 0), 0);
  const recent = sum(done.slice(-6)), prev = sum(done.slice(-12, -6));
  const vol = prev >= 10 && recent >= 5 ? (recent - prev) / prev * 100 : null;
  const price = book.trend(name, cat, "u");
  if (vol == null && price == null) return null;
  const clamp = v => Math.max(-1, Math.min(1, v));
  const score = (price != null ? clamp(price / 6) : 0) * 0.55 + (vol != null ? clamp(vol / 30) : 0) * 0.45;
  const label = score >= 0.35 ? "升溫" : score <= -0.35 ? "降溫" : "持平";
  return { score, label, price, vol, recent, prev };
}

// ---- 公設比與實坪單價：實坪＝主建物＋附屬建物＋陽台；實坪單價＝（總價 − 分開登錄的車位價）÷ 實坪
// 有車位但車位價沒有分開登錄時，算不出房子本身的價格，回傳 null
export function realUnit(x) {
  if (!(x.rp > 0)) return null;
  if (x.pk > 0 && !(x.pkp > 0)) return null;
  return (x.tw - (x.pk > 0 ? x.pkp : 0)) / x.rp;
}
export const SHARE_AGE = [[0, 5, "5 年內"], [6, 15, "6～15 年"], [16, 30, "16～30 年"], [31, 200, "30 年以上"]];
// 大樓、華廈（不含預售：預售屋檔沒有面積明細）近兩年的公設比與實坪單價，整體和依屋齡分組
export function commonAreaStats(txs, district, endYm, minN = 5) {
  const since = monthsBack(endYm, 23), all = [];
  for (const x of txs) if (x.dist === district && x.cat === "apt" && !x.presale && x.ym >= since && x.ps != null) all.push(x);
  if (all.length < minN) return null;
  const sum = rows => {
    const reals = rows.map(realUnit).filter(v => v != null);
    return rows.length >= minN ? { n: rows.length, ps: pyRound(median(rows.map(x => x.ps)), 1), u: pyRound(median(rows.map(x => x.u)), 1),
      real: reals.length >= minN ? pyRound(median(reals), 1) : null } : { n: rows.length, ps: null, u: null, real: null };
  };
  const age = x => x.built ? +x.date.slice(0, 4) - x.built : null;
  return { all: sum(all), since,
    bands: SHARE_AGE.map(([a, b, label]) => ({ label, ...sum(all.filter(x => { const g = age(x); return g != null && g >= a && g <= b; })) })) };
}
// ---- 依房數看行情：1 房、2 房、3 房、4 房以上（房數 0＝開放格局或沒填，不算）
export const ROOM_BANDS = [[1, 1, "1 房"], [2, 2, "2 房"], [3, 3, "3 房"], [4, 99, "4 房以上"]];
export function roomStats(txs, district, cat, endYm, minN = 3) {
  const since = monthsBack(endYm, 11), g = ROOM_BANDS.map(() => []);
  for (const x of txs) {
    if (x.dist !== district || x.ym < since || !inCat(x, cat) || !x.rm) continue;
    const i = ROOM_BANDS.findIndex(([a, b]) => x.rm >= a && x.rm <= b);
    if (i >= 0) g[i].push(x);
  }
  const bands = ROOM_BANDS.map(([, , label], i) => {
    const rows = g[i];
    return rows.length >= minN ? { label, n: rows.length, t: pyRound(median(rows.map(x => x.tw))), ping: pyRound(median(rows.map(x => x.ping)), 1), u: pyRound(median(rows.map(x => x.u)), 1) }
      : { label, n: rows.length, t: null, ping: null, u: null };
  });
  return bands.some(b => b.t != null) ? { bands, since } : null;
}
// 成交清單的篩選：房數（"1"～"3"、"4"＝4 房以上）、只看有電梯
export function txFilter(x, f) {
  if (f.rm && !(f.rm === "4" ? x.rm >= 4 : x.rm === +f.rm)) return false;
  if (f.ev && x.ev !== 1) return false;
  return true;
}

// ------------------------------------------------------------------ 到其他平台找物件（用 Google 站內搜尋，不爬取對方網站）
export const PLATFORMS = [["591", "sale.591.com.tw"], ["樂屋網", "rakuya.com.tw"], ["樂居", "leju.com.tw"],
                          ["永慶", "yungching.com.tw"], ["信義", "sinyi.com.tw"], ["住商", "hbhousing.com.tw"]];
export function platformLinks(district, place) {
  const where = `${COUNTY_NAME === "全台" ? "" : COUNTY_NAME}${district === CITY ? "" : district}${place || ""}`;
  const links = PLATFORMS.map(([name, site]) => [name, "https://www.google.com/search?q=" + encodeURIComponent(`site:${site} ${where}`)]);
  links.push(["Google 地圖", "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(where)]);
  return links;
}

// ------------------------------------------------------------------ 通勤時間（估計）：直線距離 × 繞路係數 ÷ 平均車速 ＋ 出發／停車時間
export const MODES = { car: ["開車", 32, "driving"], scooter: ["機車", 28, "driving"], bike: ["腳踏車", 14, "bicycling"] };
const DETOUR = 1.3, FIXED_MIN = 3;
export function commuteMin(km, mode = "car") {
  const sp = (MODES[mode] || MODES.car)[1];
  return Math.round(FIXED_MIN + km * DETOUR / sp * 60);
}
// ---- 實際道路的通勤時間：FOSSGIS 的 OSRM 公開伺服器（OpenStreetMap 道路），一次請求算上班地點到所有行政區
// 使用規則：每秒最多 1 次、不可大量使用、要標示來源；所以結果存在裝置上 30 天，同一個上班地點不重複查。
export const ROUTE_HOST = "https://routing.openstreetmap.de";
const ROUTE_PROFILE = { car: "routed-car", scooter: "routed-car", bike: "routed-bike" };
// 路線時間是不塞車的理想值：開車、機車乘上尖峰係數，再加出發、停車的固定時間
export const ROUTE_ADJ = { car: [1.25, 3], scooter: [1.15, 2], bike: [1.0, 2] };
export function routeTableUrl(mode, from, dests) {
  const pts = [from, ...dests.filter(p => p.lat != null && p.lng != null)].map(p => `${(+p.lng).toFixed(5)},${(+p.lat).toFixed(5)}`).join(";");
  return `${ROUTE_HOST}/${ROUTE_PROFILE[mode] || ROUTE_PROFILE.car}/table/v1/driving/${pts}?sources=0&annotations=duration`;
}
// OSRM table 回應 → [分鐘]（跟 dests 同順序；到不了的是 null）
export function parseRouteTable(json, mode, n) {
  if (!json || json.code !== "Ok" || !json.durations || !json.durations[0]) return null;
  const [f, fixed] = ROUTE_ADJ[mode] || ROUTE_ADJ.car;
  return json.durations[0].slice(1, n + 1).map(s => s == null ? null : Math.round(s / 60 * f + fixed));
}
export const ptKey = (lat, lng) => `${(+lat).toFixed(4)},${(+lng).toFixed(4)}`;

// ---- 房價所得比：總價 ÷ 家庭年收入＝「不吃不喝幾年」
export function priceIncomeRatio(totalWan, incomeMonthly) {
  return totalWan > 0 && incomeMonthly > 0 ? totalWan * 10000 / (incomeMonthly * 12) : null;
}
export function kmFor(min, mode = "car") {
  const sp = (MODES[mode] || MODES.car)[1];
  return Math.max(0, (min - FIXED_MIN) / 60 * sp / DETOUR);
}
export function routeUrl(from, to, mode = "car") {
  return `https://www.google.com/maps/dir/?api=1&origin=${from.lat},${from.lng}&destination=${to.lat},${to.lng}&travelmode=${(MODES[mode] || MODES.car)[2]}`;
}

// ------------------------------------------------------------------ 周邊：生活機能與嫌惡設施（OpenStreetMap，經由 Overpass API 在使用者裝置上即時查詢）
// good=生活機能、bad=一般認為的嫌惡設施；r 是統計半徑（公尺）
export const POI_CATS = [
  { key: "conv", label: "便利商店", ch: "便", color: "#1baf7a", group: "good", r: 500, q: ['nwr["shop"="convenience"]'], t: t => t.shop === "convenience" },
  { key: "mart", label: "超市／量販", ch: "超", color: "#1baf7a", group: "good", r: 1000, q: ['nwr["shop"~"^(supermarket|department_store|wholesale)$"]'], t: t => /^(supermarket|department_store|wholesale)$/.test(t.shop || "") },
  { key: "market", label: "傳統市場", ch: "市", color: "#1baf7a", group: "good", r: 1000, q: ['nwr["amenity"="marketplace"]'], t: t => t.amenity === "marketplace" },
  { key: "school", label: "國小／國中", ch: "學", color: "#2a78d6", group: "good", r: 1000, q: ['nwr["amenity"="school"]'], t: t => t.amenity === "school" && /國小|國民小學|國中|國民中學|實驗/.test(t.name || "") },
  { key: "kinder", label: "幼兒園", ch: "幼", color: "#2a78d6", group: "good", r: 500, q: ['nwr["amenity"="kindergarten"]'], t: t => t.amenity === "kindergarten" },
  { key: "hosp", label: "醫院", ch: "醫", color: "#c0302f", group: "good", r: 2000, q: ['nwr["amenity"="hospital"]'], t: t => t.amenity === "hospital" },
  { key: "clinic", label: "診所／藥局", ch: "診", color: "#c0302f", group: "good", r: 500, q: ['nwr["amenity"~"^(clinic|doctors|pharmacy|dentist)$"]'], t: t => /^(clinic|doctors|pharmacy|dentist)$/.test(t.amenity || "") },
  { key: "park", label: "公園", ch: "園", color: "#008300", group: "good", r: 500, q: ['nwr["leisure"="park"]'], t: t => t.leisure === "park" },
  { key: "station", label: "火車／捷運站", ch: "站", color: "#4a3aa7", group: "good", r: 2000, q: ['nwr["railway"="station"]'], t: t => t.railway === "station" },
  { key: "bus", label: "公車站", ch: "公", color: "#4a3aa7", group: "good", r: 500, q: ['node["highway"="bus_stop"]'], t: t => t.highway === "bus_stop" },
  { key: "grave", label: "墓地／納骨塔", ch: "墓", color: "#5b6168", group: "bad", r: 1000, q: ['nwr["landuse"="cemetery"]', 'nwr["amenity"~"^(grave_yard|crematorium)$"]'], t: t => t.landuse === "cemetery" || /^(grave_yard|crematorium)$/.test(t.amenity || "") },
  { key: "funeral", label: "殯儀館／禮儀社", ch: "殯", color: "#5b6168", group: "bad", r: 500, q: ['nwr["amenity"="funeral_hall"]', 'nwr["shop"="funeral_directors"]'], t: t => t.amenity === "funeral_hall" || t.shop === "funeral_directors" },
  { key: "fuel", label: "加油站", ch: "油", color: "#eb6834", group: "bad", r: 300, q: ['nwr["amenity"="fuel"]'], t: t => t.amenity === "fuel" },
  { key: "power", label: "變電所", ch: "電", color: "#eda100", group: "bad", r: 500, q: ['nwr["power"="substation"]'], t: t => t.power === "substation" },
  { key: "waste", label: "垃圾場／焚化爐／污水廠", ch: "垃", color: "#8a5a2b", group: "bad", r: 1000, q: ['nwr["landuse"="landfill"]', 'nwr["amenity"="waste_transfer_station"]', 'nwr["man_made"="wastewater_plant"]', 'nwr["power"="plant"]["plant:source"="waste"]'], t: t => t.landuse === "landfill" || t.amenity === "waste_transfer_station" || t.man_made === "wastewater_plant" || (t.power === "plant" && t["plant:source"] === "waste") },
  { key: "temple", label: "宮廟（見仁見智）", ch: "廟", color: "#b5651d", group: "bad", r: 200, q: ['nwr["amenity"="place_of_worship"]["religion"~"^(taoist|buddhist|chinese_folk)$"]'], t: t => t.amenity === "place_of_worship" && /^(taoist|buddhist|chinese_folk)$/.test(t.religion || "") },
  { key: "industry", label: "工業區／工廠", ch: "工", color: "#7a3fb5", group: "bad", r: 500, q: ['way["landuse"="industrial"]', 'nwr["man_made"="works"]'], t: t => t.landuse === "industrial" || t.man_made === "works" },
  // 線狀的嫌惡設施：量到線上最近的一點（geom），不是線的中心
  { key: "hvline", label: "高壓電線", ch: "線", color: "#eda100", group: "bad", r: 200, geom: true, q: ['way["power"="line"]'], t: t => t.power === "line" },
  { key: "rail", label: "鐵路、高架捷運（噪音、震動）", ch: "軌", color: "#6b4f3a", group: "bad", r: 200, geom: true,
    q: ['way["railway"~"^(rail|light_rail|subway|monorail)$"]["tunnel"!="yes"]["service"!~"."]'],
    t: t => /^(rail|light_rail|subway|monorail)$/.test(t.railway || "") && t.tunnel !== "yes" && !t.service && !(+t.layer < 0) },
  { key: "expwy", label: "高速公路、快速道路", ch: "速", color: "#8a929b", group: "bad", r: 200, geom: true,
    q: ['way["highway"~"^(motorway|trunk)$"]["tunnel"!="yes"]'], t: t => /^(motorway|trunk)$/.test(t.highway || "") && t.tunnel !== "yes" },
  { key: "airport", label: "機場（航道噪音）", ch: "機", color: "#2a78d6", group: "bad", r: 4000, q: ['nwr["aeroway"="aerodrome"]["iata"]'], t: t => t.aeroway === "aerodrome" && !!t.iata },
];
export const POI_RADIUS = 2000;      // 一般設施的查詢上限；機場另外看 4 公里
export function poiQuery(lat, lng) {
  const at = c => `(around:${c.r},${lat.toFixed(5)},${lng.toFixed(5)});`;
  const pt = [], ln = [];
  for (const c of POI_CATS) for (const q of c.q) (c.geom ? ln : pt).push(q + at(c));
  return `[out:json][timeout:25];(${pt.join("")});out center tags 2000;(${ln.join("")});out geom tags 300;`;
}
// 點到折線最近的位置（平面近似，幾公里內誤差可忽略）：回傳 [距離公尺, lat, lng]
export function nearestOnLine(lat, lng, geom) {
  const kx = 111.32 * Math.cos(lat * Math.PI / 180), ky = 110.57;
  let best = [Infinity, null, null];
  for (let i = 0; i < geom.length; i++) {
    const a = geom[i], b = geom[i + 1] || a;
    if (!a || a.lat == null || !b || b.lat == null) continue;
    const ax = (a.lon - lng) * kx, ay = (a.lat - lat) * ky, bx = (b.lon - lng) * kx, by = (b.lat - lat) * ky;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0;
    const px = ax + t * dx, py = ay + t * dy, d = Math.hypot(px, py) * 1000;
    if (d < best[0]) best = [d, lat + py / ky, lng + px / kx];
  }
  return best;
}
export function classifyPois(elements, lat, lng) {
  const items = [], seen = new Set();
  for (const e of elements || []) {
    const t = e.tags || {};
    let la = e.lat ?? (e.center && e.center.lat), lo = e.lon ?? (e.center && e.center.lon), dLine = e.dLine ?? null;
    if (Array.isArray(e.geometry) && e.geometry.length) { const n = nearestOnLine(lat, lng, e.geometry); [dLine, la, lo] = n; }
    if (la == null || lo == null) continue;
    for (const c of POI_CATS) {
      if (!c.t(t)) continue;
      const d = Math.round(dLine != null ? dLine : distKm(lat, lng, la, lo) * 1000);
      if (d > c.r) continue;
      const id = `${e.type}${e.id}`;
      if (seen.has(id + c.key)) continue;
      seen.add(id + c.key);
      // 同一條電線、鐵路在 OSM 上常拆成好幾段：同名（或同編號）的只算一條
      const same = c.geom ? (t.name || t.ref || (t.operator && t.voltage ? t.operator + t.voltage : "")) : "";
      items.push({ id, cat: c.key, name: t.name || (t.ref ? `${c.label} ${t.ref}` : c.label), lat: la, lng: lo, d, same });
      break;
    }
  }
  items.sort((a, b) => a.d - b.d);
  for (let i = items.length - 1; i >= 0; i--) {     // 由遠到近掃，同一條只留最近的那一段
    const it = items[i];
    if (it.same && items.findIndex(x => x.cat === it.cat && x.same === it.same) !== i) items.splice(i, 1);
  }
  const byCat = {};
  for (const c of POI_CATS) {
    const its = items.filter(x => x.cat === c.key);
    byCat[c.key] = { n: its.length, nearest: its[0] || null, list: its.slice(0, 5) };
  }
  return { items, byCat };
}

// ------------------------------------------------------------------ 道路位置（還沒預先整理好的區：在使用者裝置上向 OpenStreetMap 查，和 core/roads.py 同樣的條件）
const SKIP_HIGHWAY = new Set(["motorway", "motorway_link", "cycleway", "footway", "path", "steps", "pedestrian", "track",
  "construction", "proposed", "bridleway", "corridor", "platform"]);
export function roadsQuery(county, town) {
  return `[out:json][timeout:60];area["name"="${county}"]["admin_level"="4"]->.c;` +
    `rel(area.c)["boundary"="administrative"]["name"="${town}"];map_to_area->.a;` +
    `(way["highway"]["name"](area.a);node["place"]["name"](area.a););out tags geom qt;`;
}
function mergeChains(segs) {
  // 頭尾相接（而且那一點只有這兩段）的折線接成一條
  segs = segs.filter(s => s.length >= 2).map(s => s.slice());
  const key = p => p[0] + "," + p[1];
  let changed = true;
  while (changed && segs.length > 1) {
    changed = false;
    const ends = new Map();
    segs.forEach((s, i) => { for (const p of [s[0], s[s.length - 1]]) { const k = key(p); if (!ends.has(k)) ends.set(k, new Set()); ends.get(k).add(i); } });
    const used = new Set(), out = [];
    for (const [k, set] of ends) {
      if (set.size !== 2) continue;
      const [i, j] = [...set];
      if (used.has(i) || used.has(j)) continue;
      let a = segs[i], b = segs[j];
      if (key(a[a.length - 1]) !== k) a = a.slice().reverse();
      if (key(b[0]) !== k) b = b.slice().reverse();
      if (key(a[a.length - 1]) !== k || key(b[0]) !== k) continue;
      used.add(i); used.add(j); out.push(a.concat(b.slice(1))); changed = true;
    }
    segs = segs.filter((_, i) => !used.has(i)).concat(out);
  }
  return segs;
}
export function reduceRoads(raw) {
  const roads = {}, places = {};
  for (const e of raw.elements || []) {
    const t = e.tags || {}, name = (t.name || "").trim();
    if (!name) continue;
    if (e.type === "way") {
      const hw = t.highway;
      if (SKIP_HIGHWAY.has(hw)) continue;
      if (hw === "service" && !ROADLIKE.test(name) && name.length > 6) continue;
      const pts = (e.geometry || []).filter(p => p && p.lat != null).map(p => [Math.round(p.lat * 1e5) / 1e5, Math.round(p.lon * 1e5) / 1e5]);
      if (pts.length >= 2) (roads[name] = roads[name] || []).push(pts);
    } else if (e.type === "node" && e.lat != null) {
      const rank = { village: 0, hamlet: 1, neighbourhood: 2, quarter: 2, locality: 3 }[t.place] ?? 9;
      if (rank < 9 && (!places[name] || rank < places[name][2])) places[name] = [Math.round(e.lat * 1e5) / 1e5, Math.round(e.lon * 1e5) / 1e5, rank];
    }
  }
  const out = {};
  for (const [n, segs] of Object.entries(roads)) out[n] = mergeChains(segs).map(ch => ch.flat());
  return { roads: out, places: Object.fromEntries(Object.entries(places).map(([k, v]) => [k, v.slice(0, 2)])), fetched: new Date().toISOString().slice(0, 10) };
}

// ------------------------------------------------------------------ 房貸試算（本息平均攤還，可設寬限期）
// priceWan 總價（萬）、downPct 自備款比例（%）、ratePct 年利率（%）、years 貸款年限、grace 寬限期（年，只繳利息）
export function mortgage(priceWan, downPct, ratePct, years, grace = 0) {
  const loan = Math.max(0, priceWan * (1 - downPct / 100)) * 10000;
  const n = Math.round(years * 12), g = Math.min(Math.round(grace * 12), Math.max(0, n - 12));
  const r = ratePct / 100 / 12;
  if (!(loan > 0) || !(n > 0)) return null;
  const pay = m => (m <= 0 ? 0 : r > 0 ? loan * r / (1 - Math.pow(1 + r, -m)) : loan / m);
  const graceMonthly = g ? loan * r : 0, monthly = pay(n - g);
  const total = graceMonthly * g + monthly * (n - g);
  return { loan: loan / 10000, down: priceWan * downPct / 100, graceMonthly, monthly, totalInterest: (total - loan) / 10000,
    income: monthly * 3 };     // 一般建議月付不超過月收入的三分之一
}

// 青年安心成家購屋優惠貸款（新青安）：貸款上限 1,000 萬、最長 40 年、寬限期最長 5 年。
// 利率是公股銀行一段式機動利率（政府補貼後）的參考值，會隨央行升降息調整，實際以承辦銀行公告為準。
export const YOUTH_LOAN = { rate: 1.775, years: 40, grace: 5, cap: 1000 };
// 一般房貸的參考條件（房貸試算的預設、超過新青安上限的部分）：本息平均攤還、沒有寬限期
export const NORMAL_LOAN = { rate: 2.2, years: 30 };
// 有額度上限的優惠貸款：上限內用優惠條件，超過的部分當成另一筆一般房貸（restRate、restYears，不設寬限期）
export function mortgageCapped(priceWan, downPct, ratePct, years, grace, capWan, restRate, restYears) {
  const loanWan = Math.max(0, priceWan * (1 - downPct / 100));
  const main = mortgage(Math.min(loanWan, capWan), 0, ratePct, years, grace);
  if (!main) return null;
  const rest = loanWan > capWan ? mortgage(loanWan - capWan, 0, restRate, restYears, 0) : null;
  const extra = rest ? rest.monthly : 0;
  return { loan: loanWan, down: priceWan * downPct / 100, rest: rest ? rest.loan : 0,
    graceMonthly: main.graceMonthly ? main.graceMonthly + extra : 0, monthly: main.monthly + extra,
    totalInterest: main.totalInterest + (rest ? rest.totalInterest : 0), income: (main.monthly + extra) * 3 };
}

// ------------------------------------------------------------------ 合理價估算：從實價登錄找條件相近的成交
// q: {dist, cat("house"|"apt"|"presale"|"all"), ping, age(屋齡，年), road, lane, alley, num, todayYm, floor(樓層), park(車位數)}
// 相似度＝坪數接近 × 屋齡接近 × 樓層接近（大樓） × 越新的成交越重要 × 位置（同一棟 > 同巷 > 同路 > 同區），
// 用加權分位數算單價區間（25%～75%），再乘上坪數得到總價區間。
// 有車位時：實價登錄的單價已扣掉車位（有分開登錄車位價時），所以總價＝單價 ×（坪數 − 車位坪數）＋ 車位價，
// 車位的坪數與價格取比對成交裡有分開登錄車位的加權中位數。
const ymIndex = ym => +ym.slice(0, 4) * 12 + (+ym.slice(5, 7)) - 1;
function wQuantile(pairs, q) {        // pairs: [[value, weight]]，已排序
  const tot = pairs.reduce((s, p) => s + p[1], 0);
  let acc = 0;
  for (const [v, w] of pairs) { acc += w; if (acc >= q * tot) return v; }
  return pairs.length ? pairs[pairs.length - 1][0] : null;
}
export function estimate(txs, q) {
  const now = ymIndex(q.todayYm || new Date().toISOString().slice(0, 7));
  const year = +(q.todayYm || new Date().toISOString()).slice(0, 4);
  const sameRoad = x => q.road && x.road === q.road;
  // 位置等級：0 同區、1 同一條路、2 同一條巷、3 同一棟（同巷弄同門牌；在大馬路上沒有巷時，同門牌就是同一棟）
  const level = x => {
    if (!sameRoad(x) || (q.lane ?? null) !== (x.lane ?? null)) return sameRoad(x) ? 1 : 0;
    if (q.num != null && x.num === q.num && (x.alley ?? null) === (q.alley ?? null)) return 3;
    return q.lane != null ? 2 : 1;
  };
  const tries = [[24, 0.5, 12], [36, 0.7, 20], [60, 1.2, 99]];      // [月數, 坪數容許比例, 屋齡容許年]，找不到夠多就放寬
  let pool = [], used = null;
  for (const [months, pTol, aTol] of tries) {
    pool = [];
    for (const x of txs) {
      if (x.dist !== q.dist || !inCat(x, q.cat) || !(x.u > 0)) continue;
      const ago = now - ymIndex(x.ym);
      if (ago < 0 || ago > months) continue;
      if (q.ping && x.ping && Math.abs(Math.log(x.ping / q.ping)) > Math.log(1 + pTol)) continue;
      const age = x.built ? Math.max(0, +x.date.slice(0, 4) - x.built) : null;
      if (q.age != null && !q.presale && age != null && Math.abs(age - q.age) > aTol) continue;
      const lv = level(x);
      let w = Math.exp(-ago / 18) * [1, 1.6, 2.4, 3.5][lv];
      if (q.ping && x.ping) w *= Math.exp(-Math.pow(Math.log(x.ping / q.ping) / 0.3, 2));
      if (q.age != null && age != null) w *= Math.exp(-Math.pow((age - q.age) / 8, 2));
      if (q.floor != null && x.fl != null && x.cat !== "house") w *= 0.3 + 0.7 * Math.exp(-Math.pow((x.fl - q.floor) / 6, 2));
      pool.push({ x, w, lv, age, ago });
    }
    used = { months, pTol, aTol };
    if (pool.length >= 8) break;
  }
  if (pool.length < 3) return { n: pool.length, ok: false };
  const pairs = pool.map(p => [p.x.u, p.w]).sort((a, b) => a[0] - b[0]);
  const lo = wQuantile(pairs, 0.25), mid = wQuantile(pairs, 0.5), hi = wQuantile(pairs, 0.75);
  const best = Math.max(...pool.map(p => p.lv));
  const comps = pool.slice().sort((a, b) => b.w - a.w).slice(0, 12)
    .map(p => ({ ...p.x, age: p.age, level: p.lv, weight: p.w }));
  const r1 = v => Math.round(v * 10) / 10;
  // 車位：比對成交裡有分開登錄車位價格的，取每個車位的坪數與價格（加權中位數）
  let park = null;
  if (q.park > 0 && q.ping) {
    const withPark = pool.filter(p => p.x.pk > 0 && p.x.pkp > 0 && p.x.pka > 0);
    if (withPark.length >= 3) {
      const med = f => wQuantile(withPark.map(p => [f(p.x), p.w]).sort((a, b) => a[0] - b[0]), 0.5);
      const area = med(x => x.pka / x.pk), price = med(x => x.pkp / x.pk);
      if (area * q.park < q.ping * 0.6) park = { n: withPark.length, area: r1(area), price: Math.round(price), count: q.park };
    }
  }
  const total = u => !q.ping ? null : Math.round(park ? u * (q.ping - park.area * park.count) + park.price * park.count : u * q.ping);
  const floorN = q.floor != null ? pool.filter(p => p.x.fl != null && Math.abs(p.x.fl - q.floor) <= 3).length : null;
  return { ok: true, n: pool.length, months: used.months, uLo: r1(lo), uMid: r1(mid), uHi: r1(hi),
    tLo: total(lo), tMid: total(mid), tHi: total(hi), park, floorN,
    level: ["同區", "同一條路", "同一條巷", "同一棟"][best], nearN: pool.filter(p => p.lv === best).length, comps, year };
}
// 開價和合理區間比：回傳 {pos: "低於"|"區間內"|"高於", pct}
export function judgePrice(est, priceWan) {
  if (!est || !est.ok || !priceWan || !est.tMid) return null;
  const pct = (priceWan - est.tMid) / est.tMid * 100;
  return { pct, pos: priceWan < est.tLo ? "低於" : priceWan > est.tHi ? "高於" : "區間內" };
}

// ------------------------------------------------------------------ 交屋前要準備的現金（買方負擔的稅費，與 core/prices.purchase_costs 相同）
// 稅費的計算基礎是「房屋評定現值」與「土地公告現值」，比市價低很多；沒填時用總價的固定比例粗估。
export const COST_DEFAULT = { hv: "", lv: "", agent: 2, reno: 0, scrivener: 2, bankFee: 1 };
export const COST_RATIO = { house: 0.10, land: 0.25 };      // 粗估：房屋評定現值≈總價 10%、土地公告現值≈總價 25%
export function purchaseCosts(priceWan, downPct, opt = {}) {
  const o = { ...COST_DEFAULT, ...opt }, num = v => (v === "" || v == null || isNaN(+v)) ? null : +v;
  if (!(priceWan > 0)) return null;
  const hv = num(o.hv) ?? priceWan * COST_RATIO.house, lv = num(o.lv) ?? priceWan * COST_RATIO.land;
  const est = num(o.hv) == null || num(o.lv) == null;
  const loan = Math.max(0, priceWan * (1 - downPct / 100)), down = priceWan - loan;
  const items = [
    ["down", "自備款（頭期款）", down, `總價 ${downPct}%`],
    ["deed", "契稅", hv * 0.06, "房屋評定現值 × 6%"],
    ["stamp", "印花稅", (hv + lv) * 0.001, "（房屋評定現值＋土地公告現值）× 0.1%"],
    ["reg", "產權登記規費", (hv + lv) * 0.001 + 0.016, "申報價值 × 0.1%＋書狀費"],
    ["mort", "抵押權設定規費", loan * 1.2 * 0.001, "貸款 × 1.2 × 0.1%"],
    ["scrivener", "代書費", num(o.scrivener) ?? 2, "行情約 1.5～2.5 萬"],
    ["escrow", "履約保證費", priceWan * 0.0003, "總價 0.06%，買賣雙方各半"],
    ["agent", "仲介服務費", priceWan * (num(o.agent) ?? 0) / 100, `總價 ${num(o.agent) ?? 0}%（行情約 1～2%，可議價；跟建商買免付）`],
    ["bank", "貸款開辦費、火險地震險", loan > 0 ? (num(o.bankFee) ?? 1) : 0, "依銀行而定"],
    ["reno", "裝潢、家具、搬家", num(o.reno) ?? 0, "自己估"],
  ];
  const fees = items.filter(([k]) => k !== "down").reduce((s, it) => s + it[2], 0);
  return { items, down, loan, fees, total: down + fees, estimated: est, hv, lv };
}

// ------------------------------------------------------------------ 買房 vs 租房：同樣的錢，N 年後誰的資產多
// 一開始兩邊都有「自備款＋買房稅費」這筆現金：買方拿去付頭期，租方拿去投資。
// 之後每個月，買方付房貸＋持有成本、租方付房租；誰付得少，差額就拿去投資（年報酬 inv%）。
// N 年後：買方資產＝房子市值（扣賣屋成本）－剩餘房貸＋投資；租方資產＝投資。
export const RVB_DEFAULT = { years: 20, g: 1.5, rg: 1, inv: 4, hold: 0.5, sell: 3 };
export function rentVsBuy(p) {
  const o = { ...RVB_DEFAULT, ...p };
  const price = o.price * 10000, cash0 = (o.cash ?? o.price * o.down / 100) * 10000;
  const loan = Math.max(0, o.price * (1 - o.down / 100)) * 10000;
  const n = Math.round(o.loanYears * 12), r = o.rate / 100 / 12, g = Math.min(Math.round((o.grace || 0) * 12), Math.max(0, n - 12));
  if (!(price > 0) || !(o.rent > 0) || !(o.years > 0)) return null;
  const pay = m => m <= 0 ? 0 : r > 0 ? loan * r / (1 - Math.pow(1 + r, -m)) : loan / m;
  const monthly = pay(n - g), mInv = Math.pow(1 + o.inv / 100, 1 / 12) - 1;
  let bal = loan, buyInv = 0, rentInv = cash0, rent = o.rent, home = price;
  const years = [];
  let breakeven = null;
  for (let m = 1; m <= o.years * 12; m++) {
    let mort = 0;
    if (bal > 0 && m <= n) {
      const interest = bal * r;
      mort = m <= g ? interest : monthly;
      bal = Math.max(0, bal - (mort - interest));
    }
    const buyOut = mort + home * o.hold / 100 / 12;
    buyInv *= 1 + mInv; rentInv *= 1 + mInv;
    if (buyOut > rent) rentInv += buyOut - rent; else buyInv += rent - buyOut;
    home *= Math.pow(1 + o.g / 100, 1 / 12);
    if (m % 12 === 0) rent *= 1 + o.rg / 100;
    if (m % 12 === 0) {
      const buy = home * (1 - o.sell / 100) - bal + buyInv, rnt = rentInv;
      years.push({ y: m / 12, buy: buy / 10000, rent: rnt / 10000 });
      if (breakeven == null && buy >= rnt) breakeven = m / 12;
    }
  }
  const end = years[years.length - 1];
  return { years, breakeven, end, monthly, rentStart: o.rent, cash0: cash0 / 10000 };
}

// ------------------------------------------------------------------ 租金行情（tools/export_tw.py 產生的 rent.json）
// 每格：[件數, 月租中位(元), 每坪月租中位(元), 坪數中位]
export const RENT_MIN_N = 5;
export const RENT_ROOMS = [["1", "1 房"], ["2", "2 房"], ["3", "3 房"], ["4", "4 房以上"], ["s", "套房／雅房"]];
export function rentCell(rb, name, cat = "all") {
  const c = rb && rb.data && rb.data[name];
  const v = c && c[cat];
  return v && v[0] ? { n: v[0], rent: v[1], unit: v[2], ping: v[3] } : null;
}
// 毛租金報酬率（%）＝每坪月租 × 12 ÷ 每坪房價；saleU 為萬/坪
export function grossYield(rentUnit, saleU) {
  return rentUnit && saleU ? rentUnit * 12 / (saleU * 10000) * 100 : null;
}

// ------------------------------------------------------------------ 安全出價與議價空間估算
export function safetyBid(est, askingWan = null) {
  if (!est || !est.ok || !est.tMid) return null;
  const mid = est.tMid, lo = est.tLo, hi = est.tHi;
  const offerWan = Math.round(Math.min(lo, mid * 0.92));
  const targetWan = Math.round(mid);
  const ceilingWan = Math.round(Math.max(hi, mid * 1.08));

  let askingAnalysis = null;
  if (askingWan && askingWan > 0) {
    const markupPct = (askingWan - targetWan) / targetWan * 100;
    const discountToTarget = targetWan / askingWan * 10;
    const discountToOffer = offerWan / askingWan * 10;
    let verdict = "";
    if (askingWan <= offerWan) verdict = "開價極甜，接近甚至低於起標價，留意是否有特殊瑕疵";
    else if (askingWan <= targetWan) verdict = "開價合理，略高於起標價，議價空間約 95~98 折";
    else if (askingWan <= ceilingWan) verdict = "開價偏高但屬一般開價常態，建議從 " + discountToOffer.toFixed(1) + " 折開始斡旋";
    else verdict = "開價高於合理上限，溢價高達 +" + markupPct.toFixed(0) + "%，建議大膽從 " + discountToOffer.toFixed(1) + " 折下斡";

    askingAnalysis = {
      askingWan, markupPct: +markupPct.toFixed(1), discountToTarget: +discountToTarget.toFixed(1),
      discountToOffer: +discountToOffer.toFixed(1), verdict
    };
  }
  return { offerWan, targetWan, ceilingWan, uLo: est.uLo, uMid: est.uMid, uHi: est.uHi, askingAnalysis };
}

// ------------------------------------------------------------------ 新青安寬限期斷崖與家庭所得體檢
export function youthLoanCliff(priceWan, downPct = 20, incomeMonthly = 0, opt = {}) {
  const youthMax = opt.youthMaxWan ?? YOUTH_LOAN.cap;
  const yRate = opt.youthRate ?? YOUTH_LOAN.rate;
  const nRate = opt.normalRate ?? NORMAL_LOAN.rate;
  const loanTotalWan = Math.max(0, priceWan * (1 - downPct / 100));
  if (!(loanTotalWan > 0)) return null;

  const youthWan = Math.min(loanTotalWan, youthMax);
  const normalWan = Math.max(0, loanTotalWan - youthMax);

  const yMonths = YOUTH_LOAN.years * 12, yGrace = YOUTH_LOAN.grace * 12;
  const yr = yRate / 100 / 12;
  const yGraceMonthly = youthWan * 10000 * yr;
  const yPostMonthly = youthWan * 10000 * yr / (1 - Math.pow(1 + yr, -(yMonths - yGrace)));

  const nMonths = (opt.normalYears ?? NORMAL_LOAN.years) * 12, nr = nRate / 100 / 12;
  const nMonthly = normalWan > 0 ? (nr > 0 ? normalWan * 10000 * nr / (1 - Math.pow(1 + nr, -nMonths)) : normalWan * 10000 / nMonths) : 0;

  const period1 = Math.round(yGraceMonthly + nMonthly);
  const period2 = Math.round(yPostMonthly + nMonthly);
  const cliffDiff = period2 - period1;
  const cliffPct = period1 > 0 ? (cliffDiff / period1 * 100) : 0;

  let incomeEval = null;
  if (incomeMonthly > 0) {
    const ratio1 = period1 / incomeMonthly * 100;
    const ratio2 = period2 / incomeMonthly * 100;
    let safeStatus = "safe";
    if (ratio2 > 50) safeStatus = "danger";
    else if (ratio2 > 35) safeStatus = "warning";
    incomeEval = {
      incomeMonthly, ratio1: +ratio1.toFixed(1), ratio2: +ratio2.toFixed(1),
      safeStatus,
      safeMonthly: Math.round(incomeMonthly / 3),
    };
  }

  return {
    loanTotalWan, youthWan, normalWan, normalRate: nRate,
    period1, period2, cliffDiff, cliffPct: +cliffPct.toFixed(1),
    incomeEval
  };
}

// 用收入和手上現金反推可負擔總價：月付不超過收入 1/3（貸款以新青安＋一般房貸計），自備款不少於總價 downPct%；
// 另外要留交屋稅費雜支（約總價 3%）。回傳兩個限制取比較小的那個。
export function budgetFromIncome(incomeMonthly, cashWan, downPct = 20) {
  const a = affordableBudget(incomeMonthly, downPct);
  if (!a) return null;
  const cash = +cashWan > 0 ? +cashWan : null;
  const byCash = cash ? Math.floor(cash / (downPct / 100 + 0.03)) : null;
  const byIncome = Math.round(a.maxLoanWan + (cash ? Math.max(0, cash - (a.maxLoanWan + cash) * 0.03) : a.downWan));
  const price = byCash != null ? Math.min(byCash, byIncome) : a.maxPriceWan;
  return { price, byCash, byIncome: byCash != null ? byIncome : a.maxPriceWan, limit: byCash != null && byCash < byIncome ? "cash" : "income", safeMonthly: a.safeMonthly };
}
export function affordableBudget(incomeMonthly, downPct = 20, opt = {}) {
  if (!(incomeMonthly > 0)) return null;
  const safeMonthly = incomeMonthly / 3;
  const yRate = (opt.youthRate ?? YOUTH_LOAN.rate) / 100 / 12;
  const nRate = (opt.normalRate ?? NORMAL_LOAN.rate) / 100 / 12;
  const yFactor = yRate / (1 - Math.pow(1 + yRate, -(YOUTH_LOAN.years - YOUTH_LOAN.grace) * 12));   // 以寬限期結束後的月付計
  const youthMaxMonthly = YOUTH_LOAN.cap * 10000 * yFactor;

  let maxLoanWan = 0;
  if (safeMonthly <= youthMaxMonthly) {
    maxLoanWan = safeMonthly / yFactor / 10000;
  } else {
    const remMonthly = safeMonthly - youthMaxMonthly;
    const nFactor = nRate / (1 - Math.pow(1 + nRate, -NORMAL_LOAN.years * 12));
    const extraLoanWan = remMonthly / nFactor / 10000;
    maxLoanWan = YOUTH_LOAN.cap + extraLoanWan;
  }
  const maxPriceWan = Math.round(maxLoanWan / (1 - downPct / 100));
  const downWan = Math.round(maxPriceWan * downPct / 100);
  return { maxPriceWan, downWan, maxLoanWan: Math.round(maxLoanWan), safeMonthly: Math.round(safeMonthly) };
}

// ------------------------------------------------------------------ 雙區 PK 擂台
export function duelCompare(a, b, cat = "all") {
  if (!a || !b) return null;
  const buA = a.book.best(a.name, cat, "u"), buB = b.book.best(b.name, cat, "u");
  const btA = a.book.best(a.name, cat, "t"), btB = b.book.best(b.name, cat, "t");
  const trA = a.book.trend(a.name, cat, "u"), trB = b.book.trend(b.name, cat, "u");
  const rcA = rentCell(a.rent, a.name), rcB = rentCell(b.rent, b.name);
  const yldA = grossYield(rcA?.unit, buA.value), yldB = grossYield(rcB?.unit, buB.value);
  const gapA = a.book.presaleGap ? a.book.presaleGap(a.name) : null;
  const gapB = b.book.presaleGap ? b.book.presaleGap(b.name) : null;

  const rounds = [
    {
      key: "price_u", label: "單價門檻", unit: "萬/坪",
      valA: buA.value != null ? +buA.value.toFixed(1) : null,
      valB: buB.value != null ? +buB.value.toFixed(1) : null,
      win: buA.value != null && buB.value != null ? (buA.value < buB.value ? "A" : buA.value > buB.value ? "B" : "T") : null,
      note: "單價低者勝（負擔較輕）"
    },
    {
      key: "price_t", label: "總價門檻", unit: "萬",
      valA: btA.value != null ? Math.round(btA.value) : null,
      valB: btB.value != null ? Math.round(btB.value) : null,
      win: btA.value != null && btB.value != null ? (btA.value < btB.value ? "A" : btA.value > btB.value ? "B" : "T") : null,
      note: "總價低者勝（自備款門檻低）"
    },
    {
      key: "trend", label: "近半年漲跌", unit: "%",
      valA: trA != null ? +trA.toFixed(1) : null,
      valB: trB != null ? +trB.toFixed(1) : null,
      win: trA != null && trB != null ? (trA > trB ? "A" : trA < trB ? "B" : "T") : null,
      note: "動能強者勝（增值力道）"
    },
    {
      key: "yield", label: "租金毛投報", unit: "%",
      valA: yldA != null ? +yldA.toFixed(2) : null,
      valB: yldB != null ? +yldB.toFixed(2) : null,
      win: yldA != null && yldB != null ? (yldA > yldB ? "A" : yldA < yldB ? "B" : "T") : null,
      note: "投報高者勝（收租現金流優勢）"
    },
    {
      key: "presale_gap", label: "預售溢價差", unit: "%",
      valA: gapA != null ? Math.round(gapA) : null,
      valB: gapB != null ? Math.round(gapB) : null,
      win: gapA != null && gapB != null ? (gapA < gapB ? "A" : gapA > gapB ? "B" : "T") : null,
      note: "溢價低者勝（預售合理性）"
    }
  ];

  let scoreA = 0, scoreB = 0;
  rounds.forEach(r => {
    if (r.win === "A") scoreA++;
    else if (r.win === "B") scoreB++;
  });

  let verdict = "";
  if (scoreA > scoreB) {
    verdict = `${a.name} 在多項指標中以 ${scoreA}:${scoreB} 勝出，性價比與總體負擔具優勢！`;
  } else if (scoreB > scoreA) {
    verdict = `${b.name} 在多項指標中以 ${scoreB}:${scoreA} 勝出，動能與綜合潛力較佳！`;
  } else {
    verdict = `兩區各擅勝場（${scoreA}:${scoreB} 平手），可依自住剛需或投資目標評估。`;
  }

  return { rounds, scoreA, scoreB, verdict, nameA: a.name, nameB: b.name };
}

// ------------------------------------------------------------------ 即時搜尋與自動補全（Google Maps 風格）
const SECTION_NORM = { "1段": "一段", "2段": "二段", "3段": "三段", "4段": "四段", "5段": "五段", "6段": "六段", "7段": "七段", "8段": "八段", "9段": "九段" };

export function normSearchQuery(str) {
  let s = normTw(str || "").trim().toLowerCase();
  for (const [k, v] of Object.entries(SECTION_NORM)) s = s.replace(k, v);
  return s;
}

export function buildRoadCatalog(txs) {
  if (!txs || !txs.length) return [];
  const map = new Map();
  for (const x of txs) {
    const r = x.road;
    if (!r || r === "其他") continue;
    let entry = map.get(r);
    if (!entry) {
      entry = { road: r, dists: new Set(), n: 0, latestU: x.u };
      map.set(r, entry);
    }
    entry.dists.add(x.dist);
    entry.n++;
  }
  return Array.from(map.values()).map(it => ({
    road: it.road,
    dists: Array.from(it.dists),
    n: it.n,
    latestU: it.latestU
  })).sort((a, b) => b.n - a.n);
}

// 知名縮寫、大學、名校與地標別名對照表
export const SEARCH_ALIASES = [
  { keys: ["成大", "成功大學"], target: "國立成功大學" },
  { keys: ["台大", "台灣大學"], target: "國立臺灣大學" },
  { keys: ["清大", "清華大學"], target: "國立清華大學" },
  { keys: ["交大", "陽明交大"], target: "陽明交通大學" },
  { keys: ["南科", "台積電"], target: "南科台積電廠區" },
  { keys: ["南紡", "南紡夢時代", "南紡購物"], target: "南紡購物中心" },
  { keys: ["新光三越", "新光", "西門新天地", "新天地"], target: "新光三越台南新天地" },
  { keys: ["三井", "三井outlet", "outlet", "mitsui"], target: "MITSUI OUTLET PARK 台南" },
  { keys: ["好市多", "costco"], target: "好市多台南店" },
  { keys: ["成大醫院", "成醫"], target: "成大醫院" },
  { keys: ["奇美醫院", "永康奇美"], target: "奇美醫院" },
  { keys: ["市立醫院", "市醫"], target: "台南市立醫院" },
  { keys: ["花園夜市"], target: "花園夜市" },
  { keys: ["大東夜市"], target: "大東夜市" },
  { keys: ["武聖夜市"], target: "武聖夜市" },
  { keys: ["巴克禮", "巴克禮公園"], target: "巴克禮紀念公園" },
  { keys: ["文化中心", "臺南文化中心"], target: "臺南文化中心" },
  { keys: ["新市車站", "新市火車站"], target: "新市火車站" },
  { keys: ["善化車站", "善化火車站"], target: "善化火車站" },
  { keys: ["永康車站", "永康火車站"], target: "永康火車站" },
  { keys: ["藍晒圖", "藍曬圖"], target: "藍晒圖文創園區" },
  { keys: ["亞太棒球場", "亞太棒球村", "亞太國際棒球"], target: "亞太國際棒球訓練中心" },
  { keys: ["台南棒球場", "市立棒球場", "統一獅主場"], target: "台南市立棒球場" },
  { keys: ["迎曦湖", "南科管理局"], target: "南部科學園區管理局" },
  { keys: ["赤崁", "赤嵌樓"], target: "赤崁樓" },
  { keys: ["安平古堡", "熱蘭遮城"], target: "安平古堡" },
  { keys: ["奇美", "奇美博物館"], target: "奇美博物館" },
  { keys: ["101", "台北101"], target: "台北101" },
  { keys: ["大巨蛋", "台北大巨蛋"], target: "臺北大巨蛋" },
  { keys: ["小巨蛋", "台北小巨蛋"], target: "臺北小巨蛋" },
  { keys: ["台南高鐵", "高鐵台南"], target: "高鐵台南站" },
  { keys: ["台南車站", "台南火車站"], target: "臺南車站" },
  { keys: ["台北車站", "台北火車站", "北車"], target: "台北車站" },
  { keys: ["新竹高鐵", "高鐵新竹"], target: "高鐵新竹站" },
  { keys: ["桃園高鐵", "高鐵桃園"], target: "高鐵桃園站" },
  { keys: ["台中高鐵", "高鐵台中"], target: "高鐵台中站" },
  { keys: ["南一中", "台南一中"], target: "臺南第一高級中學" },
  { keys: ["後甲", "後甲國中"], target: "後甲國民中學" },
  { keys: ["建興", "建興國中"], target: "建興國民中學" },
  { keys: ["復興", "復興國中"], target: "復興國民中學" },
  { keys: ["崇明", "崇明國中"], target: "崇明國民中學" },
  { keys: ["南科實中", "南科國中"], target: "南科國際實驗高級中學" },
  { keys: ["小新", "小新國小"], target: "小新國民小學" },
  { keys: ["建中", "建國中學"], target: "中正國民中學" },
  { keys: ["師大附中", "附中"], target: "臺灣師範大學附屬高級中學" },
  { keys: ["金華", "金華國中"], target: "金華國民中學" },
  { keys: ["敦化", "敦化國中"], target: "敦化國民中學" },
  { keys: ["海山", "海山高中"], target: "海山高級中學" },
  { keys: ["培英", "培英國中"], target: "培英國民中學" },
  { keys: ["光武", "光武國中"], target: "光武國民中學" },
  { keys: ["成功國中"], target: "成功國民中學" },
  { keys: ["東興國中"], target: "東興國民中學" },
  { keys: ["居仁", "居仁國中"], target: "居仁國民中學" },
  { keys: ["惠文", "惠文高中"], target: "惠文高級中學" },
  { keys: ["七賢", "七賢國中"], target: "七賢國民中學" },
  { keys: ["陽明國中"], target: "陽明國民中學" },
  { keys: ["平實", "平實營區"], target: "平實營區重劃區" },
  { keys: ["捷運藍線", "藍線"], target: "捷運" }
];

export function landmarkMeta(lm) {
  const cat = lm.category || "";
  const name = lm.name || "";
  const note = lm.note || "";
  if (cat === "nightmarket" || name.includes("夜市") || note.includes("夜市")) {
    return { icon: "🍢", badge: "知名夜市" };
  }
  if (cat === "mall" || name.includes("購物") || name.includes("三越") || name.includes("百貨") || name.includes("Outlet") || name.includes("Costco") || name.includes("好市多")) {
    return { icon: "🛍️", badge: "核心商圈" };
  }
  if (cat === "hospital" || name.includes("醫院")) {
    return { icon: "🏥", badge: "醫療中心" };
  }
  if (cat === "station" || name.includes("火車站") || name.includes("車站") || name.includes("高鐵")) {
    return { icon: "🚄", badge: "交通樞紐" };
  }
  if (cat === "tech" || name.includes("科學園區") || name.includes("晶圓") || name.includes("台積電")) {
    return { icon: "🏢", badge: "科技園區" };
  }
  if (cat === "park" || name.includes("公園") || name.includes("湖") || name.includes("綠色隧道")) {
    return { icon: "🌳", badge: "公園休閒" };
  }
  if (name.includes("棒球") || note.includes("棒球場")) {
    return { icon: "⚾", badge: "體育休閒" };
  }
  if (name.includes("美術館") || name.includes("博物館") || name.includes("文化中心") || name.includes("文創")) {
    return { icon: "🎨", badge: "藝文地標" };
  }
  if (name.includes("廟") || name.includes("寺") || name.includes("天后宮")) {
    return { icon: "⛩️", badge: "名勝古剎" };
  }
  return { icon: "🏛️", badge: "知名地標" };
}

export const LANDMARK_CATEGORIES = [
  { label: "核心商圈", icon: "🛍️", kw: "商圈" },
  { label: "知名夜市", icon: "🍢", kw: "夜市" },
  { label: "醫療中心", icon: "🏥", kw: "醫院" },
  { label: "交通樞紐", icon: "🚄", kw: "車站" },
  { label: "公園綠地", icon: "🌳", kw: "公園" },
  { label: "明星學區", icon: "🎓", kw: "學區" }
];

export function popularLandmarks(data, options = {}) {
  const landmarks = data.landmarks || [];
  const currentDist = options.currentDistrict || "";
  const limit = options.limit || 8;
  const scored = [];

  for (const lm of landmarks) {
    const meta = landmarkMeta(lm);
    let score = (4 - (lm.rank || 2)) * 20;
    if (currentDist && lm.district === currentDist) score += 200;
    if (["🛍️", "🍢", "🏥", "🚄", "🏢"].includes(meta.icon)) score += 30;
    scored.push({ lm, meta, score });
  }

  scored.sort((a, b) => b.score - a.score || a.lm.name.localeCompare(b.lm.name));
  return scored.slice(0, limit).map(({ lm, meta }) => ({
    type: "landmark",
    title: lm.name,
    sub: `${lm.district || ""} · ${lm.note ? lm.note.slice(0, 24) + "..." : meta.badge}`,
    icon: meta.icon,
    badge: meta.badge,
    lm
  }));
}

// ------------------------------------------------------------------ 車站搜尋（台鐵、高鐵、捷運、輕軌）
// 「善化車站」「善化火車站」「台鐵善化站」「台南高鐵站」「捷運美麗島」都對到同一個站名主幹
export function stationBase(s) {
  return normTw(s || "").replace(/[（(].*$/, "").replace(/\s+/g, "")
    .replace(/^(台鐵|捷運|高鐵|輕軌)/, "").replace(/(火車站|高鐵站|捷運站|輕軌站|車站|站|火車|車)$/, "");     // 結尾的「火車」「車」：邊打邊提示用
}
export function stationKindHint(text) {
  const t = normTw(text || "");
  return /高鐵/.test(t) ? "高鐵" : /捷運/.test(t) ? "捷運" : /輕軌/.test(t) ? "輕軌" : /火車|台鐵/.test(t) ? "台鐵" : "";
}
// lines: [{name, kind, operating, stations: [[站名, lat, lng], …]}]；回傳依「種類符合 → 營運中 → 台鐵優先」排序的 [{line, st}]
export function findStations(text, lines, prefix = false) {
  const base = stationBase(text), hint = stationKindHint(text);
  if (!base) return [];
  const out = [];
  for (const ln of lines || []) for (const st of ln.stations || []) {
    const b = stationBase(st[0]);
    if (b === base || (prefix && base.length >= 2 && b.startsWith(base))) out.push({ line: ln, st, exact: b === base });
  }
  const kindOf = ln => ln.kind || (ln.operating === false ? "規劃" : "捷運");
  const rank = x => (x.exact ? 0 : 4) + (hint && kindOf(x.line) === hint ? 0 : 2) + (x.line.operating === false ? 1 : 0)
    + (!hint && kindOf(x.line) !== "台鐵" ? 0.5 : 0);
  return out.sort((a, b) => rank(a) - rank(b));
}

export function quickSuggest(rawText, data, options = {}) {
  const query = normSearchQuery(rawText);
  if (!query) return [];
  const limit = options.limit || 8;
  const currentDist = options.currentDistrict || "";
  const cityName = options.cityName || CITY || "台南市";
  const results = [];

  const districts = data.districts || [];
  const roadCatalog = data.roadCatalog || [];
  const landmarks = data.landmarks || [];
  const schools = data.schools || [];
  const intel = data.intel || [];
  const twCounties = data.twCounties || [];

  // 1. 如果輸入包含號、弄、巷等特定門牌，先做精準門牌地址解析
  const distNames = districts.map(d => d.name);
  const parsed = parseAddress(rawText, distNames);
  if (parsed.road && (parsed.num != null || parsed.lane != null)) {
    const fullDesc = `${parsed.district ? parsed.district + " " : ""}${describe(parsed)}`;
    results.push({
      type: "address",
      title: fullDesc,
      sub: "精準門牌定位 · 查看周邊成交行情",
      icon: "📍",
      badge: "門牌地址",
      score: 2000,
      addr: parsed
    });
  }

  // 2. 行政區比對 (Districts)
  for (const d of districts) {
    const dName = normTw(d.name).toLowerCase();
    const dStem = dName.replace(/區|鄉|鎮|市$/, "");
    let score = 0;
    if (dName === query || dStem === query) score = 1000;
    else if (dName.startsWith(query) || dStem.startsWith(query)) score = 700;
    else if (dName.includes(query) || query.includes(dStem)) score = 400;
    if (score > 0) {
      if (d.name === currentDist) score += 120;
      results.push({
        type: "district",
        title: d.name,
        sub: `${cityName} · 行政區行情`,
        icon: "📍",
        badge: "行政區",
        score,
        name: d.name,
        d
      });
    }
  }

  // 3. 全台其他縣市與鄉鎮 (TW Counties & Towns)
  if (twCounties.length) {
    for (const c of twCounties) {
      const cName = normTw(c.name).toLowerCase();
      const cShort = normTw(c.short).toLowerCase();
      if (cName.includes(query) || cShort.includes(query) || query.includes(cShort)) {
        results.push({
          type: "county",
          title: c.name,
          sub: "全台縣市行情動態",
          icon: "🗺️",
          badge: "縣市",
          score: 820,
          countyCode: c.code,
          c
        });
      }
      for (const t of (c.town_names || [])) {
        const tNorm = normTw(t).toLowerCase();
        if (tNorm === query || (query.length >= 2 && (tNorm.includes(query) || query.includes(tNorm)))) {
          results.push({
            type: "tw_district",
            title: `${c.short} ${t}`,
            sub: `${c.name} · 行政區`,
            icon: "📍",
            badge: "行政區",
            score: 760,
            countyCode: c.code,
            town: t
          });
        }
      }
    }
  } else {
    // 台南單一縣市專版：若使用者搜尋外縣市（台中、台北、高雄等），提示暫未收錄
    for (const c of COUNTIES) {
      if (c.code === "D") continue;
      const cName = normTw(c.name).toLowerCase();
      const cShort = normTw(c.short).toLowerCase();
      if (cName.includes(query) || cShort.includes(query) || (query.length >= 2 && (cShort.includes(query) || query.includes(cShort)))) {
        results.push({
          type: "other_county",
          title: c.short,
          sub: `目前為台南實價專版，尚未收錄此縣市`,
          icon: "🗺️",
          badge: "其他縣市",
          score: 820,
          countyCode: c.code,
          c
        });
      }
    }
  }

  // 4. 明星學區比對 (Schools)
  for (const sc of schools) {
    const sName = normTw(sc.name).toLowerCase();
    let score = 0;
    if (sName === query) score = 960;
    else if (sName.startsWith(query)) score = 660;
    else if (sName.includes(query)) score = 450;
    else if (query === "學區" || query === "明星學區" || (query.length >= 2 && "明星學區".includes(query))) {
      score = 420;
    } else {
      for (const al of SEARCH_ALIASES) {
        if (al.keys.some(k => query.includes(k) || k.includes(query)) && sName.includes(al.target.toLowerCase())) {
          score = 620;
          break;
        }
      }
    }
    if (score > 0) {
      if (sc.district === currentDist) score += 90;
      results.push({
        type: "school",
        title: sc.name,
        sub: `${sc.district || ""} · ${sc.status}（${sc.type}）`,
        icon: "🎓",
        badge: "明星學區",
        score,
        school: sc
      });
    }
  }

  // 5. 地標比對 (Landmarks)
  for (const lm of landmarks) {
    const lName = normTw(lm.name).toLowerCase();
    const lNote = normTw(lm.note || "").toLowerCase();
    const lCat = (lm.category || "").toLowerCase();
    const meta = landmarkMeta(lm);
    let score = 0;

    if (lName === query) score = 950;
    else if (lName.startsWith(query)) score = 680;
    else if (lName.includes(query)) score = 420;
    else if (lNote.includes(query)) score = 340;
    else {
      for (const al of SEARCH_ALIASES) {
        if (al.keys.some(k => query.includes(k) || k.includes(query))) {
          if (lName.includes(al.target.toLowerCase()) || lNote.includes(al.target.toLowerCase())) {
            score = 620;
            break;
          }
        }
      }
    }

    if (!score) {
      if ((query === "夜市" || query.includes("夜市")) && (lCat === "nightmarket" || meta.badge === "知名夜市" || lName.includes("夜市") || lNote.includes("夜市"))) {
        score = 550;
      } else if ((query === "商圈" || query === "百貨" || query === "購物" || query === "量販" || query === "outlet" || query === "costco" || query === "好市多") && (lCat === "mall" || meta.badge === "核心商圈" || lName.includes("購物") || lName.includes("三越") || lName.includes("好市多") || lNote.includes("百貨") || lNote.includes("商圈") || lNote.includes("outlet"))) {
        score = 540;
      } else if ((query === "醫院" || query === "醫療" || query === "成醫" || query === "奇美") && (lCat === "hospital" || meta.badge === "醫療中心" || lName.includes("醫院") || lNote.includes("醫院") || lNote.includes("醫學中心"))) {
        score = 540;
      } else if ((query === "車站" || query === "火車站" || query === "高鐵" || query === "台鐵") && (lCat === "station" || meta.badge === "交通樞紐" || lName.includes("站") || lNote.includes("車站") || lNote.includes("高鐵"))) {
        score = 530;
      } else if ((query === "公園" || query === "綠地" || query === "生態") && (lCat === "park" || meta.badge === "公園休閒" || lName.includes("公園") || lNote.includes("公園") || lNote.includes("綠地"))) {
        score = 510;
      } else if ((query === "科技" || query === "科學園區" || query === "園區" || query === "南科") && (lCat === "tech" || meta.badge === "科技園區" || lName.includes("園區") || lNote.includes("科學園區") || lNote.includes("園區"))) {
        score = 520;
      } else if ((query === "棒球" || query === "球場" || query === "棒球場") && (lName.includes("棒球") || lNote.includes("棒球"))) {
        score = 520;
      }
    }

    if (score > 0) {
      const isOtherCounty = lm.county && lm.county !== "D";
      const co = COUNTIES.find(x => x.code === lm.county);
      const coShort = co ? co.short : "";
      if (lm.district === currentDist) score += 90;
      score += Math.max(0, (4 - (lm.rank || 2)) * 15);
      if (isOtherCounty && !twCounties.length) score -= 80;
      results.push({
        type: "landmark",
        title: lm.name,
        sub: (isOtherCounty && !twCounties.length) ? `${lm.district || ""} · ${coShort}（台南專版暫未收錄行情）` : `${lm.district || ""} · ${lm.note ? lm.note.slice(0, 24) + "..." : meta.badge}`,
        icon: meta.icon,
        badge: (isOtherCounty && !twCounties.length) ? `${coShort}（未收錄）` : meta.badge,
        score,
        lm,
        isOtherCounty,
        countyCode: lm.county || "D"
      });
    }
  }

  // 6. 重大建設與重劃區 (Projects/Intel)
  for (const pr of intel) {
    if (!pr.build && !pr.name) continue;
    const pName = normTw(pr.name).toLowerCase();
    let score = 0;
    if (pName === query) score = 890;
    else if (pName.startsWith(query)) score = 590;
    else if (pName.includes(query)) score = 380;
    else {
      for (const al of SEARCH_ALIASES) {
        if (al.keys.some(k => query.includes(k) || k.includes(query)) && pName.includes(al.target.toLowerCase())) {
          score = 560;
          break;
        }
      }
    }
    if (score > 0) {
      const b = pr.build;
      const sub = b ? (b.done ? `預計 ${b.done} 完工 · 重大建設` : "建設進行中") : "都市規劃";
      results.push({
        type: "project",
        title: pr.name,
        sub: `${pr.district ? pr.district + " · " : ""}${sub}`,
        icon: "🏗️",
        badge: "重大建設",
        score,
        pr
      });
    }
  }

  // 7. 路段比對 (Roads)
  for (const r of roadCatalog) {
    const rName = normSearchQuery(r.road);
    let score = 0;
    if (rName === query) score = 860;
    else if (rName.startsWith(query)) score = 570;
    else if (rName.includes(query)) score = 330;
    if (score > 0) {
      const inCurrent = r.dists.includes(currentDist);
      if (inCurrent) score += 140;
      score += Math.min(80, r.n);
      const preferredDist = inCurrent ? currentDist : r.dists[0];
      const distLabel = r.dists.length === 1 ? r.dists[0] : inCurrent ? `${currentDist}（跨${r.dists.length}區）` : r.dists.join("、");
      results.push({
        type: "road",
        title: r.road,
        sub: `${distLabel} · 近年 ${r.n} 筆實價登錄成交`,
        icon: "🛣️",
        badge: "實價路段",
        score,
        dist: preferredDist,
        road: r.road,
        dists: r.dists
      });
    }
  }

  // 8. 車站（台鐵、高鐵、捷運、輕軌）：輸入有「站」字，或站名完全相同時才列出
  if (data.lines && query.length >= 2) {
    const hasStationWord = /[站車]$|站/.test(rawText);
    for (const { line, st, exact } of findStations(rawText, data.lines, true).slice(0, 4)) {
      if (!exact && !hasStationWord) continue;
      const kind = line.kind || (line.operating === false ? "規劃捷運" : "捷運");
      results.push({
        type: "station",
        title: st[0],
        sub: `${line.name}${line.operating === false ? "（規劃中）" : ""}`,
        icon: kind === "台鐵" ? "🚆" : kind === "高鐵" ? "🚄" : "🚇",
        badge: kind === "台鐵" ? "火車站" : kind === "高鐵" ? "高鐵站" : kind.includes("輕軌") ? "輕軌站" : "捷運站",
        score: (exact ? (hasStationWord ? 990 : 640) : 560) + (line.operating === false ? -40 : 0),
        line: line.name,
        st
      });
    }
  }

  results.sort((a, b) => b.score - a.score);
  const seen = new Set();
  const deduped = [];
  for (const res of results) {
    const key = `${res.type}|${res.title}|${res.dist || ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(res);
      if (deduped.length >= limit) break;
    }
  }
  return deduped;
}



// ------------------------------------------------------------------ 看屋筆記：檢查表與分數
// 每一項記「好／普通／差」（2／1／0 分），沒填的不算；分數＝得分 ÷ 已填項目滿分
export const VISIT_CHECKS = [
  ["light", "採光、通風"], ["noise", "噪音（車流、鄰居、夜間）"], ["leak", "漏水、壁癌、天花板水漬"], ["crack", "牆面、樑柱裂縫"],
  ["water", "水壓、排水、熱水"], ["power", "電線、插座、電箱"], ["layout", "格局、坪數實用"], ["view", "座向、景觀、西曬"],
  ["mgmt", "管委會、公設維護、管理費"], ["parking", "停車（車位、機車）"], ["neighbor", "鄰居、社區氛圍"], ["street", "巷道寬度、出入、夜間照明"],
  ["smell", "氣味（垃圾、排水、工廠）"], ["school", "學區、生活機能"],
];
export const VISIT_MARKS = [["", "—"], ["2", "好"], ["1", "普通"], ["0", "差"]];
export function visitScore(check) {
  const vals = Object.values(check || {}).filter(v => v === "0" || v === "1" || v === "2").map(Number);
  if (!vals.length) return null;
  return { pct: Math.round(vals.reduce((a, b) => a + b, 0) / (vals.length * 2) * 100), n: vals.length,
           bad: Object.entries(check).filter(([, v]) => v === "0").map(([k]) => k) };
}

// ------------------------------------------------------------------ 看屋行程：排出最順的順序（最近鄰＋2-opt），開 Google 地圖多點導航
// pts: [{id, lat, lng}]；start：出發點 {lat, lng}（沒有就從第一間開始）。回傳 {order: [pts…], legs: [km…], km}
export function planTrip(pts, start = null) {
  pts = (pts || []).filter(p => p && p.lat != null && p.lng != null);
  if (!pts.length) return { order: [], legs: [], km: 0 };
  const d = (a, b) => distKm(a.lat, a.lng, b.lat, b.lng);
  const rest = pts.slice(), order = [];
  let cur = start || rest.shift();
  if (!start) order.push(cur);
  while (rest.length) {
    let bi = 0;
    for (let i = 1; i < rest.length; i++) if (d(cur, rest[i]) < d(cur, rest[bi])) bi = i;
    cur = rest.splice(bi, 1)[0]; order.push(cur);
  }
  // 2-opt：把交叉的兩段反過來，直到不再變短（路線不回到起點）
  const path = start ? [start, ...order] : order.slice();
  const len = p => p.slice(1).reduce((s, q, i) => s + d(p[i], q), 0);
  let improved = true;
  while (improved) {
    improved = false;
    for (let i = 1; i < path.length - 1; i++) for (let k = i + 1; k < path.length; k++) {
      const cand = path.slice(0, i).concat(path.slice(i, k + 1).reverse(), path.slice(k + 1));
      if (len(cand) < len(path) - 1e-9) { path.splice(0, path.length, ...cand); improved = true; }
    }
  }
  const out = start ? path.slice(1) : path;
  const legs = out.map((p, i) => i === 0 ? (start ? d(start, p) : 0) : d(out[i - 1], p));
  return { order: out, legs, km: legs.reduce((a, b) => a + b, 0) };
}
// Google 地圖多點導航（最多 9 個中途點）
export function tripUrl(order, start = null, mode = "car") {
  if (!order.length) return null;
  const ll = p => `${(+p.lat).toFixed(6)},${(+p.lng).toFixed(6)}`;
  const origin = start || order[0], stops = (start ? order : order.slice(1)).slice(0, 10);     // 9 個中途點＋終點
  if (!stops.length) return `https://www.google.com/maps/search/?api=1&query=${ll(origin)}`;
  const dest = stops[stops.length - 1], way = stops.slice(0, -1).slice(0, 9);
  return `https://www.google.com/maps/dir/?api=1&origin=${ll(origin)}&destination=${ll(dest)}` +
    (way.length ? `&waypoints=${encodeURIComponent(way.map(ll).join("|"))}` : "") + `&travelmode=${(MODES[mode] || MODES.car)[2]}`;
}

// ------------------------------------------------------------------ 賣屋／換屋試算（個人、房地合一稅 2.0；金額單位：萬）
// 房地合一：2016/1/1 以後取得的房地。課稅所得＝成交價－取得成本－費用（沒有單據按成交價 3%，最多 30 萬）－土地漲價總數額。
// 稅率依持有期間：2 年內 45%、2～5 年 35%、5～10 年 20%、超過 10 年 15%；自住（本人、配偶或未成年子女設籍且居住滿 6 年、
// 這 6 年沒有出租或營業）：課稅所得 400 萬以下免稅，超過的部分 10%。
// 2015 年底以前取得的適用舊制：只有房屋部分的財產交易所得併入綜合所得稅，這裡用「房屋評定現值 × 所得標準 × 邊際稅率」粗估。
export const SELL_DEFAULT = { sell: "", buy: "", bought: "", years: "", self: true, loan: "", agent: 4, landInc: "", landTax: "",
  oldHouseVal: "", oldStd: 40, oldRate: 12, fees: 1.5 };
export function hrTaxRate(years, self) {
  if (self && years >= 6) return null;                      // 自住優惠另算
  return years <= 2 ? 45 : years <= 5 ? 35 : years <= 10 ? 20 : 15;
}
export function sellHouse(o) {
  const n = v => (v === "" || v == null || isNaN(+v)) ? null : +v;
  const sell = n(o.sell), buy = n(o.buy), years = n(o.years);
  if (!(sell > 0)) return null;
  const agent = sell * (n(o.agent) ?? 4) / 100, fees = n(o.fees) ?? 1.5, loan = n(o.loan) ?? 0, landTax = n(o.landTax) ?? 0;
  let bought = n(o.bought);
  if (bought != null && bought > 0 && bought < 1000) bought += 1911;      // 填民國年（例如 105）也認得
  const old = bought != null && bought < 2016;
  let tax = 0, gain = null, taxable = null, rate = null, rule;
  if (old) {
    const hv = n(o.oldHouseVal) ?? sell * 0.1;
    taxable = hv * (n(o.oldStd) ?? 40) / 100;
    rate = n(o.oldRate) ?? 12;
    tax = taxable * rate / 100;
    rule = "舊制（2015 年底前取得）：房屋評定現值 × 所得標準，併入綜合所得稅";
  } else if (buy > 0 && years != null) {
    const expense = Math.min(30, sell * 0.03);
    gain = sell - buy;
    taxable = Math.max(0, gain - expense - (n(o.landInc) ?? 0));
    if (o.self && years >= 6) {
      rate = 10; tax = Math.max(0, taxable - 400) * 0.10;
      rule = "房地合一 2.0 自住優惠：設籍滿 6 年，400 萬以下免稅，超過部分 10%";
    } else {
      rate = hrTaxRate(years, false); tax = taxable * rate / 100;
      rule = `房地合一 2.0：持有 ${years} 年，稅率 ${rate}%`;
    }
  } else {
    rule = "要填買進價格與持有年數才能算房地合一稅";
  }
  const net = sell - loan - agent - fees - tax - landTax;
  return { sell, agent, fees, loan, tax, landTax, gain, taxable, rate, rule, old, net,
           missingLandTax: n(o.landTax) == null };
}
// 重購退稅：出售後 2 年內（或先買後賣）重購自住房屋，新屋價 ≥ 舊屋售價全額退，較低按比例退（房地合一稅、舊制皆有類似規定）
export function rebuyRefund(taxPaid, sellPrice, newPrice) {
  if (!(taxPaid > 0) || !(sellPrice > 0) || !(newPrice > 0)) return 0;
  return newPrice >= sellPrice ? taxPaid : taxPaid * newPrice / sellPrice;
}

// ------------------------------------------------------------------ 長期走勢（近 5 年，tools/build_long.py 產生的 long.json）
// 每月的中位數合成「每季」：件數加權平均（季檔摘要本身就是近似值，畫長期走勢足夠）
export function longSeries(lb, name, cat, metric = "u") {
  const c = lb && lb.data && lb.data[name] && lb.data[name][cat];
  if (!c) return [];
  const q = new Map();
  lb.months.forEach((m, i) => {
    const n = c.n[i], v = c[metric][i];
    if (!n || v == null) return;
    const k = `${m.slice(0, 4)}Q${Math.floor((+m.slice(5, 7) - 1) / 3) + 1}`;
    const a = q.get(k) || [0, 0];
    a[0] += n; a[1] += n * v; q.set(k, a);
  });
  return [...q.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([m, [n, s]]) => ({ m, v: s / n, n }));
}
// 近 N 年漲跌（%）：最近兩季的平均 vs N 年前同樣兩季的平均；兩邊件數都要夠
export function longChange(series, years, minN = 10) {
  if (!series || series.length < 6) return null;
  const idx = new Map(series.map((p, i) => [p.m, i]));
  const last = series.length - 1, end = series[last].m;
  const back = m => `${+m.slice(0, 4) - years}${m.slice(4)}`;
  const pick = i => series[i];
  const a = [pick(last), pick(last - 1)], b = [back(a[0].m), back(a[1].m)].map(m => idx.has(m) ? series[idx.get(m)] : null);
  if (b.some(x => !x) || [...a, ...b].some(x => x.n < minN / 2) || a[0].n + a[1].n < minN || b[0].n + b[1].n < minN) return null;
  const avg = xs => xs.reduce((s, x) => s + x.v * x.n, 0) / xs.reduce((s, x) => s + x.n, 0);
  return { pct: (avg(a) / avg(b) - 1) * 100, from: b[1].m, to: end, years };
}

// ------------------------------------------------------------------ 人口成長與年齡結構（tools/build_population.py 產生的 pop.json）
export function popInfo(pd, name) {
  const c = pd && pd.data && (pd.data[name] || pd.data[normTw(name)]);
  if (!c) return null;
  const ys = (pd.years || []).map(String).filter(y => c.pop[y]);
  const first = ys[0], last = ys[ys.length - 1], prev = ys[ys.length - 2];
  const pct = (a, b) => a && b ? (b / a - 1) * 100 : null;
  const age = c.age || [], tot = age.reduce((a, b) => a + b, 0);
  const share = tot ? age.map(v => v / tot * 100) : null;
  const work = tot ? age[1] + age[2] + age[3] : 0;
  const now = c.now || (last ? c.pop[last] : 0);
  const nm = (pd.mig_months || []).length, net = nm ? Math.round(((c.in12 || 0) - (c.out12 || 0)) * 12 / nm) : 0;   // 不滿 12 個月時換算成一年
  return {
    now, hh: c.hh || null, perHH: c.hh && c.now ? c.now / c.hh : null,
    chgAll: pct(c.pop[first], c.pop[last]), span: first && last ? +last - +first : 0, from: first, to: last,
    chg1: pct(c.pop[prev], c.pop[last]),
    share, old: share ? share[4] : null, young: share ? share[2] : null, kids: share ? share[0] : null,
    depOld: work ? age[4] / work * 100 : null,
    net: pd.mig_months && pd.mig_months.length ? net : null, netRate: now && pd.mig_months && pd.mig_months.length ? net / now * 1000 : null,
  };
}

// ------------------------------------------------------------------ 房價時光機：各區每一季的中位價（近 5 年），給地圖上的柱子用
// 件數太少（少於 minN）的季不畫，避免單一筆成交讓柱子忽高忽低；回傳 {quarters, vals: {區: [值或 null…]}, lo, hi}
export function timeTable(lb, names, cat, metric = "u", minN = 3) {
  if (!lb) return null;
  const series = Object.fromEntries(names.map(n => [n, longSeries(lb, n, cat, metric)]));
  const qs = [...new Set(Object.values(series).flatMap(s => s.map(p => p.m)))].sort();
  if (qs.length < 4) return null;
  const vals = {}, all = [];
  for (const n of names) {
    const m = new Map(series[n].filter(p => p.n >= minN).map(p => [p.m, p.v]));
    vals[n] = qs.map(q => m.has(q) ? m.get(q) : null);
    all.push(...vals[n].filter(v => v != null));
  }
  if (!all.length) return null;
  all.sort((a, b) => a - b);
  const pick = f => all[Math.min(all.length - 1, Math.max(0, Math.round(f * (all.length - 1))))];
  return { quarters: qs, vals, lo: pick(0.05), hi: pick(0.98) };
}
