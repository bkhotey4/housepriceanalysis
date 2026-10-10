// 購屋深度分析（網頁版）：所有資料都是靜態檔案，計算全部在使用者的裝置上完成。
// 有 data/tw/index.json 時是「全台版」：首頁是 22 縣市，點縣市才下載該縣市的資料；沒有就是原本的台南版。
import * as L from "./logic.js";
import { View3D, mix } from "./view3d.js";
import { buildReport } from "./report.js";
import { CMP_MAX, cmpAdd, cmpCode, cmpDefaultPair, cmpList, cmpPickAdd, tabCmp } from "./compare.js";
import { LOAN_DEFAULT, costResult, costSection, costState, loanPrice, loanResult, loanSection, loanState, rentSection, rentYield, rvbDefaultRent, rvbResult, rvbSection, rvbState, sellResult, sellSection, sellState } from "./finance.js";
import { OVERPASS, refreshPois, showPoi } from "./poi.js";
import { hideSuggestions, pinAt, renderSuggestions, search, selectSuggestion, showAddress, sugState, updateActiveSug } from "./search.js";
import { tabValue, valState } from "./value.js";
import { TYPE_CAT, checkWatchNews, tabWatch, watchBadge, watchChange, watchClick, watchDialog } from "./watch.js";

export const $ = (s, el = document) => el.querySelector(s);
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SEQ = ["#fbe3cf", "#f6b98a", "#eb8a4c", "#d2601f", "#9a3f0c"];
const ROAD_RAMP = ["#fff3b0", "#ffc857", "#f98e3a", "#e2543d", "#a5236f"];
const YIELD_RAMP = ["#e8f5e9", "#a5d6a7", "#66bb6a", "#2e7d32", "#1b5e20"];
const NO_DATA = "#b9bfc6", DIV_NEG = "#1c5cab", DIV_MID = "#d8d7d2", DIV_POS = "#c0302f", TREND_SPAN = 8;
const WORK_COLOR = "#0b5d57", WATCH_COLOR = "#7a3fb5", SEARCH_COLOR = "#d81b60";
const MARKER_COLOR = { "商辦": "#2a78d6", "商場": "#eb6834", "科學園區": "#1baf7a", "產業園區": "#eda100", "重劃區": "#e87ba4",
                       "公共建設": "#008300", "交通建設": "#4a3aa7", "住宅開發": "#e34948" };
export const ZOOM = { district: 40, point: 60, road: 70, pin: { lane: 400, alley_mouth: 400, interp: 250, lane_mouth: 250, near_lane: 200 }, address: 120 };
const STORE = "dth_v1";

function ramp(stops, t) {
  t = Math.max(0, Math.min(1, t));
  const pos = t * (stops.length - 1), i = Math.min(Math.floor(pos), stops.length - 2);
  return mix(stops[i], stops[i + 1], pos - i);
}
const trendColor = p => p == null ? NO_DATA : (t => t < 0 ? mix(DIV_MID, DIV_NEG, -t) : mix(DIV_MID, DIV_POS, t))(Math.max(-1, Math.min(1, p / TREND_SPAN)));

// ------------------------------------------------------------------ 狀態（設定與看屋清單存在這台裝置的瀏覽器裡）
export const S = {
  cat: "all", metric: "u", current: L.CITY, tab: "overview", year: new Date().getFullYear(),
  addr: null, pin: null, roadFilter: null, picked: null, pickMode: null, roadKw: "", bldgKw: "", bldg: null, poi: null,
  settings: { town: true, liq: false, slide: false, fault: false, hires: true, lines: true, markers: true, landmarks: true, projects: true,
              roads: true, labels: true, schools: true, color: "price", work: "", workKm: 5, budget: "", mode: "car", commuteMin: 20, workPt: null, autoReport: true },
  watch: [],
};
function loadStore() {
  try {
    const d = JSON.parse(localStorage.getItem(STORE) || "{}");
    Object.assign(S.settings, d.settings || {});
    S.watch = Array.isArray(d.watch) ? d.watch : [];
  } catch (e) { /* 私密瀏覽等情況讀不到就用預設 */ }
}
export function saveStore() {
  try { localStorage.setItem(STORE, JSON.stringify({ settings: S.settings, watch: S.watch })); } catch (e) { toast("這個瀏覽器不允許儲存資料（可能是私密瀏覽），設定與看屋清單關掉後不會保留。"); }
}

// ------------------------------------------------------------------ 資料
export const D = { roads: new Map() };
// 淹水潛勢：國家災害防救科技中心「3D 災害潛勢地圖」（官方圖資沒有開放給其他網站直接疊圖，所以用連結開啟）
const FLOOD_URL = "https://dmap.ncdr.nat.gov.tw/1109/map/?group-layer=" + encodeURIComponent("淹水潛勢");
export const allLines = () => (D.mrt ? D.mrt.lines : []).concat(D.transit || []);
async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
const roadKey = dist => (D.county ? D.county.code + "/" : "") + dist;
export async function loadRoads(dist) {
  const key = roadKey(dist);
  if (D.roads.has(key)) return D.roads.get(key);
  const avail = D.county ? D.county.roads || [] : D.tw ? [] : D.meta.road_districts;
  if (!avail.includes(dist)) {
    // 全台版：這一區的道路還沒預先整理好（每次自動更新會補一些）→ 直接在這台裝置向 OpenStreetMap 查一次，存起來下次用
    if (!D.county || !D.dmap[dist]) { D.roads.set(key, null); return null; }
    const p = fetchRoadsOsm(D.county, dist).catch(e => { logError(`下載${dist}道路位置（OpenStreetMap）`, e, true); return null; });
    D.roads.set(key, p);
    const data = await p;
    D.roads.set(key, data);
    return data;
  }
  const path = D.county ? `data/tw/${D.county.code}/roads/` : "data/roads/";
  const p = getJSON(path + encodeURIComponent(dist) + ".json").catch(() => null);
  D.roads.set(key, p);
  const data = await p;
  D.roads.set(key, data);
  return data;
}
async function fetchRoadsOsm(county, dist) {
  const cacheKey = `https://cache.local/roads/${county.code}/${encodeURIComponent(dist)}.json`;
  let cache = null;
  try { cache = await caches.open("dth-roads-osm-v1"); const hit = await cache.match(cacheKey); if (hit) return await hit.json(); } catch { cache = null; }
  toast(`第一次看${dist}：正在從 OpenStreetMap 下載道路位置（約 10～40 秒）…`, 8000);
  const q = L.roadsQuery(county.name, dist);
  let last = null;
  for (const url of OVERPASS) {
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 70000);
    try {
      const r = await fetch(url, { method: "POST", body: "data=" + encodeURIComponent(q), signal: ctl.signal,
                                   headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = L.reduceRoads(await r.json());
      if (!Object.keys(data.roads).length) throw new Error("沒有抓到任何道路");
      if (cache) cache.put(cacheKey, new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } })).catch(() => {});
      return data;
    } catch (e) { last = e; } finally { clearTimeout(timer); }
  }
  throw last || new Error("查詢失敗");
}
export const roadsNow = dist => { const v = D.roads.get(roadKey(dist)); return v && !(v instanceof Promise) ? v : null; };
export const isNation = () => !!D.tw && !D.county;

export let view, toastTimer;
export function toast(msg, ms = 4200, action = null) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  if (action) {          // 附一個按鈕（例如「重新整理」）；ms=0 表示一直顯示到使用者按下或關掉
    const b = document.createElement("button");
    b.className = "toast-act"; b.textContent = action.label;
    b.addEventListener("click", () => { t.hidden = true; action.run(); });
    const x = document.createElement("button");
    x.className = "toast-x"; x.textContent = "✕"; x.setAttribute("aria-label", "關閉");
    x.addEventListener("click", () => { t.hidden = true; });
    t.append(" ", b, x);
  }
  clearTimeout(toastTimer);
  if (ms) toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// ------------------------------------------------------------------ 錯誤紀錄（存在這台裝置；「☰ → 問題回報」可以一鍵到 GitHub 回報）
// 記在手機上，並匿名送到維護者的 Google 表單（可在設定關閉）；也可以按一下帶著內容開 GitHub Issue（需要登入 GitHub）
const ERR_KEY = "dth_errors", APP_VER = "2026-10-07a";
function loadErrors() { try { return JSON.parse(localStorage.getItem(ERR_KEY) || "[]"); } catch { return []; } }
export function logError(where, err, quiet = false) {
  const e = { t: new Date().toLocaleString("sv-SE").slice(0, 19), where, msg: String((err && err.message) || err || "").slice(0, 300),
              stack: String((err && err.stack) || "").split("\n").slice(0, 4).join(" | ").slice(0, 400),
              at: (D.county ? D.county.short : "") + (S.current || ""), ver: APP_VER };
  try { const a = loadErrors(); a.push(e); localStorage.setItem(ERR_KEY, JSON.stringify(a.slice(-30))); } catch { /* 存不下就算了 */ }
  if (!quiet && typeof document !== "undefined") { const b = $("#btn-menu"); if (b) b.classList.add("has-err"); }
  console.warn("[錯誤紀錄]", where, e.msg);
  queueAutoReport(e);
}
// 匿名自動回報：送到維護者的 Google 表單（只送錯誤內容、版本、瀏覽器、所在縣市區，不含任何個人資料；設定裡可關閉）
// 同一個錯誤一天只送一次、每次開網頁最多送 5 筆；離線時先存著，連上網路再送。只在正式網站（github.io）送，本機測試不送。
const FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSe2B0IbU8MyMpVBlmn0AH34r5D6lWCwNVcXVNE4DDU4wTZHJw/formResponse",
      FORM_FIELD = "entry.1816938753", SENT_KEY = "dth_err_sent", PEND_KEY = "dth_err_pending";
