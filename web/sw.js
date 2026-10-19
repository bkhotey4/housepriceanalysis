// 離線快取：程式檔安裝時整批放進快取（新版本靠 sw.js 本身改變來安裝，不在背景一個一個換，免得新舊模組混用）；
// 資料檔先抓網路，8 秒沒回應或抓不到就用快取。
const VERSION = "v15";        // 部署時 tools/ci.sh 會換成「v15-<commit>」，每次上線自動換版，不用手動改
const SHELL = ["./", "index.html", "css/app.css", "js/main.js", "js/logic.js", "js/view3d.js", "js/report.js",
               "js/search.js", "js/poi.js", "js/finance.js", "js/watch.js", "js/compare.js", "js/value.js", "js/fit.js", "manifest.webmanifest", "img/icon-192.png"];
// 安裝時強制向網路拿最新檔（不經瀏覽器的 HTTP 快取），免得新版 main.js 配到舊版 logic.js
self.addEventListener("install", e => { e.waitUntil(caches.open("shell-" + VERSION).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" }))))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => /^(shell|data)-/.test(k) && k !== "shell-" + VERSION).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;     // 衛星圖磚等外部資源交給瀏覽器
  const isData = url.pathname.includes("/data/") || url.pathname.includes("/img/");
  if (isData) {
    const net = fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open("data").then(c => c.put(e.request, copy)); }
      return r;
    });
    const slow = new Promise(res => setTimeout(res, 8000)).then(() => caches.match(e.request)).then(hit => hit || net);
    e.respondWith(Promise.race([net.catch(() => caches.match(e.request).then(hit => hit || Promise.reject(new Error("offline")))), slow]));
  } else {
    // 分享連結帶 ?c=…&d=… 參數：開頁面時不看參數，離線也打得開
    e.respondWith(caches.match(e.request, { ignoreSearch: e.request.mode === "navigate" }).then(hit => hit || fetch(e.request)));
  }
});
