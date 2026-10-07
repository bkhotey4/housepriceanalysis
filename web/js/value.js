// 合理價估算（估價分頁）（從 main.js 拆出來；共用的狀態與小工具從 main.js 匯入）
import * as L from "./logic.js";
import { $, D, S, esc, isNation, needCounty } from "./main.js";

// ---- 合理價估算：找條件相近的實價登錄成交，算出合理價區間
const VAL_TYPES = [["apt", "大樓／華廈／公寓"], ["house", "透天厝"], ["presale", "預售屋"]];
export function valState() { return Object.assign({ dist: "", cat: "apt", ping: "", age: "", addr: "", price: "", floor: "", park: "" }, S.settings.val || {}); }
function valQuery() {
  const v = valState(), dist = D.dmap[v.dist] ? v.dist : (S.current !== L.CITY ? S.current : (D.districts[0] || {}).name);
  const q = { dist, cat: v.cat, ping: +v.ping || null, age: v.cat === "presale" ? null : (v.age === "" ? null : +v.age), presale: v.cat === "presale",
              todayYm: D.book.months[D.book.months.length - 1],
              floor: v.cat !== "house" && v.floor !== "" && +v.floor > 0 ? +v.floor : null, park: +v.park > 0 ? +v.park : 0 };
  if (v.addr) {
    const a = L.parseAddress(dist + v.addr.replace(dist, ""), D.districts.map(d => d.name));
    if (a && a.road) Object.assign(q, { road: a.road, lane: a.lane, alley: a.alley, num: a.num });
  }
  return { v, q };
}
export function tabValue() {
  if (isNation()) return needCounty();
  if (!D.txs) return `<p class="empty">成交資料載入中…</p>`;
  const { v, q } = valQuery();
  const inp = (k, label, ph, mode = "decimal") => `<label>${label}</label><input data-val="${k}" inputmode="${mode}" value="${esc(String(v[k] ?? ""))}" placeholder="${esc(ph)}">`;
  let h = `<p class="muted">輸入一間房子的條件，從實價登錄找條件相近的成交（坪數、屋齡接近、越新的越重要；同一棟、同一條巷、同一條路優先），算出合理價區間。</p>` +
    `<div class="ping-chips-row">` +
    `<span class="muted" style="font-size:12px;margin-right:4px">常用坪數快速帶入：</span>` +
    [
      ["20", "20坪 (小2房)"],
      ["30", "30坪 (標準2房)"],
      ["40", "40坪 (正3房)"],
      ["50", "50坪 (4房大戶)"]
    ].map(([p, label]) => `<button type="button" class="ping-chip${String(v.ping) === p ? " active" : ""}" data-ping="${p}">${label}</button>`).join("") +
    `</div>` +
    `<div class="grid valform"><label>行政區</label><select data-val="dist">${D.districts.map(d => `<option${d.name === q.dist ? " selected" : ""}>${esc(d.name)}</option>`).join("")}</select>` +
    `<label>房型</label><select data-val="cat">${VAL_TYPES.map(([k, t]) => `<option value="${k}"${k === v.cat ? " selected" : ""}>${t}</option>`).join("")}</select>` +
    inp("ping", "建坪（含車位）", "例：35") + (v.cat === "presale" ? "" : inp("age", "屋齡（年）", "例：12", "numeric")) +
    (v.cat === "house" ? "" : inp("floor", "樓層（可空白）", "例：8", "numeric")) + inp("park", "車位（個，可空白）", "例：1", "numeric") +
    inp("addr", "路名或門牌", "可空白，例：中華路一段", "text") + inp("price", "開價（萬，可空白）", "例：1580") + `</div>`;
  if (!q.ping) return h + `<p class="empty">填上建坪就能估價。</p>`;
  const e = L.estimate(D.txs, q);
  if (!e.ok) return h + `<p class="empty">${esc(q.dist)}條件相近的成交只有 ${e.n} 筆，太少，估不出來。可以把房型改成「全部」看看，或放寬坪數。</p>`;
  const j = L.judgePrice(e, +v.price);
  h += `<div class="summary"><b>合理總價約 ${L.fmtNum(e.tLo)}～${L.fmtNum(e.tHi)} 萬</b>（中間值 ${L.fmtNum(e.tMid)} 萬）<br>` +
    `單價 ${e.uLo}～${e.uHi} 萬/坪（中間值 ${e.uMid}）｜比對 ${e.n} 筆近 ${e.months / 12 | 0} 年成交，最接近的有 ${e.nearN} 筆${esc(e.level)}` +
    (e.park ? `<br>含 ${e.park.count} 個車位：每個約 ${L.fmtNum(e.park.price)} 萬、${e.park.area} 坪（${e.park.n} 筆有分開登錄車位的成交），總價＝單價 ×（建坪 − 車位坪數）＋ 車位價` :
      q.park ? `<br>附近有分開登錄車位價格的成交太少，車位直接併在坪數裡估` : "") +
    (e.floorN != null ? `<br>${q.floor} 樓：上下 3 層內的比對成交 ${e.floorN} 筆，樓層越接近的權重越高` : "") +
    (j ? `<br>開價 ${L.fmtNum(+v.price)} 萬：<b class="${j.pos === "高於" ? "up" : j.pos === "低於" ? "down" : ""}">${j.pos}合理區間</b>（比中間值${j.pct >= 0 ? "高" : "低"} ${Math.abs(j.pct).toFixed(0)}%）` : "") + `</div>`;

  const sb = L.safetyBid(e, +v.price);
  if (sb) {
    h += `<div class="safety-bid">
      <h4>🎯 安全出價與議價空間指南</h4>
      <div class="bid-grid">
        <div class="bid-box offer">
          <div class="t">建議斡旋起標價</div>
          <div class="p">${L.fmtNum(sb.offerWan)} 萬</div>
          <div class="u">單價約 ${sb.uLo} 萬/坪</div>
        </div>
        <div class="bid-box target">
          <div class="t">合理成交目標</div>
          <div class="p">${L.fmtNum(sb.targetWan)} 萬</div>
          <div class="u">單價約 ${sb.uMid} 萬/坪</div>
        </div>
        <div class="bid-box ceiling">
          <div class="t">偏貴警戒防線</div>
          <div class="p">${L.fmtNum(sb.ceilingWan)} 萬</div>
          <div class="u">單價約 ${sb.uHi} 萬/坪</div>
        </div>
      </div>
      ${sb.askingAnalysis ? `
        <div class="bid-verdict">
          <b>開價分析（${L.fmtNum(sb.askingAnalysis.askingWan)} 萬）：</b>${esc(sb.askingAnalysis.verdict)}<br>
          <span class="muted">合理成交相當於開價打 <b>${sb.askingAnalysis.discountToTarget} 折</b>；建議斡旋起標相當於開價打 <b>${sb.askingAnalysis.discountToOffer} 折</b>。</span>
        </div>
      ` : `<p class="muted" style="margin:4px 0 0">若在上方表單填寫「開價」，系統將自動分析開價溢價比與建議議價折數。</p>`}
    </div>`;
  }

  const targetPrice = +v.price || e.tMid;
  const incomeVal = parseFloat(S.settings.incomeMonthly) || 120000;
  const cliff = L.youthLoanCliff(targetPrice, 20, incomeVal);
  const budget = L.affordableBudget(incomeVal, 20);
  if (cliff) {
    h += `<details class="more" open><summary>新青安 40 年房貸與家庭所得體檢（以 ${L.fmtNum(targetPrice)} 萬試算）</summary>` +
      `<div class="cliff-box">` +
      `<div class="row" style="margin-bottom:6px"><span>家庭月收入（元）</span><input type="text" inputmode="numeric" data-set="incomeMonthly" value="${incomeVal}" placeholder="例 120000" style="max-width:140px"></div>` +
      `<div class="cliff-row"><span>新青安額度（${L.YOUTH_LOAN.rate}%，上限 ${L.fmtNum(L.YOUTH_LOAN.cap)} 萬）</span><b>${L.fmtNum(cliff.youthWan)} 萬</b></div>` +
      (cliff.normalWan > 0 ? `<div class="cliff-row"><span>超額一般房貸（${cliff.normalRate}%，${L.NORMAL_LOAN.years} 年、沒有寬限期）</span><b>${L.fmtNum(cliff.normalWan)} 萬</b></div>` : "") +
      `<div class="cliff-row"><span>前 5 年寬限期月繳（只繳利息）</span><b style="color:#2ea36b">${L.fmtNum(cliff.period1)} 元/月</b></div>` +
      `<div class="cliff-row"><span>第 6 年起本息攤還月繳（斷崖）</span><b class="up">${L.fmtNum(cliff.period2)} 元/月</b></div>` +
      `<div class="cliff-row"><span>斷崖月增負擔</span><b class="up">+${L.fmtNum(cliff.cliffDiff)} 元/月（增幅 +${cliff.cliffPct}%）</b></div>` +
      (cliff.incomeEval ? `
        <div style="margin-top:8px;padding-top:8px;border-top:1px solid #edf2f7">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <span>所得負擔健康度：</span>
            <span class="cliff-badge ${cliff.incomeEval.safeStatus}">
              ${cliff.incomeEval.safeStatus === "safe" ? "✓ 負擔健康（<35%）" : cliff.incomeEval.safeStatus === "warning" ? "⚠ 負擔偏高（35~50%）" : "⛔ 高度斷崖風險（>50%）"}
            </span>
          </div>
          <div class="muted">
            前 5 年房貸佔月薪 ${cliff.incomeEval.ratio1}%；第 6 年起房貸佔月薪 <b>${cliff.incomeEval.ratio2}%</b>。<br>
            以月收入 1/3（${L.fmtNum(cliff.incomeEval.safeMonthly)} 元/月）安全支出為基準，建議購屋總價上限約 <b>${L.fmtNum(budget?.maxPriceWan)} 萬</b>。
          </div>
        </div>
      ` : "") +
      `</div></details>`;
  }

  if (q.cat === "house") h += `<p class="muted">透天的單價含土地，地坪大小影響很大，這個區間只能當粗略參考。</p>`;
  S.txShown = e.comps;
  h += `<h3>比對用的成交（最相近的 ${e.comps.length} 筆）</h3><table class="list"><thead><tr><th>日期</th><th>地址／建案</th><th class="r">坪</th><th class="r">屋齡</th><th class="r">樓</th><th class="r">萬/坪</th><th class="r">總價</th></tr></thead><tbody>`;
  e.comps.forEach((x, i) => {
    const where = x.proj ? x.proj : x.addr.replace(/^.{2,3}[市縣]/, "").replace(x.dist, "");
    h += `<tr class="click${x.level >= 2 ? " lane" : ""}" data-tx="${i}"><td>${x.date.slice(2).replace(/-/g, "/")}</td><td>${esc(where.slice(0, 18))}<div class="muted">${["", "同路", "同巷", "同一棟"][x.level]}</div></td>` +
      `<td class="r">${x.ping.toFixed(1)}</td><td class="r">${x.age ?? "—"}</td><td class="r">${x.fl ?? "—"}</td><td class="r">${x.u.toFixed(1)}</td><td class="r">${L.fmtNum(x.tw)}${x.pk ? `<div class="muted">含車位 ${x.pk}</div>` : ""}</td></tr>`;
  });
  h += `</tbody></table><p class="muted">這是依過去成交推算的參考區間，不含屋況、景觀與裝潢；樓層和車位只在實價登錄有資料時納入（舊資料沒有這兩欄，會顯示「—」）。實際價格請以現場與專業估價為準，不構成購屋建議。</p>`;
  return h;
}
