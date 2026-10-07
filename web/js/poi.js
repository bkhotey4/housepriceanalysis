// 周邊生活機能與嫌惡設施（OpenStreetMap／Overpass，在使用者裝置上查詢）（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, S, logError, renderPanel, sheet, view } from "./main.js";

// ------------------------------------------------------------------ 周邊（OpenStreetMap / Overpass，在使用者裝置上查詢；結果暫存在這台裝置）
export const OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"];
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
export async function showPoi(lat, lng, label) {
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
export function refreshPois() {
  const cat = Object.fromEntries(L.POI_CATS.map(c => [c.key, c]));
  view.pois = S.poi && S.poi.res ? S.poi.res.items.map(x => ({ id: x.id + x.cat, lat: x.lat, lng: x.lng, color: cat[x.cat].color, ch: cat[x.cat].ch,
    label: `${x.name}｜${x.d} 公尺`, cat: x.cat, name: x.name, d: x.d })) : [];
  view.rings = view.rings.filter(r => !r.poi);
  if (S.poi) view.rings.push({ lat: S.poi.lat, lng: S.poi.lng, km: 0.5, color: "#1baf7a", poi: true });
  view.request();
}
// ------------------------------------------------------------------ 行情報告（列印／存成 PDF）
