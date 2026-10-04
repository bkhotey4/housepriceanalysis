// 離線快取：程式本身先用快取（有新版本時背景更新），資料檔先抓網路、抓不到再用快取。
const VERSION = "v12";
const SHELL = ["./", "index.html", "css/app.css", "js/main.js", "js/logic.js", "js/view3d.js", "js/report.js", "manifest.webmanifest", "img/icon-192.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open("shell-" + VERSION).then(c => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => !k.endsWith(VERSION)).map(k => caches.delete(k)))));
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
    e.respondWith(caches.match(e.request).then(hit => {
      const net = fetch(e.request).then(r => { if (r.ok) { const copy = r.clone(); caches.open("shell-" + VERSION).then(c => c.put(e.request, copy)); } return r; });
      return hit || net;
    }));
  }
});