let autoSent = 0, autoTimer = null;
function autoReportOn() {
  return /\.github\.io$/.test(location.hostname) && !(S.settings && S.settings.autoReport === false);
}
function queueAutoReport(e) {
  if (!autoReportOn()) return;
  try {
    const day = e.t.slice(0, 10), key = day + "|" + e.where + "|" + e.msg.slice(0, 120);
    const sent = JSON.parse(localStorage.getItem(SENT_KEY) || "{}");
    if (sent[key]) return;
    for (const k of Object.keys(sent)) if (!k.startsWith(day)) delete sent[k];
    sent[key] = 1; localStorage.setItem(SENT_KEY, JSON.stringify(sent));
    const pend = JSON.parse(localStorage.getItem(PEND_KEY) || "[]"); pend.push(e);
    localStorage.setItem(PEND_KEY, JSON.stringify(pend.slice(-10)));
  } catch { return; }
  clearTimeout(autoTimer); autoTimer = setTimeout(flushAutoReport, 3000);
}
async function flushAutoReport() {
  if (!autoReportOn() || !navigator.onLine) return;
  let pend; try { pend = JSON.parse(localStorage.getItem(PEND_KEY) || "[]"); } catch { return; }
  while (pend.length && autoSent < 5) {
    const e = pend[0];
    const text = [`${e.t}｜${e.where}｜${e.at || "-"}｜${e.msg}`, e.stack ? "堆疊：" + e.stack : "",
      `版本：${e.ver}｜網址：${safeUrl()}`, `瀏覽器：${navigator.userAgent}`].filter(Boolean).join("\n");
    try {
      await fetch(FORM_URL, { method: "POST", mode: "no-cors", body: new URLSearchParams({ [FORM_FIELD]: text }) });
    } catch { break; }   // 網路斷了：留著下次再送
    pend.shift(); autoSent++;
    try { localStorage.setItem(PEND_KEY, JSON.stringify(pend)); } catch { /* 無妨 */ }
  }
}
window.addEventListener("online", () => setTimeout(flushAutoReport, 2000));
window.addEventListener("error", ev => logError("頁面錯誤", ev.error || ev.message));
window.addEventListener("unhandledrejection", ev => logError("非同步錯誤", ev.reason));
function repoInfo() {
  // 網址是 <帳號>.github.io/<專案>/ 就回報到那個專案；其他網址（本機測試）用預設
  const m = location.hostname.match(/^([^.]+)\.github\.io$/), path = location.pathname.split("/").filter(Boolean)[0];
  return m && path ? `${m[1]}/${path}` : "bkhotey4/housepriceanalysis";
}
// 回報用的網址：只留縣市、區、分頁、房型，不含搜尋過的地址（q）等個人資料
function safeUrl() {
  const p = new URLSearchParams(location.search), keep = new URLSearchParams();
  for (const k of ["c", "d", "tab", "cat", "m"]) if (p.get(k)) keep.set(k, p.get(k));
  return location.origin + location.pathname + (keep.toString() ? "?" + keep : "");
}
function errorReport() {
  const errs = loadErrors().slice(-10), st = D.status;
  return [`**網址**：${safeUrl()}`, `**版本**：${APP_VER}　**瀏覽器**：${navigator.userAgent}`,
    st ? `**資料更新**：${st.time}　${st.ok ? "成功" : "失敗：" + (st.failed || []).join("、")}` : "",
    "", "**最近的錯誤**", "```", ...errs.map(e => `${e.t}｜${e.where}｜${e.at}｜${e.msg}${e.stack ? "｜" + e.stack : ""}`), "```",
    "", "**我在做什麼時發生的（請補充）**：", ""].join("\n");
}
function reportOnGitHub() {
  let body = errorReport();
  if (body.length > 6000) body = body.slice(0, 6000) + "\n…（太長，已截斷）";
  const url = `https://github.com/${repoInfo()}/issues/new?labels=${encodeURIComponent("使用者回報")}&title=${encodeURIComponent("問題回報：" + ((loadErrors().slice(-1)[0] || {}).where || "網頁"))}&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank", "noopener");
}

// ------------------------------------------------------------------ 地圖上的東西
export function workPlace() {
  if (S.settings.work === "__custom") return S.settings.workPt || null;
  return D.workplaces.find(w => w.name === S.settings.work) || null;
}
export const modeName = () => (L.MODES[S.settings.mode] || L.MODES.car)[0];
// 通勤分鐘：查過實際道路就用道路時間（行政區中心），不然用直線距離估算
export const minsTo = (lat, lng, w = workPlace()) => {
  if (!w) return null;
  const rt = routeTimes(w);
  const m = rt && rt.mins[L.ptKey(lat, lng)];
  return m != null ? m : L.commuteMin(L.distKm(lat, lng, w.lat, w.lng), S.settings.mode);
};
// ---- 實際道路的通勤時間（OSRM）：每個「上班地點＋交通方式＋縣市」查一次，存在這台裝置 30 天
const ROUTE_KEY = "dth_route_v1", ROUTE_DAYS = 30;
const routeState = { pending: new Set(), failed: new Map(), last: 0 }, routeMem = new Map();      // failed：key → 失敗時間（5 分鐘後可再試）
function routeCacheKey(w) { return [D.county ? D.county.code : D.tw ? "" : "D", S.settings.mode || "car", L.ptKey(w.lat, w.lng)].join("|"); }
function routeStore() { try { return JSON.parse(localStorage.getItem(ROUTE_KEY) || "{}"); } catch { return {}; } }
export function routeTimes(w = workPlace()) {
  if (!w || isNation()) return null;
  const k = routeCacheKey(w);
  if (!routeMem.has(k)) routeMem.set(k, routeStore()[k] || null);      // 每組只讀一次 localStorage
  const e = routeMem.get(k);
  return e && Date.now() - e.t < ROUTE_DAYS * 864e5 ? e : null;
}
export function routeStatus(w = workPlace()) {
  if (!w || isNation()) return "none";
  if (routeTimes(w)) return "road";
  const k = routeCacheKey(w);
  return routeState.pending.has(k) ? "loading" : Date.now() - (routeState.failed.get(k) || 0) < 5 * 60e3 ? "failed" : "estimate";
}
// 需要時才查（通勤分頁打開、或剛設定上班地點）；同一時間只查一個，兩次請求至少隔 1.1 秒
export function ensureRouteTimes() {
  const w = workPlace();
  if (!w || isNation() || !D.districts.length || routeStatus(w) !== "estimate") return;
  const k = routeCacheKey(w), mode = S.settings.mode || "car", dests = D.districts.filter(d => d.lat != null && d.lng != null);      // 和 routeTableUrl 一樣略過沒有座標的區
  routeState.pending.add(k);
  const wait = Math.max(0, routeState.last + 1100 - Date.now());
  setTimeout(async () => {
    routeState.last = Date.now();
    try {
      const r = await fetch(L.routeTableUrl(mode, w, dests));
      if (!r.ok) throw new Error("路線伺服器 " + r.status);
      const mins = L.parseRouteTable(await r.json(), mode, dests.length);
      if (!mins) throw new Error("路線伺服器沒有回傳結果");
      const all = routeStore(), entry = { t: Date.now(), mins: {} };
      dests.forEach((d, i) => { if (mins[i] != null) entry.mins[L.ptKey(d.lat, d.lng)] = mins[i]; });
      if (!Object.keys(entry.mins).length) throw new Error("路線伺服器找不到任何一區的路線");
      all[k] = entry;
      const keys = Object.keys(all).sort((a, b) => all[b].t - all[a].t).slice(0, 30);      // 最多留 30 組
      try { localStorage.setItem(ROUTE_KEY, JSON.stringify(Object.fromEntries(keys.map(x => [x, all[x]])))); } catch { /* 存不下就只用這一次 */ }
      routeMem.set(k, entry);
    } catch (err) {
      routeState.failed.set(k, Date.now()); logError("通勤路線", err, true);
    } finally {
      routeState.pending.delete(k);
      refreshBars(); refreshPins(); if (S.tab === "commute" || S.tab === "rank") renderPanel();
    }
  }, wait);
}

const commuteLimit = () => parseFloat(S.settings.commuteMin) || 0;
function budgetOK(name) {
  const b = parseFloat(S.settings.budget);
  if (!b) return true;
  const v = D.book.best(name, S.cat, "t").value;
  return v != null && v <= b;
}
function workOK(name) {
  const w = workPlace(), lim = commuteLimit();
  if (!w || !lim) return true;
  const d = D.dmap[name];
  return minsTo(d.lat, d.lng, w) <= lim;
}
const filtersOn = () => !!parseFloat(S.settings.budget) || (!!workPlace() && !!commuteLimit());

// ---- 房價時光機：柱子改成某一季的中位價（近 5 年），可以拉時間軸或按播放
function tmTable() {
  if (!D.long) return null;
  const key = `${D.county ? D.county.code : ""}|${S.cat}|${S.metric}`;
  if (!D._tm || D._tm.key !== key || D._tm.long !== D.long) D._tm = { key, long: D.long, t: L.timeTable(D.long, D.districts.map(d => d.name), S.cat, S.metric) };
  return D._tm.t;
}
function tmBars(t) {
  const i = Math.max(0, Math.min(t.quarters.length - 1, S.tm.i)), span = (t.hi - t.lo) || 1;
  view.bars = D.districts.map(d => {
    const v = (t.vals[d.name] || [])[i] ?? null;
    return { id: d.name, lat: d.lat, lng: d.lng, value: v, frac: v == null ? 0 : Math.min(1.15, v / t.hi),
             color: v == null ? NO_DATA : ramp(SEQ, (v - t.lo) / span),
             label: `${d.name} ${v == null ? "—" : S.metric === "u" ? v.toFixed(1) : L.fmtNum(v)}`, n: 0, dim: false };
  });
  D.barRange = { lo: t.lo, hi: t.hi, span, matched: null, tm: t.quarters[i] };
  renderLegend();
  view.request();
}
function tmStop() {
  if (S.tm && S.tm.timer) clearInterval(S.tm.timer);
  S.tm = null; refreshBars();
}
function tmPlay() {
  const t = tmTable(); if (!t) return;
  if (!S.tm) S.tm = { i: 0 };
  if (S.tm.timer) { clearInterval(S.tm.timer); S.tm.timer = null; tmUi(); return; }       // 再按一次＝暫停
  if (S.tm.i >= t.quarters.length - 1) S.tm.i = 0;
  S.tm.timer = setInterval(() => {
    const cur = tmTable();                          // 播放中換了房型或單價／總價：用新的表
    if (!S.tm || !cur) { if (S.tm && S.tm.timer) clearInterval(S.tm.timer); return; }
    if (S.tm.i >= cur.quarters.length - 1) { clearInterval(S.tm.timer); S.tm.timer = null; tmUi(); return; }
    S.tm.i++; tmBars(cur); tmUi();
  }, 700);
  tmBars(t); tmUi();
}
// 只更新時光機那一小塊（播放時不要整個面板重畫）
function tmUi() {
  const t = tmTable(), el = $("#tm-box");
  if (!el || !t) return;
  const i = Math.min(t.quarters.length - 1, S.tm ? S.tm.i : t.quarters.length - 1);
  const r = $("#tm-range"); if (r) { r.max = t.quarters.length - 1; r.value = i; }
  const lab = $("#tm-q"); if (lab) lab.textContent = t.quarters[i].replace("Q", " 年第 ") + " 季";
  const btn = $("#tm-play"); if (btn) btn.textContent = S.tm && S.tm.timer ? "⏸ 暫停" : "▶ 播放";
  const stop = $("#tm-stop"); if (stop) stop.hidden = !S.tm;
}
function tmSection() {
  const t = tmTable();
  if (!t) return "";
  const i = Math.min(t.quarters.length - 1, S.tm ? S.tm.i : t.quarters.length - 1);
  return `<div id="tm-box" class="tm"><h3 style="margin:10px 0 4px">⏳ 房價時光機（近 5 年）</h3>` +
    `<div class="row"><button class="btn primary small" id="tm-play" data-act="tm-play">${S.tm && S.tm.timer ? "⏸ 暫停" : "▶ 播放"}</button>` +
    `<b id="tm-q">${t.quarters[i].replace("Q", " 年第 ")} 季</b><button class="btn small" id="tm-stop" data-act="tm-stop"${S.tm ? "" : " hidden"}>回到現在</button></div>` +
    `<input type="range" id="tm-range" min="0" max="${t.quarters.length - 1}" value="${i}" aria-label="選擇季別" style="width:100%">` +
    `<p class="muted">地圖上的柱子會變成那一季的中位${S.metric === "u" ? "單價" : "總價"}（${L.CAT_LABEL[S.cat]}），顏色與高度用同一把尺，看得出哪一區先漲、哪一區後漲。件數太少的季不畫（灰色）。資料是季檔的近似值。</p></div>`;
}
function refreshBars() {
  if (S.tm) { const t = tmTable(); if (t) { tmBars(t); return; } S.tm = null; }
  if (workPlace()) ensureRouteTimes();          // 已經設過上班地點：開網頁、換縣市時查一次實際道路時間
  const vals = D.districts.map(d => [d, D.book.best(d.name, S.cat, S.metric), D.book.trend(d.name, S.cat, S.metric), rentYield(d.name, S.cat === "house" ? "house" : "apt")]);
  let solid = vals.filter(([, b]) => b.value != null && !b.low).map(([, b]) => b.value);
  if (!solid.length) solid = vals.filter(([, b]) => b.value != null).map(([, b]) => b.value);
  if (!solid.length) solid = [1];
  const lo = Math.min(...solid), hi = Math.max(...solid), span = (hi - lo) || 1, active = filtersOn();
  view.bars = vals.map(([d, b, tr, yld]) => {
    const v = b.value, ok = !active || (budgetOK(d.name) && workOK(d.name));
    let color = NO_DATA;
    if (S.settings.color === "pop") {
      const p = L.popInfo(D.pop, d.name);
      color = p && p.chgAll != null ? trendColor(p.chgAll) : NO_DATA;
    } else if (S.settings.color === "heat") {
      const ht = L.marketHeat(D.book, d.name, S.cat);
      color = ht ? trendColor(ht.score / 0.6 * TREND_SPAN) : NO_DATA;
    } else if (S.settings.color === "yield") {
      color = yld == null ? NO_DATA : ramp(YIELD_RAMP, (yld - 1.5) / 3.0);
    } else if (S.settings.color === "trend") {
      color = trendColor(tr);
    } else {
      color = v == null ? NO_DATA : b.low ? NO_DATA : ramp(SEQ, (v - lo) / span);
    }
    const num = S.settings.color === "yield" ? (yld != null ? yld.toFixed(1) + "%" : "—") : (v == null ? "—" : S.metric === "u" ? v.toFixed(1) : L.fmtNum(v));
    return { id: d.name, lat: d.lat, lng: d.lng, value: v, frac: v == null ? 0 : Math.min(1.15, v / hi), color,
             label: `${d.name} ${num}${b.low && v != null ? "*" : ""}`, n: b.n, dim: active && !ok };
  });
  D.barRange = { lo, hi, span, matched: active ? vals.filter(([d]) => budgetOK(d.name) && workOK(d.name)).length : null };
  renderLegend();
  view.request();
}
function renderLegend() {
  const el = $("#legend"), unit = S.metric === "u" ? "萬/坪" : "萬";
  if (!D.barRange) return;
  const { lo, span } = D.barRange;
  let rows;
  if (D.barRange.tm) {
    rows = [0, 0.5, 1].map(k => [ramp(SEQ, k), (S.metric === "u" ? (lo + span * k).toFixed(0) : L.fmtNum(lo + span * k)) + " " + unit]);
  } else if (S.settings.color === "pop") {
    rows = [[trendColor(-TREND_SPAN), "人口減少 8% 以上"], [trendColor(0), "持平"], [trendColor(TREND_SPAN), "人口增加 8% 以上"]];
  } else if (S.settings.color === "heat") {
    rows = [[trendColor(-TREND_SPAN), "降溫（量縮、價跌）"], [trendColor(0), "持平"], [trendColor(TREND_SPAN), "升溫（量增、價漲）"]];
  } else if (S.settings.color === "yield") {
    rows = [[ramp(YIELD_RAMP, 0), "1.5%（低收租）"], [ramp(YIELD_RAMP, 0.5), "3.0%（中等）"], [ramp(YIELD_RAMP, 1.0), "4.5%+（高投報）"]];
  } else if (S.settings.color === "trend") {
    rows = [[-TREND_SPAN, "跌 8% 以上"], [0, "持平"], [TREND_SPAN, "漲 8% 以上"]].map(([p, t]) => [trendColor(p), t]);
  } else {
    rows = [0, 0.5, 1].map(k => [ramp(SEQ, k), (S.metric === "u" ? (lo + span * k).toFixed(0) : L.fmtNum(lo + span * k)) + " " + unit]);
  }
  rows.push([NO_DATA, "樣本少／無資料"]);
  let html = `<div class="lg-head">圖例 ${el.classList.contains("collapsed") ? "▸" : "▾"}</div>` +
    (D.barRange.tm ? `<div class="tm-badge">⏳ ${esc(D.barRange.tm.replace("Q", " 年第 "))} 季</div>` : "") +
    `<div><b>${S.settings.color === "yield" ? "毛租金報酬率（年化）" : S.metric === "u" ? "中位單價" : "中位總價"}</b>${S.settings.color === "trend" ? "｜顏色：近半年漲跌" : S.settings.color === "heat" ? "｜顏色：市場冷熱" : S.settings.color === "pop" ? "｜顏色：近 5 年人口增減" : ""}</div>` +
    rows.map(([c, t]) => `<div><span class="sw" style="background:${c}"></span>${esc(t)}</div>`).join("");
  if (D.barRange.matched != null) html += `<div style="margin-top:3px"><b>符合條件 ${D.barRange.matched} 區</b></div>`;
  if (view.roads.length && S.current !== L.CITY && D.roadRange) {
    html += `<div style="margin-top:4px"><b>路段（${S.metric === "u" ? "萬/坪" : "萬"}）</b></div>` +
      [0, 0.5, 1].map(k => `<div><span class="sw" style="background:${ramp(ROAD_RAMP, k)}"></span>${S.metric === "u" ? (D.roadRange.lo + D.roadRange.span * k).toFixed(1) : L.fmtNum(D.roadRange.lo + D.roadRange.span * k)}</div>`).join("");
  }
  if (S.settings.projects) html += `<div style="margin-top:4px"><b>建設（${S.year}）</b></div><div>原色 完工｜塔吊 施工中｜淡色 規劃中</div>`;
  if (S.settings.schools) html += `<div style="margin-top:4px"><b>🎓 明星學區</b></div><div>額滿管制／名校</div>`;
  el.innerHTML = html;
  el.hidden = false;
}
// 地圖上要畫哪些建設、地標：台南版只有台南；全台版進到縣市只畫那個縣市，全台首頁只畫最重要的
const countyOf = it => it.county || "D";
function inScope(it, important) {
  if (!D.tw) return countyOf(it) === "D";
  return D.county ? countyOf(it) === D.county.code : important;
}
function projectItems() {
  if (!S.settings.projects) return [];
  return D.intel.filter(it => it.build && it.lat != null && (it.impact_level || 0) >= 3 && inScope(it, (it.impact_level || 0) >= 5)).map(it => {
    const b = it.build, state = L.buildState(b, S.year), short = it.name.split("（")[0].split("—")[0].slice(0, 14);
    const when = b.done && b.done > S.year && state !== "完工" ? `預計 ${b.done} 完工` : "";
    const lvl = it.impact_level || 2;
    return { id: it.id, hit: "project", model: b.model, state, lat: it.lat, lng: it.lng, size: 0.9,
             rank: lvl >= 5 ? 1 : lvl >= 4 ? 2 : 3, label: state === "完工" ? short : `${short}（${when || state}）` };
  });
}
function schoolItems() {
  if (!S.settings.schools || !D.schools) return [];
  return D.schools.filter(s => inScope(s, true)).map(s => ({
    id: s.id, hit: "school", model: "campus", lat: s.lat, lng: s.lng, size: 0.85,
    rank: 2, label: `🎓 ${s.name.replace(/國民[中小]學/, "").slice(0, 10)}`,
    name: s.name, district: s.district, type: s.type, status: s.status, note: s.note, county: s.county
  }));
}
function refreshModels() {
  const lms = S.settings.landmarks ? D.landmarks.filter(l => inScope(l, l.rank === 1)).map(l => ({ ...l, label: l.name })) : [];
  view.models = lms.concat(projectItems()).concat(schoolItems());
  view.markers = !S.settings.markers ? [] : D.intel.filter(it => it.lat != null && (it.impact_level || 0) >= 3 && !(it.build && S.settings.projects) && inScope(it, false))
    .map(it => ({ id: it.id, lat: it.lat, lng: it.lng, color: MARKER_COLOR[it.type] || "#6b7178", level: it.impact_level || 2,
                  label: it.name.split("（")[0].split("—")[0].slice(0, 16) }));
  renderLegend();
  view.request();
}
export function refreshPins() {
  const pins = [], rings = [], w = workPlace();
  if (w) {
    pins.push({ id: "work", kind: "work", lat: w.lat, lng: w.lng, color: WORK_COLOR, label: "上班：" + w.name });
    if (commuteLimit()) rings.push({ lat: w.lat, lng: w.lng, km: L.kmFor(commuteLimit(), S.settings.mode), color: WORK_COLOR });
  }
  for (const it of S.watch) if (it.lat != null) pins.push({ id: it.id, kind: "watch", lat: it.lat, lng: it.lng, color: WATCH_COLOR,
    label: `${(it.name || "").slice(0, 10)}${it.price ? " " + L.fmtNum(it.price) + "萬" : ""}` });
  if (S.pin) {
    pins.push({ id: "search", kind: "search", lat: S.pin.lat, lng: S.pin.lng, color: SEARCH_COLOR, label: S.pin.label });
    if (S.pin.radius) rings.push({ lat: S.pin.lat, lng: S.pin.lng, km: S.pin.radius, color: SEARCH_COLOR });
  }
  if (S.poi) rings.push({ lat: S.poi.lat, lng: S.poi.lng, km: 0.5, color: "#1baf7a", poi: true });
  view.pins = pins; view.rings = rings; view.request();
}
export async function refreshRoads() {
  const name = S.current;
  view.roads = []; D.roadRange = null;
  if (!S.settings.roads || name === L.CITY || !D.txs || S.cat === "presale") { view.request(); renderLegend(); return; }
  const data = roadsNow(name) || await loadRoads(name);
  if (S.current !== name) return;
  if (!data) { view.request(); return; }
  const key = S.metric === "u" ? "u" : "t", since = D.book.windows.y12[0];
  const rows = L.roadPrices(D.txs, name, S.cat, since);
  const found = [];
  for (const r of rows) { const loc = L.locate(data, r.name); if (loc) found.push({ ...r, ...loc }); }
  let solid = found.filter(r => !r.low).map(r => r[key]);
  if (!solid.length) solid = found.map(r => r[key]);
  if (!solid.length) solid = [0, 1];
  const lo = Math.min(...solid), hi = Math.max(...solid), span = (hi - lo) || 1;
  D.roadRange = { lo, span };
  const items = found.map(r => ({ id: r.name, n: r.n, color: ramp(ROAD_RAMP, (r[key] - lo) / span), segments: r.segments, lanes: r.lanes,
    point: r.point, dot: !r.segments.length, label: `${r.name} ${key === "u" ? r.u.toFixed(1) : L.fmtNum(r.t)}${r.low ? "*" : ""}` }));
  if (S.addr && S.addr.district === name && !items.some(i => i.id === S.addr.road)) {
    const loc = L.locate(data, S.addr.road);
    if (loc) items.push({ id: S.addr.road, n: 0, color: "#aeb4bb", ...loc, dot: !loc.segments.length, label: `${S.addr.road}（近一年無成交）` });
  }
  view.setRoads(items);
  if (S.roadFilter) view.select("road", S.roadFilter);
  renderLegend();
}
function refreshAll() { refreshBars(); refreshModels(); refreshPins(); refreshRoads(); renderPanel(); }

// ------------------------------------------------------------------ 選取
export function selectDistrict(name, fly = true) {
  if (isNation() && name !== L.CITY) { const c = D.tw.counties.find(x => x.short === name); if (c) enterCounty(c.code); return; }
  if (name !== L.CITY && !D.dmap[name]) return;
  if (S.tm && name !== L.CITY) { if (S.tm.timer) clearInterval(S.tm.timer); S.tm = null; refreshBars(); }   // 時光機只在縣市總覽用
  S.current = name; S.roadFilter = null; S.addr = null; S.pin = null; S.bldg = null;
  if (S.poi) { S.poi = null; refreshPois(); }
  if (S.tab === "poi") S.tab = "overview";
  if (name === L.CITY) { view.select(null); if (fly) view.flyHome(); }
  else {
    view.select("district", name);
    const d = D.dmap[name];
    if (fly) view.flyTo(d.lat, d.lng, Math.max(view.zoom, ZOOM.district));
  }
  refreshPins(); refreshRoads();
  if (S.tab === "detail") S.tab = "overview";
  renderPanel();
}
function selectRoad(name, focus = true) {
  if (S.addr && S.addr.road !== name) { S.addr = null; S.pin = null; refreshPins(); }
  S.roadFilter = name;
  view.select("road", name);
  if (focus) {
    const it = view.roads.find(r => r.id === name);
    if (it) view.flyTo(it.point[0], it.point[1], Math.max(view.zoom, ZOOM.road));
  }
  S.tab = "tx"; renderPanel(); sheet("half");
}

function reportButton() { return `<button class="btn small" data-act="report">行情報告</button>`; }
function reportDialog() {
  const a = S.settings.agent || {};
  let dlg = $("#rep-dlg");
  if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "rep-dlg"; document.body.appendChild(dlg); }
  const where = S.addr && S.addr.district === S.current ? `${S.current} ${L.describe(S.addr)}` : S.current;
  dlg.innerHTML = `<form method="dialog"><h2 style="margin-top:0">行情報告：${esc(where)}</h2>
    <div class="grid"><label>房仲／姓名</label><input name="name" value="${esc(a.name || "")}" placeholder="可留空">
    <label>電話</label><input name="phone" value="${esc(a.phone || "")}" inputmode="tel" placeholder="可留空">
    <label>給（客戶）</label><input name="client" placeholder="可留空">
    <label>備註</label><textarea name="note" rows="3" placeholder="可留空"></textarea></div>
    <p class="muted">報告在這台裝置上產生，不會上傳。打開後按「列印／存成 PDF」，手機可用分享 → 列印 → 存成 PDF。</p>
    <div class="actions"><button value="cancel" class="btn">取消</button><button value="ok" class="btn primary">產生報告</button></div></form>`;
  dlg.querySelector("form").addEventListener("submit", ev => {
    if (ev.submitter && ev.submitter.value !== "ok") return;
    const f = new FormData(ev.target), agent = { name: f.get("name").trim(), phone: f.get("phone").trim() };
    S.settings.agent = agent; saveStore();
    const html = buildReport({ book: D.book, txs: D.txs, intel: D.intel, district: S.current, cat: S.cat,
      q: S.addr && S.addr.district === S.current ? S.addr : null,
      point: S.pin ? [S.pin.lat, S.pin.lng] : [D.dmap[S.current].lat, D.dmap[S.current].lng],
      agent: { ...agent, client: f.get("client").trim(), note: f.get("note").trim() },
      county: D.county ? D.county.code : "D", work: workPlace(), mode: S.settings.mode, poi: S.poi && S.poi.status === "ok" ? S.poi : null, meta: D.meta });
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    const w = window.open(url, "_blank");
    if (!w) { const link = document.createElement("a"); link.href = url; link.download = `${where}_行情報告.html`; link.click(); toast("瀏覽器擋住新視窗，已改成下載報告檔。"); }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  });
  dlg.showModal();
}
function poiButton(lat, lng, label) {
  return `<div class="row"><button class="btn small primary" data-act="poi" data-lat="${lat}" data-lng="${lng}" data-label="${esc(label)}">看周邊生活機能、咖啡甜點與嫌惡設施</button></div>`;
}
function tabPoi() {
  const p = S.poi;
  if (!p) return `<p class="muted">先搜尋地址或點一筆成交，再按「看周邊生活機能、咖啡甜點與嫌惡設施」。</p>`;
  let h = `<div class="summary"><b>${esc(p.label)}</b> 周邊</div>`;
  const sweets = `<h2>☕ 咖啡、飲料、甜點、蛋糕</h2><div class="row">` +
    [["咖啡店", "咖啡店"], ["飲料店", "飲料店"], ["甜點店", "甜點店"], ["蛋糕店", "蛋糕店"], ["下午茶", "下午茶"]].map(([t, kw]) =>
      `<a class="btn small" data-sweet="${esc(kw)}" target="_blank" rel="noopener" href="${L.nearbySearchUrl(p.lat, p.lng, kw)}">Google 地圖找附近${t}</a>`).join("") +
    `</div><p class="muted">Google 地圖上有評分、照片和營業時間；下面的清單來自 OpenStreetMap，小店可能沒登錄。</p>`;
  if (p.status === "loading") return h + `<p class="empty">向 OpenStreetMap 查詢中…（約 5～20 秒）</p>` + sweets;
  if (p.status === "error") return h + `<p class="note">查詢失敗：${esc(p.err || "")}。OpenStreetMap 的查詢伺服器可能正忙，請稍後再按一次。</p>` + poiButton(p.lat, p.lng, p.label) + sweets;
  const fmtD = d => d >= 1000 ? (d / 1000).toFixed(1) + " 公里" : d + " 公尺";
  const block = (group, title) => {
    let t = `${title ? `<h2>${title}</h2>` : ""}<table class="list"><tbody>`;
    for (const c of L.POI_CATS.filter(c => c.group === group)) {
      const b = p.res.byCat[c.key], rr = fmtD(c.r);
      t += `<tr${b.n ? ` class="click" data-poi="${esc(b.nearest.id + c.key)}"` : ""}><td><span class="pill" style="background:${c.color};color:#fff">${c.ch}</span>${esc(c.label)}` +
        `<div class="muted">${b.n ? `最近：${esc(b.nearest.name)} ${fmtD(b.nearest.d)}` : `${rr}內沒有`}</div></td><td class="r">${rr}內<br><b>${b.n}</b></td></tr>`;
    }
    return t + "</tbody></table>";
  };
  const schools = (p.res.items || []).filter(x => x.cat === "school");
  const near = re => schools.filter(x => re.test(x.name)).slice(0, 2);
  const es = near(/國小|國民小學/), js = near(/國中|國民中學/);
  if (es.length || js.length) {
    const li = x => `${esc(x.name)} <span class="muted">${fmtD(x.d)}</span>`;
    h += `<h2>學區參考</h2><div class="summary">${es.length ? `最近的國小：${es.map(li).join("、")}` : "1 公里內沒有國小"}<br>${js.length ? `最近的國中：${js.map(li).join("、")}` : "1 公里內沒有國中"}</div>` +
      `<p class="muted">學區是依門牌（里、鄰）劃分的，不一定是最近的那一所，熱門學校還有設籍年限的規定；請以縣市教育局的學區查詢為準。</p>`;
  }
  h += block("good", "生活機能") + sweets + block("fun", "") + block("bad", "嫌惡設施");
  h += `<div class="row">${reportButton()}</div>`;
  h += `<p class="muted">資料來自 OpenStreetMap 志工繪製，可能有缺漏或過時（特別是禮儀社、宮廟、小型工廠），看屋前請實地走一圈。宮廟是否算嫌惡因人而異。高壓電線、鐵路、快速道路量的是到線上最近一點的距離；機場看 4 公里內，實際航道噪音請看各機場公告的噪音管制區。</p>`;
  return h;
}

// ------------------------------------------------------------------ 點選地圖
export function pick(hit, latlng) {
  if (S.pickMode) {
    const cb = S.pickMode; S.pickMode = null;
    cb(latlng); return;
  }
  if (!hit) return;
  const [kind, id] = hit;
  if (kind === "district") { selectDistrict(id); sheet("peek"); return; }
  if (kind === "poi") { const o = view.pois.find(x => x.id === id); if (o) { view.select("poi", id); toast(`${o.name}｜距離 ${o.d} 公尺`); } return; }
  if (kind === "road") { selectRoad(id); return; }
  if (kind === "pin" && id === "search") { if (S.pin) view.flyTo(S.pin.lat, S.pin.lng, Math.max(view.zoom, ZOOM.address)); S.tab = "tx"; renderPanel(); sheet("half"); return; }
  if (kind === "pin" && id !== "work") { S.tab = "watch"; S.watchSel = id; renderPanel(); sheet("half"); return; }
  const item = kind === "landmark" ? D.landmarks.find(x => x.id === id) : kind === "school" ? (D.schools || []).find(x => x.id === id) : (kind === "project" || kind === "marker") ? D.intel[id] : null;
  const where = (kind === "landmark" || kind === "school") ? (item || {}).district : item ? ((item.district || "").split(/[、／\/,，\s（(]/)[0]) : null;
  if (D.tw && item) {
    // 全台版：圖案屬於別的縣市，先切到那個縣市（舊資料沒有標縣市的都是臺南市）
    const code = item.county || "D";
    if (!D.county || D.county.code !== code) {
      const c = D.tw.counties.find(x => x.code === code);
      if (c && c.has_data) { enterCounty(code, false).then(ok => { if (ok) pick(hit, latlng); }); return; }
    }
  }
  if (where && D.dmap[where] && where !== S.current) selectDistrict(where, false);
  S.picked = hit; S.tab = "detail";
  view.select(kind === "station" ? "line" : kind, kind === "station" ? id[0] : id);
  let ll = null;
  if (kind === "landmark") { const l = D.landmarks.find(x => x.id === id); ll = [l.lat, l.lng]; }
  else if (kind === "school") { const sc = (D.schools || []).find(x => x.id === id); if (sc) ll = [sc.lat, sc.lng]; }
  else if (kind === "project" || kind === "marker") { const it = D.intel[id]; ll = [it.lat, it.lng]; }
  else if (kind === "station") { const ln = allLines().find(l => l.name === id[0]); const st = ln && ln.stations.find(s => s[0] === id[1]); if (st) ll = [st[1], st[2]]; }
  else if (kind === "pin" && id === "work") { const w = workPlace(); if (w) ll = [w.lat, w.lng]; }
  if (ll) view.flyTo(ll[0], ll[1], Math.max(view.zoom, ZOOM.point));
  renderPanel(); sheet("half");
}

// ------------------------------------------------------------------ 面板
const TABS = [["overview", "概況"], ["rank", "排行"], ["commute", "通勤"], ["roads", "路段"], ["bldg", "社區"], ["tx", "成交"], ["value", "估價"], ["cmp", "比較"], ["projects", "建設"], ["detail", "點選"], ["poi", "周邊"], ["watch", "看屋"]];
export function renderPanel() {
  const name = S.current, b = D.book;
  $("#d-name").textContent = name;
  $("#btn-city").hidden = name === L.CITY;
  $("#btn-city").textContent = D.tw ? "全" + L.CITY : "全市";
  $("#btn-nation").hidden = !D.county;
  $("#map-tools [data-act='home']").textContent = D.tw ? (D.county && S.current !== L.CITY ? "縣市" : "全台") : "全市";
  const bu = b.best(name, S.cat, "u"), bt = b.best(name, S.cat, "t"), tr = b.trend(name, S.cat, S.metric);
  const win = bu.window === "h6" ? "近半年" : bu.window === "y12" ? "近一年" : "";
  const zone = name === L.CITY ? "" : (D.dmap[name].zone || "") + "｜";
  $("#d-sub").textContent = `${zone}${L.CAT_LABEL[S.cat]}｜${win ? win + "（" + b.windowLabel(bu.window) + "）" : "近一年沒有成交"}`;
  const trCls = tr == null ? "" : tr > 0.5 ? "up" : tr < -0.5 ? "down" : "";
  $("#kpis").innerHTML = [
    ["中位單價", bu.value == null ? "—" : bu.value.toFixed(1), "萬/坪"],
    ["中位總價", L.fmtNum(bt.value), "萬"],
    ["成交件數", L.fmtNum(bu.n), bu.low && bu.n ? "樣本少" : "件"],
    ["近半年", `<span class="${trCls}">${L.trendText(tr).replace("▲ ", "▲").replace("▼ ", "▼")}</span>`, ""],
  ].map(([k, v, u]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}<small> ${u}</small></div></div>`).join("");
  $("#tabs").innerHTML = TABS.filter(([k]) => (k !== "detail" || S.picked) && (k !== "poi" || S.poi)).map(([k, t]) =>
    `<button role="tab" id="tab-${k}" data-tab="${k}" aria-controls="tab-body" aria-selected="${S.tab === k}" tabindex="${S.tab === k ? 0 : -1}">${t}${k === "watch" ? watchBadge() : ""}</button>`).join("");
  const body = $("#tab-body"), keepTop = body.scrollTop;
  body.setAttribute("aria-labelledby", "tab-" + S.tab);
  body.innerHTML = ({ overview: tabOverview, rank: tabRank, commute: tabCommute, roads: tabRoads, bldg: tabBldg, tx: tabTx, value: tabValue, cmp: tabCmp, projects: tabProjects, detail: tabDetail, poi: tabPoi, watch: tabWatch }[S.tab] || tabOverview)();
  const key = [S.tab, S.current, D.county ? D.county.code : "", S.bldg, S.watchSel, S.addr ? S.addr.text : ""].join("|");
  body.scrollTop = key === renderPanel.lastKey ? keepTop : 0;
  renderPanel.lastKey = key;
  const on = $("#tabs [aria-selected='true']");
  if (on) { const bar = $("#tabs"); if (on.offsetLeft < bar.scrollLeft || on.offsetLeft + on.offsetWidth > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = on.offsetLeft - 16; }
  syncUrl();
}

