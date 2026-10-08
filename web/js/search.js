// 搜尋：即時自動補全、地址／地標／路名搜尋與標記（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, ZOOM, allLines, enterCounty, esc, isNation, loadRoads, main, pick, refreshPins, refreshRoads, renderPanel, roadsNow, selectDistrict, sheet, toast, view } from "./main.js";

// 車站：全台版先切到車站所在的縣市（看路線標的縣市；跨縣市的線用最近的縣市中心），再移到最近的行政區
async function gotoStation(lineName, st) {
  const [name, lat, lng] = st;
  if (D.tw) {
    const ln = allLines().find(l => l.name === lineName) || {};
    const near = D.tw.counties.filter(c => c.has_data && (!(ln.counties || []).length || ln.counties.includes(c.code)))
      .map(c => [c, L.distKm(lat, lng, c.lat, c.lng)]).sort((a, b) => a[1] - b[1]);
    const code = (ln.counties || []).length === 1 ? ln.counties[0] : near.length ? near[0][0].code : null;
    if (code && (!D.county || D.county.code !== code)) { if (!(await enterCounty(code, false))) return; }
  }
  const d = (D.districts || []).map(x => [x, L.distKm(lat, lng, x.lat, x.lng)]).sort((a, b) => a[1] - b[1])[0];
  if (d && d[1] <= 15 && d[0].name !== S.current) selectDistrict(d[0].name, false);
  pick(["station", [lineName, name]]);
  view.flyTo(lat, lng, Math.max(view.zoom, ZOOM.point));
  toast(`已定位車站：${name}（${lineName}）`);
}

// ------------------------------------------------------------------ 即時自動補全與搜尋提示（Google Maps 風格）
export const sugState = { index: -1, list: [], timer: null };      // 目前的提示清單、鍵盤選到第幾個、輸入防抖計時器

function highlightMatch(text, query) {
  if (!query) return esc(text);
  const qNorm = L.normSearchQuery(query);
  const tNorm = L.normSearchQuery(text);
  const idx = tNorm.indexOf(qNorm);
  if (idx === -1) return esc(text);
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + query.length);
  const after = text.slice(idx + query.length);
  return `${esc(before)}<mark>${esc(match)}</mark>${esc(after)}`;
}

export function updateActiveSug() {
  const items = document.querySelectorAll("#search-sug .sug-item");
  items.forEach((el, i) => {
    if (i === sugState.index) {
      el.classList.add("active");
      el.scrollIntoView({ block: "nearest" });
    } else {
      el.classList.remove("active");
    }
  });
}

export function hideSuggestions() {
  const sug = $("#search-sug");
  if (sug) {
    sug.hidden = true;
    sug.innerHTML = "";
  }
  sugState.index = -1;
  sugState.list = [];
}

export function renderSuggestions(query) {
  query = (query || "").trim();
  const sug = $("#search-sug");
  if (!sug) return;

  const data = {
    districts: D.districts || [],
    roadCatalog: D.roadCatalog || [],
    landmarks: D.landmarks || [],
    schools: D.schools || [],
    intel: D.intel || [],
    twCounties: D.tw ? D.tw.counties : [],
    lines: allLines()
  };

  if (!query) {
    const popular = L.popularLandmarks(data, { currentDistrict: S.current, cityName: L.CITY, limit: 8 });
    if (!popular.length) { hideSuggestions(); return; }
    sugState.list = popular;
    sugState.index = -1;

    const chipsHtml = L.LANDMARK_CATEGORIES.map(c => `
      <button type="button" class="sug-chip" data-kw="${esc(c.kw)}">
        <span aria-hidden="true">${c.icon}</span> ${esc(c.label)}
      </button>
    `).join("");

    sug.innerHTML = `
      <div class="sug-section">
        <div class="sug-header">📍 熱門生活地標捷徑</div>
        <div class="sug-chips">${chipsHtml}</div>
      </div>
      <div class="sug-section">
        <div class="sug-section-title">熱門推薦地標</div>
        <ul class="sug-list" role="listbox">
          ${popular.map((item, idx) => `
            <li class="sug-item" role="option" data-idx="${idx}">
              <span class="sug-icon" aria-hidden="true">${item.icon}</span>
              <div class="sug-main">
                <div class="sug-title">${esc(item.title)}<span class="sug-badge">${item.badge}</span></div>
                <div class="sug-sub">${esc(item.sub)}</div>
              </div>
            </li>
          `).join("")}
        </ul>
      </div>
    `;
    sug.hidden = false;
    return;
  }

  const items = L.quickSuggest(query, data, { currentDistrict: S.current, cityName: L.CITY, limit: 8 });
  sugState.list = items;
  sugState.index = -1;
  if (!items.length) { hideSuggestions(); return; }
  sug.innerHTML = items.map((item, idx) => `
    <li class="sug-item" role="option" data-idx="${idx}">
      <span class="sug-icon" aria-hidden="true">${item.icon}</span>
      <div class="sug-main">
        <div class="sug-title">${highlightMatch(item.title, query)}<span class="sug-badge">${item.badge}</span></div>
        <div class="sug-sub">${esc(item.sub)}</div>
      </div>
    </li>
  `).join("");
  sug.hidden = false;
}

