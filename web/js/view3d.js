// 3D 地圖（Canvas 2D）：正交投影＋畫家演算法。
// 手機：單指拖曳平移、雙指捏合縮放＋旋轉、雙指上下滑動調整俯角；點一下選取。
// 滑鼠：左鍵拖曳平移、右鍵（或 Shift）拖曳旋轉、滾輪對著游標縮放。
import { toXY, toLatLng, LAT0, LNG0, KM_LAT, KM_LNG } from "./logic.js";

export const WATERMARK = "全台房價即時動態分析｜bkhotey4.github.io/housepriceanalysis";
const INK = "#1f2328", MUTED = "#5b6168", BG = "#e9edf1";
const MIN_ZOOM = 3, MAX_ZOOM = 2600;
const TILE_URL = "https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}";

export function hex(rgb) { return "#" + rgb.map(c => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join(""); }
export function rgb(h) { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); }
export function shade(h, k) { return hex(rgb(h).map(c => c * k)); }
export function mix(a, b, t) { const A = rgb(a), B = rgb(b); return hex(A.map((c, i) => c + (B[i] - c) * t)); }

function brightness(n) {
  const side = Math.max(0, -n[0] * 0.7071 + n[1] * 0.7071);
  return Math.max(0.7, Math.min(1.0, 0.80 + 0.2 * Math.max(0, n[2]) + 0.14 * side));
}