// ------------------------------------------------------------------ 分享連結：網址記住縣市、區域（或地址）、房型、單價／總價、分頁
// 例：?c=A&d=大安區&cat=apt&tab=rank；比較分頁另外帶 cmp=A:大安區,D:東區。畫面一變就更新網址列，重新整理或加入書籤也會回到同一個畫面。
const SHARE_TABS = ["overview", "rank", "commute", "roads", "bldg", "tx", "value", "cmp", "projects"];
function shareParams() {
  const p = new URLSearchParams(), cur = new URLSearchParams(location.search);
  if (cur.get("tw") === "0") p.set("tw", "0");
  if (D.county) p.set("c", D.county.code);
  if (S.addr && S.addr.road) p.set("q", (D.county ? D.county.short : "") + S.addr.district + L.describe(S.addr).replace(/ /g, ""));
  else if (S.current !== L.CITY) p.set("d", S.current);
  if (S.cat !== "all") p.set("cat", S.cat);
  if (S.metric !== "u") p.set("m", S.metric);
  if (S.tab !== "overview" && SHARE_TABS.includes(S.tab) && !(S.addr && S.tab === "tx")) p.set("tab", S.tab);
  if (S.tab === "cmp" && cmpList().length) p.set("cmp", cmpList().map(x => `${x.code}:${x.name}`).join(","));
  return p;
}
function shareUrl() { const q = shareParams().toString(); return location.origin + location.pathname + (q ? "?" + q : ""); }
function syncUrl() {
  if (!S.ready) return;            // 啟動還原完成前不要動網址（還要讀裡面的參數）
  try { const u = shareUrl(); if (u !== location.href) history.replaceState(null, "", u); } catch { /* file:// 等情況 */ }
}
async function shareNow() {
  const url = shareUrl(), name = S.addr ? `${S.addr.district}${L.describe(S.addr).replace(/ /g, "")}` : S.current;
  const title = `${D.county && name !== L.CITY ? D.county.short : ""}${name}｜房價行情`;
  if (navigator.share) { try { await navigator.share({ title, text: title, url }); return; } catch (e) { if (e && e.name === "AbortError") return; } }
  try { await navigator.clipboard.writeText(url); toast("已複製連結，貼給家人朋友就能看到同一個畫面。"); }
  catch { window.prompt("複製這個連結：", url); }
}
// 開啟分享連結：在縣市載入後套用區域、房型、分頁、比較清單（地址由 ?q= 交給搜尋處理）
function applyShared(params) {
  const cat = params.get("cat"), m = params.get("m"), tab = params.get("tab"), d = params.get("d"), cmp = params.get("cmp");
  if (cat && L.CAT_LABEL[cat]) S.cat = cat;
  if (m === "u" || m === "t") S.metric = m;
  $("#chips").querySelectorAll("button").forEach(x => x.setAttribute("aria-checked", x.dataset.cat ? x.dataset.cat === S.cat : x.dataset.metric === S.metric));
  if (cmp) {
    const okCode = code => D.tw ? D.tw.counties.some(c => c.code === code && c.has_data) : code === "D";
    const list = cmp.split(",").map(s => s.split(":")).filter(a => a.length === 2 && a[1] && okCode(a[0])).slice(0, CMP_MAX)
      .map(([code, name]) => ({ code, name, county: D.tw ? ((D.tw.counties.find(c => c.code === code) || {}).short || "") : L.CITY }));
    if (list.length) { S.settings.cmp = list; saveStore(); }
  }
  if (tab && SHARE_TABS.includes(tab)) S.tab = tab;
  if (d && D.dmap && D.dmap[d] && !params.get("q")) { refreshBars(); selectDistrict(d); }     // 房型、單價／總價變了：柱子也要重畫
  else refreshAll();
}
function trendSVG(series, every = 3) {
  const pts = series.map((p, i) => ({ ...p, i })), vals = pts.filter(p => p.v != null).map(p => p.v);
  if (vals.length < 2) return `<p class="empty">成交太少，畫不出走勢。</p>`;
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.15 || 1; lo -= pad; hi += pad;
  const W = 360, H = 170, l = 40, r = 10, t = 10, bH = 34, nmax = Math.max(...pts.map(p => p.n)) || 1;
  const step = (W - l - r) / Math.max(1, pts.length - 1), x = i => l + i * step, y = v => t + (hi - v) / (hi - lo) * (H - t - bH - 26);
  let s = `<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="每月中位價走勢">`;
  for (const p of pts) { const h = p.n / nmax * bH; s += `<rect x="${x(p.i) - step * 0.3}" y="${H - 22 - h}" width="${step * 0.6}" height="${h}" fill="${p.partial ? "#e3e6ea" : "#c4cad1"}"/>`; }
  for (const f of [0, 0.5, 1]) { const v = hi - (hi - lo) * f, yy = y(v); s += `<line x1="${l}" x2="${W - r}" y1="${yy}" y2="${yy}" stroke="#eceff2"/><text x="${l - 5}" y="${yy + 4}" font-size="10" text-anchor="end" fill="#5b6168">${S.metric === "u" ? v.toFixed(1) : L.fmtNum(v)}</text>`; }
  const line = pts.filter(p => p.v != null && !p.partial).map(p => `${x(p.i)},${y(p.v)}`).join(" ");
  s += `<polyline fill="none" stroke="#2a78d6" stroke-width="2.2" points="${line}"/>`;
  for (const p of pts) if (p.v != null) s += `<circle cx="${x(p.i)}" cy="${y(p.v)}" r="3" fill="${p.partial ? "#fff" : "#2a78d6"}" stroke="#2a78d6"/>`;
  pts.forEach(p => { if (p.i % every === 0 || p.i === pts.length - 1) s += `<text x="${x(p.i)}" y="${H - 8}" font-size="10" text-anchor="middle" fill="#5b6168">${p.m.slice(2).replace("-", "/")}</text>`; });
  return s + "</svg>";
}
// 近一年成交的價格分佈：中位數之外，看得出價格集中在哪、預算落在第幾個百分位
function distSVG(name) {
  if (!D.txs || name === L.CITY) return "";
  const since = D.book.windows.y12[0], isU = S.metric === "u";
  const vals = D.txs.filter(x => x.dist === name && x.ym >= since && L.inCat(x, S.cat)).map(x => isU ? x.u : x.tw);
  const hg = L.priceHistogram(vals);
  if (!hg) return "";
  const W = 360, H = 144, l = 14, r = 14, t = 20, b = 34, bw = (W - l - r) / hg.counts.length, max = Math.max(...hg.counts);
  const x = v => l + Math.max(0, Math.min(1, (v - hg.lo) / (hg.hi - hg.lo || 1))) * (W - l - r);
  const fmt = v => isU ? v.toFixed(1) : L.fmtNum(Math.round(v));
  const budget = !isU ? parseFloat(S.settings.budget) : 0;
  let g = hg.counts.map((c, i) => `<rect x="${(l + i * bw + 1).toFixed(1)}" y="${(H - b - c / max * (H - t - b)).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(c / max * (H - t - b)).toFixed(1)}" fill="${budget && hg.lo + (i + 1) * hg.w > budget ? "#d5d9de" : "#7fb9b3"}"><title>${fmt(hg.lo + i * hg.w)}～${fmt(hg.lo + (i + 1) * hg.w)}：${c} 筆</title></rect>`).join("");
  const mark = (v, label, color, dy) => `<line x1="${x(v)}" x2="${x(v)}" y1="${t - 4}" y2="${H - b}" stroke="${color}" stroke-width="1.5"${label === "預算" ? "" : ' stroke-dasharray="3 2"'}/>` +
    `<text x="${x(v)}" y="${H - b + dy}" text-anchor="middle" font-size="10" fill="${color}">${label} ${fmt(v)}</text>`;
  g += mark(hg.p25, "P25", "#5b6168", 12) + mark(hg.p50, "中位", "#0b5d57", 24) + mark(hg.p75, "P75", "#5b6168", 12);
  if (budget) {        // 預算線的標籤放在上方，才不會和下方的中位數標籤疊在一起
    const bx = x(budget), anchor = bx > W - 60 ? "end" : bx < 60 ? "start" : "middle";
    g += `<line x1="${bx}" x2="${bx}" y1="${t - 2}" y2="${H - b}" stroke="#d2601f" stroke-width="1.5"/>` +
      `<text x="${bx}" y="${t - 5}" text-anchor="${anchor}" font-size="10" fill="#d2601f">預算 ${fmt(budget)}</text>`;
  }
  const unit = isU ? "萬/坪" : "萬";
  const note = `近一年 ${hg.n} 筆：一半的成交在 ${fmt(hg.p25)}～${fmt(hg.p75)} ${unit} 之間` +
    (budget ? `；總價在預算 ${L.fmtNum(budget)} 萬以內的約佔 <b>${Math.round(hg.below(budget) * 100)}%</b>` : "") + "。";
  return `<h3>${isU ? "單價" : "總價"}分佈</h3><svg class="dist" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)}近一年成交${isU ? "單價" : "總價"}分佈">${g}</svg><p class="muted">${note}</p>`;
}
// 人口成長與年齡結構（戶政司開放資料）：人口增減、淨遷入、年齡分布
const AGE_COLORS = ["#7fb9b3", "#a8d5ba", "#2a78d6", "#f6b98a", "#d2601f"];
function popSection(name) {
  const p = L.popInfo(D.pop, name);
  if (!p) return "";
  const sgn = v => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
  const bits = [`人口 <b>${L.fmtNum(p.now)}</b> 人` + (p.chgAll != null ? `，近 ${p.span} 年 <b class="${p.chgAll >= 0 ? "up" : "down"}">${sgn(p.chgAll)}</b>` : "") +
    (p.chg1 != null ? `（最近一年 ${sgn(p.chg1)}）` : "")];
  if (p.net != null) bits.push(`近 12 個月遷入比遷出${p.net >= 0 ? "多" : "少"} <b>${L.fmtNum(Math.abs(p.net))}</b> 人` +
    (p.netRate != null ? `（每千人 ${p.netRate >= 0 ? "+" : "−"}${Math.abs(p.netRate).toFixed(1)}）` : ""));
  if (p.old != null) bits.push(`65 歲以上 ${p.old.toFixed(1)}%（扶老比 ${p.depOld.toFixed(0)}）、25～44 歲 ${p.young.toFixed(1)}%、14 歲以下 ${p.kids.toFixed(1)}%` +
    (p.perHH ? `；平均每戶 ${p.perHH.toFixed(2)} 人` : ""));
  let bar = "";
  if (p.share) {
    let x = 0;
    bar = `<svg class="agebar" viewBox="0 0 360 30" role="img" aria-label="年齡結構">` + p.share.map((v, i) => {
      const w = v / 100 * 360, r = `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="16" fill="${AGE_COLORS[i]}"><title>${esc(D.pop.bands[i])} 歲 ${v.toFixed(1)}%</title></rect>` +
        (w > 34 ? `<text x="${(x + w / 2).toFixed(1)}" y="28" font-size="10" text-anchor="middle" fill="#5b6168">${esc(D.pop.bands[i])}</text>` : "");
      x += w; return r;
    }).join("") + `</svg>`;
  }
  return `<h3>人口與年齡結構</h3><div class="summary">${bits.join("<br>")}</div>${bar}` +
    `<p class="muted">內政部戶政司開放資料：人口為每年底與 ${esc(String(D.pop.month || "").replace(/^(\d{3})(\d{2})$/, "$1 年 $2 月"))}的戶籍人口，遷入遷出為最近 12 個月合計。` +
    `人口持續移入、年輕人口比例高的區，買房需求通常比較撐得住；戶籍人口不等於實際居住人口（學生、外地工作者常沒遷戶籍）。</p>`;
}
// 學區：各縣市教育局的學區查詢系統不一樣，用 Google 搜尋帶到官方頁面（學區以教育局公告為準）
function schoolLink(dist, road = "") {
  const county = D.county ? D.county.name : "臺南市";
  return `<a class="btn" target="_blank" rel="noopener" href="https://www.google.com/search?q=${encodeURIComponent(`${county}${dist}${road} 國小 國中 學區 查詢`)}">查學區</a>`;
}
// 概況裡的「進階行情」：市場冷熱、樓層價差、屋齡與單價、車位行情（都在裝置上用逐筆成交算）
function heatText(h) {
  if (!h) return "";
  const bits = [h.price != null ? `價格近 3 個月${h.price >= 0 ? "漲" : "跌"} ${Math.abs(h.price).toFixed(1)}%` : "",
    h.vol != null ? `成交量近半年${h.vol >= 0 ? "增" : "減"} ${Math.abs(h.vol).toFixed(0)}%（${h.prev}→${h.recent} 件）` : ""].filter(Boolean);
  return `市場熱度：<b class="${h.label === "升溫" ? "up" : h.label === "降溫" ? "down" : ""}">${h.label}</b>（${bits.join("、")}）`;
}
function marketSection(name) {
  if (!D.txs) return "";
  const end = D.book.windows.y12[1], since = D.book.windows.y12[0];
  let h = "";
  const fp = S.cat !== "house" ? L.floorPremium(D.txs, name, since) : null;
  if (fp) {
    const max = Math.max(...fp.bands.map(b => Math.abs(b.pct || 0)), 1);
    h += `<h3>樓層價差（大樓／華廈）</h3><table class="list"><tbody>` + fp.bands.map(b => `<tr${b.pct == null ? ' class="low"' : ""}><td>${b.label}</td>` +
      `<td class="r">${b.pct == null ? "—" : `<b class="${b.pct >= 0 ? "up" : "down"}">${b.pct >= 0 ? "+" : ""}${b.pct.toFixed(1)}%</b>`}</td>` +
      `<td style="width:42%"><div class="pbar${b.pct != null && b.pct < 0 ? " neg" : ""}" style="width:${b.pct == null ? 0 : Math.max(3, Math.abs(b.pct) / max * 100).toFixed(0)}%"></div></td>` +
      `<td class="r muted">${b.n} 筆</td></tr>`).join("") +
      `</tbody></table><p class="muted">同一棟裡比：每筆單價和那一棟的中位數差多少，再依樓層取中位數（近一年 ${fp.bldgs} 棟有樓層資料的大樓）。高樓層的景觀、採光通常比較貴，1 樓常因為隱私、潮濕比較便宜。</p>`;
  }
  const ac = L.ageCurve(D.txs, name, S.cat === "presale" ? "all" : S.cat, end);
  if (ac) {
    h += `<h3>屋齡與單價</h3><table class="list"><thead><tr><th>屋齡</th><th class="r">件</th><th class="r">中位萬/坪</th><th class="r">比${ac.base}</th></tr></thead><tbody>` +
      ac.bands.map(b => `<tr${b.u == null ? ' class="low"' : ""}><td>${b.label}</td><td class="r">${b.n}</td><td class="r">${b.u == null ? "—" : b.u.toFixed(1)}</td>` +
        `<td class="r">${b.pct == null || b.label === ac.base ? "—" : `${b.pct >= 0 ? "+" : ""}${b.pct}%`}</td></tr>`).join("") +
      `</tbody></table><p class="muted">近兩年的中古屋成交（不含預售），依成交當時的屋齡分組。同一區的新舊屋常在不同地段，差距不全是「折舊」，但看得出買新一點的房子大約要多付多少。</p>`;
  }
  const ca = L.commonAreaStats(D.txs, name, end);
  if (ca) {
    h += `<h3>公設比與實坪單價（大樓／華廈）</h3><div class="summary">公設比中位數 <b>${ca.all.ps}%</b>：權狀單價 ${ca.all.u} 萬/坪` +
      (ca.all.real != null ? ` → 扣掉公設後的實坪單價 <b>${ca.all.real}</b> 萬/坪` : "") + `</div>` +
      `<table class="list"><thead><tr><th>屋齡</th><th class="r">件</th><th class="r">公設比</th><th class="r">權狀萬/坪</th><th class="r">實坪萬/坪</th></tr></thead><tbody>` +
      ca.bands.map(b => `<tr${b.ps == null ? ' class="low"' : ""}><td>${b.label}</td><td class="r">${b.n}</td><td class="r">${b.ps == null ? "—" : b.ps + "%"}</td>` +
        `<td class="r">${b.u == null ? "—" : b.u.toFixed(1)}</td><td class="r">${b.real == null ? "—" : b.real.toFixed(1)}</td></tr>`).join("") +
      `</tbody></table><p class="muted">近兩年中古大樓、華廈的成交（預售屋的實價登錄沒有面積明細）。實坪＝主建物＋附屬建物＋陽台；公設比＝權狀扣掉車位後，公共設施佔的比例。` +
      `新大樓公設比通常比較高，比單價時用實坪單價比較公平；車位價沒有分開登錄的成交不算實坪單價。</p>`;
  }
  const rs = L.roomStats(D.txs, name, S.cat, end);
  if (rs) {
    h += `<h3>依房數看行情</h3><table class="list"><thead><tr><th>格局</th><th class="r">件</th><th class="r">中位總價</th><th class="r">坪數</th><th class="r">萬/坪</th></tr></thead><tbody>` +
      rs.bands.map(b => `<tr${b.t == null ? ' class="low"' : ""}><td>${b.label}</td><td class="r">${b.n}</td><td class="r">${b.t == null ? "—" : `<b>${L.fmtNum(b.t)}</b> 萬`}</td>` +
        `<td class="r">${b.ping == null ? "—" : b.ping.toFixed(1)}</td><td class="r">${b.u == null ? "—" : b.u.toFixed(1)}</td></tr>`).join("") +
      `</tbody></table><p class="muted">近一年${L.CAT_LABEL[S.cat]}的成交，依實價登錄的「建物現況格局－房」分組（開放格局、沒填的不算）。坪數是權狀坪數，含公設與車位。</p>`;
  }
  const pk = L.parkingStats(D.txs, name, end);
  if (pk) {
    const row = (label, x) => x ? `<tr><td>${label}</td><td class="r">${x.n}</td><td class="r"><b>${L.fmtNum(x.price)}</b></td><td class="r">${L.fmtNum(x.lo)}～${L.fmtNum(x.hi)}</td><td class="r">${x.area ? x.area.toFixed(1) : "—"}</td></tr>` : "";
    h += `<h3>車位行情</h3><table class="list"><thead><tr><th>類別</th><th class="r">件</th><th class="r">中位（萬）</th><th class="r">一半落在</th><th class="r">坪</th></tr></thead><tbody>` +
      row("平面車位", pk.flat) + row("機械車位", pk.mech) + row("其他／未註明", pk.other) +
      `</tbody></table><p class="muted">近兩年「含一個車位、而且車位價格分開登錄」的成交；車位價併在房價裡的不算。</p>`;
  }
  if (!h) return "";
  return `<details class="more" data-det="mktOpen"${S.settings.mktOpen !== false ? " open" : ""}><summary>樓層、屋齡、公設、房數、車位行情</summary>${h}</details>`;
}
function tabOverview() {
  const name = S.current, b = D.book, bt = b.best(name, S.cat, "t");
  const ls = D.long ? L.longSeries(D.long, name, S.cat, S.metric) : [], long5 = S.settings.span === 5 && ls.length >= 4;
  const spanSeg = ls.length >= 4 ? `<div class="seg span-seg" role="radiogroup" aria-label="走勢期間">${[[1, "近 1 年"], [5, "近 5 年"]].map(([k, t]) =>
    `<button role="radio" data-act="span" data-span="${k}" aria-checked="${(S.settings.span === 5) === (k === 5)}">${t}</button>`).join("")}</div>` : "";
  let h = `<h2 style="margin-top:2px">${esc(name)}${long5 ? "每季" : "每月"}中位${S.metric === "u" ? "單價（萬/坪）" : "總價（萬）"}</h2>${spanSeg}` +
    (long5 ? trendSVG(ls, 4) : trendSVG(b.series(name, S.cat, S.metric)));
  const c5 = L.longChange(ls, 5), c3 = L.longChange(ls, 3);
  if (c5 || c3) h += `<div class="summary">${[[c5, 5], [c3, 3]].filter(([c]) => c).map(([c, y]) =>
    `近 ${y} 年${S.metric === "u" ? "單價" : "總價"}<b class="${c.pct >= 0 ? "up" : "down"}">${c.pct >= 0 ? "漲" : "跌"} ${Math.abs(c.pct).toFixed(1)}%</b>（${c.from}→${c.to}）`).join("　")}</div>`;
  h += `<p class="muted">${long5 ? "近 5 年由每一季的實價登錄季檔整理，每季件數加權平均，是近似值；灰色長條是每季件數。" : "空心點是資料還沒到齊的月份；灰色長條是每月件數。"}${esc(D.meta.describe)}</p>`;
  if (name !== L.CITY) {
    const gap = b.presaleGap(name), w = workPlace(), d = D.dmap[name];
    const bits = [];
    if (gap != null) bits.push(`預售屋單價比中古大樓${gap >= 0 ? "高" : "低"} ${Math.abs(gap).toFixed(0)}%`);
    const pir = L.priceIncomeRatio(bt.value, parseFloat(S.settings.incomeMonthly));
    if (pir) bits.push(`以家庭月收入 ${L.fmtNum(+S.settings.incomeMonthly)} 元計，這一區中位總價要<b>不吃不喝 ${pir.toFixed(1)} 年</b>（房價所得比）`);
    const heat = L.marketHeat(D.book, name, S.cat);
    if (heat) bits.push(heatText(heat));
    if (w) { const road = routeTimes(w)?.mins[L.ptKey(d.lat, d.lng)] != null;
      bits.push(`到${esc(w.name)}：${modeName()}約 ${minsTo(d.lat, d.lng, w)} 分鐘（${road ? ((L.ROUTE_ADJ[S.settings.mode] || L.ROUTE_ADJ.car)[0] > 1 ? "依道路路線、含尖峰" : "依道路路線") : `直線 ${L.distKm(d.lat, d.lng, w.lat, w.lng).toFixed(1)} 公里，估計`}）`); }
    if (bits.length) h += `<div class="summary">${bits.join("<br>")}</div>`;
    h += popSection(name) + distSVG(name) + marketSection(name);
    h += `<div class="row">${reportButton()}<button class="btn small" data-act="cmp-add">加入比較</button><a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/@${d.lat},${d.lng},14z">Google 地圖</a><a class="btn" target="_blank" rel="noopener" href="${FLOOD_URL}">淹水潛勢</a>${schoolLink(name)}` +
      (w ? `<a class="btn" target="_blank" rel="noopener" href="${L.routeUrl(d, w, S.settings.mode)}">通勤路線</a>` : "") + `</div>`;
    h += loanSection(bt.value) + costSection(bt.value) + sellSection(bt.value) + rentSection(name) + rvbSection(name, bt.value);
  } else {
    // 情境捷徑：南科、明星學區是台南限定，只在台南顯示；新青安與雙區 PK 全台都能用
    const tainan = !D.tw || (D.county && D.county.code === "D");
    const card = (k, icon, title, desc) => `<button type="button" class="scenario-card" data-scenario="${k}"><span class="sc-icon" aria-hidden="true">${icon}</span>` +
      `<span class="sc-content"><span class="sc-title">${title}</span><span class="sc-desc">${desc}</span></span></button>`;
    const pair = cmpDefaultPair();
    h += `<div class="scenario-section"><h3 style="margin:14px 0 8px">🧭 買房情境快捷導航</h3><div class="scenario-grid">` +
      (tainan ? card("nanke", "🚄", "南科通勤生活圈", "善化、新市、安南科技聚落") + card("school", "🎓", "明星額滿學區地圖", "建興、後甲、復興熱門雙語學區") : "") +
      card("youth", "💰", "新青安首購試算", "40 年期與 5 年寬限期斷崖體檢") +
      card("duel", "⚔️", "雙區買房 PK 擂台", pair ? `${esc(pair[0].name)} vs ${esc(pair[1].name)}，或自選任兩區` : "全台任選兩區（可跨縣市）指標對決") +
      `</div></div>`;
    h += tmSection() + popSection(name) + loanSection(bt.value) + costSection(bt.value) + sellSection(bt.value) + rentSection(name);
    h += isNation() ? `<p class="muted">點地圖上的柱子（或「排行」）進入一個縣市，才會下載那個縣市的逐筆成交與路段；也可以直接搜尋「台北市大安區…」這樣的地址。透天厝的單價含土地，看透天請以總價為主。</p>`
      : `<p class="muted">點地圖上的柱子看各區，或在上方搜尋地址。透天厝的單價含土地，看透天請以總價為主。</p>`;
  }
  return h;
}
function workplaceOptions(sel) {
  const groups = new Map();
  for (const w of D.workplaces) { const c = countyOf(w); if (!groups.has(c)) groups.set(c, []); groups.get(c).push(w); }
  const order = [...groups.keys()].sort((a, b) => (D.county && a === D.county.code ? -1 : 0) - (D.county && b === D.county.code ? -1 : 0)
    || L.COUNTIES.findIndex(c => c.code === a) - L.COUNTIES.findIndex(c => c.code === b));
  const opt = w => `<option${w.name === sel ? " selected" : ""}>${esc(w.name)}</option>`;
  if (!D.tw) return (groups.get("D") || []).map(opt).join("");
  return order.map(c => `<optgroup label="${esc((L.COUNTIES.find(x => x.code === c) || {}).short || c)}">${groups.get(c).map(opt).join("")}</optgroup>`).join("");
}
function tabCommute() {
  const s = S.settings, w = workPlace(), lim = commuteLimit() || 20;
  const opts = workplaceOptions(s.work) +
    (s.workPt ? `<option value="__custom"${s.work === "__custom" ? " selected" : ""}>自訂地點</option>` : "");
  let h = `<div class="row"><span>上班地點 A</span><select data-set="work"><option value="">（請選擇）</option>${opts}</select></div>
    <div class="row"><button class="btn small" data-act="work-pick">在地圖上點選 A</button>
    <div class="seg">${Object.entries(L.MODES).map(([k, m]) => `<button data-act="mode" data-mode="${k}" aria-checked="${s.mode === k}">${m[0]}</button>`).join("")}</div></div>
    <div class="year"><span>通勤上限</span><input type="range" id="commute-min" min="10" max="60" step="5" value="${lim}"><b id="commute-v">${lim} 分鐘</b></div>`;
  if (!w) return h + `<p class="muted">先選上班地點，或在地圖上點一下公司位置。地圖會畫出${modeName()} ${lim} 分鐘的範圍，下面列出範圍內每一區的房價。</p>`;
  ensureRouteTimes();
  const rs = routeStatus(w);
  const rows = D.districts.map(d => ({ d, m: minsTo(d.lat, d.lng, w), b: D.book.best(d.name, S.cat, "u"), t: D.book.best(d.name, S.cat, "t") }))
    .sort((a, b) => a.m - b.m);
  const inside = rows.filter(r => r.m <= lim && r.b.value != null);
  const cheap = [...inside].sort((a, b) => a.b.value - b.b.value)[0];
  h += `<div class="summary"><b>${esc(w.name)}</b>｜${modeName()} ${lim} 分鐘內：<b>${inside.length}</b> 個行政區` +
    (cheap ? `<br>範圍內單價最低：<a href="#" data-goto="${esc(cheap.d.name)}">${esc(cheap.d.name)}</a> ${cheap.b.value.toFixed(1)} 萬/坪、總價約 ${L.fmtNum(cheap.t.value)} 萬` : "") + `</div>`;
  h += `<table class="list"><thead><tr><th>B 行政區</th><th class="r">通勤</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>`;
  for (const r of rows) {
    const ok = r.m <= lim;
    h += `<tr class="click${r.b.low ? " low" : ""}" data-dist="${esc(r.d.name)}" style="${ok ? "" : "opacity:.4"}"><td>${esc(r.d.name)}</td><td class="r">${ok ? "<b>" + r.m + "</b>" : r.m} 分</td>` +
      `<td class="r">${r.b.value == null ? "—" : r.b.value.toFixed(1)}</td><td class="r">${L.fmtNum(r.t.value)}</td></tr>`;
  }
  const [f] = L.ROUTE_ADJ[S.settings.mode] || L.ROUTE_ADJ.car;
  const note = rs === "road" ? `通勤時間是依 OpenStreetMap 道路算的路線時間（到各區中心）${f > 1 ? `，${modeName()}已乘上尖峰係數 ${f}` : ""}，再加出發與停車的時間。` +
      `路線：<a href="https://project-osrm.org/" target="_blank" rel="noopener">OSRM</a>（FOSSGIS 公開伺服器）／© OpenStreetMap 貢獻者，道路有錯可以<a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener">回報修正</a>。`
    : rs === "loading" ? "正在向路線伺服器查實際道路的時間…（幾秒鐘）目前先顯示直線距離估算。"
    : `通勤時間是用直線距離 ×1.3 與平均車速（開車 32、機車 28、腳踏車 14 公里/時）估算${rs === "failed" ? "（路線伺服器暫時連不上，之後重新整理會再試）" : ""}，尖峰時段可能多 3～5 成。`;
  return h + `</tbody></table><p class="muted">${note}實際路線請按各區「概況」裡的「通勤路線」用 Google 地圖查。</p>`;
}
function tabRank() {
  const w = workPlace();
  const rows = D.districts.map(d => ({ d, b: D.book.best(d.name, S.cat, S.metric), t: D.book.best(d.name, S.cat, "t"), tr: D.book.trend(d.name, S.cat, S.metric),
    km: w ? minsTo(d.lat, d.lng, w) : null, ok: !filtersOn() || (budgetOK(d.name) && workOK(d.name)) }));
  rows.sort((a, b) => (b.b.value ?? -1) - (a.b.value ?? -1));
  const inc = parseFloat(S.settings.incomeMonthly) || 0;
  const ch5 = D.long ? new Map(rows.map(r => [r.d.name, L.longChange(L.longSeries(D.long, r.d.name, S.cat, S.metric), 5) || L.longChange(L.longSeries(D.long, r.d.name, S.cat, S.metric), 3)])) : null;
  const has5 = ch5 && [...ch5.values()].some(Boolean);
  let h = `<table class="list"><thead><tr><th>行政區</th><th class="r">${S.metric === "u" ? "萬/坪" : "總價"}</th><th class="r">總價</th>${inc ? '<th class="r" title="中位總價 ÷ 家庭年收入">年</th>' : ""}${w ? '<th class="r">通勤</th>' : ""}<th class="r">半年</th>${has5 ? '<th class="r" title="近 5 年漲跌（件數不夠時改看近 3 年，標 *）">5 年</th>' : ""}</tr></thead><tbody>`;
  for (const r of rows) {
    h += `<tr class="click${r.b.low ? " low" : ""}${r.d.name === S.current ? " sel" : ""}" data-dist="${esc(r.d.name)}" style="${r.ok ? "" : "opacity:.45"}"><td>${esc(r.d.name)}</td>` +
      `<td class="r">${r.b.value == null ? "—" : S.metric === "u" ? r.b.value.toFixed(1) : L.fmtNum(r.b.value)}</td><td class="r">${L.fmtNum(r.t.value)}</td>` +
      (inc ? `<td class="r">${(v => v ? v.toFixed(1) : "—")(L.priceIncomeRatio(r.t.value, inc))}</td>` : "") +
      (w ? `<td class="r">${r.km}分</td>` : "") + `<td class="r">${L.trendText(r.tr).replace("樣本不足", "—")}</td>` +
      (has5 ? (c => `<td class="r">${c ? `${c.pct >= 0 ? "+" : ""}${c.pct.toFixed(0)}%${c.years < 5 ? "*" : ""}` : "—"}</td>`)(ch5.get(r.d.name)) : "") + `</tr>`;
  }
  return h + `</tbody></table><p class="muted">灰字是樣本少（近半年不到 5 件）。${filtersOn() ? "淡色是不符合預算／通勤條件。" : ""}` +
    (inc ? `「年」是中位總價 ÷ 你的家庭年收入（${L.fmtNum(inc * 12 / 10000)} 萬），也就是不吃不喝幾年買得起。` : `在「☰ → 篩選 → 用收入算」填家庭月收入，這裡會多一欄「不吃不喝幾年」。`) +
    ` 全國與各縣市的官方房價所得比：<a href="https://pip.moi.gov.tw/Publicize/Info/Index" target="_blank" rel="noopener">內政部不動產資訊平台</a>（每季發布）。</p>`;
}
export const needCounty = () => `<p class="muted">先在地圖上點一個縣市的柱子（或從「排行」選），才會載入那個縣市的逐筆成交、路段與社區。</p>`;
function tabRoads() {
  if (isNation()) return needCounty();
  if (!D.txs) return `<p class="empty">成交資料載入中…</p>`;
  const since = D.book.windows.y12[0], kw = S.roadKw.trim();
  let list, note;
  if (S.current === L.CITY) {
    list = kw ? L.searchRoads(D.txs, kw, S.cat, since) : [];
    note = kw ? `全市路名含「${esc(kw)}」的路段 ${list.length} 個，點一列會到那一區。` : "輸入路名（例如「中山路」）搜尋全市；或先選一個行政區，列出區內所有路段。";
  } else {
    list = L.roadPrices(D.txs, S.current, S.cat, since);
    if (kw) list = list.filter(r => r.name.includes(kw));
    note = `${esc(S.current)}近一年有成交的${S.cat === "presale" ? "建案" : "路段"} ${list.length} 個（灰字不到 3 件），點一列看逐筆成交並在地圖上標出來。`;
  }
  const city = S.current === L.CITY;
  let h = `<div class="row"><input type="search" id="road-kw" placeholder="路名，例如：中山路" value="${esc(kw)}"></div><p class="muted">${note}</p>`;
  if (!list.length) return h;
  h += `<table class="list"><thead><tr>${city ? "<th>區</th>" : ""}<th>${S.cat === "presale" ? "建案" : "路段"}</th><th class="r">件</th><th class="r">萬/坪</th><th class="r">總價</th><th class="r">最近</th></tr></thead><tbody>`;
  for (const r of list.slice(0, 300)) {
    h += `<tr class="click${r.low ? " low" : ""}${r.name === S.roadFilter && r.dist === S.current ? " sel" : ""}" data-road="${esc(r.name)}" data-rdist="${esc(r.dist)}">` +
      (city ? `<td>${esc(r.dist)}</td>` : "") + `<td>${esc(r.name)}${r.low ? "*" : ""}</td><td class="r">${r.n}</td><td class="r">${r.u.toFixed(1)}</td><td class="r">${L.fmtNum(r.t)}</td><td class="r">${r.last.slice(2, 7).replace("-", "/")}</td></tr>`;
  }
  return h + "</tbody></table>";
}
function linksRow(dist, place, title) {
  return `<div class="links"><span class="muted">${esc(title)}：</span>` + L.platformLinks(dist, place).map(([n, u]) =>
    `<a class="btn small" href="${esc(u)}" target="_blank" rel="noopener">${esc(n)}</a>`).join("") + `</div>`;
}
function tabBldg() {
  if (isNation()) return needCounty();
  if (!D.txs) return `<p class="empty">成交資料載入中…</p>`;
  if (S.current === L.CITY) return `<p class="muted">先在地圖或「排行」選一個行政區，這裡會列出區內有多筆成交的社區／大樓。</p>`;
  const since = D.book.windows.y12[0], kw = S.bldgKw.trim();
  const all = L.buildings(D.txs, S.current, S.cat, since);
  let h = "";
  const b = S.bldg && all.find(r => r.key === S.bldg);
  // 預售屋解約：已解約筆數 ÷（有效成交＋已解約）；資料是實價登錄「解約情形」欄
  const cancelOf = r => {
    if (!r.presale || !D.cancel) return null;
    const c = D.cancel.get(S.current + "|" + r.name) || 0;
    return { n: c, pct: c / (c + r.n) * 100, warn: c >= 3 && c / (c + r.n) >= 0.1 };
  };
  if (b) {
    const age = b.built ? `屋齡約 ${Math.max(0, new Date().getFullYear() - b.built)} 年｜` : "";
    h += `<div class="summary"><b>${esc(b.name)}</b>｜${esc(S.current)}<br>${esc(b.btype)}｜${age}共 ${b.n} 筆，中位單價 ${b.u.toFixed(1)} 萬/坪、總價 ${L.fmtNum(b.t)} 萬` +
      (b.n12 ? `<br>近一年 ${b.n12} 筆：中位單價 ${b.u12.toFixed(1)} 萬/坪` : `<br>近一年沒有成交`) + `</div>`;
    const cx = cancelOf(b);
    if (cx && cx.n) h += `<div class="${cx.warn ? "note" : "summary"}">已解約 <b>${cx.n} 筆</b>（佔登錄的 ${cx.pct.toFixed(1)}%）。` +
      (cx.warn ? "解約比例偏高，可能是投資客轉手不順、建案或建商出狀況，買之前多打聽、注意履約保證。" : "少量解約很常見（換約、貸款不過）。") + `</div>`;
    else if (cx) h += `<p class="muted">這個建案在實價登錄沒有解約紀錄。</p>`;
    h += linksRow(S.current, b.presale ? b.name : b.name, "找這個社區正在賣的房子");
    h += `<div class="row"><button class="btn small" data-act="bldg-back">← 回社區列表</button></div>`;
    if (S.pin) h += poiButton(S.pin.lat, S.pin.lng, b.name);
    const rows = D.txs.filter(x => x.dist === S.current && L.inCat(x, S.cat) && L.bldgKey(x) === b.key);
    // 這一棟的公設比、實坪單價、電梯、管理組織（看最近的登錄）
    const shares = rows.filter(x => x.ps != null).map(x => x.ps), reals = rows.map(L.realUnit).filter(v => v != null);
    const flag = k => { const v = rows.map(x => x[k]).find(v => v); return v === 1 ? "有" : v === 2 ? "無" : null; };
    const feats = [shares.length ? `公設比約 ${L.median(shares).toFixed(1)}%` : "", reals.length ? `實坪單價 ${L.median(reals).toFixed(1)} 萬/坪` : "",
      flag("ev") ? `電梯：${flag("ev")}` : "", flag("mg") ? `管理組織：${flag("mg")}` : ""].filter(Boolean);
    if (feats.length) h += `<p class="muted">${feats.join("｜")}</p>`;
    const fpro = L.floorProfile(rows);
    if (fpro) {
      const mid = L.median(fpro.flatMap(r => Array(r.n).fill(r.u)));
      h += `<h3>各樓層單價</h3><table class="list"><thead><tr><th>樓層</th><th class="r">件</th><th class="r">中位萬/坪</th><th class="r">比整棟中位</th></tr></thead><tbody>` +
        fpro.map(r => `<tr><td>${r.fl} 樓</td><td class="r">${r.n}</td><td class="r">${r.u.toFixed(1)}</td><td class="r">${mid ? `${r.u >= mid ? "+" : ""}${((r.u - mid) / mid * 100).toFixed(1)}%` : "—"}</td></tr>`).join("") + `</tbody></table>`;
    }
    const qs = L.quarterSeries(rows);
    if (qs) {
      const max = Math.max(...qs.rows.map(r => r.n));
      h += `<h3>每季成交單價</h3><div class="summary">${b.presale ? "首批登錄" : "最早"}（${qs.first.q}）${qs.first.u.toFixed(1)} 萬/坪 → 最近（${qs.last.q}）<b>${qs.last.u.toFixed(1)}</b> 萬/坪` +
        (qs.pct != null ? `，<b class="${qs.pct >= 0 ? "up" : "down"}">${qs.pct >= 0 ? "漲" : "跌"} ${Math.abs(qs.pct).toFixed(1)}%</b>` : "") +
        `${b.presale ? "<br>預售屋後期釋出的多半是高樓層或邊間，單價變化不完全是漲價。" : ""}</div>` +
        `<table class="list"><thead><tr><th>季</th><th class="r">件</th><th class="r">中位萬/坪</th><th></th></tr></thead><tbody>` +
        qs.rows.map(r => `<tr${r.n < 3 ? ' class="low"' : ""}><td>${r.q}</td><td class="r">${r.n}</td><td class="r">${r.u.toFixed(1)}</td>` +
          `<td style="width:40%"><div class="qbar" style="width:${Math.max(4, r.n / max * 100).toFixed(0)}%"></div></td></tr>`).join("") + `</tbody></table>`;
    }
    h += `<h3>每一筆成交</h3><table class="list"><thead><tr><th>日期</th><th>樓層／地址</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">坪</th></tr></thead><tbody>`;
    for (const x of rows.slice(0, 300))
      h += `<tr><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${x.fl != null ? `<b>${x.fl}F</b> ` : ""}${esc(x.addr)}${x.pk ? `<div class="muted">含車位 ${x.pk}${x.pkp ? `（${L.fmtNum(x.pkp)} 萬）` : ""}</div>` : ""}</td><td class="r">${L.fmtNum(x.tw)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${x.ping.toFixed(1)}</td></tr>`;
    return h + `</tbody></table>`;
  }
  const list = kw ? all.filter(r => r.name.includes(kw)) : all;
  h += `<div class="row"><input type="search" id="bldg-kw" placeholder="社區或路名，例如：成功路" value="${esc(kw)}"></div>`;
  h += `<p class="muted">${esc(S.current)}有 2 筆以上成交的${S.cat === "presale" ? "建案" : "社區／大樓"} ${list.length} 個。實價登錄沒有社區名稱，中古屋以「同一個門牌」當作同一棟；預售屋用建案名稱。點一列看每一筆成交。</p>`;
  if (!list.length) return h;
  const presale = S.cat === "presale" && D.cancel && D.cancel.size;
  if (presale) {
    const warn = list.filter(r => cancelOf(r)?.warn).length;
    h += `<p class="muted">「解約」欄是實價登錄的已解約筆數與比例；${warn ? `<b class="up">${warn} 個建案</b>解約偏多（3 筆以上、而且超過 1 成），標成紅色。` : "目前沒有解約偏多的建案。"}</p>`;
  }
  h += `<table class="list"><thead><tr><th>社區／門牌</th><th class="r">件</th><th class="r">萬/坪</th><th class="r">近一年</th><th class="r">${presale ? "解約" : "屋齡"}</th></tr></thead><tbody>`;
  const yr = new Date().getFullYear();
  for (const r of list.slice(0, 300)) {
    const cx = presale ? cancelOf(r) : null;
    h += `<tr class="click" data-bldg="${esc(r.key)}"><td>${esc(r.name)}<div class="muted">${esc(r.btype)}｜最近 ${r.last.slice(2, 7).replace("-", "/")}</div></td><td class="r">${r.n}</td>` +
      `<td class="r">${r.u.toFixed(1)}</td><td class="r">${r.u12 == null ? "—" : r.u12.toFixed(1)}</td>` +
      (presale ? `<td class="r${cx && cx.warn ? " up" : ""}">${cx && cx.n ? `${cx.n}（${cx.pct.toFixed(0)}%）` : "—"}</td></tr>` : `<td class="r">${r.built ? Math.max(0, yr - r.built) : "—"}</td></tr>`);
  }
  return h + "</tbody></table>";
}
function txRows() {
  const name = S.current;
  const f = S.txf || {};
  let rows = D.txs.filter(x => (name === L.CITY || x.dist === name) && L.inCat(x, S.cat) && L.txFilter(x, f));
  if (S.roadFilter && name !== L.CITY) rows = rows.filter(x => (S.cat === "presale" ? (x.proj || "未命名建案") : x.road) === S.roadFilter);
  const q = S.addr && S.addr.district === name && S.roadFilter === S.addr.road && S.cat !== "presale" ? S.addr : null;
  return { q, ranked: q ? L.rankByAddress(rows, q) : rows.map(x => ({ level: 1, x })) };
}
function tabTx() {
  if (isNation()) return needCounty();
  if (!D.txs) return `<p class="empty">成交資料載入中…</p>`;
  const { q, ranked } = txRows();
  S.txShown = ranked.slice(0, 300).map(r => r.x);
  let h = "";
  if (q) {
    const st = L.addressSummary(ranked), part = (t, g) => `${t} ${g.n} 筆：中位單價 ${g.u.toFixed(1)} 萬/坪、總價 ${L.fmtNum(g.t)} 萬`;
    const lines = [`<b>${esc(q.district)} ${esc(L.describe(q))}</b>｜${L.CAT_LABEL[S.cat]}`];
    if (!ranked.length) lines.push("實價登錄裡這條路沒有符合的成交。");
    else {
      if (q.num != null) lines.push(st.exact.n ? part("同門牌", st.exact) : "同門牌沒有成交紀錄，下面依門牌號碼由近到遠排列。");
      if (q.lane != null && st.lane.n > st.exact.n) lines.push(part("同一條巷", st.lane));
      lines.push(part("整條路", st.road));
    }
    const w = workPlace();
    if (w && S.pin) lines.push(`到${esc(w.name)}：${modeName()}約 ${minsTo(S.pin.lat, S.pin.lng, w)} 分鐘（估計）｜<a target="_blank" rel="noopener" href="${L.routeUrl(S.pin, w, S.settings.mode)}">看實際路線</a>`);
    h += `<div class="summary">${lines.join("<br>")}</div>`;
    if (S.pin) h += poiButton(S.pin.lat, S.pin.lng, S.pin.label).replace("</div>", reportButton() + "</div>");
  } else {
    const scope = S.roadFilter ? `${S.current} ${S.roadFilter}` : S.current;
    h += `<p class="muted">${esc(scope)}｜${L.CAT_LABEL[S.cat]}｜共 ${ranked.length} 筆，列出最近 ${Math.min(300, ranked.length)} 筆（已排除親友等特殊交易）。點一列在地圖上標出大概位置。</p>`;
  }
  if (S.roadFilter) h += `<div class="row"><button class="btn small" data-act="clear-road">顯示全區</button></div>`;
  const f = S.txf || {};
  h += `<div class="row tx-filter"><span class="muted">格局</span><div class="seg">` +
    [["", "不限"], ["1", "1房"], ["2", "2房"], ["3", "3房"], ["4", "4房+"]].map(([v, t]) => `<button data-act="txf" data-k="rm" data-v="${v}" aria-checked="${(f.rm || "") === v}">${t}</button>`).join("") +
    `</div><label class="chk"><input type="checkbox" data-txf-ev${f.ev ? " checked" : ""}> 只看有電梯</label></div>`;
  if (S.roadFilter && S.cat !== "presale") h += linksRow(S.current, q && q.district === S.current ? L.describe(q).replace(/ /g, "") : S.roadFilter, "找這條路正在賣的房子");
  h += `<table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">坪</th></tr></thead><tbody>`;
  ranked.slice(0, 300).forEach((r, i) => {
    const x = r.x, where = x.proj ? `${x.proj}（${x.addr.slice(0, 12)}）` : x.addr;
    const age = x.built ? ` ${Math.max(0, +x.date.slice(0, 4) - x.built)}年` : "";
    const extra = [x.rm ? `${x.rm}房` : "", x.ps != null && x.cat === "apt" ? `公設${Math.round(x.ps)}%` : "", x.fl != null ? `${x.fl}樓` : "", x.ev === 1 && x.cat !== "house" ? "電梯" : ""].filter(Boolean).join(" ");
    h += `<tr class="click ${r.level === 3 ? "exact" : r.level === 2 ? "lane" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td>` +
      `<td>${esc(where)}<div class="muted">${esc(x.btype)}${age}${extra ? "｜" + extra : ""}${S.current === L.CITY ? "｜" + esc(x.dist) : ""}</div></td>` +
      `<td class="r">${L.fmtNum(x.tw)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${x.ping.toFixed(1)}</td></tr>`;
  });
  return h + `</tbody></table>${ranked.length ? "" : '<p class="empty">沒有符合的成交。</p>'}`;
}
function stateClass(s) { return s === "完工" ? "done" : s === "施工中" ? "build" : "plan"; }
function tabProjects() {
  const items = D.intel.filter(it => it.build && it.lat != null && inScope(it, true) && (S.current === L.CITY || (it.district || "").includes(S.current)));
  const yMin = new Date().getFullYear();
  let h = `<div class="year"><span>建設年份</span><input type="range" id="year" min="${yMin}" max="${yMin + 9}" value="${S.year}"><b id="year-v">${S.year} 年</b></div>`;
  h += `<p class="muted">拉到未來的年份，看那時候哪些建設完工。年份依報導與官方說法整理，常會延後。</p>`;
  if (!items.length) return h + `<p class="empty">這一區沒有收錄有時程的重大建設。</p>`;
  const rows = items.map(it => ({ it, st: L.buildState(it.build, S.year) })).sort((a, b) => (b.it.impact_level || 0) - (a.it.impact_level || 0));
  h += `<table class="list"><tbody>`;
  for (const { it, st } of rows) h += `<tr class="click" data-proj="${it.id}"><td><span class="pill ${stateClass(st)}">${st}</span>${esc(it.name)}<div class="muted">${esc(it.district || "")}｜${esc(it.build.note || "")}</div></td></tr>`;
  return h + "</tbody></table>";
}
function writeIntel(it) {
  let h = `<h2 style="margin-top:2px">${esc(it.name)}</h2><p class="muted">${esc([it.type, it.district, it.impact_level ? "影響度 " + it.impact_level + "/5" : "", it.confidence ? "可信度 " + it.confidence : ""].filter(Boolean).join("｜"))}</p>`;
  if (it.build) {
    const st = L.buildState(it.build, S.year);
    h += `<h3>時程</h3><p><span class="pill ${stateClass(st)}">${S.year} 年：${st}</span> ${esc(it.build.note || "")}</p>`;
  }
  h += `<h3>現況</h3><p>${esc(it.status)}</p>`;
  for (const [t, k] of [["時程", "timeline"], ["主辦／開發商", "developer"], ["規模", "scale"], ["對周邊的可能影響", "impact"]]) if (it[k]) h += `<h3>${t}</h3><p>${esc(it[k])}</p>`;
  const dists = D.districts.filter(d => (it.district || "").includes(d.name));
  if (dists.length) {
    h += `<h3>所在區的房價</h3>`;
    for (const d of dists) {
      const b = D.book.best(d.name, S.cat, "u"), tr = D.book.trend(d.name, S.cat, "u");
      h += `<p><a href="#" data-goto="${esc(d.name)}">${esc(d.name)}</a> <span class="muted">${b.value != null ? "中位單價 " + b.value.toFixed(1) + " 萬/坪" : ""}${tr != null ? "、近半年 " + L.trendText(tr) : ""}</span></p>`;
    }
  }
  if (it.sources && it.sources.length) {
    h += `<h3>來源</h3>` + it.sources.slice(0, 4).map(s => `<p class="muted">· <a target="_blank" rel="noopener" href="${esc(s.url)}">${esc(s.title)}</a> ${esc(s.date || "")}</p>`).join("");
  }
  return h + `<p class="muted">影響度為整理資料時的主觀評估，不是投資建議。</p>`;
}
function tabDetail() {
  if (!S.picked) return `<p class="empty">點地圖上的地標、建設、開發案或車站，這裡會顯示說明。</p>`;
  const [kind, id] = S.picked;
  if (kind === "landmark") {
    const l = D.landmarks.find(x => x.id === id);
    const dists = D.districts.filter(d => (l.district || "").includes(d.name));
    return `<h2 style="margin-top:2px">${esc(l.name)}</h2><p class="muted">${esc(l.district || "")}</p><p>${esc(l.note || "")}</p>` +
      dists.map(d => { const b = D.book.best(d.name, S.cat, "u"); return `<p><a href="#" data-goto="${esc(d.name)}">看${esc(d.name)}的房價</a> <span class="muted">${b.value != null ? "中位單價 " + b.value.toFixed(1) + " 萬/坪" : ""}</span></p>`; }).join("") +
      `<p><a target="_blank" rel="noopener" href="https://www.google.com/maps/search/${encodeURIComponent(L.COUNTY_NAME.replace("全台", "") + " " + l.name)}">在 Google 地圖查看</a></p><p class="muted">圖案是示意造型，位置取自 OpenStreetMap。</p>`;
  }
  if (kind === "school") {
    const s = (D.schools || []).find(x => x.id === id);
    if (!s) return "";
    const b = D.book.best(s.district, S.cat, "u");
    return `<h2 style="margin-top:2px">🎓 ${esc(s.name)}</h2>` +
      `<p><span class="badge ${s.status.includes('額滿') ? 'danger' : 'primary'}">${esc(s.status)}</span> <span class="muted">${esc(s.type)}｜${esc(s.district)}</span></p>` +
      `<p>${esc(s.note)}</p>` +
      `<p><a href="#" data-goto="${esc(s.district)}">查看 ${esc(s.district)} 房價行情</a> <span class="muted">${b.value != null ? "（中位單價 " + b.value.toFixed(1) + " 萬/坪）" : ""}</span></p>` +
      `<p><a target="_blank" rel="noopener" href="https://www.google.com/maps/search/${encodeURIComponent(s.name)}">在 Google 地圖查看</a></p>` +
      `<p class="muted">學區劃分與入學管制以各縣市教育局最新公告為準。</p>`;
  }
  if (kind === "project" || kind === "marker") return writeIntel(D.intel[id]);
  if (kind === "station") {
    const ln = allLines().find(l => l.name === id[0]);
    if (!ln) return "";
    if (ln.operating) return `<h2 style="margin-top:2px">${esc(id[1])}</h2><p><span class="pill" style="background:${esc(ln.color)};color:#fff">${esc(ln.kind || "捷運")}</span> ${esc(ln.full_name || ln.name)}｜營運中</p>` +
      `<p class="muted">${esc(ln.network || "")}</p><p><a target="_blank" rel="noopener" href="https://www.google.com/maps/search/${encodeURIComponent(id[1] + " " + (ln.kind || ""))}">在 Google 地圖查看</a></p>` +
      `<p class="muted">路線與車站位置取自 OpenStreetMap。</p>`;
    return `<h2 style="margin-top:2px">${esc(id[0])}｜${esc(id[1])}</h2><p>${esc(ln.status)}</p><p class="muted">預計動工：${esc(ln.construction_start)}｜預計通車：${esc(ln.estimated_completion)}</p>` +
      (ln.sources || []).map(s => `<p class="muted">· <a target="_blank" rel="noopener" href="${esc(s.url)}">${esc(s.title)}</a></p>`).join("") +
      `<p class="muted">站位依路口與地標估算，誤差可能達數百公尺。</p>`;
  }
  if (kind === "pin" && id === "work") {
    const w = workPlace();
    if (!w) return "";
    const near = D.districts.map(d => [minsTo(d.lat, d.lng, w), d.name]).sort((a, b) => a[0] - b[0]).slice(0, 8);
    return `<h2 style="margin-top:2px">上班地點：${esc(w.name)}</h2><p class="muted">通勤時間是${modeName()}的估計值。完整比較請看「通勤」分頁。</p><h3>最近的行政區</h3>` +
      near.map(([m, n]) => `<p><a href="#" data-goto="${esc(n)}">${esc(n)}</a> <span class="muted">約 ${m} 分鐘</span></p>`).join("");
  }
  return "";
}