export async function selectSuggestion(item) {
  if (!item) return;
  hideSuggestions();
  $("#q").value = item.title;
  $("#btn-clear").hidden = false;
  $("#q").blur();

  if (item.type === "other_county" && D.tw && item.countyCode) { await enterCounty(item.countyCode, true); return; }
  if (item.type === "other_county") {
    toast(`「${item.title}」非台南地區。目前本站為【台南房價專版】，暫未收錄該縣市實價行情。`);
    return;
  }
  if (!D.tw && item.type === "landmark" && (item.isOtherCounty || (item.lm && item.lm.county && item.lm.county !== "D"))) {
    const co = L.COUNTIES.find(x => x.code === (item.countyCode || (item.lm && item.lm.county)));
    const coName = co ? co.short : "其他縣市";
    toast(`「${item.title}」位於${coName}。目前本站為【台南房價專版】，暫未收錄該區實價行情。`);
    return;
  }
  if (!D.tw && item.type === "school" && item.school && item.school.county && item.school.county !== "D") {
    const co = L.COUNTIES.find(x => x.code === item.school.county);
    const coName = co ? co.short : "其他縣市";
    toast(`「${item.title}」位於${coName}。目前本站為【台南房價專版】，暫未收錄該區實價行情。`);
    return;
  }

  if (item.type === "district") {
    selectDistrict(item.name, true);
    toast(`已移到${item.name}`);
    sheet("peek");
  } else if (item.type === "tw_district") {
    if (item.countyCode && (!D.county || D.county.code !== item.countyCode)) {
      await enterCounty(item.countyCode, true);
    }
    if (!D.dmap[item.town]) { toast(`${item.town}還沒有行政區資料。`); return; }
    selectDistrict(item.town, true);
    toast(`已移到${item.town}`);
    sheet("peek");
  } else if (item.type === "county") {
    enterCounty(item.countyCode, true);
    toast(`已前往${item.title}`);
    sheet("peek");
  } else if (item.type === "school") {
    pick(["school", item.school.id]);
    toast(`已定位學區：${item.title}`);
  } else if (item.type === "landmark") {
    pick(["landmark", item.lm.id]);
    toast(`已定位地標：${item.title}`);
  } else if (item.type === "project") {
    pick(["project", item.pr.id]);
    toast(`已定位建設：${item.title}`);
  } else if (item.type === "station") {
    await gotoStation(item.line, item.st);
  } else if (item.type === "road") {
    await showAddress({ district: item.dist, road: item.road, text: item.road });
  } else if (item.type === "address") {
    await showAddress(item.addr);
  }
}