export class View3D {
  constructor(canvas, opts = {}) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.az = -24; this.pitch = 40; this.zoom = 10; this.tx = -6; this.ty = -3;
    this.autoZoom = true;
    // 「全部」的範圍（公里座標）：台南版是台南市；全台版依目前看的是全台或某縣市改變（setExtent）
    this.extent = { cx: -6, cy: -3, w: 62, wp: 50, h: 45 };
    this.bounds = { x0: -45, x1: 45, y0: -40, y1: 40 };
    this.minZoom = MIN_ZOOM;
    this.tileLayers = null;          // 全台版：{ photo: {tiles, max_z}, town: …, liq: …, fault: {wms} }
    this.inset = { left: 0, bottom: 0, top: 0, right: 0 };    // 被面板蓋住的區域（像素）
    this.bars = []; this.lines = []; this.markers = []; this.models = []; this.roads = []; this.pins = []; this.rings = []; this.pois = [];
    this.layers = {}; this.layerOn = { town: true }; this.layerOpacity = { liq: 0.55, slide: 0.5, fault: 1, town: 1 };
    this.selected = null; this.show = { labels: true, lines: true, markers: true, hires: true };
    this.modelFaces = opts.models || {};
    this.onPick = null; this.onViewChange = null;
    this.hits = [];
    this.tiles = new Map();
    this.sprites = new Map();
    this.anim = null;
    this.pending = false;
    this.fast = false;
    this._fullTimer = null;
    this._bindInput();
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
  }

  // ---------------------------------------------------------------- 尺寸與投影
  resize() {
    const r = this.cv.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    this.dpr = dpr; this.W = r.width; this.H = r.height;
    this.cv.width = Math.round(r.width * dpr); this.cv.height = Math.round(r.height * dpr);
    if (this.autoZoom) this.fitZoom();
    this.redraw(false);
  }
  setInset(inset) { this.inset = Object.assign({ left: 0, bottom: 0, top: 0, right: 0 }, inset); if (this.autoZoom) this.fitZoom(); this.request(); }
  get w2() { return (this.W + this.inset.left - this.inset.right) / 2; }
  get h2() { const top = this.inset.top, bot = this.H - this.inset.bottom; return top + (bot - top) * 0.54; }
  fitZoom() {
    const w = this.W - this.inset.left - this.inset.right, h = this.H - this.inset.top - this.inset.bottom;
    const e = this.extent;
    if (w > 50 && h > 50) this.zoom = Math.max(this.minZoom, Math.min(w / (w < 600 ? e.wp : e.w), h / e.h));
  }
  setExtent(ext, bounds, minZoom) {
    this.extent = Object.assign({}, ext, { wp: ext.wp || ext.w * 50 / 62 });
    if (bounds) this.bounds = bounds;
    if (minZoom) this.minZoom = minZoom;
  }
  setup() {
    const a = this.az * Math.PI / 180, p = this.pitch * Math.PI / 180;
    this.ca = Math.cos(a); this.sa = Math.sin(a); this.cp = Math.cos(p); this.sp = Math.sin(p);
    this.W2 = this.w2; this.H2 = this.h2;
  }
  project(x, y, z = 0) {
    const dx = x - this.tx, dy = y - this.ty;
    const xr = dx * this.ca - dy * this.sa, yr = dx * this.sa + dy * this.ca;
    return [this.W2 + xr * this.zoom, this.H2 - (yr * this.sp + z * this.cp) * this.zoom, yr];
  }
  screenToXY(sx, sy) {
    this.setup();
    const sp = Math.max(1e-3, this.sp), xr = (sx - this.W2) / this.zoom, yr = (this.H2 - sy) / (this.zoom * sp);
    return [this.tx + xr * this.ca + yr * this.sa, this.ty - xr * this.sa + yr * this.ca];
  }
  screenToLatLng(sx, sy) { const [x, y] = this.screenToXY(sx, sy); return toLatLng(x, y); }
  center() { return this.screenToLatLng(this.w2, this.h2); }

  // ---------------------------------------------------------------- 視角操作
  stop() { this.anim = null; this.zoomTarget = null; }
  flyTo(lat, lng, zoom, ms = 450) {
    this.stop();
    const [x, y] = toXY(lat, lng), z1 = zoom ? this.clampZoom(zoom) : this.zoom;
    if (zoom) this.autoZoom = false;
    if (ms <= 0) { this.tx = x; this.ty = y; this.zoom = z1; this.request(); return; }
    this.anim = { t0: performance.now(), ms, from: [this.tx, this.ty, this.zoom], to: [x, y, z1] };
    this._tick();
  }
  flyHome() {
    this.stop();
    const save = this.zoom; this.fitZoom(); const z = this.zoom; this.zoom = save;
    this.anim = { t0: performance.now(), ms: 450, from: [this.tx, this.ty, this.zoom], to: [this.extent.cx, this.extent.cy, z], auto: true };
    this._tick();
  }
  reset() { this.stop(); this.az = -24; this.pitch = 40; this.tx = this.extent.cx; this.ty = this.extent.cy; this.autoZoom = true; this.fitZoom(); this.request(); }
  topView() { this.az = 0; this.pitch = 89; this.request(); }
  rotate(dAz = 0, dPitch = 0) {
    this.az = ((this.az + dAz + 180) % 360 + 360) % 360 - 180;
    this.pitch = Math.max(12, Math.min(89, this.pitch + dPitch));
    this.request(true);
  }
  clampZoom(z) { return Math.max(this.minZoom, Math.min(MAX_ZOOM, z)); }
  zoomAt(factor, sx, sy) {
    this.autoZoom = false; this.stop();
    const z = this.clampZoom(this.zoom * factor);
    if (sx != null) {
      const [x0, y0] = this.screenToXY(sx, sy);
      this.zoom = z;
      const [x1, y1] = this.screenToXY(sx, sy);
      this.tx += x0 - x1; this.ty += y0 - y1;
    } else this.zoom = z;
    this.clampCenter();
    this.request(true);
  }
  clampCenter() { const b = this.bounds; this.tx = Math.max(b.x0, Math.min(b.x1, this.tx)); this.ty = Math.max(b.y0, Math.min(b.y1, this.ty)); }
  _tick() {
    const a = this.anim;
    if (!a) return;
    const k = Math.min(1, (performance.now() - a.t0) / a.ms), e = 1 - (1 - k) ** 3;
    this.tx = a.from[0] + (a.to[0] - a.from[0]) * e;
    this.ty = a.from[1] + (a.to[1] - a.from[1]) * e;
    this.zoom = a.from[2] * (a.to[2] / a.from[2]) ** e;
    if (k >= 1) { this.anim = null; if (a.auto) this.autoZoom = true; this.request(); this.onViewChange && this.onViewChange(); return; }
    this.request(true);
    requestAnimationFrame(() => this._tick());
  }

  // ---------------------------------------------------------------- 重畫排程：互動中畫簡化版，停下來 150ms 後畫完整版
  request(fast = false) {
    if (fast) {
      this.fast = true;
      clearTimeout(this._fullTimer);
      this._fullTimer = setTimeout(() => { if (this.anim || this.drag) { this.request(true); return; } this.fast = false; this.request(); }, 160);
    }
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => { this.pending = false; this.redraw(this.fast); });
  }

  // ---------------------------------------------------------------- 底圖
  setLayer(id, meta, base) {
    const files = meta.files;
    const img = new Image();
    img.decoding = "async";
    img.onload = () => this.request();
    img.src = base + files[0].file;
    this.layers[id] = { meta, img, hi: null, files, base };
  }
  _layerImage(L) {
    // 放大到一定程度才載入高解析版本（手機省流量）
    if (L.files.length > 1 && this.zoom > 90 && !L.hi) {
      L.hi = new Image(); L.hi.decoding = "async"; L.hi.onload = () => this.request(); L.hi.src = L.base + L.files[1].file;
    }
    return L.hi && L.hi.complete && L.hi.naturalWidth ? L.hi : L.img;
  }
  _drawImageGeo(img, west, east, north, south, alpha = 1) {
    if (!img.complete || !img.naturalWidth) return false;
    const c = this.ctx, iw = img.naturalWidth, ih = img.naturalHeight;
    const ax = (east - west) / iw * KM_LNG, bx = (west - LNG0) * KM_LNG;
    const ay = -(north - south) / ih * KM_LAT, by = (north - LAT0) * KM_LAT;
    const z = this.zoom, ca = this.ca, sa = this.sa, sp = this.sp, d = this.dpr;
    const A = z * ca * ax, C = -z * sa * ay, E = this.W2 + z * ((bx - this.tx) * ca - (by - this.ty) * sa);
    const B = -z * sp * sa * ax, D = -z * sp * ca * ay, F = this.H2 - z * sp * ((bx - this.tx) * sa + (by - this.ty) * ca);
    c.save();
    c.globalAlpha = alpha;
    c.setTransform(A * d, B * d, C * d, D * d, E * d, F * d);
    c.drawImage(img, 0, 0);
    c.restore();
    return true;
  }
  _drawTiles(id = "photo", load = true) {
    // 國土測繪中心 WMTS 圖磚。台南版只在放大後補高解析衛星圖；全台版所有底圖、圖層都用圖磚
    const cfg = this.tileLayers ? this.tileLayers[id] : (id === "photo" ? { tiles: TILE_URL, max_z: 18 } : null);
    if (!cfg) return;
    if (!this.tileLayers && (!this.show.hires || this.zoom < 70)) return;
    const ideal = Math.round(Math.log2(this.zoom * this.dpr * 40075 * Math.cos(LAT0 * Math.PI / 180) / 256 / 1.15));
    let z = Math.max(this.tileLayers ? 6 : 14, Math.min(cfg.max_z || 18, ideal));
    const lat2y = (lat, n) => (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * n;
    const y2lat = (y, n) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
    const corners = [[0, this.inset.top], [this.W, this.inset.top], [this.W, this.H], [0, this.H]].map(([x, y]) => this.screenToLatLng(x, y));
    const lats = corners.map(c => Math.max(-80, Math.min(80, c[0]))), lngs = corners.map(c => c[1]);
    let n, x0, x1, y0, y1;
    for (;;) {
      n = 2 ** z;
      x0 = Math.floor((Math.min(...lngs) + 180) / 360 * n); x1 = Math.floor((Math.max(...lngs) + 180) / 360 * n);
      y0 = Math.floor(lat2y(Math.max(...lats), n)); y1 = Math.floor(lat2y(Math.min(...lats), n));
      if ((x1 - x0 + 1) * (y1 - y0 + 1) <= 90) break;
      if (!this.tileLayers || z <= 5) return;          // 太多張（俯角太低看得很遠）就少抓一點
      z--;
    }
    const alpha = id === "photo" ? 1 : (this.layerOpacity[id] ?? cfg.opacity ?? 1), drawnParents = new Set();
    const ready = t => t && t.complete && t.naturalWidth;
    const list = [];
    for (let ty = y0; ty <= y1; ty++) for (let tx = x0; tx <= x1; tx++) {
      const key = `${id}/${z}/${ty}/${tx}`;
      let t = this.tiles.get(key);
      if (!t && load) {
        const w = tx / n * 360 - 180, e = (tx + 1) / n * 360 - 180, no = y2lat(ty, n), so = y2lat(ty + 1, n);
        t = new Image(); t.decoding = "async"; t.onload = () => this.request(); t.onerror = () => { t.failed = true; };
        t.src = cfg.wms ? cfg.wms.replace("{w}", w).replace("{e}", e).replace("{n}", no).replace("{s}", so)
          : (cfg.tiles || TILE_URL).replace("{z}", z).replace("{y}", ty).replace("{x}", tx);
        this.tiles.set(key, t);
        if (this.tiles.size > 600) this.tiles.delete(this.tiles.keys().next().value);
      }
      list.push([tx, ty, t]);
    }
    // 先畫還沒到的那幾張的上一層（較模糊）頂著，再畫已經到的，畫面不會一片空白
    if (this.tileLayers) for (const [tx, ty, t] of list) {
      if (ready(t)) continue;
      for (let k = 1; k <= 4; k++) {
        const pk = `${id}/${z - k}/${ty >> k}/${tx >> k}`, pt = this.tiles.get(pk);
        if (!ready(pt)) continue;
        if (!drawnParents.has(pk)) {
          drawnParents.add(pk);
          const pn = 2 ** (z - k), px = tx >> k, py = ty >> k;
          this._drawImageGeo(pt, px / pn * 360 - 180, (px + 1) / pn * 360 - 180, y2lat(py, pn), y2lat(py + 1, pn), alpha);
        }
        break;
      }
    }
    for (const [tx, ty, t] of list) {
      if (!ready(t) || t.failed) continue;
      this._drawImageGeo(t, tx / n * 360 - 180, (tx + 1) / n * 360 - 180, y2lat(ty, n), y2lat(ty + 1, n), alpha);
    }
  }

  // ---------------------------------------------------------------- 繪製
  redraw(fast) {
    const c = this.ctx, d = this.dpr, W = this.W, H = this.H;
    if (!W || !H) return;
    this.setup();
    c.setTransform(d, 0, 0, d, 0, 0);
    c.fillStyle = BG; c.fillRect(0, 0, W, H);
    this.hits = [];
    const base = this.layers.photo;
    if (base) this._drawImageGeo(this._layerImage(base), base.meta.west, base.meta.east, base.meta.north, base.meta.south);
    if (this.tileLayers) {
      this._drawTiles("photo", !fast);
      for (const id of ["slide", "liq", "fault", "town"]) if (this.layerOn[id]) this._drawTiles(id, !fast);
    } else if (!fast) this._drawTiles();
    for (const id of ["liq", "fault", "town"]) {
      const L = this.layers[id];
      if (L && this.layerOn[id]) this._drawImageGeo(L.img, L.meta.west, L.meta.east, L.meta.north, L.meta.south, this.layerOpacity[id] ?? 1);
    }
    c.setTransform(d, 0, 0, d, 0, 0);
    this._drawRings();
    if (this.show.lines) this._drawLines(fast);
    this._drawRoads(fast);
    const labels = this._drawObjects(fast);
    if (this.show.labels && !fast) this._drawLabels(labels.concat(this._roadLabels || [], this._stationLabels || []));
    else this._drawLabels(labels.filter(l => l.prio === 2).concat((this._roadLabels || []).filter(l => l.prio === 2)));
    this._drawCompass();
    this._drawWatermark();
  }
  _onScreen(sx, sy, m = 40) { return sx > -m && sx < this.W + m && sy > -m && sy < this.H + m; }

  _drawRings() {
    const c = this.ctx;
    for (const r of this.rings) {
      const [cx, cy] = toXY(r.lat, r.lng);
      c.beginPath();
      for (let k = 0; k <= 72; k++) {
        const a = k * 5 * Math.PI / 180, [sx, sy] = this.project(cx + r.km * Math.cos(a), cy + r.km * Math.sin(a));
        k ? c.lineTo(sx, sy) : c.moveTo(sx, sy);
      }
      c.lineWidth = 4; c.strokeStyle = "#ffffff"; c.setLineDash([]); c.stroke();
      c.lineWidth = 2; c.strokeStyle = r.color || INK; c.setLineDash([7, 5]); c.stroke(); c.setLineDash([]);
    }
  }

  _drawLines(fast) {
    const c = this.ctx;
    this._stationLabels = [];
    for (const ln of this.lines) {
      const sel = this.selected && this.selected[0] === "line" && this.selected[1] === ln.name;
      for (const seg of ln.segments) {
        c.beginPath();
        for (let i = 0; i < seg.length; i += 2) {
          const [x, y] = toXY(seg[i], seg[i + 1]), [sx, sy] = this.project(x, y, 0.02);
          i ? c.lineTo(sx, sy) : c.moveTo(sx, sy);
        }
        c.lineCap = "round"; c.lineJoin = "round";
        const rail = ln.kind === "台鐵";            // 台鐵畫細一點，壓在捷運底下
        c.setLineDash([]); c.lineWidth = sel ? 7 : rail ? 3.5 : 5; c.strokeStyle = "#ffffff"; c.stroke();
        c.setLineDash(ln.approved ? [] : [8, 6]); c.lineWidth = sel ? 4.5 : rail ? 2 : 3; c.strokeStyle = ln.color; c.stroke();
        c.setLineDash([]);
      }
      if (fast || this.zoom < 14) continue;
      const r = this.zoom < 40 ? 3 : 5;
      for (const [name, lat, lng] of ln.stations) {
        const [x, y] = toXY(lat, lng), [sx, sy, dp] = this.project(x, y, 0.05);
        if (!this._onScreen(sx, sy)) continue;
        c.beginPath(); c.arc(sx, sy, r, 0, 7); c.fillStyle = "#fff"; c.fill(); c.lineWidth = 2; c.strokeStyle = ln.color; c.stroke();
        this.hits.push({ kind: "station", id: [ln.name, name], x0: sx - 9, y0: sy - 9, x1: sx + 9, y1: sy + 9, depth: dp });
        if (this.zoom >= 48) this._stationLabels.push({ prio: -2, n: 0, kind: "station", text: name.split("（")[0].slice(0, 14), x: sx, y: sy - r - 2, small: true });
      }
    }
  }

  setRoads(roads) {
    // roads: [{id, color, segments:[flat...], lanes:[flat...], point:[lat,lng], dot, label, n}]
    const conv = flat => { const o = []; for (let i = 0; i < flat.length; i += 2) o.push(toXY(flat[i], flat[i + 1])); return o; };
    for (const r of roads) { r._segs = r.segments.map(conv); r._lanes = (r.lanes || []).map(conv); r._pt = toXY(r.point[0], r.point[1]); }
    this.roads = roads.sort((a, b) => (b.n || 0) - (a.n || 0));
    this.request();
  }
  _drawRoads(fast) {
    const c = this.ctx, z = this.zoom;
    this._roadLabels = [];
    if (!this.roads.length) return;
    const baseW = z < 12 ? 2 : z < 40 ? 3 : 5, showLanes = z >= 45 && !fast;
    const list = fast ? this.roads.slice(0, 120) : this.roads;
    c.lineCap = "round"; c.lineJoin = "round";
    for (const r of list) {
      const sel = this.selected && this.selected[0] === "road" && this.selected[1] === r.id;
      const width = baseW + (sel ? 2 : 0);
      const all = r._segs.map(s => [s, false]).concat(showLanes || (sel && !fast) ? r._lanes.map(s => [s, true]) : []);
      for (const [seg, lane] of all) {
        const pts = seg.map(([x, y]) => this.project(x, y, 0.01));
        const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
        if (Math.max(...xs) < -20 || Math.min(...xs) > this.W + 20 || Math.max(...ys) < -20 || Math.min(...ys) > this.H + 20) continue;
        c.beginPath(); pts.forEach(([sx, sy], i) => i ? c.lineTo(sx, sy) : c.moveTo(sx, sy));
        const lw = lane ? Math.max(2, width - 2) : width;
        if (!fast && !lane) { c.lineWidth = lw + 2; c.strokeStyle = sel ? INK : "#ffffff"; c.stroke(); }
        c.lineWidth = lw; c.strokeStyle = r.color; c.stroke();
        if (!fast) this.hits.push({ kind: "road", id: r.id, poly: pts, tol: 10, depth: -800 + pts[0][2] });
      }
      const [sx, sy, dp] = this.project(r._pt[0], r._pt[1], 0.01);
      if (!this._onScreen(sx, sy, 20)) continue;
      let ay = sy - baseW - 3;
      if (r.dot) {
        const rad = (z < 30 ? 6 : 9) + (sel ? 2 : 0);
        c.beginPath(); c.arc(sx, sy, rad, 0, 7); c.fillStyle = r.color; c.fill();
        c.lineWidth = 2; c.strokeStyle = sel ? INK : "#fff"; c.stroke();
        this.hits.push({ kind: "road", id: r.id, x0: sx - rad - 4, y0: sy - rad - 4, x1: sx + rad + 4, y1: sy + rad + 4, depth: dp - 800 });
        ay = sy - rad - 2;
      }
      if (sel || z >= 22) this._roadLabels.push({ prio: sel ? 2 : -1, n: 5 + (r.n || 0), kind: "road", text: r.label, x: sx, y: ay });
    }
  }

  // ---- 房價柱、標記、立體圖案、圖釘（依深度由遠到近）
  _barPolys(b) {
    const [x, y] = toXY(b.lat, b.lng), z = this.zoom;
    const hw = Math.max(6, Math.min(11, 0.62 * z)) / z, hmax = Math.max(80, Math.min(135, 6.5 * z)) / z;
    const dim = b.dim && !(this.selected && this.selected[0] === "district" && this.selected[1] === b.id);
    const hk = b.value != null && !dim ? Math.max(0.02 * hmax, (b.frac || 0) * hmax) : 0.02 * hmax;
    const cs = [[x - hw, y - hw], [x + hw, y - hw], [x + hw, y + hw], [x - hw, y + hw]];
    const bot = cs.map(([cx, cy]) => this.project(cx, cy, 0)), top = cs.map(([cx, cy]) => this.project(cx, cy, hk));
    const faces = [];
    const shades = [0.70, 0.84, 0.70, 0.84];
    for (let k = 0; k < 4; k++) {
      const k2 = (k + 1) % 4;
      faces.push({ depth: (bot[k][2] + bot[k2][2]) / 2, pts: [bot[k], bot[k2], top[k2], top[k]], k: shades[k] });
    }
    faces.sort((a, b) => b.depth - a.depth);
    const all = bot.concat(top), xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const [cx, , dp] = this.project(x, y, hk);
    return { faces, top, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], anchor: [cx, Math.min(...ys)], depth: dp, dim };
  }
  _sprite(m, sel) {
    // 立體圖案先畫在小畫布上（快取），每一格只要貼圖
    const sizePx = Math.max(42, Math.min(88, 36 + this.zoom * 0.35)) * (m.size || 1);
    const sizeQ = Math.round(sizePx / 4) * 4, azQ = Math.round(this.az / 2) * 2, pQ = Math.round(this.pitch / 2) * 2;
    const key = [m.model, m.state || "", sizeQ, azQ, pQ, sel ? 1 : 0].join("|");
    let sp = this.sprites.get(key);
    if (sp) return sp;
    const faces = this.facesFor(m);
    const a = azQ * Math.PI / 180, p = pQ * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a), cp = Math.cos(p), spp = Math.sin(p);
    const cam = [-sa * cp, -ca * cp, spp], unit = sizeQ / 2.2;
    const polys = [];
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const [pts, color, n] of faces) {
      if (n[0] * cam[0] + n[1] * cam[1] + n[2] * cam[2] <= 0.02) continue;
      const poly = []; let depth = 0;
      for (let i = 0; i < pts.length; i += 3) {
        const px = pts[i], py = pts[i + 1], pz = pts[i + 2];
        const u = (px * ca - py * sa) * unit, v = -((px * sa + py * ca) * spp + pz * cp) * unit;
        poly.push(u, v); depth += (px * sa + py * ca) * cp - pz * spp;
        x0 = Math.min(x0, u); y0 = Math.min(y0, v); x1 = Math.max(x1, u); y1 = Math.max(y1, v);
      }
      let ground = n[2] > 0.99;                          // 貼地的面（湖面、草地、海面）一律最先畫
      for (let i = 2; i < pts.length && ground; i += 3) if (pts[i] > 0.06) ground = false;
      polys.push({ depth: ground ? 1e9 : depth / (pts.length / 3), poly, fill: shade(color, brightness(n)), edge: shade(color, 0.72) });
    }
    if (!polys.length) return null;
    polys.sort((A, B) => B.depth - A.depth);
    const pad = 2, d = this.dpr, cw = Math.ceil(x1 - x0) + pad * 2, ch = Math.ceil(y1 - y0) + pad * 2;
    const cv = document.createElement("canvas");
    cv.width = Math.ceil(cw * d); cv.height = Math.ceil(ch * d);
    const g = cv.getContext("2d");
    g.setTransform(d, 0, 0, d, (pad - x0) * d, (pad - y0) * d);
    g.lineJoin = "round";
    for (const f of polys) {
      g.beginPath();
      for (let i = 0; i < f.poly.length; i += 2) i ? g.lineTo(f.poly[i], f.poly[i + 1]) : g.moveTo(f.poly[i], f.poly[i + 1]);
      g.closePath(); g.fillStyle = f.fill; g.fill();
      g.lineWidth = sel ? 1.6 : 0.8; g.strokeStyle = sel ? INK : f.edge; g.stroke();
    }
    sp = { cv, dx: x0 - pad, dy: y0 - pad, w: cw, h: ch, box: [x0, y0, x1, y1] };
    if (this.sprites.size > 600) this.sprites.clear();
    this.sprites.set(key, sp);
    return sp;
  }
  facesFor(m) {
    const base = this.modelFaces[m.model] || this.modelFaces.museum || [];
    if (!m.state || m.state === "完工") return base;
    const k = m.state === "規劃中" ? 0.58 : 0.18;
    const out = base.map(([p, c, n]) => [p, mix(c, "#ffffff", k), n]);
    if (m.state === "施工中" && this.modelFaces.crane) {
      for (const [p, c, n] of this.modelFaces.crane) {
        const q = [];
        for (let i = 0; i < p.length; i += 3) q.push(p[i] + 0.85, p[i + 1] + 0.55, p[i + 2] * 0.82);
        out.push([q, c, n]);
      }
    }
    return out;
  }
  _drawObjects(fast) {
    const c = this.ctx, items = [], labels = [], z = this.zoom;
    for (const b of this.bars) {
      const g = this._barPolys(b);
      if (g.box[2] < -30 || g.box[0] > this.W + 30 || g.box[3] < -30 || g.box[1] > this.H + 30) continue;
      items.push({ depth: g.depth, kind: 0, o: b, g });
    }
    const near = z >= 4;            // 全台縮小時不畫地標與建設圖案（太擠）
    if (this.show.markers && near) for (const m of this.markers) {
      const [x, y] = toXY(m.lat, m.lng), [sx, sy, dp] = this.project(x, y);
      if (this._onScreen(sx, sy)) items.push({ depth: dp, kind: 1, o: m, g: [sx, sy] });
    }
    if (this.models.length && near) {
      const placed = [], k = z < 40 ? 0.8 : z >= 150 ? 0.42 : 0.8 - (z - 40) / 110 * 0.38;
      const gap = Math.max(42, Math.min(88, 36 + z * 0.35)) * k;
      const order = [...this.models].sort((A, B) => {
        const sa = this.selected && this.selected[0] === A.hit && this.selected[1] === A.id ? 0 : 1;
        const sb = this.selected && this.selected[0] === B.hit && this.selected[1] === B.id ? 0 : 1;
        return sa - sb || (A.rank || 3) - (B.rank || 3);
      });
      for (const m of order) {
        const [x, y] = toXY(m.lat, m.lng), [sx, sy, dp] = this.project(x, y);
        if (sx < -60 || sx > this.W + 60 || sy < -40 || sy > this.H + 90) continue;
        if (placed.some(([px, py]) => (sx - px) ** 2 + (sy - py) ** 2 < gap * gap)) continue;
        placed.push([sx, sy]);
        items.push({ depth: dp, kind: 3, o: m, g: [sx, sy] });
      }
    }
    for (const p of this.pois) {
      const [x, y] = toXY(p.lat, p.lng), [sx, sy, dp] = this.project(x, y);
      if (this._onScreen(sx, sy)) items.push({ depth: dp, kind: 4, o: p, g: [sx, sy] });
    }
    for (const p of this.pins) {
      const [x, y] = toXY(p.lat, p.lng), [sx, sy, dp] = this.project(x, y);
      if (this._onScreen(sx, sy, 60)) items.push({ depth: p.kind === "search" ? -1e9 : dp, kind: 2, o: p, g: [sx, sy] });
    }
    // 地標與建設圖案畫在房價柱之後（不會被柱子擋住，市區地標才看得到），圖釘永遠在最上層
    const layer = it => it.kind === 2 ? 2 : it.kind === 3 ? 1 : 0;
    items.sort((A, B) => layer(A) - layer(B) || B.depth - A.depth);
    for (const it of items) {
      const o = it.o;
      if (it.kind === 0) {
        const { faces, top, box, anchor, dim } = it.g;
        const sel = this.selected && this.selected[0] === "district" && this.selected[1] === o.id;
        const color = dim ? "#d5d8dc" : o.color, edge = sel ? INK : dim ? "#8d949c" : shade(color, 0.55);
        c.lineWidth = 1;
        for (const f of faces.slice(2)) {
          c.beginPath(); f.pts.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])); c.closePath();
          c.fillStyle = shade(color, f.k); c.fill(); c.strokeStyle = edge; c.stroke();
        }
        c.beginPath(); top.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])); c.closePath();
        c.fillStyle = color; c.fill(); c.lineWidth = sel ? 2 : 1; c.strokeStyle = edge; c.stroke();
        this.hits.push({ kind: "district", id: o.id, x0: box[0] - 6, y0: box[1] - 6, x1: box[2] + 6, y1: box[3] + 6, depth: it.depth });
        if (!dim) labels.push({ prio: sel ? 2 : 0, n: o.n || 0, kind: "district", id: o.id, text: o.label, x: anchor[0], y: anchor[1] - 3, bold: true });
      } else if (it.kind === 1) {
        const [sx, sy] = it.g, sel = this.selected && this.selected[0] === "marker" && this.selected[1] === o.id;
        const lvl = o.level || 3, stem = 14 + 3 * lvl, r = 4 + lvl * 0.8 + (sel ? 2 : 0), ty = sy - stem;
        c.beginPath(); c.moveTo(sx, sy); c.lineTo(sx, ty); c.lineWidth = 1; c.strokeStyle = MUTED; c.stroke();
        c.beginPath(); c.moveTo(sx, ty - r); c.lineTo(sx + r, ty); c.lineTo(sx, ty + r); c.lineTo(sx - r, ty); c.closePath();
        c.fillStyle = o.color; c.fill(); c.lineWidth = sel ? 2 : 1; c.strokeStyle = sel ? INK : "#fff"; c.stroke();
        this.hits.push({ kind: "marker", id: o.id, x0: sx - r - 8, y0: ty - r - 8, x1: sx + r + 8, y1: ty + r + 8, depth: it.depth - 1000 });
        if (sel || (!fast && (lvl >= 5 || z >= 30))) labels.push({ prio: sel ? 2 : -1, n: lvl, kind: "marker", id: o.id, text: o.label, x: sx, y: ty - r - 2, small: true });
      } else if (it.kind === 3) {
        const [sx, sy] = it.g, hk = o.hit || "landmark", sel = this.selected && this.selected[0] === hk && this.selected[1] === o.id;
        const sp = this._sprite(o, sel);
        if (!sp) continue;
        c.drawImage(sp.cv, Math.round(sx + sp.dx), Math.round(sy + sp.dy), sp.w, sp.h);
        const box = [sx + sp.box[0], sy + sp.box[1], sx + sp.box[2], sy + sp.box[3]];
        this.hits.push({ kind: hk, id: o.id, x0: box[0] - 2, y0: box[1] - 2, x1: box[2] + 2, y1: box[3] + 2, depth: it.depth + 500 });
        if (sel || (!fast && z >= (hk === "project" ? 22 : 26)))
          labels.push({ prio: sel ? 2 : -1, n: 30 - (o.rank || 3), kind: hk, id: o.id, text: o.label, x: (box[0] + box[2]) / 2, y: box[1] - 2, small: true });
      } else if (it.kind === 4) {
        const [sx, sy] = it.g, sel = this.selected && this.selected[0] === "poi" && this.selected[1] === o.id, r = sel ? 10 : 8;
        c.beginPath(); c.arc(sx, sy - r, r, 0, 7); c.fillStyle = o.color; c.fill(); c.lineWidth = sel ? 2.5 : 1.5; c.strokeStyle = sel ? INK : "#fff"; c.stroke();
        c.fillStyle = "#fff"; c.font = `bold ${r + 2}px system-ui, sans-serif`; c.textAlign = "center"; c.textBaseline = "middle";
        c.fillText(o.ch, sx, sy - r + 0.5);
        this.hits.push({ kind: "poi", id: o.id, x0: sx - r - 4, y0: sy - 2 * r - 4, x1: sx + r + 4, y1: sy + 4, depth: it.depth - 1200 });
        if (sel) labels.push({ prio: 2, n: 99, kind: "poi", id: o.id, text: o.label, x: sx, y: sy - 2 * r - 2, small: true });
      } else {
        const [sx, sy] = it.g, big = o.kind === "search";
        const sel = this.selected && this.selected[0] === "pin" && this.selected[1] === o.id;
        const r = big ? 11 : sel ? 8 : 7, ty = sy - (big ? 34 : 22);
        if (big) { c.beginPath(); c.ellipse(sx, sy, 6, 3, 0, 0, 7); c.fillStyle = shade(o.color, 0.6); c.fill(); }
        c.beginPath(); c.moveTo(sx, sy); c.lineTo(sx, ty); c.lineWidth = big ? 3 : 2; c.strokeStyle = INK; c.stroke();
        c.beginPath(); c.arc(sx, ty, r, 0, 7); c.fillStyle = o.color; c.fill(); c.lineWidth = 2; c.strokeStyle = "#fff"; c.stroke();
        c.beginPath();
        if (o.kind === "work") c.rect(sx - 3, ty - 3, 6, 6); else c.arc(sx, ty, big ? 4 : 2.5, 0, 7);
        c.fillStyle = "#fff"; c.fill();
        this.hits.push({ kind: "pin", id: o.id, x0: sx - r - 8, y0: ty - r - 8, x1: sx + r + 8, y1: ty + r + 8, depth: it.depth - 1500 });
        labels.push({ prio: big ? 2 : 1, n: 99, kind: "pin", id: o.id, text: o.label, x: sx, y: ty - r - 2, small: !big });
      }
    }
    return labels;
  }
  _drawLabels(labels) {
    const c = this.ctx;
    labels.sort((a, b) => b.prio - a.prio || b.n - a.n);
    const placed = [], lh = 18;
    const reserved = [[this.W - 60, 0, this.W, 60]].concat(this.reserved || []);
    for (const L of labels) {
      if (!L.text) continue;
      const font = `${L.bold ? 600 : 400} ${L.small ? 12 : 13}px system-ui, "Noto Sans TC", "Microsoft JhengHei", sans-serif`;
      c.font = font;
      const tw = c.measureText(L.text).width;
      if (L.x < -20 || L.x > this.W + 20 || L.y < 0 || L.y > this.H + lh) continue;
      const x = Math.min(Math.max(L.x, tw / 2 + 6), this.W - tw / 2 - 6);
      const box = [x - tw / 2 - 4, L.y - lh, x + tw / 2 + 4, L.y];
      if (L.prio < 2 && reserved.some(([a, b, cc, dd]) => !(box[2] < a || box[0] > cc || box[3] < b || box[1] > dd))) continue;
      if (L.prio < 1 && placed.some(([a, b, cc, dd]) => !(box[2] < a || box[0] > cc || box[3] < b || box[1] > dd))) continue;
      placed.push(box);
      const sel = L.prio === 2;
      c.fillStyle = sel ? INK : L.kind === "station" ? "rgba(255,255,255,0.85)" : "#fff";
      c.beginPath(); c.roundRect ? c.roundRect(box[0], box[1], box[2] - box[0], lh, 3) : c.rect(box[0], box[1], box[2] - box[0], lh);
      c.fill();
      if (!sel && L.kind !== "station") { c.lineWidth = 1; c.strokeStyle = "#c9ced4"; c.stroke(); }
      c.fillStyle = sel ? "#fff" : L.kind === "station" ? MUTED : INK;
      c.textAlign = "center"; c.textBaseline = "alphabetic";
      c.fillText(L.text, x, L.y - 4.5);
      if (L.id != null && L.kind !== "station") this.hits.push({ kind: L.kind, id: L.id, x0: box[0], y0: box[1], x1: box[2], y1: box[3], depth: -2000 });
    }
  }
  _drawWatermark() {
    // 版權浮水印：畫在地圖畫布上，截圖也會帶著
    const c = this.ctx, small = this.W < 600, x = this.W - 10 - this.inset.right, y = this.H - this.inset.bottom - (small ? 44 : 8);   // 手機上左下的資料來源標示有兩行，浮水印排在它上面
    c.font = `600 ${small ? 10 : 12}px system-ui, sans-serif`; c.textAlign = "right"; c.textBaseline = "bottom";
    c.lineWidth = 3; c.strokeStyle = "rgba(255,255,255,0.75)"; c.strokeText(WATERMARK, x, y);
    c.fillStyle = "rgba(20,60,56,0.62)"; c.fillText(WATERMARK, x, y);
  }
  _drawCompass() {
    const c = this.ctx, cx = this.W - 30 - this.inset.right, cy = this.inset.top + 30, r = 18;
    c.beginPath(); c.arc(cx, cy, r, 0, 7); c.fillStyle = "rgba(255,255,255,0.92)"; c.fill();
    c.lineWidth = 1; c.strokeStyle = "#c9ced4"; c.stroke();
    let nx = -this.sa, ny = -this.ca * this.sp; const ln = Math.hypot(nx, ny) || 1; nx /= ln; ny /= ln;
    c.beginPath(); c.moveTo(cx - nx * (r - 7), cy - ny * (r - 7)); c.lineTo(cx + nx * (r - 5), cy + ny * (r - 5));
    c.lineWidth = 3; c.strokeStyle = "#c0392b"; c.stroke();
    c.font = "600 11px system-ui, sans-serif"; c.fillStyle = "#c0392b"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText("北", cx + nx * (r + 8), cy + ny * (r + 8));
    this.compassBox = [cx - r, cy - r, cx + r, cy + r];
  }

  // ---------------------------------------------------------------- 點選
  pick(x, y) {
    let best = null;
    for (const h of this.hits) {
      let ok;
      if (h.poly) {
        ok = false;
        for (let i = 0; i < h.poly.length - 1 && !ok; i++) {
          const [x0, y0] = h.poly[i], [x1, y1] = h.poly[i + 1], dx = x1 - x0, dy = y1 - y0, s2 = dx * dx + dy * dy;
          const t = s2 ? Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / s2)) : 0;
          ok = Math.hypot(x - x0 - dx * t, y - y0 - dy * t) <= h.tol;
        }
      } else ok = x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1;
      if (ok && (!best || h.depth < best.depth)) best = h;
    }
    return best ? [best.kind, best.id] : null;
  }
  select(kind, id) { this.selected = kind ? [kind, id] : null; this.request(); }

  // ---------------------------------------------------------------- 觸控與滑鼠
  _bindInput() {
    const cv = this.cv, ptrs = new Map();
    let gesture = null, moved = false, downAt = null;
    cv.style.touchAction = "none";
    cv.addEventListener("contextmenu", e => e.preventDefault());
    cv.addEventListener("pointerdown", e => {
      cv.setPointerCapture(e.pointerId);
      ptrs.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      this.stop();
      if (ptrs.size === 1) {
        moved = false; downAt = { x: e.offsetX, y: e.offsetY, t: performance.now() };
        gesture = { mode: (e.button === 2 || e.shiftKey) ? "rotate" : "pan", x: e.offsetX, y: e.offsetY };
      } else if (ptrs.size === 2) {
        const [a, b] = [...ptrs.values()];
        gesture = { mode: "pinch", d: Math.hypot(a.x - b.x, a.y - b.y), ang: Math.atan2(b.y - a.y, b.x - a.x),
                    cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
        moved = true;
      }
      this.drag = true;
    });
    cv.addEventListener("pointermove", e => {
      if (!ptrs.has(e.pointerId)) {
        if (e.pointerType === "mouse" && !this.drag) {
          const hit = this.pick(e.offsetX, e.offsetY);
          cv.style.cursor = hit ? "pointer" : "default";
          this.onHover && this.onHover(hit, e);
        }
        return;
      }
      ptrs.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      if (!gesture) return;
      if (gesture.mode === "pinch" && ptrs.size >= 2) {
        const [a, b] = [...ptrs.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y), ang = Math.atan2(b.y - a.y, b.x - a.x);
        const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
        if (gesture.d > 10 && d > 10) this.zoomAt(d / gesture.d, cx, cy);
        let dAng = (ang - gesture.ang) * 180 / Math.PI;
        if (dAng > 180) dAng -= 360; if (dAng < -180) dAng += 360;
        const dy = cy - gesture.cy;
        // 兩指一起上下滑：調整俯角；兩指轉動：旋轉
        if (Math.abs(d - gesture.d) < 6 && Math.abs(dy) > 2) this.rotate(0, -dy * 0.3);
        else this.rotate(-dAng, 0);
        this._panBy(cx - gesture.cx, Math.abs(d - gesture.d) < 6 ? 0 : cy - gesture.cy);
        Object.assign(gesture, { d, ang, cx, cy });
        this.autoZoom = false;
        this.request(true);
        return;
      }
      const dx = e.offsetX - gesture.x, dy = e.offsetY - gesture.y;
      if (!moved && Math.abs(e.offsetX - downAt.x) + Math.abs(e.offsetY - downAt.y) < 7) return;
      moved = true;
      gesture.x = e.offsetX; gesture.y = e.offsetY;
      if (gesture.mode === "rotate") this.rotate(dx * 0.35, dy * 0.3);
      else { this._panBy(dx, dy); this.request(true); }
    });
    const end = e => {
      if (!ptrs.has(e.pointerId)) return;
      ptrs.delete(e.pointerId);
      if (ptrs.size === 1 && gesture && gesture.mode === "pinch") {
        const [p] = [...ptrs.values()]; gesture = { mode: "pan", x: p.x, y: p.y }; return;
      }
      if (ptrs.size) return;
      this.drag = false;
      const tap = !moved && downAt && performance.now() - downAt.t < 600;
      gesture = null;
      if (tap) {
        const cb = this.compassBox;
        if (cb && e.offsetX >= cb[0] && e.offsetX <= cb[2] && e.offsetY >= cb[1] && e.offsetY <= cb[3]) { this.az = 0; this.request(); return; }
        const hit = this.pick(e.offsetX, e.offsetY);
        this.onPick && this.onPick(hit, this.screenToLatLng(e.offsetX, e.offsetY));
      } else {
        this.request(true);
        this.onViewChange && this.onViewChange();
      }
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("pointerleave", () => {
      cv.style.cursor = "default";
      if (this.onHover) this.onHover(null);
    });
    cv.addEventListener("wheel", e => {
      e.preventDefault();
      const k = Math.max(-3, Math.min(3, -e.deltaY / (e.deltaMode === 1 ? 3 : 100)));
      this.zoomAt(1.2 ** k, e.offsetX, e.offsetY);
    }, { passive: false });
  }
  _panBy(dx, dy) {
    const xr = -dx / this.zoom, yr = dy / (this.zoom * Math.max(0.2, Math.sin(this.pitch * Math.PI / 180)));
    const a = this.az * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
    this.tx += xr * ca + yr * sa; this.ty += -xr * sa + yr * ca;
    this.autoZoom = false;
    this.clampCenter();
  }
}
