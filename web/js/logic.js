// 資料與計算：房價統計、逐筆成交、路段、地址解析與門牌位置推估。
// 和桌面版 core/prices.py、core/roads.py、core/address.py 的邏輯一致（測試會比對結果）。

export const LAT0 = 23.145, LNG0 = 120.34;
export const KM_LAT = 110.57;
export const KM_LNG = 111.32 * Math.cos(LAT0 * Math.PI / 180);
export const CITY = "台南市";
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
// 和 Python 的 round() 一樣：剛好在中間時取偶數（統計值才會和桌面版完全一致）
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
               road: r[11], lane: r[12] < 0 ? null : r[12], alley: r[13] < 0 ? null : r[13], num: r[14] < 0 ? null : r[14] });
  }
  return out;
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
  out.sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
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
  for (const p of ["臺南市", "台南市", "臺南", "台南"]) {
    if (s.startsWith(p) && s.length > p.length) { s = s.slice(p.length); break; }
  }
  return s;
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

// ------------------------------------------------------------------ 到其他平台找物件（用 Google 站內搜尋，不爬取對方網站）
export const PLATFORMS = [["591", "sale.591.com.tw"], ["樂屋網", "rakuya.com.tw"], ["樂居", "leju.com.tw"],
                          ["永慶", "yungching.com.tw"], ["信義", "sinyi.com.tw"], ["住商", "hbhousing.com.tw"]];
export function platformLinks(district, place) {
  const where = `台南市${district === CITY ? "" : district}${place || ""}`;
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
  { key: "station", label: "火車站", ch: "站", color: "#4a3aa7", group: "good", r: 2000, q: ['nwr["railway"="station"]'], t: t => t.railway === "station" },
  { key: "bus", label: "公車站", ch: "公", color: "#4a3aa7", group: "good", r: 500, q: ['node["highway"="bus_stop"]'], t: t => t.highway === "bus_stop" },
  { key: "grave", label: "墓地／納骨塔", ch: "墓", color: "#5b6168", group: "bad", r: 1000, q: ['nwr["landuse"="cemetery"]', 'nwr["amenity"~"^(grave_yard|crematorium)$"]'], t: t => t.landuse === "cemetery" || /^(grave_yard|crematorium)$/.test(t.amenity || "") },
  { key: "funeral", label: "殯儀館／禮儀社", ch: "殯", color: "#5b6168", group: "bad", r: 500, q: ['nwr["amenity"="funeral_hall"]', 'nwr["shop"="funeral_directors"]'], t: t => t.amenity === "funeral_hall" || t.shop === "funeral_directors" },
  { key: "fuel", label: "加油站", ch: "油", color: "#eb6834", group: "bad", r: 300, q: ['nwr["amenity"="fuel"]'], t: t => t.amenity === "fuel" },
  { key: "power", label: "變電所", ch: "電", color: "#eda100", group: "bad", r: 500, q: ['nwr["power"="substation"]'], t: t => t.power === "substation" },
  { key: "waste", label: "垃圾場／焚化爐／污水廠", ch: "垃", color: "#8a5a2b", group: "bad", r: 1000, q: ['nwr["landuse"="landfill"]', 'nwr["amenity"="waste_transfer_station"]', 'nwr["man_made"="wastewater_plant"]', 'nwr["power"="plant"]["plant:source"="waste"]'], t: t => t.landuse === "landfill" || t.amenity === "waste_transfer_station" || t.man_made === "wastewater_plant" || (t.power === "plant" && t["plant:source"] === "waste") },
  { key: "temple", label: "宮廟（見仁見智）", ch: "廟", color: "#b5651d", group: "bad", r: 200, q: ['nwr["amenity"="place_of_worship"]["religion"~"^(taoist|buddhist|chinese_folk)$"]'], t: t => t.amenity === "place_of_worship" && /^(taoist|buddhist|chinese_folk)$/.test(t.religion || "") },
  { key: "industry", label: "工業區／工廠", ch: "工", color: "#7a3fb5", group: "bad", r: 500, q: ['way["landuse"="industrial"]', 'nwr["man_made"="works"]'], t: t => t.landuse === "industrial" || t.man_made === "works" },
];
export const POI_RADIUS = 2000;
export function poiQuery(lat, lng) {
  const parts = [];
  for (const c of POI_CATS) for (const q of c.q) parts.push(`${q}(around:${Math.min(c.r, POI_RADIUS)},${lat.toFixed(5)},${lng.toFixed(5)});`);
  return `[out:json][timeout:25];(${parts.join("")});out center tags 2000;`;
}
export function classifyPois(elements, lat, lng) {
  const items = [], seen = new Set();
  for (const e of elements || []) {
    const t = e.tags || {}, la = e.lat ?? (e.center && e.center.lat), lo = e.lon ?? (e.center && e.center.lon);
    if (la == null || lo == null) continue;
    for (const c of POI_CATS) {
      if (!c.t(t)) continue;
      const d = Math.round(distKm(lat, lng, la, lo) * 1000);
      if (d > c.r) continue;
      const id = `${e.type}${e.id}`;
      if (seen.has(id + c.key)) continue;
      seen.add(id + c.key);
      items.push({ id, cat: c.key, name: t.name || c.label, lat: la, lng: lo, d });
      break;
    }
  }
  items.sort((a, b) => a.d - b.d);
  const byCat = {};
  for (const c of POI_CATS) {
    const its = items.filter(x => x.cat === c.key);
    byCat[c.key] = { n: its.length, nearest: its[0] || null, list: its.slice(0, 5) };
  }
  return { items, byCat };
}
