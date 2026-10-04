# 宣傳短片製作程式

上一層資料夾的 mp4 就是用這裡的程式做出來的。要重做或改內容時：

1. 準備工具：Python 3、`pip install playwright pillow numpy`、`playwright install chromium`、ffmpeg（要能在命令列執行 `ffmpeg`）。
2. 開本機網頁伺服器（在專案根目錄）：`python -m http.server 8765 --directory web`
3. 產生背景音樂（已經有 music.wav 就可以跳過）：`python music.py`
4. 錄畫面：`python record3.py phone`、`python record3.py wide`（直式與橫式；畫面存在 frames3/，不會放進 git）
5. 合成影片：`python compose3.py phone`、`python compose3.py wide`，成品輸出到上一層「宣傳短片」資料夾。

| 程式 | 成品 |
|---|---|
| record.py ＋ compose.py | 台南購屋_介紹_直式／橫式（18 秒） |
| record30.py ＋ compose30.py | 台南購屋_介紹30秒_直式／橫式 |
| record3.py ＋ compose3.py | 台南購屋_介紹30秒_v2_直式／橫式（含安平、赤崁樓、通勤 A→B） |

背景音樂是程式用數學合成的（music.py），沒有版權問題。字型：Linux 用 Noto Sans CJK，Windows 用微軟正黑體。
