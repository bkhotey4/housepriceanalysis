# 網頁版

這個資料夾就是整個網頁版：純靜態檔案，所有計算都在使用者的瀏覽器裡完成，不需要伺服器。

* `index.html`、`css/`、`js/`：畫面與程式（不需要編譯）。
  `js/main.js` 是進入點（狀態、地圖、分頁切換）；`logic.js` 放純計算（和 core/ 的 Python 對照測試）；
  各功能拆在 `search.js`（搜尋與自動補全）、`poi.js`（周邊設施）、`finance.js`（房貸／新青安、交屋現金、租金、租或買）、
  `watch.js`（看屋清單）、`compare.js`（區域比較）、`value.js`（估價）、`report.js`（行情報告）、`view3d.js`（3D 地圖）。
  新增 js 檔時記得加進 `sw.js` 的 SHELL 清單，離線才打得開。
* `data/`、`img/`：由 `python tools/export_web.py` 從桌面版的資料產生，請不要手動改。
* `sw.js`、`manifest.webmanifest`：讓手機可以「加到主畫面」、離線開啟。

在自己電腦上預覽：在專案資料夾執行 `python -m http.server 8000 --directory web`，用瀏覽器開 http://localhost:8000 。
（直接雙擊 index.html 不行，瀏覽器不允許 file:// 讀取資料檔。）
