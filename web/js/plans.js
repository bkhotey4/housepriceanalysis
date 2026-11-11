// 規劃中的公共建設：政府電子採購網的可行性評估、環評、規劃設計、新建工程、招商公告（tools/build_plans.py 整理成 data/tw/<代碼>/plans.json）
// 比新聞、建照早好幾年的訊號；放在「建設」分頁的重大建設清單下面。
import * as L from "./logic.js";
import { D, S, esc, renderPanel } from "./main.js";

const CACHE = new Map();
export function loadPlans(code) {
  D.plans = CACHE.get(code) || null;
  if (!code || CACHE.has(code)) return;
  fetch(`data/tw/${code}/plans.json`).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(j => {
    CACHE.set(code, j);
    if (D.county && D.county.code === code) { D.plans = j; if (S.tab === "projects") renderPanel(); }
  }).catch(() => {});        // 沒有這個檔（資料流程還沒跑過）：不顯示這一段
}
// 階段篩選按鈕（不經過 main.js 的事件分派）
document.addEventListener("click", e => {
  const b = e.target.closest && e.target.closest("[data-plan-stage]");
  if (!b) return;
  S.planStage = b.dataset.planStage; renderPanel();
});
const STAGE_ORDER = ["可行性評估", "環評", "招商", "規劃設計", "新建工程"];
const money = w => w == null ? "" : w >= 10000 ? `${(w / 10000).toFixed(w >= 100000 ? 0 : 1)} 億` : `${L.fmtNum(Math.round(w))} 萬`;
const ymd = s => s ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : "";
export function plansSection() {
  const pd = D.plans;
  if (!D.county || !pd || !pd.items) return "";
  const inDist = S.current !== L.CITY;
  let items = pd.items.filter(it => !inDist || it.district === S.current);
  const stage = S.planStage || "";
  const counts = Object.fromEntries(STAGE_ORDER.map(s => [s, items.filter(it => it.stage === s).length]));
  if (stage) items = items.filter(it => it.stage === stage);
  let h = `<h3>規劃中的公共建設（政府標案）</h3>`;
  h += `<div class="row">` + [["", `全部 ${Object.values(counts).reduce((a, b) => a + b, 0)}`], ...STAGE_ORDER.filter(s => counts[s]).map(s => [s, `${s} ${counts[s]}`])]
    .map(([v, t]) => `<button class="btn small${stage === v ? " primary" : ""}" data-plan-stage="${esc(v)}">${esc(t)}</button>`).join("") + `</div>`;
  if (!items.length) return h + `<p class="empty">${inDist ? "這一區最近沒有（或標案名稱看不出在這一區的）大型建設標案；切到全縣市看看。" : "最近沒有符合條件的大型建設標案。"}</p>`;
  h += `<table class="list"><tbody>`;
  for (const it of items.slice(0, 80)) {
    const amt = it.award_wan != null ? `決標 ${money(it.award_wan)}` : it.budget_wan != null ? `預算 ${money(it.budget_wan)}` : "";
    const sub = [inDist ? "" : it.district, it.unit, amt, it.winner ? `得標：${it.winner}` : "", `${it.status} ${ymd(it.last)}`].filter(Boolean).join("｜");
    h += `<tr><td><span class="pill ${it.stage === "新建工程" ? "build" : "plan"}">${esc(it.stage)}</span>${esc(it.title)}` +
      `<div class="muted">${esc(sub)}｜<a href="${esc(it.url)}" target="_blank" rel="noopener">公告</a></div></td></tr>`;
  }
  h += `</tbody></table>`;
  return h + `<p class="muted">整理自政府電子採購網的公告（${pd.through ? `看到 ${esc(ymd(pd.through))}，` : ""}每次資料更新接著抓）：機關要蓋大型建設，通常好幾年前就會先發包可行性評估、環評、規劃設計，` +
    `比新聞和建照都早。只收名稱看得出是建設、委託案 100 萬以上或工程 5,000 萬以上的；可行性評估不代表一定會蓋，很多評估完就沒下文。行政區是從標案名稱或履約地點判斷的，可能不準。</p>`;
}
