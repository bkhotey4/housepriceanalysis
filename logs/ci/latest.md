# 資料更新紀錄 2026-11-11 09:01

- 觸發：push　commit：3e3ee65
- 結果：失敗 1 步：捷運與高鐵路線（有 1 則提醒）
- 執行紀錄：https://github.com/bkhotey4/housepriceanalysis/actions/runs/42931989664
- 資料：{"mode": "全台版", "as_of": "2026-11-10", "complete_through": "2026-07", "tx_count": 520298, "counties_with_data": 22, "road_districts": 365, "town_districts": 369, "missing": [], "counts": {"A": 17263, "F": 38194, "C": 3295, "H": 27815, "O": 3493, "J": 5137, "G": 4614, "K": 3753, "B": 25794, "N": 5071, "M": 2090, "P": 2885, "I": 2069, "Q": 2019, "D": 14605, "E": 22666, "T": 4421, "U": 1965, "V": 946, "X": 221, "W": 528, "Z": 6}}

| 步驟 | 結果 | 秒 |
|---|---|---|
| 全台鄉鎮市區清單 | 成功 | 0 |
| 情資、捷運、地標 | 成功 | 1 |
| 全台實價登錄 | 成功 | 141 |
| 長期房價走勢（近 5 年） | 成功 | 2 |
| 預售屋建案報備 | 成功 | 1 |
| 各區生活機能（稅籍登記） | 成功 | 91 |
| 人口成長與年齡結構 | 成功 | 0 |
| 捷運與高鐵路線 | **失敗（124）** | 1200 |
| 各區道路位置（逐步補抓） | 成功 | 342 |
| 更新道路清單 | 成功 | 1 |
| 資料檢查 | 成功 | 0 |

## 提醒

- [提醒] 連江縣 沒有 rent.json

## 捷運與高鐵路線 的最後 60 行輸出

```
  overpass-api.de 第 1 次：無法連線到 overpass-api.de：HTTP 502 Bad Gateway（# 502 Gateway Timeout This Overpass API server is currently at capacity. All query workers are busy and the request q
台鐵北部：2045 個軌道與車站
  overpass-api.de 第 1 次：無法連線到 overpass-api.de：HTTP 504 Gateway Timeout（OSM3S Response       The data included in this document is from www.openstreetmap.org. The data is made available
  overpass-api.de 第 2 次：無法連線到 overpass-api.de：HTTP 502 Bad Gateway（# 502 Gateway Timeout This Overpass API server is currently at capacity. All query workers are busy and the request q
  maps.mail.ru 第 1 次：無法連線到 maps.mail.ru：HTTP 504 Gateway Timeout（OSM3S Response       The data included in this document is from www.openstreetmap.org. The data is made available un
  maps.mail.ru 第 2 次：無法連線到 maps.mail.ru：HTTP 504 Gateway Time-out（504 Gateway Time-out       504 Gateway Time-out     nginx）
台鐵中部：808 個軌道與車站
  overpass-api.de 第 1 次：無法連線到 overpass-api.de：HTTP 502 Bad Gateway（# 502 Gateway Timeout This Overpass API server is currently at capacity. All query workers are busy and the request q
  overpass-api.de 第 2 次：無法連線到 overpass-api.de：HTTP 502 Bad Gateway（# 502 Gateway Timeout This Overpass API server is currently at capacity. All query workers are busy and the request q
  maps.mail.ru 第 1 次：無法連線到 maps.mail.ru：HTTP 504 Gateway Timeout（OSM3S Response       The data included in this document is from www.openstreetmap.org. The data is made available un
  maps.mail.ru 第 2 次：無法連線到 maps.mail.ru：HTTP 504 Gateway Time-out（504 Gateway Time-out       504 Gateway Time-out     nginx）
  overpass.private.coffee 第 1 次：無法連線到 overpass.private.coffee：HTTP 504 Gateway Timeout（OSM3S Response       The data included in this document is from www.openstreetmap.org. The data is made a
台鐵嘉南：218 個軌道與車站
  overpass-api.de 第 1 次：無法連線到 overpass-api.de：HTTP 502 Bad Gateway（# 502 Gateway Timeout This Overpass API server is currently at capacity. All query workers are busy and the request q
```
