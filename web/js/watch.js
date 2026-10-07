// 看屋清單：與行情比較、附近新成交提醒（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, esc, refreshPins, renderPanel, saveStore, toast } from "./main.js";
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
      const cheaper = c && c.unit ? news.filter(x => x.u < c.unit) : [];
      h += `<h3>上次看過之後，附近的新成交（${news.length} 筆）</h3>` +
        (cheaper.length ? `<div class="summary">其中 <b>${cheaper.length} 筆</b>單價比這間（${c.unit.toFixed(1)} 萬/坪）低，最低 ${Math.min(...cheaper.map(x => x.u)).toFixed(1)} 萬/坪（綠色標示）；屋齡、樓層、坪數不同時價格本來就會有差，可以當議價時的參考。</div>`
          : c && c.unit ? `<p class="muted">新成交的單價都不低於這間（${c.unit.toFixed(1)} 萬/坪）。</p>` : "") + `<table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">坪</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>` +
        S.txShown.map((x, i) => `<tr class="click${c && c.unit && x.u < c.unit ? " cheaper" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc((x.proj || x.addr.replace(/^.{2,3}[市縣]/, "").replace(x.dist, "")).slice(0, 18))}</td>` +
          `<td class="r">${x.ping.toFixed(1)}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${L.fmtNum(x.tw)}</td></tr>`).join("") +
        `</tbody></table><div class="row"><button class="btn small" data-act="watch-seen">我看過了</button></div>`;
    }
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
