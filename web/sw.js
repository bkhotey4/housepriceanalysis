// 離線快取：程式檔安裝時整批放進快取（新版本靠 sw.js 本身改變來安裝，不在背景一個一個換，免得新舊模組混用）；
// 資料檔先抓網路，8 秒沒回應或抓不到就用快取；逐筆成交（tx.json）檔案大，慢網路常超過 8 秒，
// 只有真的抓不到才用快取（不然會配到上一版，和新的統計數字對不起來）。
const VERSION = "v15";        // 部署時 tools/ci.sh 會換成「v15-<commit>」，每次上線自動換版，不用手動改
const DATA = "data-v1", TX_KEEP = 6;      // 逐筆成交只留最近看過的 6 個縣市，免得手機空間一直被吃掉
const SHELL = ["./", "index.html", "css/app.css", "js/main.js", "js/logic.js", "js/view3d.js", "js/report.js",
               "js/search.js", "js/poi.js", "js/finance.js", "js/watch.js", "js/compare.js", "js/value.js", "js/fit.js", "js/land.js", "js/shops.js", "manifest.webmanifest", "img/icon-192.png"];
// 安裝時強制向網路拿最新檔（不經瀏覽器的 HTTP 快取），免得新版 main.js 配到舊版 logic.js
self.addEventListener("install", e => { e.waitUntil(caches.open("shell-" + VERSION).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" }))))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => /^(shell-|data$|data-)/.test(k) && k !== "shell-" + VERSION && k !== DATA).map(k => caches.delete(k)))));
  self.clients.claim();
});
// 快取裡的順序就是存入順序：刪掉最舊的，只留最近的 TX_KEEP 份
async function pruneTx(c) {
  const tx = (await c.keys()).filter(q => new URL(q.url).pathname.endsWith("/tx.json"));
  await Promise.all(tx.slice(0, Math.max(0, tx.length - TX_KEEP)).map(q => c.delete(q)));
}
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;     // 衛星圖磚等外部資源交給瀏覽器
  const isData = url.pathname.includes("/data/") || url.pathname.includes("/img/"), isTx = url.pathname.endsWith("/tx.json");
  if (isData) {
    const net = fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(DATA).then(c => c.put(e.request, copy).then(() => isTx && pruneTx(c))); }
      return r;
    });
    if (isTx) { e.respondWith(net.catch(() => caches.match(e.request).then(hit => hit || Promise.reject(new Error("offline"))))); return; }
    const slow = new Promise(res => setTimeout(res, 8000)).then(() => caches.match(e.request)).then(hit => hit || net);
    e.respondWith(Promise.race([net.catch(() => caches.match(e.request).then(hit => hit || Promise.reject(new Error("offline")))), slow]));
  } else {
    // 分享連結帶 ?c=…&d=… 參數：開頁面時不看參數，離線也打得開
    e.respondWith(caches.match(e.request, { ignoreSearch: e.request.mode === "navigate" }).then(hit => hit || fetch(e.request)));
  }
});
