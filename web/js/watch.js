// 看屋清單：與行情比較、附近新成交提醒（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, esc, refreshPins, renderPanel, saveStore, toast, workPlace } from "./main.js";
import { cmpCode } from "./compare.js";

// ---- 看屋清單（只存在這台裝置）
const WATCH_TYPES = ["透天厝", "大樓／華廈", "公寓", "預售屋", "店面／透店", "土地", "其他"];
export const TYPE_CAT = { "透天厝": "house", "店面／透店": "house", "大樓／華廈": "apt", "公寓": "all", "預售屋": "presale" };
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
// 「看屋」分頁上的紅點：看屋清單附近還沒看過的新成交筆數
export function watchBadge() {
  const n = Object.values(S.watchNews || {}).reduce((a, v) => a + v.length, 0);
  return n ? ` <span class="tab-badge" aria-label="${n} 筆新成交">${n > 99 ? "99+" : n}</span>` : "";
}
export function checkWatchNews() {
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
export function tabWatch() {
  let h = `<div class="row"><button class="btn primary" data-act="watch-add">新增物件</button><button class="btn" data-act="watch-export">匯出備份</button><label class="btn">匯入<input type="file" id="watch-import" accept="application/json" hidden></label></div>`;
  h += `<p class="muted">看屋清單只存在這台裝置的瀏覽器裡，不會上傳。換手機時請用「匯出備份」再到新手機「匯入」。</p>`;
  if (!S.watch.length) return h + `<p class="empty">清單是空的。按「新增物件」把正在看的房子記下來，就能和那一區的行情比較。</p>`;
  h += `<table class="list"><thead><tr><th title="排入看屋行程">行程</th><th>物件</th><th class="r">總價</th><th class="r">萬/坪</th><th class="r">對區中位</th><th class="r">評分</th></tr></thead><tbody>`;
  for (const it of S.watch) {
    const c = compareWatch(it);
    const nn = ((S.watchNews || {})[it.id] || []).length, sc = L.visitScore(it.check);
    h += `<tr class="click${S.watchSel === it.id ? " sel" : ""}" data-watch="${esc(it.id)}"><td><input type="checkbox" data-trip="${esc(it.id)}" aria-label="排入看屋行程"${it.trip ? " checked" : ""}></td>` +
      `<td>${esc(it.name)}${nn ? ` <span class="pill new">新成交 ${nn}</span>` : ""}<div class="muted">${esc(it.district || "")}｜${esc(it.type || "")}${it.visit ? "｜" + esc(it.visit.slice(5).replace("-", "/")) + " 看過" : ""}</div></td>` +
      `<td class="r">${it.price ? L.fmtNum(it.price) : "—"}</td><td class="r">${c && c.unit ? c.unit.toFixed(1) : "—"}</td><td class="r">${c ? pct(c.vsT) : "—"}</td>` +
      `<td class="r">${it.rating ? "★".repeat(it.rating) : ""}${sc ? `<div class="muted">檢查 ${sc.pct}%</div>` : ""}</td></tr>`;
  }
  h += "</tbody></table>";
  h += tripSection() + compareNotesSection();
  const it = S.watch.find(w => w.id === S.watchSel);
  if (it) {
    const c = compareWatch(it);
    h += `<h2>${esc(it.name)}</h2><p class="muted">${esc([it.district, it.address, it.type].filter(Boolean).join("｜"))}</p>`;
    if (c && c.bt.value != null) h += `<div class="summary">${esc(it.district)}${L.CAT_LABEL[c.cat]}中位總價 ${L.fmtNum(c.bt.value)} 萬（${c.bt.n} 件）→ 這間 ${pct(c.vsT)}<br>中位單價 ${c.bu.value != null ? c.bu.value.toFixed(1) : "—"} 萬/坪 → 這間 ${pct(c.vsU)}</div>`;
    if (it.note) h += `<p>${esc(it.note)}</p>`;
    const news = (S.watchNews || {})[it.id] || [];
    if (news.length) {
      S.txShown = news.slice(0, 30);
      const cheaper = c && c.unit ? news.filter(x => x.u < c.unit) : [];
      h += `<h3>上次看過之後，附近的新成交（${news.length} 筆）</h3>` +
        (cheaper.length ? `<div class="summary">其中 <b>${cheaper.length} 筆</b>單價比這間（${c.unit.toFixed(1)} 萬/坪）低，最低 ${Math.min(...cheaper.map(x => x.u)).toFixed(1)} 萬/坪（綠色標示）；屋齡、樓層、坪數不同時價格本來就會有差，可以當議價時的參考。</div>`
          : c && c.unit ? `<p class="muted">新成交的單價都不低於這間（${c.unit.toFixed(1)} 萬/坪）。</p>` : "") + `<table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">坪</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>` +
        S.txShown.map((x, i) => `<tr class="click${c && c.unit && x.u < c.unit ? " cheaper" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc((x.proj || x.addr.replace(/^.{2,3}[市縣]/, "").replace(x.dist, "")).slice(0, 18))}</td>` +
          `<td class="r">${x.ping.toFixed(1)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${L.fmtNum(x.tw)}</td></tr>`).join("") +
        `</tbody></table><div class="row"><button class="btn small" data-act="watch-seen">我看過了</button></div>`;
    }
    h += notesSection(it);
    h += `<div class="row"><button class="btn primary" data-act="watch-value">估合理價</button><button class="btn" data-act="watch-edit">編輯</button><button class="btn" data-act="watch-pin">在地圖上標位置</button>` +
      (it.lat != null ? `<button class="btn" data-act="watch-map">在地圖上看</button>` : "") +
      (/^https?:\/\//i.test(it.url || "") ? `<a class="btn" target="_blank" rel="noopener noreferrer" href="${esc(it.url)}">物件網址</a>` : "") +
      `<button class="btn" data-act="watch-del">刪除</button></div>`;
  }
  return h;
}

export function watchDialog(item) {
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

// ---- 看屋筆記：檢查表（好／普通／差）、評分、優缺點、看屋日期（都存在這台裝置，匯出備份會一起帶走）
const CHECK_LABEL = Object.fromEntries(L.VISIT_CHECKS);
function notesSection(it) {
  const ck = it.check || {}, sc = L.visitScore(ck);
  let h = `<h3>看屋筆記</h3><div class="valform">` +
    `<label>看屋日期</label><input type="date" data-wnote="visit" value="${esc(it.visit || "")}">` +
    `<label>整體評分</label><select data-wnote="rating">${["", 1, 2, 3, 4, 5].map(v => `<option value="${v}"${String(it.rating || "") === String(v) ? " selected" : ""}>${v ? "★".repeat(v) : "—"}</option>`).join("")}</select></div>`;
  h += `<table class="list checks"><tbody>` + L.VISIT_CHECKS.map(([k, label]) =>
    `<tr><td>${esc(label)}</td><td class="r"><select data-wcheck="${k}" aria-label="${esc(label)}">${L.VISIT_MARKS.map(([v, t]) => `<option value="${v}"${(ck[k] || "") === v ? " selected" : ""}>${t}</option>`).join("")}</select></td></tr>`).join("") + `</tbody></table>`;
  if (sc) h += `<div class="summary">檢查表 ${sc.n} 項、得分 <b>${sc.pct}%</b>${sc.bad.length ? `<br>要注意：${sc.bad.map(k => esc(CHECK_LABEL[k] || k)).join("、")}` : ""}</div>`;
  h += `<div class="valform"><label>優點</label><textarea rows="2" data-wnote="pros" placeholder="例：邊間、採光好、近市場">${esc(it.pros || "")}</textarea>` +
    `<label>缺點</label><textarea rows="2" data-wnote="cons" placeholder="例：西曬、巷子窄、管理費高">${esc(it.cons || "")}</textarea></div>`;
  return h;
}
// 有評分或檢查表的物件，並排比較（最多 5 間）
function compareNotesSection() {
  const list = S.watch.filter(w => w.rating || L.visitScore(w.check)).slice(0, 5);
  if (list.length < 2) return "";
  if (!S.watchCmpOpen) return `<div class="row"><button class="btn small" data-act="wnote-cmp">並排比較看過的 ${list.length} 間</button></div>`;
  const cols = list.map(it => ({ it, c: compareWatch(it), sc: L.visitScore(it.check) }));
  const best = Math.max(...cols.map(x => x.sc ? x.sc.pct : -1));
  const mark = v => ({ "2": "✓ 好", "1": "△ 普通", "0": "✗ 差" }[v] || "");
  let h = `<h3>並排比較</h3><table class="list cmp"><thead><tr><th></th>${cols.map(x => `<th class="r">${esc(x.it.name.slice(0, 8))}</th>`).join("")}</tr></thead><tbody>`;
  const row = (k, f) => `<tr><td>${esc(k)}</td>${cols.map(x => `<td class="r">${f(x)}</td>`).join("")}</tr>`;
  h += row("總價（萬）", x => x.it.price ? L.fmtNum(x.it.price) : "—") + row("萬/坪", x => x.c && x.c.unit ? x.c.unit.toFixed(1) : "—") +
    row("對區中位", x => x.c ? pct(x.c.vsT) : "—") + row("評分", x => x.it.rating ? "★".repeat(x.it.rating) : "—") +
    row("檢查表", x => x.sc ? `${x.sc.pct === best ? "<b>" : ""}${x.sc.pct}%${x.sc.pct === best ? "</b>" : ""}` : "—");
  for (const [k, label] of L.VISIT_CHECKS) if (cols.some(x => (x.it.check || {})[k])) h += row(label, x => mark((x.it.check || {})[k]));
  h += row("優點", x => esc(x.it.pros || "")) + row("缺點", x => esc(x.it.cons || ""));
  return h + `</tbody></table><div class="row"><button class="btn small" data-act="wnote-cmp">收起比較</button></div>`;
}
// ---- 看屋行程：勾選的物件排出最順的順序（從上班地點出發；沒設定就從第一間開始），開 Google 地圖導航
function tripSection() {
  const picked = S.watch.filter(w => w.trip);
  if (!picked.length) return `<p class="muted">勾選「行程」欄，可以把要看的房子排成最順的路線，並用 Google 地圖導航。</p>`;
  const noPos = picked.filter(w => w.lat == null);
  const pts = picked.filter(w => w.lat != null), w = workPlace(), start = S.tripFromWork && w ? { lat: w.lat, lng: w.lng, name: w.name } : null;
  let h = `<h3>看屋行程（${picked.length} 間）</h3>`;
  if (noPos.length) h += `<p class="muted">${noPos.map(x => esc(x.name)).join("、")} 還沒標位置（點物件 →「在地圖上標位置」），先不排進路線。</p>`;
  if (!pts.length) return h;
  const t = L.planTrip(pts, start), mode = S.settings.mode || "car";
  h += (w ? `<label class="row" style="gap:6px;font-size:14px"><input type="checkbox" data-trip-start${S.tripFromWork ? " checked" : ""}> 從上班地點（${esc(w.name)}）出發</label>` : "") +
    `<ol class="trip">${t.order.map((p, i) => `<li>${esc(p.name)}<span class="muted">｜${esc(p.district || "")}${t.legs[i] ? `｜${t.legs[i].toFixed(1)} 公里、${(L.MODES[mode] || L.MODES.car)[0]}約 ${L.commuteMin(t.legs[i], mode)} 分` : ""}</span></li>`).join("")}</ol>` +
    `<div class="summary">直線距離合計約 ${t.km.toFixed(1)} 公里${pts.length > (start ? 10 : 11) ? `；Google 地圖一次最多 ${start ? 10 : 11} 間，只導航前 ${start ? 10 : 11} 間` : ""}</div>` +
    `<div class="row"><a class="btn primary" target="_blank" rel="noopener" href="${esc(L.tripUrl(t.order, start, mode))}">用 Google 地圖導航</a><button class="btn small" data-act="trip-clear">清空行程</button></div>`;
  return h;
}
// main.js 的事件轉來這裡：處理看屋筆記與行程的勾選、選單、文字欄位；處理了就回傳 true
export function watchClick(t) {
  const act = t.closest("[data-act]")?.dataset.act;
  if (t.matches("[data-trip]")) {                 // 勾選框在表格列裡：不要觸發選取那一列
    const it = S.watch.find(w => w.id === t.dataset.trip);
    if (it) { it.trip = t.checked; saveStore(); renderPanel(); }
    return true;
  }
  if (t.matches("[data-trip-start]")) { S.tripFromWork = t.checked; renderPanel(); return true; }
  if (act === "trip-clear") { S.watch.forEach(w => { w.trip = false; }); saveStore(); renderPanel(); return true; }
  if (act === "wnote-cmp") { S.watchCmpOpen = !S.watchCmpOpen; renderPanel(); return true; }
  return false;
}
export function watchChange(el) {
  const it = S.watch.find(w => w.id === S.watchSel);
  if (!it || !el.dataset) return false;
  if (el.dataset.wcheck) { it.check = { ...(it.check || {}), [el.dataset.wcheck]: el.value }; }
  else if (el.dataset.wnote) {
    const k = el.dataset.wnote;
    it[k] = k === "rating" ? (+el.value || null) : el.value.trim();
  } else return false;
  saveStore();
  // 文字欄位（優點、缺點、日期）存好就好，不重畫：重畫會吃掉使用者接著按的按鈕
  if (el.dataset.wnote && el.dataset.wnote !== "rating") return true;
  const sc = $("#tab-body").scrollTop; renderPanel(); $("#tab-body").scrollTop = sc;
  return true;
}
