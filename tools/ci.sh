#!/usr/bin/env bash
# GitHub Actions 的資料更新流程（workflow 只呼叫這支；之後改流程只要改這個檔，不用再動 .github/）。
#   bash tools/ci.sh <push|schedule|workflow_dispatch>
# 每一步的輸出都存到 logs/ci/raw/<步驟>.log；最後由 tools/ci_report.py 整理成
#   web/data/status.json（網站讀取，顯示資料更新狀態）、logs/ci/latest.md（存回專案，git pull 就能在本機看到），
#   有步驟失敗時在 GitHub 開一張 Issue（自動回報）。
set -u
EVENT="${1:-push}"
mkdir -p logs/ci/raw
: > logs/ci/steps.tsv

step() {   # step <代號> <說明> <必要 1/0> <指令…>
  local id="$1" title="$2" must="$3"; shift 3
  local log="logs/ci/raw/$id.log" t0=$(date +%s)
  echo "::group::$title"
  "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  echo "::endgroup::"
  printf '%s\t%s\t%s\t%s\t%s\n' "$id" "$title" "$rc" "$(( $(date +%s) - t0 ))" "$must" >> logs/ci/steps.tsv
  if [ "$rc" != "0" ]; then echo "::warning title=$title 失敗::結束代碼 $rc，詳見 logs/ci/latest.md"; fi
  return 0
}

if [ "$EVENT" = "push" ]; then ROAD_MIN=10; else ROAD_MIN=45; fi

step towns   "全台鄉鎮市區清單"           0 python tools/build_towns.py
step static  "情資、捷運、地標"           1 python tools/export_web.py --no-images
step plvr    "全台實價登錄"               0 python tools/export_tw.py --update
step transit "捷運與高鐵路線"             0 python tools/build_transit.py
git add data/tw/transit.json 2>/dev/null || true     # 和鄉鎮清單一起存回專案（每 30 天重抓一次）
step roads   "各區道路位置（逐步補抓）"    0 python tools/fetch_roads_tw.py --minutes "$ROAD_MIN"
if [ -f web/data/tw/index.json ]; then
  step index "更新道路清單"               0 python tools/export_tw.py --refresh-roads
fi
step check   "資料檢查"                   1 python tools/check_data.py

python tools/ci_report.py "$EVENT"
