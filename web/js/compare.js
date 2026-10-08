// 區域比較：最多 3 個區並排，可以跨縣市（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, allLines, countyData, esc, isNation, logError, minsTo, modeName, renderPanel, saveStore, toast, workPlace } from "./main.js";

// ---- 區域比較：最多 3 個區並排，可以跨縣市（例如台南東區 vs 高雄左營 vs 台中北屯）
export const CMP_MAX = 3;
export const cmpCode = () => (D.county ? D.county.code : D.tw ? "" : "D");
export function cmpList() { return (S.settings.cmp || []).filter(x => x && x.name); }
export function cmpAdd() {
  const code = cmpCode(), name = S.current;
  if (!name || name === L.CITY || (D.tw && !D.county)) { toast("先選一個行政區再加入比較。"); return; }
  const list = cmpList().filter(x => !(x.code === code && x.name === name));
  list.push({ code, name, county: D.county ? D.county.short : L.CITY });
  S.settings.cmp = list.slice(-CMP_MAX); saveStore();
  toast(`已加入比較（${S.settings.cmp.length}/${CMP_MAX}）`); S.tab = "cmp"; renderPanel();
}
// 直接選縣市＋行政區加入比較（不用先在地圖上點到那一區）；全台版用 index.json 裡各縣市的 town_names
function pickCounties() {
  if (D.tw) return D.tw.counties.filter(c => c.has_data).map(c => ({ code: c.code, short: c.short, names: c.town_names || [] }));
  return [{ code: "D", short: L.CITY, names: D.districts.map(d => d.name) }];
}
export function cmpPickAdd(code, name) {
  const c = pickCounties().find(x => x.code === code);
  if (!c || !name) return;
  const list = cmpList().filter(x => !(x.code === code && x.name === name));
  list.push({ code, name, county: c.short });
  S.settings.cmp = list.slice(-CMP_MAX); saveStore(); renderPanel();
}
function cmpPicker() {
  const cs = pickCounties();
  if (!cs.length) return "";
  const code = cs.some(c => c.code === S.cmpPick) ? S.cmpPick : (D.county ? D.county.code : cs[0].code);
  const c = cs.find(x => x.code === code);
  return `<div class="row cmp-pick">` +
    (cs.length > 1 ? `<select id="cmp-county" aria-label="縣市">${cs.map(x => `<option value="${x.code}"${x.code === code ? " selected" : ""}>${esc(x.short)}</option>`).join("")}</select>` : "") +
    `<select id="cmp-dist" data-code="${code}" aria-label="行政區">${c.names.map(n => `<option${n === S.current ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>` +
    `<button class="btn small primary" data-act="cmp-pick">加入比較</button></div>`;
}
// 「雙區 PK」預設帶入的兩區：目前所在縣市（或選中的區）成交最多的兩區；全台總覽時不預設，讓使用者自己挑
export function cmpDefaultPair() {
  if (isNation()) return null;
  const code = cmpCode() || "D", county = D.county ? D.county.short : L.CITY;
  const n = name => { const c = D.book.cell(name, "all"); return c && c.y12 ? c.y12[0] : 0; };
  const names = D.districts.map(d => d.name).sort((a, b) => n(b) - n(a));
  const first = S.current !== L.CITY && names.includes(S.current) ? S.current : names[0];
  const second = names.find(x => x !== first);
  return first && second ? [{ code, name: first, county }, { code, name: second, county }] : null;
}
const CMP_DATA = new Map();      // "代碼|區" → {book, d}
function cmpEnsure() {
  const need = cmpList().filter(x => !CMP_DATA.has(x.code + "|" + x.name));
  if (!need.length) return true;
  // 一個一個載入：載不到的（縣市代碼錯、網路斷）從清單拿掉，其他照常顯示
  Promise.allSettled(need.map(async x => {
    if (!D.tw) { CMP_DATA.set(x.code + "|" + x.name, { book: D.book, d: D.dmap[x.name] }); return; }
    const cd = await countyData(x.code);
    CMP_DATA.set(x.code + "|" + x.name, { book: cd.book, d: cd.dmap[x.name], rent: cd.rent, pop: cd.pop });
  })).then(rs => {
    const bad = need.filter((x, i) => rs[i].status === "rejected");
    if (bad.length) {
      logError("載入比較資料", rs.find(r => r.status === "rejected").reason, true);
      S.settings.cmp = cmpList().filter(x => !bad.includes(x)); saveStore();
      toast(`${bad.map(x => x.name).join("、")}的資料載入失敗，已從比較拿掉。`);
    }
    if (S.tab === "cmp") renderPanel();
  });
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
export function tabCmp() {
  const list = cmpList();
  let h = cmpPicker() + `<div class="row">${S.current !== L.CITY && !isNation() ? `<button class="btn" data-act="cmp-add">把目前的${esc(S.current)}加入</button>` : ""}` +
    (list.length ? `<button class="btn" data-act="cmp-clear">清空</button>` : "") + `</div>`;
  if (!list.length) return h + `<p class="empty">還沒有要比較的區。用上面的選單挑${D.tw ? "縣市和" : ""}行政區按「加入比較」，最多 ${CMP_MAX} 個${D.tw ? "，可以跨縣市（例如台北大安 vs 新北板橋）" : ""}。選兩個區會出現「雙區 PK」對決。</p>`;
  if (list.length === 1) h += `<p class="muted">再加一個區，就會出現「雙區 PK」逐項對決。</p>`;
  if (!cmpEnsure()) return h + `<p class="empty">載入比較資料中…</p>`;
  const cols = list.map((x, idx) => ({ ...x, idx, ...CMP_DATA.get(x.code + "|" + x.name), label: (D.tw ? x.county.replace(/[市縣]$/, "") + " " : "") + x.name }))
    .filter(c => c.book && c.d);
  // 資料載入了、那個縣市卻沒有這一區（例如分享連結打錯字）：從清單拿掉，免得佔名額
  const missing = list.filter(x => { const cd = CMP_DATA.get(x.code + "|" + x.name); return cd && cd.book && !cd.d; });
  if (missing.length) { S.settings.cmp = list.filter(x => !missing.includes(x)); saveStore(); }

  if (cols.length === 2) {
    const duel = L.duelCompare(cols[0], cols[1], S.cat);
    if (duel) {
      h += `<div class="duel-card">
        <div class="duel-header">
          <div class="duel-team">
            <div class="name">${esc(cols[0].label)}</div>
            <div class="score">${duel.scoreA}</div>
          </div>
          <div class="duel-vs">⚔️ VS</div>
          <div class="duel-team">
            <div class="name">${esc(cols[1].label)}</div>
            <div class="score">${duel.scoreB}</div>
          </div>
        </div>
        <table class="duel-table">
          <thead><tr><th>評比指標</th><th>${esc(cols[0].name)}</th><th>勝負</th><th>${esc(cols[1].name)}</th></tr></thead>
          <tbody>
            ${duel.rounds.map(r => `
              <tr>
                <td>${esc(r.label)}</td>
                <td class="${r.win === 'A' ? 'duel-win' : ''}">${r.valA != null ? r.valA + (r.unit || '') : '—'}</td>
                <td>${r.win === 'A' ? '◀ 勝' : r.win === 'B' ? '勝 ▶' : '平'}</td>
                <td class="${r.win === 'B' ? 'duel-win' : ''}">${r.valB != null ? r.valB + (r.unit || '') : '—'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
        <div class="duel-verdict"><b>🏆 雙區 PK 點評：</b>${esc(duel.verdict)}</div>
      </div>`;
    }
  }

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
    ["人口（近 5 年增減）", c => { const p = L.popInfo(c.pop, c.name); return p ? `${L.fmtNum(p.now)}${p.chgAll != null ? `<div class="muted">${p.chgAll >= 0 ? "+" : "−"}${Math.abs(p.chgAll).toFixed(1)}%</div>` : ""}` : "—"; }],
    ["65 歲以上／25～44 歲", c => { const p = L.popInfo(c.pop, c.name); return p && p.old != null ? `${p.old.toFixed(0)}%／${p.young.toFixed(0)}%` : "—"; }],
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
  h += `<table class="list cmp"><thead><tr><th></th>${cols.map((c, i) => `<th class="r">${esc(c.label)}<div><a href="#" data-cmpdel="${c.idx}">移除</a></div></th>`).join("")}</tr></thead><tbody>` +
    rows.map(([k, f]) => `<tr><td>${esc(k)}</td>${cols.map(c => `<td class="r">${f(c)}</td>`).join("")}</tr>`).join("") + `</tbody></table>`;
  h += `<p class="muted">房型：${L.CAT_LABEL[cat]}｜近半年統計，件數太少時改用近一年（標 *）。通勤：目前所在縣市的區用實際道路時間（查得到時），其他用直線距離估計。</p>`;
  h += `<h3>每月中位${S.metric === "u" ? "單價" : "總價"}</h3>` + cmpSeriesSVG(cols);
  return h;
}