// ------------------------------------------------------------------ 地址搜尋
export async function search(text) {
  text = (text || "").trim();
  if (!text) return;
  hideSuggestions();
  // 車站：有「站」字就先找站名（例如「善化車站」「善化火車站」「台南高鐵站」）；前面帶縣市的先拿掉
  if (/站/.test(text)) {
    const bare = L.splitCounty(text)[1] || text;
    const hits = L.findStations(bare, allLines());
    if (hits.length) { await gotoStation(hits[0].line.name, hits[0].st); return "station"; }
  }
  if (D.tw) {
    // 全台版：先判斷縣市；地址開頭有縣市就切過去，沒有就在目前的縣市找，首頁時再用鄉鎮名稱猜縣市
    let [c, rest] = L.splitCounty(text);
    if (!c && isNation()) {
      const lm = D.landmarks.find(l => text.length >= 2 && (l.name.includes(text) || text.includes(l.name)));
      if (lm) { pick(["landmark", lm.id]); return "landmark"; }
      const sc = (D.schools || []).find(s => text.length >= 2 && (s.name.includes(text) || text.includes(s.name)));
      if (sc) { pick(["school", sc.id]); return "school"; }
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
      if (!D.county || D.county.code !== c.code) { if (!(await enterCounty(c.code, false))) return "none"; }
      if (!rest) { selectDistrict(L.CITY); return "county"; }
      text = rest;
    }
  } else {
    // 台南單一專版：若輸入帶有其他縣市名稱（如「台中市」、「台中市政府」、「台北101」）
    const [c, rest] = L.splitCounty(text);
    if (c && c.code !== "D") {
      toast(`「${c.short}」非台南地區。目前本站為【台南房價專版】，暫未收錄${c.short}實價行情與圖資。`);
      return "other_county";
    }
  }

  // 先以完整關鍵字尋找地標與學區（避免被 parseAddress 拆掉縣市名或路段名導致誤判為其他同名地點）
  const normT = L.normTw(text);
  let lmHit = D.landmarks.find(l => normT.length >= 2 && (L.normTw(l.name) === normT || L.normTw(l.name).startsWith(normT) || normT.startsWith(L.normTw(l.name))));
  if (!lmHit && normT.length >= 2) {
    lmHit = D.landmarks.find(l => L.normTw(l.name).includes(normT) || normT.includes(L.normTw(l.name)));
  }
  if (!lmHit) {
    for (const al of L.SEARCH_ALIASES) {
      if (al.keys.some(k => normT.includes(k) || k.includes(normT))) {
        lmHit = D.landmarks.find(l => l.name.includes(al.target) || (l.note && l.note.includes(al.target)));
        if (lmHit) break;
      }
    }
  }
  if (lmHit) {
    if (!D.tw && lmHit.county && lmHit.county !== "D") {
      const co = L.COUNTIES.find(x => x.code === lmHit.county);
      const coName = co ? co.short : "其他縣市";
      toast(`「${lmHit.name}」位於${coName}。目前本站為【台南房價專版】，暫未收錄該區實價行情。`);
      return "other_county";
    }
    pick(["landmark", lmHit.id]);
    toast(`已定位地標：${lmHit.name}`);
    return "landmark";
  }

  // 學區完整名稱比對
  let scHit = (D.schools || []).find(sc => normT.length >= 2 && (L.normTw(sc.name).includes(normT) || normT.includes(L.normTw(sc.name))));
  if (!scHit) {
    for (const al of L.SEARCH_ALIASES) {
      if (al.keys.some(k => normT.includes(k) || k.includes(normT))) {
        scHit = (D.schools || []).find(x => x.name.includes(al.target));
        if (scHit) break;
      }
    }
  }
  if (scHit) {
    if (!D.tw && scHit.county && scHit.county !== "D") {
      const co = L.COUNTIES.find(x => x.code === scHit.county);
      const coName = co ? co.short : "其他縣市";
      toast(`「${scHit.name}」位於${coName}。目前本站為【台南房價專版】，暫未收錄該區實價行情。`);
      return "other_county";
    }
    pick(["school", scHit.id]);
    toast(`已定位學區：${scHit.name}`);
    return "school";
  }

  // 重大建設完整名稱比對
  const prHit = D.intel.find(it => it.build && normT.length >= 2 && it.name.includes(normT));
  if (prHit) {
    pick(["project", prHit.id]);
    toast(`已定位建設：${prHit.name}`);
    return "project";
  }

  // 行政區與門牌地址比對
  const names = D.districts.map(d => d.name), q = L.parseAddress(text, names), s = q.text;
  const only = names.includes(s) ? s : names.includes(s + "區") ? s + "區" : null;
  if (only || (q.district && !q.road)) {
    selectDistrict(only || q.district); toast(`已移到${only || q.district}`); sheet("peek"); return "district";
  }
  if (!q.road) { toast("看不出這是哪一條路。請輸入像「善化區中山路123號」「大同路一段」這樣的地址或路名。"); return "none"; }
  if (!q.district) {
    if (!D.txs) {
      const catRoad = (D.roadCatalog || []).find(r => r.road === q.road);
      if (catRoad && catRoad.dists.length === 1) q.district = catRoad.dists[0];
      else { toast("成交資料還在載入，請稍候再試一次。"); return "none"; }
    } else {
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
  }
  await showAddress(q);
  return "address";
}
export async function showAddress(q) {
  if (S.current !== q.district) selectDistrict(q.district, false);
  S.addr = q; S.roadFilter = q.road; S.pendingAddr = null;
  view.select("road", q.road);
  S.tab = "tx"; renderPanel(); sheet("half");

  // 若尚未取得精確道路資料，先順暢將鏡頭飛往行政區中心，讓使用者感到完全零停頓
  const d = D.dmap && D.dmap[q.district];
  if (d && !roadsNow(q.district)) {
    view.flyTo(d.lat, d.lng, Math.max(view.zoom, ZOOM.district));
  }
  await pinAt(q, `${q.district} ${L.describe(q)}`, L.describe(q), true);
}
export async function pinAt(q, what, label, isSearch) {
  const cached = roadsNow(q.district);
  if (!cached) toast(`正在定位 ${what}...`);
  const data = cached || await loadRoads(q.district);
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