// ------------------------------------------------------------------ 設定
function renderMenu() {
  const s = S.settings, chk = (k, t) => `<label class="chk"><input type="checkbox" data-set="${k}"${s[k] ? " checked" : ""}> ${t}</label>`;
  $("#menu-body").innerHTML = `
    <h3>地圖圖層</h3>${chk("town", "行政區界")}${chk("liq", "土壤液化潛勢")}${D.tw ? chk("slide", "山崩與地滑（地質敏感區）") : ""}${chk("fault", "活動斷層")}
    <p class="muted">淹水潛勢：官方圖資沒有開放疊圖，請到 <a target="_blank" rel="noopener" href="${FLOOD_URL}">國家災害防救科技中心 3D 災害潛勢地圖</a> 查詢（各區「概況」也有「淹水潛勢」按鈕）。</p>${chk("hires", "放大時載入高解析衛星影像（較耗流量）")}
    ${chk("lines", "捷運、輕軌、高鐵（營運中與規劃）")}${chk("markers", "開發案與情資（菱形）")}${chk("landmarks", "知名地標 3D")}${chk("projects", "重大建設 3D")}${chk("schools", "🎓 明星學區與額滿學校")}${chk("roads", "路段房價（選了行政區才畫）")}${chk("labels", "名稱標籤")}
    <h3>柱子顏色</h3><div class="row"><select data-set="color"><option value="price"${s.color === "price" ? " selected" : ""}>價格高低</option><option value="trend"${s.color === "trend" ? " selected" : ""}>近半年漲跌</option><option value="yield"${s.color === "yield" ? " selected" : ""}>毛租金投報率</option><option value="heat"${s.color === "heat" ? " selected" : ""}>市場冷熱（量＋價）</option><option value="pop"${s.color === "pop" ? " selected" : ""}>近 5 年人口增減</option></select></div>
    <h3>外觀</h3><div class="row"><select data-set="theme" aria-label="外觀">${[["", "跟著系統"], ["light", "淺色"], ["dark", "深色"]].map(([v, t]) => `<option value="${v}"${(s.theme || "") === v ? " selected" : ""}>${t}</option>`).join("")}</select></div>
    <h3>篩選</h3>
    <div class="row"><span>總價預算</span><input type="text" inputmode="decimal" data-set="budget" value="${esc(s.budget)}" placeholder="萬，例 1500"></div>
    <details class="more" data-det="incomeOpen"${s.incomeOpen ? " open" : ""}><summary>不知道預算多少？用收入算</summary>
    <div class="row"><span>家庭月收入</span><input type="text" inputmode="numeric" data-set="incomeMonthly" value="${esc(s.incomeMonthly || "")}" placeholder="元，例 120000"></div>
    <div class="row"><span>可用現金</span><input type="text" inputmode="decimal" data-set="cash" value="${esc(s.cash || "")}" placeholder="萬，自備款＋稅費，例 350"></div>
    <div id="budget-calc">${budgetCalc()}</div></details>
    <div class="row"><span>上班地點</span><select data-set="work"><option value="">（不設定）</option>${workplaceOptions(s.work)}${s.workPt ? `<option value="__custom"${s.work === "__custom" ? " selected" : ""}>自訂地點</option>` : ""}</select></div>
    <div class="row"><span>通勤上限</span><input type="text" inputmode="numeric" data-set="commuteMin" value="${esc(s.commuteMin)}"> <span>分鐘（${modeName()}）</span></div>
    <p class="muted">不符合預算或通勤範圍的行政區，柱子會縮成灰色小方塊。</p>
    <h3>資料</h3><p class="muted">${esc(D.meta.describe)}；成交 ${L.fmtNum(D.meta.tx_count)} 筆；整理於 ${esc(D.meta.built)}。<br>
    房價：內政部實價登錄開放資料。道路位置：© OpenStreetMap 貢獻者。影像與行政區界：內政部國土測繪中心。
    土壤液化、山崩與地滑、活動斷層：經濟部地質調查及礦業管理中心。捷運與高鐵路線：© OpenStreetMap 貢獻者。重大建設整理自新聞與官方公告。統計值為中位數，僅供看屋參考，不構成投資或購屋建議。</p>
    <p class="muted"><b>程式與設計 © 全台房價即時動態分析，保留所有權利。</b>未經授權請勿複製、轉載或改作本網站的程式、介面設計與 3D 造型；房價、行政區、影像等資料依各來源的開放授權使用。</p>
    <p class="muted">這個網頁的所有計算都在你的裝置上完成；設定與看屋清單只存在這台裝置的瀏覽器裡。<br>
    手機瀏覽器選單裡的「加到主畫面」，之後可以像 App 一樣開啟。</p>
    ${problemSection()}`;
  $("#btn-menu").classList.remove("has-err");
}
function budgetCalc() {
  const r = L.budgetFromIncome(parseFloat(S.settings.incomeMonthly), parseFloat(S.settings.cash));
  if (!r) return `<p class="muted">填月收入（和可用現金）就能算出大約買得起多少。</p>`;
  return `<div class="summary">大約可以買到 <b>${L.fmtNum(r.price)} 萬</b>` +
    (r.byCash != null ? `<br>收入可負擔 ${L.fmtNum(r.byIncome)} 萬、現金夠付 ${L.fmtNum(r.byCash)} 萬的頭期款與稅費，${r.limit === "cash" ? "卡在現金" : "卡在收入"}` : `<br>（沒填現金：假設自備兩成）`) +
    `<br>每月房貸控制在 ${L.fmtNum(r.safeMonthly)} 元（收入 1/3）以內</div>` +
    `<div class="row"><button type="button" class="btn small primary" data-act="use-budget" data-budget="${r.price}">用 ${L.fmtNum(r.price)} 萬當預算，地圖標出買得起的區</button></div>` +
    `<p class="muted">貸款以新青安（1,000 萬內）＋一般房貸試算，自備至少兩成，另留總價約 3% 的稅費雜支。銀行實際核貸要看信用與負債，這不是貸款建議。</p>`;
}
function problemSection() {
  const errs = loadErrors(), st = D.status;
  let h = `<h3 id="problems">問題回報</h3>`;
  if (st) h += `<p class="muted">資料自動更新：${esc(st.time)}　${st.ok ? "✓ 正常" : `<b class="up">有步驟失敗：${esc((st.failed || []).join("、"))}</b>（已自動通知維護者）`}</p>`;
  h += errs.length ? `<p class="muted">這台裝置記錄到 ${errs.length} 筆錯誤，最近的：</p>` +
      errs.slice(-3).reverse().map(e => `<p class="muted">· ${esc(e.t.slice(5, 16))} ${esc(e.where)}：${esc(e.msg.slice(0, 80))}</p>`).join("")
    : `<p class="muted">這台裝置沒有記錄到錯誤。</p>`;
  h += `<div class="row"><button class="btn small primary" data-act="err-report">到 GitHub 回報</button><button class="btn small" data-act="err-copy">複製錯誤內容</button>` +
    (errs.length ? `<button class="btn small" data-act="err-clear">清除紀錄</button>` : "") + `</div>` +
    `<label class="chk"><input type="checkbox" data-set="autoReport"${S.settings.autoReport !== false ? " checked" : ""}> 自動匿名回報錯誤（只送錯誤內容與瀏覽器版本，不含個人資料）</label>` +
    `<p class="muted">錯誤會自動匿名送給維護者（不需要帳號）。想補充說明的話，按「到 GitHub 回報」會開一張已經填好錯誤內容的回報單（要登入 GitHub 才能送出）；沒有帳號的話，按「複製錯誤內容」貼給維護者就好。</p>`;
  return h;
}
function onSetting(el) {
  const k = el.dataset.set, v = el.type === "checkbox" ? el.checked : el.value;
  S.settings[k] = v; saveStore();
  view.layerOn = { town: S.settings.town, liq: S.settings.liq, slide: S.settings.slide, fault: S.settings.fault };
  view.show.hires = S.settings.hires; view.show.lines = S.settings.lines; view.show.labels = S.settings.labels;
  if (["budget", "work", "workKm", "commuteMin", "mode", "color", "incomeMonthly"].includes(k)) { refreshBars(); refreshPins(); renderPanel(); }
  if (["landmarks", "projects", "markers", "schools"].includes(k)) refreshModels();
  if (k === "roads") refreshRoads();
  if (k === "theme") applyTheme();
  if (k === "work" && workPlace()) { const w = workPlace(); view.flyTo(w.lat, w.lng, Math.max(view.zoom, 30)); ensureRouteTimes(); }
  view.request();
}

