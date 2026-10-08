// 離線快取：程式本身先用快取（有新版本時背景更新），資料檔先抓網路、抓不到再用快取。
const VERSION = "v15";        // 部署時 tools/ci.sh 會換成「v15-<commit>」，每次上線自動換版，不用手動改
const SHELL = ["./", "index.html", "css/app.css", "js/main.js", "js/logic.js", "js/view3d.js", "js/report.js",
               "js/search.js", "js/poi.js", "js/finance.js", "js/watch.js", "js/compare.js", "js/value.js", "manifest.webmanifest", "img/icon-192.png"];
// 安裝時強制向網路拿最新檔（不經瀏覽器的 HTTP 快取），免得新版 main.js 配到舊版 logic.js
self.addEventListener("install", e => { e.waitUntil(caches.open("shell-" + VERSION).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" }))))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => /^(shell|data)-/.test(k) && !k.endsWith(VERSION)).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;     // 衛星圖磚等外部資源交給瀏覽器
  const isData = url.pathname.includes("/data/") || url.pathname.includes("/img/");
  if (isData) {
    e.respondWith(fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open("data-" + VERSION).then(c => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request)));
  } else {
    // 分享連結帶 ?c=…&d=… 參數：開頁面時不看參數，離線也打得開
    e.respondWith(caches.match(e.request, { ignoreSearch: e.request.mode === "navigate" }).then(hit => {
      const net = fetch(e.request).then(r => { if (r.ok) { const copy = r.clone(); caches.open("shell-" + VERSION).then(c => c.put(e.request, copy)); } return r; });
      if (hit) { net.catch(() => {}); return hit; }        // 離線時背景更新失敗不要變成未處理的錯誤
      return net;
    }));
  }
});
