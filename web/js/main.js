// 購屋深度分析（網頁版）：所有資料都是靜態檔案，計算全部在使用者的裝置上完成。
// 有 data/tw/index.json 時是「全台版」：首頁是 22 縣市，點縣市才下載該縣市的資料；沒有就是原本的台南版。
import * as L from "./logic.js";
import { View3D, mix } from "./view3d.js";
import { buildReport } from "./report.js";

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SEQ = ["#fbe3cf", "#f6b98a", "#eb8a4c", "#d2601f", "#9a3f0c"];
const ROAD_RAMP = ["#fff3b0", "#ffc857", "#f98e3a", "#e2543d", "#a5236f"];
const NO_DATA = "#b9bfc6", DIV_NEG = "#1c5cab", DIV_MID = "#d8d7d2", DIV_POS = "#c0302f", TREND_SPAN = 8;
const WORK_COLOR = "#0b5d57", WATCH_COLOR = "#7a3fb5", SEARCH_COLOR = "#d81b60";
const MARKER_COLOR = { "商辦": "#2a78d6", "商場": "#eb6834", "科學園區": "#1baf7a", "產業園區": "#eda100", "重劃區": "#e87ba4",
                       "公共建設": "#008300", "交通建設": "#4a3aa7", "住宅開發": "#e34948" };
const ZOOM = { district: 40, point: 60, road: 70, pin: { lane: 400, alley_mouth: 400, interp: 250, lane_mouth: 250, near_lane: 200 }, address: 120 };
const STORE = "dth_v1";

function ramp(stops, t) {
  t = Math.max(0, Math.min(1, t));
  const pos = t * (stops.length - 1), i = Math.min(Math.floor(pos), stops.length - 2);
  return mix(stops[i], stops[i + 1], pos - i);
}
const trendColor = p => p == null ? NO_DATA : (t => t < 0 ? mix(DIV_MID, DIV_NEG, -t) : mix(DIV_MID, DIV_POS, t))(Math.max(-1, Math.min(1, p / TREND_SPAN)));

// ------------------------------------------------------------------ 狀態（設定與看屋清單存在這台裝置的瀏覽器裡）
const S = {
  cat: "all", metric: "u", current: L.CITY, tab: "overview", year: new Date().getFullYear(),
  addr: null, pin: null, roadFilter: null, picked: null, pickMode: null, roadKw: "", bldgKw: "", bldg: null, poi: null,
  settings: { town: true, liq: false, slide: false, fault: false, hires: true, lines: true, markers: true, landmarks: true, projects: true,
              roads: true, labels: true, color: "price", work: "", workKm: 5, budget: "", mode: "car", commuteMin: 20, workPt: null, autoReport: true },
  watch: [],
};
function loadStore() {
  try {
    const d = JSON.parse(localStorage.getItem(STORE) || "{}");
    Object.assign(S.settings, d.settings || {});
    S.watch = Array.isArray(d.watch) ? d.watch : [];
  } catch (e) { /* 私密瀏覽等情況讀不到就用預設 */ }
}
function saveStore() {
  try { localStorage.setItem(STORE, JSON.stringify({ settings: S.settings, watch: S.watch })); } catch (e) { toast("這個瀏覽器不允許儲存資料（可能是私密瀏覽），設定與看屋清單關掉後不會保留。"); }
}