// 外觀：空白＝跟著系統的深淺色；選了淺色／深色就固定（CSS 看 <html data-theme>）
function applyTheme() {
  const t = S.settings.theme;
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]').content = dark ? "#14857c" : "#0b5d57";      // 和頂列的顏色一致
}

// ------------------------------------------------------------------ 底部抽屜（手機）
export function sheet(state) {
  if (window.innerWidth >= 900) { view.setInset({ top: 44 }); placeAttrib(); return; }
  const el = $("#sheet");
  el.classList.toggle("half", state === "half");
  el.classList.toggle("full", state === "full");
  S.sheet = state;
  const appH = $("#app").clientHeight, peek = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sheet-peek")) || 168;
  view.setInset({ bottom: state === "peek" ? peek : appH * 0.55, top: 96 });
  // 抽屜只拉出一半時，面板下半截在螢幕外：清單底部留白，最後幾列才捲得上來
  $("#tab-body").style.paddingBottom = state === "half" ? `${Math.round(el.clientHeight * 0.45) + 16}px` : "";
  placeAttrib();
}
// 浮在地圖上的按鈕、圖例：名稱標籤不要畫在它們底下
function updateReserved() {
  const m = $("#map").getBoundingClientRect(), pad = 4;
  view.reserved = ["#chips", "#map-tools", "#legend", "#attrib"].map(sel => $(sel)).filter(el => el && !el.hidden && el.offsetParent)
    .map(el => { const r = el.getBoundingClientRect(); return [r.left - m.left - pad, r.top - m.top - pad, r.right - m.left + pad, r.bottom - m.top + pad]; });
  view.request();
}
function placeAttrib() {
  const a = $("#attrib"), wide = window.innerWidth >= 900;
  const bottom = wide ? 4 : (S.sheet === "peek" || !S.sheet ? (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sheet-peek")) || 168) + 4 : $("#app").clientHeight * 0.55 + 4);
  a.style.bottom = bottom + "px";
  a.textContent = "影像、行政區界：內政部國土測繪中心｜道路：© OpenStreetMap 貢獻者";
  requestAnimationFrame(updateReserved);
}
function bindSheetDrag() {
  const el = $("#sheet"), handle = [$("#sheet-handle"), $("#sheet-head")];
  let y0 = null, s0 = null, moved = false;
  for (const h of handle) {
    h.addEventListener("pointerdown", e => { if (window.innerWidth >= 900 || e.target.closest("button")) return; y0 = e.clientY; s0 = S.sheet || "peek"; moved = false; h.setPointerCapture(e.pointerId); el.classList.add("dragging"); });
    h.addEventListener("pointermove", e => {
      if (y0 == null) return;
      const dy = e.clientY - y0; if (Math.abs(dy) > 6) moved = true;
      const H = el.clientHeight, peek = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sheet-peek")) || 168;
      const base = s0 === "full" ? 0 : s0 === "half" ? H * 0.45 : H - peek;
      el.style.transform = `translateY(${Math.max(0, Math.min(H - peek, base + dy))}px)`;
    });
    const up = e => {
      if (y0 == null) return;
      const dy = e.clientY - y0; y0 = null; el.classList.remove("dragging"); el.style.transform = "";
      const order = ["peek", "half", "full"], i = order.indexOf(s0);
      if (!moved) sheet(s0 === "peek" ? "half" : s0 === "half" ? "peek" : "half");
      else sheet(order[Math.max(0, Math.min(2, i + (dy < -40 ? 1 : dy > 40 ? -1 : 0)))]);
    };
    h.addEventListener("pointerup", up); h.addEventListener("pointercancel", up);
  }
}

// ------------------------------------------------------------------ 事件
function bindUI() {
  $("#seg-cat").innerHTML = L.CATS.map(([k, t]) => `<button role="radio" data-cat="${k}" aria-checked="${S.cat === k}">${t.replace("大樓／華廈", "大樓")}</button>`).join("");
  $("#seg-metric").innerHTML = [["u", "單價"], ["t", "總價"]].map(([k, t]) => `<button role="radio" data-metric="${k}" aria-checked="${S.metric === k}">${t}</button>`).join("");
  $("#chips").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.cat) { S.cat = b.dataset.cat; if (!(S.addr && S.cat !== "presale")) S.roadFilter = null; }
    if (b.dataset.metric) S.metric = b.dataset.metric;
    $("#chips").querySelectorAll("button").forEach(x => x.setAttribute("aria-checked", x.dataset.cat ? x.dataset.cat === S.cat : x.dataset.metric === S.metric));
    refreshAll();
  });
  $("#map-tools").addEventListener("click", e => {
    const a = (e.target.closest("button") || {}).dataset?.act;
    if (a === "home") { if (D.county && S.current === L.CITY) enterNation(); else selectDistrict(L.CITY); }
    if (a === "zin") view.zoomAt(1.4); if (a === "zout") view.zoomAt(1 / 1.4);
    if (a === "rotl") view.rotate(-20); if (a === "rotr") view.rotate(20);
    if (a === "tilt") { view.pitch = view.pitch > 70 ? 40 : 89; view.request(); }
    if (a === "share") shareNow();
  });
  $("#btn-city").addEventListener("click", () => selectDistrict(L.CITY));
  $("#btn-nation").addEventListener("click", () => enterNation());

  const qInput = $("#q");
  const clearBtn = $("#btn-clear");
  const sugEl = $("#search-sug");

  qInput.addEventListener("input", () => {
    const val = qInput.value.trim();
    clearBtn.hidden = !val;
    renderSuggestions(val);
  });

  let suppressSugOnce = false;

  qInput.addEventListener("focus", () => {
    if (suppressSugOnce) { suppressSugOnce = false; return; }
    const val = qInput.value.trim();
    clearBtn.hidden = !val;
    renderSuggestions(val);
  });

  qInput.addEventListener("click", () => {
    if (!qInput.value.trim() && sugEl.hidden) {
      renderSuggestions("");
    }
  });

  qInput.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") {
      if (sugEl.hidden || !sugState.list.length) return;
      e.preventDefault();
      sugState.index = (sugState.index + 1) % sugState.list.length;
      updateActiveSug();
    } else if (e.key === "ArrowUp") {
      if (sugEl.hidden || !sugState.list.length) return;
      e.preventDefault();
      sugState.index = (sugState.index - 1 + sugState.list.length) % sugState.list.length;
      updateActiveSug();
    } else if (e.key === "Enter") {
      if (!sugEl.hidden && sugState.index >= 0 && sugState.list.length) {
        e.preventDefault();
        selectSuggestion(sugState.list[sugState.index]);
      }
    } else if (e.key === "Escape") {
      hideSuggestions();
    }
  });

  sugEl.addEventListener("click", e => {
    const chip = e.target.closest(".sug-chip");
    if (chip) {
      e.preventDefault();
      e.stopPropagation();
      const kw = chip.dataset.kw;
      qInput.value = kw;
      clearBtn.hidden = false;
      renderSuggestions(kw);
      qInput.focus();
      return;
    }
    const li = e.target.closest(".sug-item");
    if (!li) return;
    const idx = +li.dataset.idx;
    if (sugState.list[idx]) selectSuggestion(sugState.list[idx]);
  });

  clearBtn.addEventListener("click", () => {
    qInput.value = "";
    clearBtn.hidden = true;
    hideSuggestions();
    suppressSugOnce = true;
    qInput.focus();
  });

  document.addEventListener("click", e => {
    if (!e.target.closest("#search-wrap")) hideSuggestions();
  });

  $("#search").addEventListener("submit", e => {
    e.preventDefault();
    hideSuggestions();
    $("#q").blur();
    search($("#q").value);
  });
  $("#btn-menu").addEventListener("click", () => {
    renderMenu(); $("#menu").hidden = !$("#menu").hidden;
    $("#btn-menu").setAttribute("aria-expanded", String(!$("#menu").hidden));
    if (!$("#menu").hidden) $("#menu [data-close]")?.focus();
  });
  $("#menu").addEventListener("click", e => {
    if (e.target.closest("[data-close]")) { $("#menu").hidden = true; $("#btn-menu").setAttribute("aria-expanded", "false"); $("#btn-menu").focus(); return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "err-report") reportOnGitHub();
    if (act === "err-copy") { (navigator.clipboard ? navigator.clipboard.writeText(errorReport()) : Promise.reject()).then(() => toast("已複製錯誤內容"), () => toast("這個瀏覽器不能自動複製，請改用「到 GitHub 回報」。")); }
    if (act === "err-clear") { try { localStorage.removeItem(ERR_KEY); } catch { /* 無妨 */ } renderMenu(); }
    if (act === "use-budget") {
      S.settings.budget = e.target.closest("[data-budget]").dataset.budget; saveStore();
      const inp = $("#menu [data-set='budget']"); if (inp) inp.value = S.settings.budget;
      refreshBars(); refreshPins(); renderPanel();
      toast(`預算設為 ${L.fmtNum(+S.settings.budget)} 萬：買不起的區，柱子會縮成灰色小方塊（${D.barRange.matched} 區符合）。`);
    }
  });
  $("#menu").addEventListener("change", e => { if (e.target.dataset.set) onSetting(e.target); });
  // 收入、現金邊打邊算；選單裡的 <details> 開合也記住
  $("#menu").addEventListener("input", e => {
    const k = e.target.dataset.set;
    if (k === "incomeMonthly" || k === "cash") { S.settings[k] = e.target.value; saveStore(); const el = $("#budget-calc"); if (el) el.innerHTML = budgetCalc(); }
  });
  $("#menu").addEventListener("toggle", e => { const d = e.target; if (d.dataset && d.dataset.det) { S.settings[d.dataset.det] = d.open; saveStore(); } }, true);
  $("#tabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    S.tab = b.dataset.tab; renderPanel(); if (S.sheet !== "full") sheet("half");
  });
  // 鍵盤：左右鍵換分頁、Home／End 到頭尾（WAI-ARIA tabs 的慣例）
  $("#tabs").addEventListener("keydown", e => {
    const keys = { ArrowRight: 1, ArrowLeft: -1, Home: "first", End: "last" };
    if (!(e.key in keys)) return;
    const btns = [...$("#tabs").querySelectorAll("button[data-tab]")], i = btns.findIndex(b => b.dataset.tab === S.tab);
    const k = keys[e.key], j = k === "first" ? 0 : k === "last" ? btns.length - 1 : (i + k + btns.length) % btns.length;
    e.preventDefault();
    S.tab = btns[j].dataset.tab; renderPanel();
    $(`#tab-${S.tab}`)?.focus();
  });
  // Esc 關掉設定選單，焦點回到選單按鈕
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !$("#menu").hidden) { $("#menu").hidden = true; $("#btn-menu").setAttribute("aria-expanded", "false"); $("#btn-menu").focus(); }
  });
  const body = $("#tab-body");
  body.addEventListener("click", async e => {
    const t = e.target;
    if (S.tab === "watch" && watchClick(t)) return;
    const scCard = t.closest(".scenario-card");
    if (scCard) {
      const mode = scCard.dataset.scenario;
      if (mode === "nanke") {
        selectDistrict("善化區");
        toast("已前往南科生活圈：善化區");
      } else if (mode === "school") {
        selectDistrict("東區");
        toast("已前往明星學區重鎮：東區");
      } else if (mode === "youth") {
        // 直接把房貸試算切成新青安，捲到試算那一段（全台、各縣市都能用）
        const y = L.YOUTH_LOAN;
        S.settings.loan = { ...loanState(), rate: y.rate, years: y.years, grace: y.grace, youth: true }; saveStore();
        renderPanel(); sheet("half");
        $(".loan-presets")?.scrollIntoView({ block: "start" });
        toast("房貸試算已切換成新青安，下方有和一般房貸的比較；估價分頁另有寬限期斷崖體檢。");
      } else if (mode === "duel") {
        S.tab = "cmp"; S.cmpPick = null;       // 選單回到目前所在的縣市
        const pair = cmpDefaultPair();
        if (cmpList().length < 2 && pair) { S.settings.cmp = pair; saveStore(); }
        renderPanel(); sheet("half");
        toast(cmpList().length >= 2 ? "雙區 PK：可以用上方選單換成其他區（可跨縣市）" : "用上方選單挑兩個區（可跨縣市），就會開始 PK");
      }
      return;
    }
    const pChip = t.closest(".ping-chip");
    if (pChip) {
      const p = pChip.dataset.ping;
      S.settings.val = Object.assign(valState(), { ping: p });
      saveStore();
      renderPanel();
      return;
    }
    const go = t.closest("[data-goto]"); if (go) { e.preventDefault(); selectDistrict(go.dataset.goto); return; }
    const tr = t.closest("tr.click");
    if (tr && tr.dataset.dist) { selectDistrict(tr.dataset.dist); return; }
    if (tr && tr.dataset.road) {
      const dist = tr.dataset.rdist, pend = S.pendingAddr;
      if (pend && tr.dataset.road === pend.road) { S.roadKw = ""; await showAddress({ ...pend, district: dist }); return; }
      if (dist !== S.current) { S.roadKw = ""; selectDistrict(dist); await refreshRoads(); }
      selectRoad(tr.dataset.road); return;
    }
    if (tr && tr.dataset.tx != null) {
      body.querySelectorAll("tr.sel").forEach(r => r.classList.remove("sel")); tr.classList.add("sel");
      const x = S.txShown[+tr.dataset.tx];
      if (!x.road || x.road === "其他") { toast("看不出這筆是哪一條路，無法標在地圖上。"); return; }
      const q = { district: x.dist, road: x.road, lane: x.lane, alley: x.alley, num: x.num };
      await pinAt(q, `${x.dist}${x.addr}`, `${L.describe(q).replace(/ /g, "")} ${L.fmtNum(x.tw)}萬`, false);
      return;
    }
    if (tr && tr.dataset.proj) { pick(["project", +tr.dataset.proj]); return; }
    if (tr && tr.dataset.poi) { const o = view.pois.find(x => x.id === tr.dataset.poi); if (o) { view.select("poi", o.id); view.flyTo(o.lat, o.lng, Math.max(view.zoom, 110)); toast(`${o.name}｜距離 ${o.d} 公尺`); } return; }
    if (tr && tr.dataset.bldg) {
      S.bldg = tr.dataset.bldg; renderPanel();
      const b = L.buildings(D.txs, S.current, S.cat, D.book.windows.y12[0]).find(r => r.key === S.bldg);
      if (b && b.road && b.road !== "其他") {
        const q = { district: S.current, road: b.road, lane: b.lane, alley: b.alley, num: b.num };
        await pinAt(q, `${S.current} ${b.name}`, b.name, false);
        if (S.tab === "bldg") renderPanel();
      }
      return;
    }
    if (tr && tr.dataset.watch) { S.watchSel = tr.dataset.watch; renderPanel(); const it = S.watch.find(w => w.id === S.watchSel); if (it && it.lat != null) view.flyTo(it.lat, it.lng, Math.max(view.zoom, 60)); return; }
    const cdel = t.closest("[data-cmpdel]");
    if (cdel) { e.preventDefault(); const l = cmpList(); l.splice(+cdel.dataset.cmpdel, 1); S.settings.cmp = l; saveStore(); renderPanel(); return; }
    const act = t.closest("[data-act]")?.dataset.act;
    const it = S.watch.find(w => w.id === S.watchSel);
    if (act === "report") { if (S.current === L.CITY) toast("先選一個行政區或搜尋地址，再產生報告。"); else reportDialog(); return; }
    if (act === "poi") { const el = t.closest("[data-act]"); showPoi(+el.dataset.lat, +el.dataset.lng, el.dataset.label); return; }
    if (act === "mode") { S.settings.mode = t.closest("[data-mode]").dataset.mode; saveStore(); ensureRouteTimes(); refreshBars(); refreshPins(); renderPanel(); return; }
    if (act === "work-pick") {
      sheet("peek"); toast("在地圖上點一下上班地點 A", 6000);
      S.pickMode = ll => { S.settings.workPt = { name: "自訂地點", lat: +ll[0].toFixed(5), lng: +ll[1].toFixed(5) }; S.settings.work = "__custom";
        saveStore(); refreshBars(); refreshPins(); S.tab = "commute"; renderPanel(); sheet("half"); toast("已設定上班地點"); };
      return;
    }
    if (act === "bldg-back") { S.bldg = null; S.pin = null; refreshPins(); renderPanel(); return; }
    if (act === "clear-road") { S.roadFilter = null; S.addr = null; S.pin = null; refreshPins(); view.select(S.current === L.CITY ? null : "district", S.current); renderPanel(); }
    if (act === "watch-add") watchDialog(null);
    if (act === "cmp-add") { cmpAdd(); return; }
    if (act === "tm-play") { tmPlay(); return; }
    if (act === "tm-stop") { tmStop(); tmUi(); return; }
    if (act === "span") { S.settings.span = +t.closest("[data-span]").dataset.span; saveStore(); const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; return; }
    if (act === "txf") { const el = t.closest("[data-k]"); S.txf = { ...(S.txf || {}), [el.dataset.k]: el.dataset.v }; renderPanel(); return; }
    if (act === "loan-preset") {
      const youth = t.closest("[data-preset]").dataset.preset === "youth", y = L.YOUTH_LOAN, st = loanState();
      S.settings.loan = youth ? { ...st, rate: y.rate, years: y.years, grace: y.grace, youth: true }
        : { ...st, rate: LOAN_DEFAULT.rate, years: LOAN_DEFAULT.years, grace: LOAN_DEFAULT.grace, youth: false };
      saveStore(); const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; return;
    }
    if (act === "watch-seen" && it) {
      if (!D.txs) { toast("先進入這個物件所在的縣市，再按「我看過了」。"); return; }
      it.seen = D.txs.reduce((m, x) => x.date > m ? x.date : m, it.seen || ""); S.watchNews[it.id] = []; saveStore(); renderPanel(); return;
    }
    if (act === "cmp-clear") { S.settings.cmp = []; saveStore(); renderPanel(); return; }
    if (act === "cmp-pick") { const sel = $("#cmp-dist"); if (sel) cmpPickAdd(sel.dataset.code, sel.value); return; }
    if (act === "watch-edit" && it) watchDialog(it);
    if (act === "watch-value" && it) {
      const cat = TYPE_CAT[it.type] === "house" ? "house" : it.type === "預售屋" ? "presale" : "apt";
      S.settings.val = { dist: it.district, cat, ping: it.ping ?? "", age: it.age ?? "", addr: it.address || "", price: it.price ?? "" }; saveStore();
      if (it.district !== S.current && D.dmap[it.district]) selectDistrict(it.district);
      S.tab = "value"; renderPanel(); return;
    }
    if (act === "watch-del" && it && confirm(`要把「${it.name}」從看屋清單刪除嗎？`)) { S.watch = S.watch.filter(w => w !== it); S.watchSel = null; saveStore(); refreshPins(); renderPanel(); }
    if (act === "watch-map" && it) view.flyTo(it.lat, it.lng, Math.max(view.zoom, 60));
    if (act === "watch-pin" && it) {
      sheet("peek"); toast("請在地圖上點一下這間房子的位置", 6000);
      const d = D.dmap[it.district]; if (d) view.flyTo(d.lat, d.lng, Math.max(view.zoom, 60));
      S.pickMode = ll => { it.lat = +ll[0].toFixed(6); it.lng = +ll[1].toFixed(6); saveStore(); refreshPins(); sheet("half"); renderPanel(); toast("已標出位置"); };
    }
    if (act === "watch-export") {
      const blob = new Blob([JSON.stringify({ app: "deep_tainan_house", watch: S.watch }, null, 1)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "看屋清單備份.json"; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    }
  });
  body.addEventListener("change", e => {
    if (e.target.dataset && e.target.dataset.set) { onSetting(e.target); renderPanel(); return; }
    if (S.tab === "watch" && watchChange(e.target)) return;
    if (e.target.hasAttribute && e.target.hasAttribute("data-txf-ev")) { S.txf = { ...(S.txf || {}), ev: e.target.checked }; renderPanel(); return; }
    if (e.target.id === "cmp-county") { S.cmpPick = e.target.value; const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; return; }
    if (e.target.dataset && e.target.dataset.val) {
      S.settings.val = Object.assign(valState(), { [e.target.dataset.val]: e.target.value.trim() }); saveStore();
      const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; return;
    }
    if (e.target.id === "watch-import") {
      const f = e.target.files[0]; if (!f) return;
      f.text().then(txt => {
        const d = JSON.parse(txt), list = Array.isArray(d) ? d : d.watch || d.items;
        if (!Array.isArray(list)) throw new Error("格式不對");
        const have = new Set(S.watch.map(w => w.id)); let n = 0;
        for (const w of list) if (w && w.name && !have.has(w.id)) { S.watch.push({ lat: null, lng: null, ...w, id: w.id || "w" + Date.now() + n }); n++; }
        saveStore(); refreshPins(); renderPanel(); toast(`匯入 ${n} 筆`);
      }).catch(err => toast("匯入失敗：" + err.message));
    }
  });
  body.addEventListener("input", e => {
    const ds = e.target.dataset;
    if (ds.loan || ds.cost || ds.rvb || ds.sell) {
      if (ds.sell) S.settings.sell = Object.assign(sellState(), { [ds.sell]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
      if (ds.loan) S.settings.loan = Object.assign(loanState(), { [ds.loan]: e.target.value });
      if (ds.cost) S.settings.cost = Object.assign(costState(), { [ds.cost]: e.target.value });
      if (ds.rvb) S.settings.rvb = Object.assign(rvbState(), { [ds.rvb]: e.target.value });
      saveStore();
      const med = D.book.best(S.current, S.cat, "t").value, set = (id, f) => { const el = $(id); if (el) el.innerHTML = f(); };
      set("#loan-out", () => loanResult(med)); set("#cost-out", () => costResult(med)); set("#rvb-out", () => rvbResult(S.current, med)); set("#sell-out", () => sellResult(med));
      if (ds.sell === "bought") { const o = $("#sell-old"); if (o) o.hidden = !(+e.target.value && +e.target.value < 2016); }
      const pr = loanPrice(med), dr = rvbDefaultRent(S.current, med), ph = (sel, v) => { const el = $(sel); if (el) el.placeholder = v; };
      ph("[data-cost='hv']", pr ? "約 " + Math.round(pr * L.COST_RATIO.house) : ""); ph("[data-cost='lv']", pr ? "約 " + Math.round(pr * L.COST_RATIO.land) : "");
      ph("[data-rvb='rent']", dr ? String(dr) : "");
    }
    if (e.target.id === "commute-min") {
      S.settings.commuteMin = +e.target.value; $("#commute-v").textContent = e.target.value + " 分鐘"; saveStore(); refreshBars(); refreshPins();
      clearTimeout(S._cmT); S._cmT = setTimeout(() => { const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; }, 150);
    }
    if (e.target.id === "bldg-kw") { S.bldgKw = e.target.value; clearTimeout(S._bkT); S._bkT = setTimeout(() => { const pos = e.target.selectionStart; renderPanel(); const i = $("#bldg-kw"); i.focus(); i.setSelectionRange(pos, pos); }, 350); }
    if (e.target.id === "road-kw") { S.roadKw = e.target.value; clearTimeout(S._kwT); S._kwT = setTimeout(() => { const pos = e.target.selectionStart; renderPanel(); const i = $("#road-kw"); i.focus(); i.setSelectionRange(pos, pos); }, 350); }
    if (e.target.id === "tm-range") {
      const t = tmTable(); if (!t) return;
      if (!S.tm) S.tm = { i: 0 };
      if (S.tm.timer) { clearInterval(S.tm.timer); S.tm.timer = null; }
      S.tm.i = +e.target.value; tmBars(t); tmUi(); return;
    }
    if (e.target.id === "year") { S.year = +e.target.value; $("#year-v").textContent = S.year + " 年"; clearTimeout(S._yT); S._yT = setTimeout(() => { refreshModels(); const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc; }, 120); refreshModels(); }
  });
  body.addEventListener("toggle", e => { const d = e.target; if (d.dataset && d.dataset.det) { S.settings[d.dataset.det] = d.open; saveStore(); } }, true);
  window.addEventListener("resize", () => { sheet(S.sheet || "peek"); placeAttrib(); });
}

// ------------------------------------------------------------------ 啟動
// ------------------------------------------------------------------ 全台版：全台首頁 ↔ 縣市
const TW_ORIGIN = [23.7, 120.95];
function extentOf(points, padKm = 4, minKm = 16) {
  const xy = points.map(p => L.toXY(p.lat, p.lng)), xs = xy.map(p => p[0]), ys = xy.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 - 2, w: Math.max(minKm, x1 - x0 + 2 * padKm), h: Math.max(minKm * 0.75, y1 - y0 + 2 * padKm) };
}
// 縣市總覽的取景：以成交集中的區為主（佔近一年成交 85% 的那幾區），山區、離島可以拖過去看。
// 例如高雄市含桃源、那瑪夏，整個縣市框進手機畫面時市區會被擠到邊緣、地標也疊在一起看不到。
function coreExtent(districts, book) {
  const n = d => { const c = book.cell(d.name, "all"); return c && c.y12 ? c.y12[0] : 0; };
  const ranked = districts.map(d => [d, n(d)]).sort((a, b) => b[1] - a[1]), total = ranked.reduce((s, x) => s + x[1], 0);
  if (!total || districts.length <= 6) return extentOf(districts);
  const core = []; let acc = 0;
  for (const [d, k] of ranked) { core.push(d); acc += k; if (acc >= total * 0.85 && core.length >= 3) break; }
  return extentOf(core, 5);
}
function resetSelection() {
  if (S.tm) { if (S.tm.timer) clearInterval(S.tm.timer); S.tm = null; }      // 換縣市：時光機回到現在
  S.roadFilter = null; S.addr = null; S.pin = null; S.bldg = null; S.picked = null; S.pendingAddr = null; S.roadKw = ""; S.bldgKw = "";
  if (S.poi) { S.poi = null; refreshPois(); }
  if (["roads", "bldg", "tx", "detail", "poi"].includes(S.tab)) S.tab = "overview";
}
function enterNation(fly = true) {
  D.county = null;
  L.setCity(D.tw.nation || "全台", "全台");
  enterSeq++;
  D.book = D.twBook; D.rent = D.twRent; D.pop = D.twPop; D.txs = null; D.txPromise = Promise.resolve(); loadLong("");
  D.roadCatalog = []; D.cancel = null; S.watchNews = {};
  D.districts = D.tw.counties.map(c => ({ name: c.short, lat: c.lat, lng: c.lng, zone: c.region, code: c.code }));
  D.dmap = Object.fromEntries(D.districts.map(d => [d.name, d]));
  D.meta = { ...D.tw, road_districts: [] };
  S.current = L.CITY; resetSelection();
  // 本島為主（離島可以拖過去看）
  view.setExtent(extentOf(D.districts.filter(d => !["W", "Z"].includes(d.code)), 12, 60));
  S.settings.lastCounty = ""; saveStore();
  view.select(null);
  if (fly) view.flyHome();
  refreshAll();
}
let enterSeq = 0;           // 每次換縣市（含回全台）加一；載入完成時不是最新的那次就丟掉
// 各縣市的統計與行政區（比較功能會同時用到好幾個縣市，讀過的留著）
const COUNTY_CACHE = new Map();
export function countyData(code) {
  if (!COUNTY_CACHE.has(code)) {
    const base = `data/tw/${code}/`;
    COUNTY_CACHE.set(code, Promise.all([getJSON(base + "book.json"), getJSON(base + "districts.json"), getJSON(base + "rent.json").catch(() => null),
      getJSON(base + "pop.json").catch(() => null)])
      .then(([raw, dd, rent, pop]) => ({ raw, dd, rent, pop, book: new L.Book(raw), dmap: Object.fromEntries(dd.districts.map(d => [d.name, d])) }))
      .catch(e => { COUNTY_CACHE.delete(code); throw e; }));
  }
  return COUNTY_CACHE.get(code);
}
// 長期走勢（近 5 年）：另外載入，沒有這個檔（還沒補齊）就只顯示近一年
const LONG_CACHE = new Map();
function loadLong(code) {
  D.long = LONG_CACHE.get(code) || null;
  if (LONG_CACHE.has(code)) return;
  getJSON(code ? `data/tw/${code}/long.json` : "data/tw/long.json").then(lb => {
    LONG_CACHE.set(code, lb);
    if ((D.county ? D.county.code : "") === code) { D.long = lb; if (["overview", "rank"].includes(S.tab)) renderPanel(); }
  }).catch(() => LONG_CACHE.set(code, null));
}
export async function enterCounty(code, fly = true) {
  const c = D.tw.counties.find(x => x.code === code);
  S.cmpPick = null;                       // 比較分頁的縣市選單跟著換到這個縣市
  if (!c) return false;
  if (!c.has_data) { toast(`${c.short}的資料還在準備中（每次自動更新會補上）。`); return false; }
  const base = `data/tw/${code}/`, seq = ++enterSeq;
  let book, dd, rent, pop;
  try { ({ raw: book, dd, rent, pop } = await countyData(code)); }
  catch (e) { logError(`載入${c.short}資料`, e); toast(`${c.short}的資料載入失敗，請檢查網路後再試。`); return false; }
  if (seq !== enterSeq) return false;           // 等資料時使用者又換到別的縣市了
  D.county = c; D.rent = rent; D.pop = pop; loadLong(code);
  D.roadCatalog = []; D.cancel = null; S.watchNews = {};
  L.setCity(c.short, c.short);
  D.book = new L.Book(book);
  D.districts = dd.districts; D.dmap = Object.fromEntries(D.districts.map(d => [d.name, d]));
  D.meta = { ...D.tw, describe: D.tw.describe, tx_count: c.tx_count || 0, road_districts: c.roads || [] };
  D.txs = null;
  D.txPromise = getJSON(base + "tx.json").then(raw => { if (D.county === c) { D.txs = L.decodeTx(raw); D.cancel = L.decodeCancel(raw); D.roadCatalog = L.buildRoadCatalog(D.txs); refreshRoads(); checkWatchNews(); renderPanel(); } })
    .catch(e => { logError("載入成交資料", e); toast("成交資料載入失敗，請檢查網路後重新整理。"); });
  S.current = L.CITY; resetSelection();
  view.setExtent(coreExtent(D.districts, D.book));
  S.settings.lastCounty = code; saveStore();
  view.select(null);
  if (fly) view.flyHome(); else { view.stop(); view.autoZoom = true; view.fitZoom(); view.tx = view.extent.cx; view.ty = view.extent.cy; }
  refreshAll();
  return true;
}

// ------------------------------------------------------------------ 啟動
export async function main() {
  loadStore();
  applyTheme();
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);
  setTimeout(flushAutoReport, 5000);   // 上次離線時沒送出的錯誤回報
  const params = new URLSearchParams(location.search);
  const tw = params.get("tw") === "0" ? null : await getJSON("data/tw/index.json").catch(() => null);    // ?tw=0：強制台南版（測試用）
  const shared = ["intel", "mrt", "landmarks", "models", "workplaces", "schools"];
  const [intel, mrt, landmarks, models, workplaces, schools] = await Promise.all(shared.map(n => getJSON(`data/${n}.json`).catch(() => n === "schools" ? [] : null)));
  Object.assign(D, { intel: intel.items, mrt, landmarks, workplaces, schools: schools || [], roadCatalog: [] });
  if (tw) {
    L.setOrigin(...TW_ORIGIN);
    D.tw = tw;
    const [twBook, twRent, twPop] = await Promise.all([getJSON("data/tw/book.json"), getJSON("data/tw/rent.json").catch(() => null),
      getJSON("data/tw/pop.json").catch(() => null)]);
    D.twBook = new L.Book(twBook); D.twRent = twRent; D.twPop = twPop;
  } else {
    const [meta, book, districts] = await Promise.all(["meta", "book", "districts"].map(n => getJSON(`data/${n}.json`)));
    Object.assign(D, { meta, book: new L.Book(book), districts });
    D.dmap = Object.fromEntries(districts.map(d => [d.name, d]));
  }
  view = new View3D($("#map"), { models });
  view.lines = mrt.lines;
  if (tw) {     // 全台營運中的捷運、輕軌、高鐵（GitHub Actions 由 OpenStreetMap 整理）；沒有這個檔就只畫台南的規劃線
    getJSON("data/tw/transit.json").then(t => {
      D.transit = (t.lines || []).slice().sort((a, b) => (b.kind === "台鐵") - (a.kind === "台鐵"));      // 台鐵先畫（在捷運底下）
      view.lines = D.transit.filter(l => l.kind === "台鐵").concat(mrt.lines, D.transit.filter(l => l.kind !== "台鐵")); view.request();
    })
      .catch(() => { D.transit = []; });
  }
  view.layerOn = { town: S.settings.town, liq: S.settings.liq, slide: S.settings.slide, fault: S.settings.fault };
  Object.assign(view.show, { hires: S.settings.hires, lines: S.settings.lines, labels: S.settings.labels });
  if (tw) {
    view.tileLayers = tw.layers;
    view.setExtent({ cx: 0, cy: 0, w: 260, h: 380 }, { x0: -320, x1: 160, y0: -230, y1: 320 }, 0.6);
  } else for (const [id, m] of Object.entries(D.meta.layers || {})) view.setLayer(id, m, "");
  view.onPick = pick;
  const tooltip = $("#map-tooltip");
  view.onHover = (hit, e) => {
    if (!hit || window.innerWidth < 900) {
      if (tooltip) tooltip.hidden = true;
      return;
    }
    const [kind, id] = hit;
    let html = "";
    if (kind === "district") {
      const bu = D.book && D.book.best(id, S.cat, "u");
      const bt = D.book && D.book.best(id, S.cat, "t");
      html = `<b>📍 ${esc(id)}</b><br><small>中位單價：${bu && bu.value != null ? bu.value.toFixed(1) + " 萬/坪" : "—"}<br>中位總價：${bt && bt.value != null ? L.fmtNum(bt.value) + " 萬" : "—"}</small>`;
    } else if (kind === "landmark") {
      const lm = (D.landmarks || []).find(l => l.id === id);
      if (lm) html = `<b>🏛️ ${esc(lm.name)}</b><br><small>${esc(lm.district || "")} · ${esc(lm.note ? lm.note.slice(0, 30) : "知名地標")}</small>`;
    } else if (kind === "school") {
      const sc = (D.schools || []).find(s => s.id === id);
      if (sc) html = `<b>🎓 ${esc(sc.name)}</b><br><small>${esc(sc.district || "")} · ${esc(sc.status)}（${esc(sc.type)}）</small>`;
    } else if (kind === "project") {
      const pr = (D.intel || []).find(p => p.id === id);
      if (pr) html = `<b>🏗️ ${esc(pr.name)}</b><br><small>${esc(pr.status || "")} · ${esc(pr.agency || "")}</small>`;
    } else if (kind === "road") {
      html = `<b>🛣️ ${esc(id)}</b><br><small>點擊查看路段成交</small>`;
    }
    if (html && tooltip) {
      tooltip.innerHTML = html;
      const x = Math.min(e.clientX + 14, window.innerWidth - 260);
      const y = Math.min(e.clientY + 14, window.innerHeight - 100);
      tooltip.style.left = `${Math.max(10, x)}px`;
      tooltip.style.top = `${Math.max(10, y)}px`;
      tooltip.hidden = false;
    } else if (tooltip) {
      tooltip.hidden = true;
    }
  };
  const lg = $("#legend");
  if (window.innerWidth < 900 || S.settings.legendCollapsed) lg.classList.add("collapsed");
  lg.addEventListener("click", () => { lg.classList.toggle("collapsed"); S.settings.legendCollapsed = lg.classList.contains("collapsed"); saveStore(); renderLegend(); updateReserved(); });
  bindUI(); bindSheetDrag();
  sheet("peek");
  if (tw) {
    const shared = ["d", "tab", "cat", "m", "cmp", "q"].some(k => params.has(k));
    const want = (params.get("c") || (shared ? "" : S.settings.lastCounty) || "").toUpperCase();
    enterNation(false); view.reset();
    if (want && !params.get("q")) await enterCounty(want, false);
  } else {
    refreshAll();
    // 逐筆成交比較大（壓縮後約 0.6MB），畫面先出來再載入
    D.txPromise = getJSON("data/tx.json").then(raw => { D.txs = L.decodeTx(raw); D.cancel = L.decodeCancel(raw); D.roadCatalog = L.buildRoadCatalog(D.txs); refreshRoads(); checkWatchNews(); renderPanel(); })
      .catch(e => { logError("載入成交資料", e); toast("成交資料載入失敗，請檢查網路後重新整理。"); });
  }
  applyShared(params);
  S.ready = true; syncUrl();
  if (params.get("q")) { $("#q").value = params.get("q"); const wait = () => (D.tw || D.txs) ? search(params.get("q")) : setTimeout(wait, 200); wait(); }
  getJSON("data/status.json").then(st => { D.status = st; if (!st.ok) $("#btn-menu").classList.add("has-err"); }).catch(() => {});
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    // 程式檔先用快取開（離線也能用、開得快），新版本在背景下載；下載好就提示使用者重新整理，而不是默默等到下次開
    let hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController) toast("網站有新版本。", 0, { label: "重新整理", run: () => location.reload() });
      hadController = true;
    });
    navigator.serviceWorker.register("sw.js").then(reg => {
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reg.update().catch(() => {}); });
    }).catch(() => {});
  }
  window.__app = { S, D, view, search, selectDistrict, pick, L, enterCounty, enterNation, logError, shareUrl, renderSuggestions, selectSuggestion, hideSuggestions, minsTo };   // 測試用
}
main().catch(err => { logError("啟動", err); document.body.insertAdjacentHTML("beforeend", `<div class="note" style="position:fixed;top:60px;left:10px;right:10px;z-index:99">載入失敗：${esc(err.message)}</div>`); });
