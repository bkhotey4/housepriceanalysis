# 網頁版

這個資料夾就是整個網頁版：純靜態檔案，所有計算都在使用者的瀏覽器裡完成，不需要伺服器。

* `index.html`、`css/`、`js/`：畫面與程式（不需要編譯）。
* `data/`、`img/`：由 `python tools/export_web.py` 從桌面版的資料產生，請不要手動改。
* `sw.js`、`manifest.webmanifest`：讓手機可以「加到主畫面」、離線開啟。

在自己電腦上預覽：在專案資料夾執行 `python -m http.server 8000 --directory web`，用瀏覽器開 http://localhost:8000 。
（直接雙擊 index.html 不行，瀏覽器不允許 file:// 讀取資料檔。）