// ------------------------------------------------------------------ 資料
const D = { roads: new Map() };
// 淹水潛勢：國家災害防救科技中心「3D 災害潛勢地圖」（官方圖資沒有開放給其他網站直接疊圖，所以用連結開啟）
const FLOOD_URL = "https://dmap.ncdr.nat.gov.tw/1109/map/?group-layer=" + encodeURIComponent("淹水潛勢");
const allLines = () => (D.mrt ? D.mrt.lines : []).concat(D.transit || []);
async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
const roadKey = dist => (D.county ? D.county.code + "/" : "") + dist;
async function loadRoads(dist) {
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
const roadsNow = dist => { const v = D.roads.get(roadKey(dist)); return v && !(v instanceof Promise) ? v : null; };
const isNation = () => !!D.tw && !D.county;

let view, toastTimer;
function toast(msg, ms = 4200) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// ------------------------------------------------------------------ 錯誤紀錄（存在這台裝置；「☰ → 問題回報」可以一鍵到 GitHub 回報）
// 記在手機上，並匿名送到維護者的 Google 表單（可在設定關閉）；也可以按一下帶著內容開 GitHub Issue（需要登入 GitHub）
const ERR_KEY = "dth_errors", APP_VER = "2026-10-06a";
function loadErrors() { try { return JSON.parse(localStorage.getItem(ERR_KEY) || "[]"); } catch { return []; } }
function logError(where, err, quiet = false) {
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
      `版本：${e.ver}｜網址：${location.pathname}${location.search}`, `瀏覽器：${navigator.userAgent}`].filter(Boolean).join("\n");
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
function errorReport() {
  const errs = loadErrors().slice(-10), st = D.status;
  return [`**網址**：${location.href}`, `**版本**：${APP_VER}　**瀏覽器**：${navigator.userAgent}`,
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
function workPlace() {
  if (S.settings.work === "__custom") return S.settings.workPt || null;
  return D.workplaces.find(w => w.name === S.settings.work) || null;
}
const modeName = () => (L.MODES[S.settings.mode] || L.MODES.car)[0];
const minsTo = (lat, lng, w = workPlace()) => w ? L.commuteMin(L.distKm(lat, lng, w.lat, w.lng), S.settings.mode) : null;
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

function refreshBars() {
  const vals = D.districts.map(d => [d, D.book.best(d.name, S.cat, S.metric), D.book.trend(d.name, S.cat, S.metric)]);
  let solid = vals.filter(([, b]) => b.value != null && !b.low).map(([, b]) => b.value);
  if (!solid.length) solid = vals.filter(([, b]) => b.value != null).map(([, b]) => b.value);
  if (!solid.length) solid = [1];
  const lo = Math.min(...solid), hi = Math.max(...solid), span = (hi - lo) || 1, active = filtersOn();
  view.bars = vals.map(([d, b, tr]) => {
    const v = b.value, ok = !active || (budgetOK(d.name) && workOK(d.name));
    const color = v == null ? NO_DATA : S.settings.color === "trend" ? trendColor(tr) : b.low ? NO_DATA : ramp(SEQ, (v - lo) / span);
    const num = v == null ? "—" : S.metric === "u" ? v.toFixed(1) : L.fmtNum(v);
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
  if (S.settings.color === "trend") rows = [[-TREND_SPAN, "跌 8% 以上"], [0, "持平"], [TREND_SPAN, "漲 8% 以上"]].map(([p, t]) => [trendColor(p), t]);
  else rows = [0, 0.5, 1].map(k => [ramp(SEQ, k), (S.metric === "u" ? (lo + span * k).toFixed(0) : L.fmtNum(lo + span * k)) + " " + unit]);
  rows.push([NO_DATA, "樣本少／無資料"]);
  let html = `<div class="lg-head">圖例 ${el.classList.contains("collapsed") ? "▸" : "▾"}</div>` +
    `<div><b>${S.metric === "u" ? "中位單價" : "中位總價"}</b>${S.settings.color === "trend" ? "｜顏色：近半年漲跌" : ""}</div>` +
    rows.map(([c, t]) => `<div><span class="sw" style="background:${c}"></span>${esc(t)}</div>`).join("");
  if (D.barRange.matched != null) html += `<div style="margin-top:3px"><b>符合條件 ${D.barRange.matched} 區</b></div>`;
  if (view.roads.length && S.current !== L.CITY && D.roadRange) {
    html += `<div style="margin-top:4px"><b>路段（${S.metric === "u" ? "萬/坪" : "萬"}）</b></div>` +
      [0, 0.5, 1].map(k => `<div><span class="sw" style="background:${ramp(ROAD_RAMP, k)}"></span>${S.metric === "u" ? (D.roadRange.lo + D.roadRange.span * k).toFixed(1) : L.fmtNum(D.roadRange.lo + D.roadRange.span * k)}</div>`).join("");
  }
  if (S.settings.projects) html += `<div style="margin-top:4px"><b>建設（${S.year}）</b></div><div>原色 完工｜塔吊 施工中｜淡色 規劃中</div>`;
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
function refreshModels() {
  const lms = S.settings.landmarks ? D.landmarks.filter(l => inScope(l, l.rank === 1)).map(l => ({ ...l, label: l.name })) : [];
  view.models = lms.concat(projectItems());
  view.markers = !S.settings.markers ? [] : D.intel.filter(it => it.lat != null && (it.impact_level || 0) >= 3 && !(it.build && S.settings.projects) && inScope(it, false))
    .map(it => ({ id: it.id, lat: it.lat, lng: it.lng, color: MARKER_COLOR[it.type] || "#6b7178", level: it.impact_level || 2,
                  label: it.name.split("（")[0].split("—")[0].slice(0, 16) }));
  renderLegend();
  view.request();
}
function refreshPins() {
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
async function refreshRoads() {
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
function selectDistrict(name, fly = true) {
  if (isNation() && name !== L.CITY) { const c = D.tw.counties.find(x => x.short === name); if (c) enterCounty(c.code); return; }
  S.current = name; S.roadFilter = null; S.addr = null; S.pin = null; S.bldg = null;
  if (S.poi) { S.poi = null; refreshPois(); }
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

// ------------------------------------------------------------------ 地址搜尋
async function search(text) {
  text = (text || "").trim();
  if (!text) return;
  if (D.tw) {
    // 全台版：先判斷縣市；地址開頭有縣市就切過去，沒有就在目前的縣市找，首頁時再用鄉鎮名稱猜縣市
    let [c, rest] = L.splitCounty(text);
    if (!c && isNation()) {
      const lm = D.landmarks.find(l => text.length >= 2 && (l.name.includes(text) || text.includes(l.name)));
      if (lm) { pick(["landmark", lm.id]); return "landmark"; }
      const pr = D.intel.find(it => it.build && text.length >= 2 && it.name.includes(text));
      if (pr) { pick(["project", pr.id]); return "project"; }
      const hits = D.tw.counties.filter(x => (x.town_names || []).some(t => text.startsWith(t) || L.normTw(text).startsWith(L.normTw(t))));
      if (hits.length === 1) c = hits[0];
      else {
        toast(hits.length ? `有好幾個縣市都有這個地名（${hits.map(x => x.short).join("、")}），請在前面加上縣市，例如「${hits[0].short}${text}」。`
          : "請在地址前面加上縣市，例如「台北市大安區信義路三段」。");
        return "none";
      }
      rest = text;
    }
    if (c) {
      const entry = D.tw.counties.find(x => x.code === c.code);
      if (!D.county || D.county.code !== c.code) { if (!(await enterCounty(c.code, false))) return "none"; }
      if (!rest) { selectDistrict(L.CITY); return "county"; }
      text = rest;
      if (entry) await D.txPromise;
    }
  }
  const names = D.districts.map(d => d.name), q = L.parseAddress(text, names), s = q.text;
  const only = names.includes(s) ? s : names.includes(s + "區") ? s + "區" : null;
  if (only || (q.district && !q.road)) {
    selectDistrict(only || q.district); toast(`已移到${only || q.district}`); sheet("peek"); return "district";
  }
  if (q.num == null && q.lane == null && !q.district) {
    const lm = D.landmarks.find(l => s.length >= 2 && (l.name.includes(s) || s.includes(l.name)));
    if (lm) { pick(["landmark", lm.id]); return "landmark"; }
    const pr = D.intel.find(it => it.build && s.length >= 2 && it.name.includes(s));
    if (pr) { pick(["project", pr.id]); return "project"; }
  }
  if (!q.road) { toast("看不出這是哪一條路。請輸入像「善化區中山路123號」「大同路一段」這樣的地址或路名。"); return "none"; }
  if (!D.txs) { toast("成交資料還在載入，請稍候再試一次。"); return "none"; }
  if (!q.district) {
    const found = [...new Set(D.txs.filter(x => x.road === q.road).map(x => x.dist))];
    let cand = found;
    if (found.length > 1 && q.lane != null) {
      const narrow = [...new Set(D.txs.filter(x => x.road === q.road && x.lane === q.lane).map(x => x.dist))];
      if (narrow.length === 1) cand = narrow;
    }
    if (cand.length === 1) q.district = cand[0];
    else {
      S.pendingAddr = q; S.roadKw = q.road;
      selectDistrict(L.CITY, false);
      S.pendingAddr = q;
      S.tab = "roads"; renderPanel(); sheet("half");
      toast(cand.length ? `有 ${cand.length} 個行政區都有「${q.road}」，請在下面挑一區。` : `沒有剛好叫「${q.road}」的路段，下面列出路名相近的。`);
      return "choose";
    }
  }
  await showAddress(q);
  return "address";
}
async function showAddress(q) {
  if (S.current !== q.district) selectDistrict(q.district, true);
  S.addr = q; S.roadFilter = q.road; S.pendingAddr = null;
  view.select("road", q.road);
  S.tab = "tx"; renderPanel(); sheet("half");
  await pinAt(q, `${q.district} ${L.describe(q)}`, L.describe(q), true);
}
async function pinAt(q, what, label, isSearch) {
  const data = roadsNow(q.district) || await loadRoads(q.district);
  if (!data) { S.pin = null; refreshPins(); toast(`${what}：這一區沒有道路位置資料，無法標在地圖上。`); return; }
  const pos = L.position(data, q);
  if (!pos) { S.pin = null; refreshPins(); toast(`${what}：OpenStreetMap 上找不到「${q.road}」的位置。`); return; }
  S.pin = { lat: pos.lat, lng: pos.lng, label, radius: pos.radius, note: pos.note, what };
  refreshPins();
  if (isSearch && S.tab === "tx") renderPanel();
  if (isSearch) refreshRoads();
  view.flyTo(pos.lat, pos.lng, Math.max(view.zoom, ZOOM.pin[pos.precision] || ZOOM.address));
  toast(`已標出 ${what}（${pos.note}）`);
}

// ------------------------------------------------------------------ 周邊（OpenStreetMap / Overpass，在使用者裝置上查詢；結果暫存在這台裝置）
const OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"];
const POI_CACHE = "dth_poi_v2";      // v2：加了高壓電線、鐵路、快速道路、機場
function poiCacheGet(k) { try { const c = JSON.parse(localStorage.getItem(POI_CACHE) || "{}"); const e = c[k]; return e && Date.now() - e.t < 30 * 864e5 ? e.d : null; } catch { return null; } }
function poiCachePut(k, d) {
  try { const c = JSON.parse(localStorage.getItem(POI_CACHE) || "{}"); c[k] = { t: Date.now(), d };
    const keys = Object.keys(c).sort((a, b) => c[b].t - c[a].t); for (const old of keys.slice(40)) delete c[old];
    localStorage.setItem(POI_CACHE, JSON.stringify(c)); } catch { /* 存不下就算了 */ }
}
async function fetchPoiElements(lat, lng) {
  const k = `${lat.toFixed(4)},${lng.toFixed(4)}`, hit = poiCacheGet(k);
  if (hit) return hit;
  const q = L.poiQuery(lat, lng);
  let last = null;
  for (const url of OVERPASS) {
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 30000);
    try {
      const r = await fetch(url, { method: "POST", body: "data=" + encodeURIComponent(q), signal: ctl.signal,
                                   headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      // 線狀的（電線、鐵路）只留離查詢點最近的那一點，暫存才不會太大
      const els = (j.elements || []).map(e => {
        if (Array.isArray(e.geometry) && e.geometry.length) { const [d, la, lo] = L.nearestOnLine(lat, lng, e.geometry); return { type: e.type, id: e.id, lat: la, lon: lo, dLine: d, tags: e.tags }; }
        return { type: e.type, id: e.id, lat: e.lat, lon: e.lon, center: e.center, tags: e.tags };
      });
      poiCachePut(k, els);
      return els;
    } catch (e) { last = e; } finally { clearTimeout(timer); }
  }
  throw last || new Error("查詢失敗");
}
async function showPoi(lat, lng, label) {
  S.poi = { lat, lng, label, status: "loading" };
  S.tab = "poi"; renderPanel(); sheet("half"); refreshPois();
  try {
    const els = await fetchPoiElements(lat, lng);
    if (!S.poi || S.poi.lat !== lat || S.poi.lng !== lng) return;
    S.poi.res = L.classifyPois(els, lat, lng); S.poi.status = "ok";
  } catch (e) {
    if (!S.poi || S.poi.lat !== lat) return;
    S.poi.status = "error"; S.poi.err = e.message; logError("周邊查詢（OpenStreetMap）", e, true);
  }
  refreshPois();
  if (S.tab === "poi") renderPanel();
  view.flyTo(lat, lng, Math.max(view.zoom, 110));
}
function refreshPois() {
  const cat = Object.fromEntries(L.POI_CATS.map(c => [c.key, c]));
  view.pois = S.poi && S.poi.res ? S.poi.res.items.map(x => ({ id: x.id + x.cat, lat: x.lat, lng: x.lng, color: cat[x.cat].color, ch: cat[x.cat].ch,
    label: `${x.name}｜${x.d} 公尺`, cat: x.cat, name: x.name, d: x.d })) : [];
  view.rings = view.rings.filter(r => !r.poi);
  if (S.poi) view.rings.push({ lat: S.poi.lat, lng: S.poi.lng, km: 0.5, color: "#1baf7a", poi: true });
  view.request();
}
// ------------------------------------------------------------------ 行情報告（列印／存成 PDF）
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
  return `<div class="row"><button class="btn small primary" data-act="poi" data-lat="${lat}" data-lng="${lng}" data-label="${esc(label)}">看周邊生活機能與嫌惡設施</button></div>`;
}
function tabPoi() {
  const p = S.poi;
  if (!p) return `<p class="muted">先搜尋地址或點一筆成交，再按「看周邊生活機能與嫌惡設施」。</p>`;
  let h = `<div class="summary"><b>${esc(p.label)}</b> 周邊</div>`;
  if (p.status === "loading") return h + `<p class="empty">向 OpenStreetMap 查詢中…（約 5～20 秒）</p>`;
  if (p.status === "error") return h + `<p class="note">查詢失敗：${esc(p.err || "")}。OpenStreetMap 的查詢伺服器可能正忙，請稍後再按一次。</p>` + poiButton(p.lat, p.lng, p.label);
  const fmtD = d => d >= 1000 ? (d / 1000).toFixed(1) + " 公里" : d + " 公尺";
  const block = (group, title) => {
    let t = `<h2>${title}</h2><table class="list"><tbody>`;
    for (const c of L.POI_CATS.filter(c => c.group === group)) {
      const b = p.res.byCat[c.key], rr = fmtD(c.r);
      t += `<tr${b.n ? ` class="click" data-poi="${esc(b.nearest.id + c.key)}"` : ""}><td><span class="pill" style="background:${c.color};color:#fff">${c.ch}</span>${esc(c.label)}` +
        `<div class="muted">${b.n ? `最近：${esc(b.nearest.name)} ${fmtD(b.nearest.d)}` : `${rr}內沒有`}</div></td><td class="r">${rr}內<br><b>${b.n}</b></td></tr>`;
    }
    return t + "</tbody></table>";
  };
  h += block("good", "生活機能") + block("bad", "嫌惡設施");
  h += `<div class="row">${reportButton()}</div>`;
  h += `<p class="muted">資料來自 OpenStreetMap 志工繪製，可能有缺漏或過時（特別是禮儀社、宮廟、小型工廠），看屋前請實地走一圈。宮廟是否算嫌惡因人而異。高壓電線、鐵路、快速道路量的是到線上最近一點的距離；機場看 4 公里內，實際航道噪音請看各機場公告的噪音管制區。</p>`;
  return h;
}

// ------------------------------------------------------------------ 點選地圖
function pick(hit, latlng) {
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
  const item = kind === "landmark" ? D.landmarks.find(x => x.id === id) : (kind === "project" || kind === "marker") ? D.intel[id] : null;
  const where = kind === "landmark" ? (item || {}).district : item ? ((item.district || "").split(/[、／\/,，\s（(]/)[0]) : null;
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
  else if (kind === "project" || kind === "marker") { const it = D.intel[id]; ll = [it.lat, it.lng]; }
  else if (kind === "station") { const ln = allLines().find(l => l.name === id[0]); const st = ln && ln.stations.find(s => s[0] === id[1]); if (st) ll = [st[1], st[2]]; }
  else if (kind === "pin" && id === "work") { const w = workPlace(); if (w) ll = [w.lat, w.lng]; }
  if (ll) view.flyTo(ll[0], ll[1], Math.max(view.zoom, ZOOM.point));
  renderPanel(); sheet("half");
}

// ------------------------------------------------------------------ 面板
const TABS = [["overview", "概況"], ["rank", "排行"], ["commute", "通勤"], ["roads", "路段"], ["bldg", "社區"], ["tx", "成交"], ["value", "估價"], ["cmp", "比較"], ["projects", "建設"], ["detail", "點選"], ["poi", "周邊"], ["watch", "看屋"]];
function renderPanel() {
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
    `<button role="tab" data-tab="${k}" aria-selected="${S.tab === k}">${t}</button>`).join("");
  const body = $("#tab-body");
  body.innerHTML = ({ overview: tabOverview, rank: tabRank, commute: tabCommute, roads: tabRoads, bldg: tabBldg, tx: tabTx, value: tabValue, cmp: tabCmp, projects: tabProjects, detail: tabDetail, poi: tabPoi, watch: tabWatch }[S.tab] || tabOverview)();
  body.scrollTop = 0;
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
    const list = cmp.split(",").map(s => s.split(":")).filter(a => a.length === 2 && a[1]).slice(0, CMP_MAX)
      .map(([code, name]) => ({ code, name, county: D.tw ? ((D.tw.counties.find(c => c.code === code) || {}).short || "") : L.CITY }));
    if (list.length) { S.settings.cmp = list; saveStore(); }
  }
  if (tab && SHARE_TABS.includes(tab)) S.tab = tab;
  if (d && D.dmap && D.dmap[d] && !params.get("q")) selectDistrict(d);
  else refreshAll();
}
function trendSVG(series) {
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
  pts.forEach(p => { if (p.i % 3 === 0 || p.i === pts.length - 1) s += `<text x="${x(p.i)}" y="${H - 8}" font-size="10" text-anchor="middle" fill="#5b6168">${p.m.slice(2).replace("-", "/")}</text>`; });
  return s + "</svg>";
}
function tabOverview() {
  const name = S.current, b = D.book, bt = b.best(name, S.cat, "t");
  let h = `<h2 style="margin-top:2px">${esc(name)}每月中位${S.metric === "u" ? "單價（萬/坪）" : "總價（萬）"}</h2>${trendSVG(b.series(name, S.cat, S.metric))}`;
  h += `<p class="muted">空心點是資料還沒到齊的月份；灰色長條是每月件數。${esc(D.meta.describe)}</p>`;
  if (name !== L.CITY) {
    const gap = b.presaleGap(name), w = workPlace(), d = D.dmap[name];
    const bits = [];
    if (gap != null) bits.push(`預售屋單價比中古大樓${gap >= 0 ? "高" : "低"} ${Math.abs(gap).toFixed(0)}%`);
    if (w) bits.push(`到${esc(w.name)}：${modeName()}約 ${minsTo(d.lat, d.lng, w)} 分鐘（直線 ${L.distKm(d.lat, d.lng, w.lat, w.lng).toFixed(1)} 公里，估計）`);
    if (bits.length) h += `<div class="summary">${bits.join("<br>")}</div>`;
    h += `<div class="row">${reportButton()}<button class="btn small" data-act="cmp-add">加入比較</button><a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/@${d.lat},${d.lng},14z">Google 地圖</a><a class="btn" target="_blank" rel="noopener" href="${FLOOD_URL}">淹水潛勢</a>` +
      (w ? `<a class="btn" target="_blank" rel="noopener" href="${L.routeUrl(d, w, S.settings.mode)}">通勤路線</a>` : "") + `</div>`;
    h += loanSection(bt.value) + costSection(bt.value) + rentSection(name) + rvbSection(name, bt.value);
  } else {
    h += loanSection(bt.value) + costSection(bt.value) + rentSection(name);
    h += isNation() ? `<p class="muted">點地圖上的柱子（或「排行」）進入一個縣市，才會下載那個縣市的逐筆成交與路段；也可以直接搜尋「台北市大安區…」這樣的地址。透天厝的單價含土地，看透天請以總價為主。</p>`
      : `<p class="muted">點地圖上的柱子看各區，或在上方搜尋地址。透天厝的單價含土地，看透天請以總價為主。</p>`;
  }
  return h;
}
// ---- 房貸試算：總價預設帶入這一區的中位總價，其他條件記在這台裝置
const LOAN_DEFAULT = { price: "", down: 20, rate: 2.2, years: 30, grace: 0 };
function loanState() { return Object.assign({}, LOAN_DEFAULT, S.settings.loan || {}); }
function loanResult(median) {
  const st = loanState(), price = +st.price || median;
  const m = price ? L.mortgage(price, +st.down, +st.rate, +st.years, +st.grace) : null;
  if (!m) return `<p class="muted">輸入總價就能試算。</p>`;
  const yuan = v => Math.round(v).toLocaleString("zh-TW");
  return `<div class="summary">總價 ${L.fmtNum(price)} 萬：自備款 ${L.fmtNum(Math.round(m.down))} 萬、貸款 ${L.fmtNum(Math.round(m.loan))} 萬<br>` +
    (m.graceMonthly ? `寬限期每月只繳利息 <b>${yuan(m.graceMonthly)}</b> 元，之後` : "") + `每月約繳 <b>${yuan(m.monthly)}</b> 元<br>` +
    `總利息約 ${L.fmtNum(Math.round(m.totalInterest))} 萬｜月付控制在收入三分之一，家庭月收入約需 ${yuan(m.income)} 元</div>`;
}
function loanSection(median) {
  const st = loanState(), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-loan="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  return `<h3>房貸試算</h3><div class="loan">${num("price", "總價", 10, "萬", median ? String(Math.round(median)) : "")}${num("down", "自備款", 5, "%")}` +
    `${num("rate", "年利率", 0.05, "%")}${num("years", "年限", 5, "年")}${num("grace", "寬限期", 1, "年")}</div>` +
    `<div id="loan-out">${loanResult(median)}</div><p class="muted">本息平均攤還的估算，總價空白就用這一區的中位總價；實際利率、成數與寬限期以銀行核貸為準，這不是貸款建議。</p>`;
}
// ---- 交屋前要準備的現金：自備款＋買方稅費（契稅、印花稅、規費、代書、仲介…）
const loanPrice = median => +loanState().price || median;
function costState() { return Object.assign({}, L.COST_DEFAULT, S.settings.cost || {}); }
const wan = v => v >= 100 ? L.fmtNum(v) : v >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/0$/, "");
function costResult(median) {
  const st = loanState(), price = loanPrice(median), c = price ? L.purchaseCosts(price, +st.down, costState()) : null;
  if (!c) return `<p class="muted">輸入總價就能試算。</p>`;
  const m = L.mortgage(price, +st.down, +st.rate, +st.years, +st.grace);
  const reserve = m ? Math.max(m.monthly, m.graceMonthly || 0) * 6 / 10000 : 0;
  let h = `<table class="list cost"><tbody>` + c.items.filter(([k, , v]) => v > 0 || k === "agent")
    .map(([k, label, v, note]) => `<tr${k === "down" ? ' class="strong"' : ""}><td>${esc(label)}<div class="muted">${esc(note)}</div></td><td class="r">${wan(v)} 萬</td></tr>`).join("") +
    `<tr class="total"><td>合計（交屋前要準備）</td><td class="r">${L.fmtNum(c.total)} 萬</td></tr></tbody></table>`;
  h += `<div class="summary">頭期款以外的稅費與雜支約 <b>${wan(c.fees)} 萬</b>（總價的 ${(c.fees / price * 100).toFixed(1)}%）` +
    (reserve ? `<br>另外建議預留 6 個月房貸約 ${wan(reserve)} 萬，以免收入中斷時繳不出來` : "") + `</div>`;
  if (c.estimated) h += `<p class="muted">房屋評定現值、土地公告現值沒填，暫用總價的 ${L.COST_RATIO.house * 100}%、${L.COST_RATIO.land * 100}% 粗估（新大樓通常更低、老透天的土地比例更高）；實際數字看賣方的房屋稅單、地價稅單，或請代書查。</p>`;
  return h;
}
function costSection(median) {
  const st = costState(), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-cost="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  const price = loanPrice(median);
  return `<details class="more" data-det="costOpen"${S.settings.costOpen ? " open" : ""}><summary>交屋前要準備多少現金</summary>` +
    `<div class="loan">${num("hv", "房屋現值", 1, "萬", price ? "約 " + Math.round(price * L.COST_RATIO.house) : "")}${num("lv", "土地現值", 1, "萬", price ? "約 " + Math.round(price * L.COST_RATIO.land) : "")}` +
    `${num("agent", "仲介費", 0.5, "%")}${num("reno", "裝潢搬家", 10, "萬")}</div><div id="cost-out">${costResult(median)}</div>` +
    `<p class="muted">總價、自備款比例沿用上面的房貸試算。稅率依現行法規（契稅 6%、印花稅與登記規費 0.1%、抵押權設定規費 0.1%）；房屋稅、地價稅依交屋日分算，不在這裡。這是估算，不是稅務建議。</p></details>`;
}

// ---- 租金行情：實價登錄租賃（近一年），加上毛租金報酬率
function rentYield(name, cat) {
  const rc = L.rentCell(D.rent, name, cat), su = D.book.best(name, cat, "u").value;
  return rc && rc.n >= 5 ? L.grossYield(rc.unit, su) : null;
}
function rentSection(name) {
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
function rvbState() { return Object.assign({ rent: "" }, L.RVB_DEFAULT, S.settings.rvb || {}); }
function rvbDefaultRent(name, median) {
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
function rvbResult(name, median) {
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
function rvbSection(name, median) {
  const st = rvbState(), def = rvbDefaultRent(name, median), num = (k, label, step, unit, ph) =>
    `<label class="loan-f"><span>${label}</span><input type="number" inputmode="decimal" step="${step}" data-rvb="${k}" value="${esc(String(st[k]))}"${ph ? ` placeholder="${esc(ph)}"` : ""}><small>${unit}</small></label>`;
  return `<details class="more" data-det="rvbOpen"${S.settings.rvbOpen ? " open" : ""}><summary>買房還是租房比較划算</summary>` +
    `<div class="loan">${num("rent", "月租", 500, "元", def ? String(def) : "")}${num("years", "比較", 1, "年")}${num("g", "房價年漲", 0.5, "%")}` +
    `${num("rg", "租金年漲", 0.5, "%")}${num("inv", "投資報酬", 0.5, "%")}</div><div id="rvb-out">${rvbResult(name, median)}</div>` +
    `<p class="muted">月租空白時用這一區的毛租金報酬率推算同總價房子的租金。房貸條件沿用上面的試算；持有成本（房屋稅、地價稅、管理費、修繕）以每年房價 ${L.RVB_DEFAULT.hold}% 估，賣屋時扣 ${L.RVB_DEFAULT.sell}% 仲介與稅費，未計房地合一稅。結果對「房價年漲」與「投資報酬」很敏感，請多試幾組；這不是投資建議。</p></details>`;
}
// 上班地點選單：依縣市分組，目前看的縣市排最前面
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
  return h + `</tbody></table><p class="muted">通勤時間用直線距離 ×1.3 與平均車速（開車 32、機車 28、腳踏車 14 公里/時）加 3 分鐘出發時間估算，尖峰時段可能多 3～5 成；實際路線請按各區「概況」裡的「通勤路線」用 Google 地圖查。</p>`;
}
function tabRank() {
  const w = workPlace();
  const rows = D.districts.map(d => ({ d, b: D.book.best(d.name, S.cat, S.metric), t: D.book.best(d.name, S.cat, "t"), tr: D.book.trend(d.name, S.cat, S.metric),
    km: w ? minsTo(d.lat, d.lng, w) : null, ok: !filtersOn() || (budgetOK(d.name) && workOK(d.name)) }));
  rows.sort((a, b) => (b.b.value ?? -1) - (a.b.value ?? -1));
  let h = `<table class="list"><thead><tr><th>行政區</th><th class="r">${S.metric === "u" ? "萬/坪" : "總價"}</th><th class="r">總價</th>${w ? '<th class="r">通勤</th>' : ""}<th class="r">半年</th></tr></thead><tbody>`;
  for (const r of rows) {
    h += `<tr class="click${r.b.low ? " low" : ""}${r.d.name === S.current ? " sel" : ""}" data-dist="${esc(r.d.name)}" style="${r.ok ? "" : "opacity:.45"}"><td>${esc(r.d.name)}</td>` +
      `<td class="r">${r.b.value == null ? "—" : S.metric === "u" ? r.b.value.toFixed(1) : L.fmtNum(r.b.value)}</td><td class="r">${L.fmtNum(r.t.value)}</td>` +
      (w ? `<td class="r">${r.km}分</td>` : "") + `<td class="r">${L.trendText(r.tr).replace("樣本不足", "—")}</td></tr>`;
  }
  return h + `</tbody></table><p class="muted">灰字是樣本少（近半年不到 5 件）。${filtersOn() ? "淡色是不符合預算／通勤條件。" : ""}</p>`;
}
const needCounty = () => `<p class="muted">先在地圖上點一個縣市的柱子（或從「排行」選），才會載入那個縣市的逐筆成交、路段與社區。</p>`;
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
  if (b) {
    const age = b.built ? `屋齡約 ${Math.max(0, new Date().getFullYear() - b.built)} 年｜` : "";
    h += `<div class="summary"><b>${esc(b.name)}</b>｜${esc(S.current)}<br>${esc(b.btype)}｜${age}共 ${b.n} 筆，中位單價 ${b.u.toFixed(1)} 萬/坪、總價 ${L.fmtNum(b.t)} 萬` +
      (b.n12 ? `<br>近一年 ${b.n12} 筆：中位單價 ${b.u12.toFixed(1)} 萬/坪` : `<br>近一年沒有成交`) + `</div>`;
    h += linksRow(S.current, b.presale ? b.name : b.name, "找這個社區正在賣的房子");
    h += `<div class="row"><button class="btn small" data-act="bldg-back">← 回社區列表</button></div>`;
    if (S.pin) h += poiButton(S.pin.lat, S.pin.lng, b.name);
    const rows = D.txs.filter(x => x.dist === S.current && L.inCat(x, S.cat) && L.bldgKey(x) === b.key);
    h += `<table class="list"><thead><tr><th>日期</th><th>樓層／地址</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">坪</th></tr></thead><tbody>`;
    for (const x of rows.slice(0, 300))
      h += `<tr><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc(x.addr)}</td><td class="r">${L.fmtNum(x.tw)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${x.ping.toFixed(1)}</td></tr>`;
    return h + `</tbody></table>`;
  }
  const list = kw ? all.filter(r => r.name.includes(kw)) : all;
  h += `<div class="row"><input type="search" id="bldg-kw" placeholder="社區或路名，例如：成功路" value="${esc(kw)}"></div>`;
  h += `<p class="muted">${esc(S.current)}有 2 筆以上成交的${S.cat === "presale" ? "建案" : "社區／大樓"} ${list.length} 個。實價登錄沒有社區名稱，中古屋以「同一個門牌」當作同一棟；預售屋用建案名稱。點一列看每一筆成交。</p>`;
  if (!list.length) return h;
  h += `<table class="list"><thead><tr><th>社區／門牌</th><th class="r">件</th><th class="r">萬/坪</th><th class="r">近一年</th><th class="r">屋齡</th></tr></thead><tbody>`;
  const yr = new Date().getFullYear();
  for (const r of list.slice(0, 300))
    h += `<tr class="click" data-bldg="${esc(r.key)}"><td>${esc(r.name)}<div class="muted">${esc(r.btype)}｜最近 ${r.last.slice(2, 7).replace("-", "/")}</div></td><td class="r">${r.n}</td>` +
      `<td class="r">${r.u.toFixed(1)}</td><td class="r">${r.u12 == null ? "—" : r.u12.toFixed(1)}</td><td class="r">${r.built ? Math.max(0, yr - r.built) : "—"}</td></tr>`;
  return h + "</tbody></table>";
}
function txRows() {
  const name = S.current;
  let rows = D.txs.filter(x => (name === L.CITY || x.dist === name) && L.inCat(x, S.cat));
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
  if (S.roadFilter && S.cat !== "presale") h += linksRow(S.current, q && q.district === S.current ? L.describe(q).replace(/ /g, "") : S.roadFilter, "找這條路正在賣的房子");
  h += `<table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">坪</th></tr></thead><tbody>`;
  ranked.slice(0, 300).forEach((r, i) => {
    const x = r.x, where = x.proj ? `${x.proj}（${x.addr.slice(0, 12)}）` : x.addr;
    const age = x.built ? ` ${Math.max(0, +x.date.slice(0, 4) - x.built)}年` : "";
    h += `<tr class="click ${r.level === 3 ? "exact" : r.level === 2 ? "lane" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td>` +
      `<td>${esc(where)}<div class="muted">${esc(x.btype)}${age}${S.current === L.CITY ? "｜" + esc(x.dist) : ""}</div></td>` +
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

// ---- 看屋清單（只存在這台裝置）
const WATCH_TYPES = ["透天厝", "大樓／華廈", "公寓", "預售屋", "店面／透店", "土地", "其他"];
const TYPE_CAT = { "透天厝": "house", "店面／透店": "house", "大樓／華廈": "apt", "公寓": "all", "預售屋": "presale" };
function compareWatch(it) {
  const cat = TYPE_CAT[it.type];
  if (!cat || !D.dmap[it.district]) return null;
  const bt = D.book.best(it.district, cat, "t"), bu = D.book.best(it.district, cat, "u");
  const unit = it.price && it.ping ? it.price / it.ping : null;
  return { cat, bt, bu, unit, vsT: it.price && bt.value ? (it.price - bt.value) / bt.value * 100 : null, vsU: unit && bu.value ? (unit - bu.value) / bu.value * 100 : null };
}
const pct = v => v == null ? "—" : `${v >= 0 ? "高" : "低"} ${Math.abs(v).toFixed(0)}%`;
// ---- 看屋清單附近的新成交：每次載入成交資料時，找出物件同一條路（沒填路名就同一區、同房型）上次看過之後的新成交
const watchCode = it => it.code || "D";
function watchNearby(it) {
  if (!D.txs) return [];
  const cat = TYPE_CAT[it.type] || "all";
  let road = null;
  if (it.address) { const a = L.parseAddress(it.district + it.address.replace(it.district, ""), D.districts.map(d => d.name)); road = a && a.road; }
  return D.txs.filter(x => x.dist === it.district && L.inCat(x, cat) && (!road || x.road === road));
}
function checkWatchNews() {
  if (!D.txs) return;
  const code = cmpCode() || "D", latest = D.txs.reduce((m, x) => x.date > m ? x.date : m, "");
  let changed = false, total = 0, names = [];
  S.watchNews = S.watchNews || {};
  for (const it of S.watch) {
    if (D.tw && watchCode(it) !== code) continue;
    if (!D.dmap[it.district]) continue;
    if (!it.seen) { it.seen = latest; changed = true; S.watchNews[it.id] = []; continue; }   // 第一次：從現在開始算
    const news = watchNearby(it).filter(x => x.date > it.seen).sort((a, b) => b.date.localeCompare(a.date));
    S.watchNews[it.id] = news;
    if (news.length) { total += news.length; names.push(it.name); }
  }
  if (changed) saveStore();
  if (total && !S._watchToasted) { S._watchToasted = true; toast(`看屋清單：${names.slice(0, 2).join("、")}${names.length > 2 ? "等" : ""}附近有 ${total} 筆新成交，到「看屋」分頁看。`, 6000); }
}
function tabWatch() {
  let h = `<div class="row"><button class="btn primary" data-act="watch-add">新增物件</button><button class="btn" data-act="watch-export">匯出備份</button><label class="btn">匯入<input type="file" id="watch-import" accept="application/json" hidden></label></div>`;
  h += `<p class="muted">看屋清單只存在這台裝置的瀏覽器裡，不會上傳。換手機時請用「匯出備份」再到新手機「匯入」。</p>`;
  if (!S.watch.length) return h + `<p class="empty">清單是空的。按「新增物件」把正在看的房子記下來，就能和那一區的行情比較。</p>`;
  h += `<table class="list"><thead><tr><th>物件</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">對區中位</th></tr></thead><tbody>`;
  for (const it of S.watch) {
    const c = compareWatch(it);
    const nn = ((S.watchNews || {})[it.id] || []).length;
    h += `<tr class="click${S.watchSel === it.id ? " sel" : ""}" data-watch="${esc(it.id)}"><td>${esc(it.name)}${nn ? ` <span class="pill new">新成交 ${nn}</span>` : ""}<div class="muted">${esc(it.district || "")}｜${esc(it.type || "")}</div></td>` +
      `<td class="r">${it.price ? L.fmtNum(it.price) : "—"}</td><td class="r">${c && c.unit ? c.unit.toFixed(1) : "—"}</td><td class="r">${c ? pct(c.vsT) : "—"}</td></tr>`;
  }
  h += "</tbody></table>";
  const it = S.watch.find(w => w.id === S.watchSel);
  if (it) {
    const c = compareWatch(it);
    h += `<h2>${esc(it.name)}</h2><p class="muted">${esc([it.district, it.address, it.type].filter(Boolean).join("｜"))}</p>`;
    if (c && c.bt.value != null) h += `<div class="summary">${esc(it.district)}${L.CAT_LABEL[c.cat]}中位總價 ${L.fmtNum(c.bt.value)} 萬（${c.bt.n} 件）→ 這間 ${pct(c.vsT)}<br>中位單價 ${c.bu.value != null ? c.bu.value.toFixed(1) : "—"} 萬/坪 → 這間 ${pct(c.vsU)}</div>`;
    if (it.note) h += `<p>${esc(it.note)}</p>`;
    const news = (S.watchNews || {})[it.id] || [];
    if (news.length) {
      S.txShown = news.slice(0, 30);
      h += `<h3>上次看過之後，附近的新成交（${news.length} 筆）</h3><table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">坪</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>` +
        S.txShown.map((x, i) => `<tr class="click" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc((x.proj || x.addr.replace(/^.{2,3}[市縣]/, "").replace(x.dist, "")).slice(0, 18))}</td>` +
          `<td class="r">${x.ping.toFixed(1)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${L.fmtNum(x.tw)}</td></tr>`).join("") +
        `</tbody></table><div class="row"><button class="btn small" data-act="watch-seen">我看過了</button></div>`;
    }
    h += `<div class="row"><button class="btn primary" data-act="watch-value">估合理價</button><button class="btn" data-act="watch-edit">編輯</button><button class="btn" data-act="watch-pin">在地圖上標位置</button>` +
      (it.lat != null ? `<button class="btn" data-act="watch-map">在地圖上看</button>` : "") +
      (it.url ? `<a class="btn" target="_blank" rel="noopener" href="${esc(it.url)}">物件網址</a>` : "") +
      `<button class="btn" data-act="watch-del">刪除</button></div>`;
  }
  return h;
}
// ---- 區域比較：最多 3 個區並排，可以跨縣市（例如台南東區 vs 高雄左營 vs 台中北屯）
const CMP_MAX = 3;
const cmpCode = () => (D.county ? D.county.code : D.tw ? "" : "D");
function cmpList() { return (S.settings.cmp || []).filter(x => x && x.name); }
function cmpAdd() {
  const code = cmpCode(), name = S.current;
  if (!name || name === L.CITY || (D.tw && !D.county)) { toast("先選一個行政區再加入比較。"); return; }
  const list = cmpList().filter(x => !(x.code === code && x.name === name));
  list.push({ code, name, county: D.county ? D.county.short : L.CITY });
  S.settings.cmp = list.slice(-CMP_MAX); saveStore();
  toast(`已加入比較（${S.settings.cmp.length}/${CMP_MAX}）`); S.tab = "cmp"; renderPanel();
}
const CMP_DATA = new Map();      // "代碼|區" → {book, d}
function cmpEnsure() {
  const need = cmpList().filter(x => !CMP_DATA.has(x.code + "|" + x.name));
  if (!need.length) return true;
  Promise.all(need.map(async x => {
    if (!D.tw) { CMP_DATA.set(x.code + "|" + x.name, { book: D.book, d: D.dmap[x.name] }); return; }
    const cd = await countyData(x.code);
    CMP_DATA.set(x.code + "|" + x.name, { book: cd.book, d: cd.dmap[x.name], rent: cd.rent });
  })).then(() => { if (S.tab === "cmp") renderPanel(); }).catch(e => { logError("載入比較資料", e); toast("比較資料載入失敗，請檢查網路。"); });
  return false;
}
function cmpSeriesSVG(cols) {
  const colors = ["#2a78d6", "#e3542c", "#2ea36b"], all = [];
  const ser = cols.map(c => c.book.series(c.name, S.cat, S.metric).filter(p => !p.partial));
  ser.forEach(s => s.forEach(p => { if (p.v != null) all.push(p.v); }));
  if (all.length < 2) return "";
  let lo = Math.min(...all), hi = Math.max(...all); const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
  const months = [...new Set(ser.flat().map(p => p.m))].sort(), W = 360, H = 150, l = 40, r = 10, t = 10, b = 22;
  const x = m => l + months.indexOf(m) * (W - l - r) / Math.max(1, months.length - 1), y = v => t + (hi - v) / (hi - lo) * (H - t - b);
  let g = `<svg class="trend" viewBox="0 0 ${W} ${H}" role="img" aria-label="各區每月中位價比較">`;
  for (const f of [0, 0.5, 1]) { const v = hi - (hi - lo) * f; g += `<line x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}" stroke="#eceff2"/><text x="${l - 5}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#5b6168">${S.metric === "u" ? v.toFixed(0) : L.fmtNum(v)}</text>`; }
  ser.forEach((s, i) => {
    const pts = s.filter(p => p.v != null).map(p => `${x(p.m)},${y(p.v)}`).join(" ");
    g += `<polyline fill="none" stroke="${colors[i]}" stroke-width="2.2" points="${pts}"/>`;
  });
  months.forEach((m, i) => { if (i % 3 === 0 || i === months.length - 1) g += `<text x="${x(m)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#5b6168">${m.slice(2).replace("-", "/")}</text>`; });
  g += "</svg>";
  return g + `<p class="muted">${cols.map((c, i) => `<span style="color:${colors[i]}">━</span> ${esc(c.label)}`).join("　")}</p>`;
}
function tabCmp() {
  const list = cmpList();
  let h = `<div class="row">${S.current !== L.CITY && !isNation() ? `<button class="btn primary" data-act="cmp-add">把${esc(S.current)}加入比較</button>` : ""}` +
    (list.length ? `<button class="btn" data-act="cmp-clear">清空</button>` : "") + `</div>`;
  if (!list.length) return h + `<p class="empty">還沒有要比較的區。選一個行政區後按「加入比較」，最多 ${CMP_MAX} 個，可以跨縣市。</p>`;
  if (!cmpEnsure()) return h + `<p class="empty">載入比較資料中…</p>`;
  const cols = list.map(x => ({ ...x, ...CMP_DATA.get(x.code + "|" + x.name), label: (D.tw ? x.county.replace(/[市縣]$/, "") + " " : "") + x.name }))
    .filter(c => c.book && c.d);
  const w = workPlace(), cat = S.cat;
  const stations = allLines().flatMap(ln => ln.stations.map(st => ({ ln, st })));
  const rows = [
    ["中位單價（萬/坪）", c => { const b = c.book.best(c.name, cat, "u"); return b.value == null ? "—" : b.value.toFixed(1) + (b.low ? "*" : ""); }],
    ["中位總價（萬）", c => L.fmtNum(c.book.best(c.name, cat, "t").value)],
    ["成交件數", c => L.fmtNum(c.book.best(c.name, cat, "u").n)],
    ["近半年漲跌", c => L.trendText(c.book.trend(c.name, cat, S.metric))],
    ["預售比中古大樓", c => { const g = c.book.presaleGap(c.name); return g == null ? "—" : `${g >= 0 ? "高" : "低"} ${Math.abs(g).toFixed(0)}%`; }],
    [w ? `到${w.name}（${modeName()}）` : "通勤（先設定上班地點）", c => w ? `約 ${minsTo(c.d.lat, c.d.lng, w)} 分` : "—"],
    ["月租中位（整層住家）", c => { const r = L.rentCell(c.rent, c.name, "apt"); return r ? `${L.fmtNum(r.rent)}${r.n < L.RENT_MIN_N ? "*" : ""}` : "—"; }],
    ["毛租金報酬率", c => { const r = L.rentCell(c.rent, c.name, "apt"), su = c.book.best(c.name, "apt", "u").value, y = r && r.n >= L.RENT_MIN_N ? L.grossYield(r.unit, su) : null; return y == null ? "—" : y.toFixed(1) + "%"; }],
    ["最近的車站", c => {
      let best = null; for (const { ln, st } of stations) { const k = L.distKm(c.d.lat, c.d.lng, st[1], st[2]); if (!best || k < best.k) best = { k, n: st[0], ln }; }
      return best && best.k <= 8 ? `${esc(best.n.split("（")[0].slice(0, 10))} ${best.k.toFixed(1)} 公里${best.ln.operating ? "" : "（規劃）"}<div class="muted">${esc(best.ln.name)}</div>` : "8 公里內沒有";
    }],
    ["3 公里內重大建設", c => {
      const n = D.intel.filter(it => it.lat != null && (it.impact_level || 0) >= 4 && L.distKm(c.d.lat, c.d.lng, it.lat, it.lng) <= 3).length;
      return n ? `${n} 項` : "—";
    }],
  ];
  h += `<table class="list cmp"><thead><tr><th></th>${cols.map((c, i) => `<th class="r">${esc(c.label)}<div><a href="#" data-cmpdel="${i}">移除</a></div></th>`).join("")}</tr></thead><tbody>` +
    rows.map(([k, f]) => `<tr><td>${esc(k)}</td>${cols.map(c => `<td class="r">${f(c)}</td>`).join("")}</tr>`).join("") + `</tbody></table>`;
  h += `<p class="muted">房型：${L.CAT_LABEL[cat]}｜近半年統計，件數太少時改用近一年（標 *）。通勤是直線距離的估計。</p>`;
  h += `<h3>每月中位${S.metric === "u" ? "單價" : "總價"}</h3>` + cmpSeriesSVG(cols);
  return h;
}
// ---- 合理價估算：找條件相近的實價登錄成交，算出合理價區間
const VAL_TYPES = [["apt", "大樓／華廈／公寓"], ["house", "透天厝"], ["presale", "預售屋"]];
function valState() { return Object.assign({ dist: "", cat: "apt", ping: "", age: "", addr: "", price: "" }, S.settings.val || {}); }
function valQuery() {
  const v = valState(), dist = D.dmap[v.dist] ? v.dist : (S.current !== L.CITY ? S.current : (D.districts[0] || {}).name);
  const q = { dist, cat: v.cat, ping: +v.ping || null, age: v.cat === "presale" ? null : (v.age === "" ? null : +v.age), presale: v.cat === "presale",
              todayYm: D.book.months[D.book.months.length - 1] };
  if (v.addr) {
    const a = L.parseAddress(dist + v.addr.replace(dist, ""), D.districts.map(d => d.name));
    if (a && a.road) Object.assign(q, { road: a.road, lane: a.lane, alley: a.alley, num: a.num });
  }
  return { v, q };
}
function tabValue() {
  if (isNation()) return needCounty();
  if (!D.txs) return `<p class="empty">成交資料載入中…</p>`;
  const { v, q } = valQuery();
  const inp = (k, label, ph, mode = "decimal") => `<label>${label}</label><input data-val="${k}" inputmode="${mode}" value="${esc(String(v[k] ?? ""))}" placeholder="${esc(ph)}">`;
  let h = `<p class="muted">輸入一間房子的條件，從實價登錄找條件相近的成交（坪數、屋齡接近、越新的越重要；同一棟、同一條巷、同一條路優先），算出合理價區間。</p>` +
    `<div class="grid valform"><label>行政區</label><select data-val="dist">${D.districts.map(d => `<option${d.name === q.dist ? " selected" : ""}>${esc(d.name)}</option>`).join("")}</select>` +
    `<label>房型</label><select data-val="cat">${VAL_TYPES.map(([k, t]) => `<option value="${k}"${k === v.cat ? " selected" : ""}>${t}</option>`).join("")}</select>` +
    inp("ping", "建坪（含車位）", "例：35") + (v.cat === "presale" ? "" : inp("age", "屋齡（年）", "例：12", "numeric")) +
    inp("addr", "路名或門牌", "可空白，例：中華路一段", "text") + inp("price", "開價（萬，可空白）", "例：1580") + `</div>`;
  if (!q.ping) return h + `<p class="empty">填上建坪就能估價。</p>`;
  const e = L.estimate(D.txs, q);
  if (!e.ok) return h + `<p class="empty">${esc(q.dist)}條件相近的成交只有 ${e.n} 筆，太少，估不出來。可以把房型改成「全部」看看，或放寬坪數。</p>`;
  const j = L.judgePrice(e, +v.price);
  h += `<div class="summary"><b>合理總價約 ${L.fmtNum(e.tLo)}～${L.fmtNum(e.tHi)} 萬</b>（中間值 ${L.fmtNum(e.tMid)} 萬）<br>` +
    `單價 ${e.uLo}～${e.uHi} 萬/坪（中間值 ${e.uMid}）｜比對 ${e.n} 筆近 ${e.months / 12 | 0} 年成交，最接近的有 ${e.nearN} 筆${esc(e.level)}` +
    (j ? `<br>開價 ${L.fmtNum(+v.price)} 萬：<b class="${j.pos === "高於" ? "up" : j.pos === "低於" ? "down" : ""}">${j.pos}合理區間</b>（比中間值${j.pct >= 0 ? "高" : "低"} ${Math.abs(j.pct).toFixed(0)}%）` : "") + `</div>`;
  if (q.cat === "house") h += `<p class="muted">透天的單價含土地，地坪大小影響很大，這個區間只能當粗略參考。</p>`;
  S.txShown = e.comps;
  h += `<h3>比對用的成交（最相近的 ${e.comps.length} 筆）</h3><table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">坪</th><th class="r">屋齡</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>`;
  e.comps.forEach((x, i) => {
    const where = x.proj ? x.proj : x.addr.replace(/^.{2,3}[市縣]/, "").replace(x.dist, "");
    h += `<tr class="click${x.level >= 2 ? " lane" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc(where.slice(0, 18))}<div class="muted">${["", "同路", "同巷", "同一棟"][x.level]}</div></td>` +
      `<td class="r">${x.ping.toFixed(1)}</td><td class="r">${x.age ?? "—"}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${L.fmtNum(x.tw)}</td></tr>`;
  });
  h += `</tbody></table><p class="muted">這是依過去成交推算的參考區間，不含屋況、樓層、景觀、車位價差與裝潢；實際價格請以現場與專業估價為準，不構成購屋建議。</p>`;
  return h;
}
function watchDialog(item) {
  const dlg = document.createElement("dialog"), v = item || {};
  dlg.innerHTML = `<form method="dialog"><h2 style="margin-top:0">${item ? "編輯物件" : "新增物件"}</h2><div class="grid">
    <label>名稱</label><input name="name" required value="${esc(v.name || "")}" placeholder="例：善化透天 A">
    <label>行政區</label><select name="district">${D.districts.map(d => `<option${d.name === (v.district || S.current) ? " selected" : ""}>${esc(d.name)}</option>`).join("")}</select>
    <label>地址</label><input name="address" value="${esc(v.address || "")}" placeholder="可只填路名">
    <label>類型</label><select name="type">${WATCH_TYPES.map(t => `<option${t === v.type ? " selected" : ""}>${t}</option>`).join("")}</select>
    <label>總價（萬）</label><input name="price" inputmode="decimal" value="${v.price ?? ""}">
    <label>建坪</label><input name="ping" inputmode="decimal" value="${v.ping ?? ""}">
    <label>屋齡（年）</label><input name="age" inputmode="numeric" value="${v.age ?? ""}">
    <label>網址</label><input name="url" type="url" value="${esc(v.url || "")}">
    <label>備註</label><textarea name="note" rows="3">${esc(v.note || "")}</textarea></div>
    <div class="actions"><button value="cancel" class="btn">取消</button><button value="ok" class="btn primary">儲存</button></div></form>`;
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => {
    if (dlg.returnValue === "ok") {
      const f = new FormData(dlg.querySelector("form")), num = k => { const n = parseFloat(String(f.get(k)).replace(/,/g, "")); return isFinite(n) && n > 0 ? n : null; };
      const data = { name: String(f.get("name")).trim() || "未命名", district: f.get("district"), address: String(f.get("address")).trim(), type: f.get("type"),
                     price: num("price"), ping: num("ping"), age: (() => { const a = parseFloat(f.get("age")); return isFinite(a) && a >= 0 ? a : null; })(), url: String(f.get("url")).trim(), note: String(f.get("note")).trim() };
      if (item) Object.assign(item, data);
      else { const it = { id: "w" + Date.now(), lat: null, lng: null, code: D.county ? D.county.code : "D", ...data }; S.watch.push(it); S.watchSel = it.id; }
      saveStore(); refreshPins(); renderPanel();
    }
    dlg.remove();
  });
  dlg.showModal();
}

// ------------------------------------------------------------------ 設定
function renderMenu() {
  const s = S.settings, chk = (k, t) => `<label class="chk"><input type="checkbox" data-set="${k}"${s[k] ? " checked" : ""}> ${t}</label>`;
  $("#menu-body").innerHTML = `
    <h3>地圖圖層</h3>${chk("town", "行政區界")}${chk("liq", "土壤液化潛勢")}${D.tw ? chk("slide", "山崩與地滑（地質敏感區）") : ""}${chk("fault", "活動斷層")}
    <p class="muted">淹水潛勢：官方圖資沒有開放疊圖，請到 <a target="_blank" rel="noopener" href="${FLOOD_URL}">國家災害防救科技中心 3D 災害潛勢地圖</a> 查詢（各區「概況」也有「淹水潛勢」按鈕）。</p>${chk("hires", "放大時載入高解析衛星影像（較耗流量）")}
    ${chk("lines", "捷運、輕軌、高鐵（營運中與規劃）")}${chk("markers", "開發案與情資（菱形）")}${chk("landmarks", "知名地標 3D")}${chk("projects", "重大建設 3D")}${chk("roads", "路段房價（選了行政區才畫）")}${chk("labels", "名稱標籤")}
    <h3>柱子顏色</h3><div class="row"><select data-set="color"><option value="price"${s.color === "price" ? " selected" : ""}>價格高低</option><option value="trend"${s.color === "trend" ? " selected" : ""}>近半年漲跌</option></select></div>
    <h3>篩選</h3>
    <div class="row"><span>總價預算</span><input type="text" inputmode="decimal" data-set="budget" value="${esc(s.budget)}" placeholder="萬，例 1500"></div>
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
  if (["budget", "work", "workKm", "commuteMin", "mode", "color"].includes(k)) { refreshBars(); refreshPins(); renderPanel(); }
  if (["landmarks", "projects", "markers"].includes(k)) refreshModels();
  if (k === "roads") refreshRoads();
  if (k === "work" && workPlace()) { const w = workPlace(); view.flyTo(w.lat, w.lng, Math.max(view.zoom, 30)); }
  view.request();
}

// ------------------------------------------------------------------ 底部抽屜（手機）
function sheet(state) {
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
  $("#search").addEventListener("submit", e => { e.preventDefault(); $("#q").blur(); search($("#q").value); });
  $("#btn-menu").addEventListener("click", () => { renderMenu(); $("#menu").hidden = !$("#menu").hidden; });
  $("#menu").addEventListener("click", e => {
    if (e.target.closest("[data-close]")) { $("#menu").hidden = true; return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "err-report") reportOnGitHub();
    if (act === "err-copy") { (navigator.clipboard ? navigator.clipboard.writeText(errorReport()) : Promise.reject()).then(() => toast("已複製錯誤內容"), () => toast("這個瀏覽器不能自動複製，請改用「到 GitHub 回報」。")); }
    if (act === "err-clear") { try { localStorage.removeItem(ERR_KEY); } catch { /* 無妨 */ } renderMenu(); }
  });
  $("#menu").addEventListener("change", e => { if (e.target.dataset.set) onSetting(e.target); });
  $("#tabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    S.tab = b.dataset.tab; renderPanel(); if (S.sheet !== "full") sheet("half");
  });
  const body = $("#tab-body");
  body.addEventListener("click", async e => {
    const t = e.target;
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
    if (act === "mode") { S.settings.mode = t.closest("[data-mode]").dataset.mode; saveStore(); refreshBars(); refreshPins(); renderPanel(); return; }
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
    if (act === "watch-seen" && it) {
      it.seen = D.txs.reduce((m, x) => x.date > m ? x.date : m, it.seen || ""); S.watchNews[it.id] = []; saveStore(); renderPanel(); return;
    }
    if (act === "cmp-clear") { S.settings.cmp = []; saveStore(); renderPanel(); return; }
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
    if (ds.loan || ds.cost || ds.rvb) {
      if (ds.loan) S.settings.loan = Object.assign(loanState(), { [ds.loan]: e.target.value });
      if (ds.cost) S.settings.cost = Object.assign(costState(), { [ds.cost]: e.target.value });
      if (ds.rvb) S.settings.rvb = Object.assign(rvbState(), { [ds.rvb]: e.target.value });
      saveStore();
      const med = D.book.best(S.current, S.cat, "t").value, set = (id, f) => { const el = $(id); if (el) el.innerHTML = f(); };
      set("#loan-out", () => loanResult(med)); set("#cost-out", () => costResult(med)); set("#rvb-out", () => rvbResult(S.current, med));
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
  S.roadFilter = null; S.addr = null; S.pin = null; S.bldg = null; S.picked = null; S.pendingAddr = null; S.roadKw = ""; S.bldgKw = "";
  if (S.poi) { S.poi = null; refreshPois(); }
  if (["roads", "bldg", "tx", "detail", "poi"].includes(S.tab)) S.tab = "overview";
}
function enterNation(fly = true) {
  D.county = null;
  L.setCity(D.tw.nation || "全台", "全台");
  D.book = D.twBook; D.rent = D.twRent; D.txs = null; D.txPromise = Promise.resolve();
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
// 各縣市的統計與行政區（比較功能會同時用到好幾個縣市，讀過的留著）
const COUNTY_CACHE = new Map();
function countyData(code) {
  if (!COUNTY_CACHE.has(code)) {
    const base = `data/tw/${code}/`;
    COUNTY_CACHE.set(code, Promise.all([getJSON(base + "book.json"), getJSON(base + "districts.json"), getJSON(base + "rent.json").catch(() => null)])
      .then(([raw, dd, rent]) => ({ raw, dd, rent, book: new L.Book(raw), dmap: Object.fromEntries(dd.districts.map(d => [d.name, d])) }))
      .catch(e => { COUNTY_CACHE.delete(code); throw e; }));
  }
  return COUNTY_CACHE.get(code);
}
async function enterCounty(code, fly = true) {
  const c = D.tw.counties.find(x => x.code === code);
  if (!c) return false;
  if (!c.has_data) { toast(`${c.short}的資料還在準備中（每次自動更新會補上）。`); return false; }
  const base = `data/tw/${code}/`;
  let book, dd, rent;
  try { ({ raw: book, dd, rent } = await countyData(code)); }
  catch (e) { logError(`載入${c.short}資料`, e); toast(`${c.short}的資料載入失敗，請檢查網路後再試。`); return false; }
  D.county = c; D.rent = rent;
  L.setCity(c.short, c.short);
  D.book = new L.Book(book);
  D.districts = dd.districts; D.dmap = Object.fromEntries(D.districts.map(d => [d.name, d]));
  D.meta = { ...D.tw, describe: D.tw.describe, tx_count: c.tx_count || 0, road_districts: c.roads || [] };
  D.txs = null;
  D.txPromise = getJSON(base + "tx.json").then(raw => { if (D.county === c) { D.txs = L.decodeTx(raw); refreshRoads(); checkWatchNews(); renderPanel(); } })
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
async function main() {
  loadStore();
  setTimeout(flushAutoReport, 5000);   // 上次離線時沒送出的錯誤回報
  const params = new URLSearchParams(location.search);
  const tw = params.get("tw") === "0" ? null : await getJSON("data/tw/index.json").catch(() => null);    // ?tw=0：強制台南版（測試用）
  const shared = ["intel", "mrt", "landmarks", "models", "workplaces"];
  const [intel, mrt, landmarks, models, workplaces] = await Promise.all(shared.map(n => getJSON(`data/${n}.json`)));
  Object.assign(D, { intel: intel.items, mrt, landmarks, workplaces });
  if (tw) {
    L.setOrigin(...TW_ORIGIN);
    D.tw = tw;
    const [twBook, twRent] = await Promise.all([getJSON("data/tw/book.json"), getJSON("data/tw/rent.json").catch(() => null)]);
    D.twBook = new L.Book(twBook); D.twRent = twRent;
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
  const lg = $("#legend");
  if (window.innerWidth < 900 || S.settings.legendCollapsed) lg.classList.add("collapsed");
  lg.addEventListener("click", () => { lg.classList.toggle("collapsed"); S.settings.legendCollapsed = lg.classList.contains("collapsed"); saveStore(); renderLegend(); updateReserved(); });
  bindUI(); bindSheetDrag();
  sheet("peek");
  if (tw) {
    const want = (params.get("c") || S.settings.lastCounty || "").toUpperCase();
    enterNation(false); view.reset();
    if (want && !params.get("q")) await enterCounty(want, false);
  } else {
    refreshAll();
    // 逐筆成交比較大（壓縮後約 0.6MB），畫面先出來再載入
    D.txPromise = getJSON("data/tx.json").then(raw => { D.txs = L.decodeTx(raw); refreshRoads(); checkWatchNews(); renderPanel(); })
      .catch(e => { logError("載入成交資料", e); toast("成交資料載入失敗，請檢查網路後重新整理。"); });
  }
  applyShared(params);
  S.ready = true; syncUrl();
  if (params.get("q")) { $("#q").value = params.get("q"); const wait = () => (D.tw || D.txs) ? search(params.get("q")) : setTimeout(wait, 200); wait(); }
  getJSON("data/status.json").then(st => { D.status = st; if (!st.ok) $("#btn-menu").classList.add("has-err"); }).catch(() => {});
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
  window.__app = { S, D, view, search, selectDistrict, pick, L, enterCounty, enterNation, logError, shareUrl };   // 測試用
}
main().catch(err => { logError("啟動", err); document.body.insertAdjacentHTML("beforeend", `<div class="note" style="position:fixed;top:60px;left:10px;right:10px;z-index:99">載入失敗：${esc(err.message)}</div>`); });
