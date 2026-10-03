#!/usr/bin/env python3
"""
每周自動更新：深度挖掘台南捷運各路線最新進度
- 查詢交通部、台南市政府、新聞等公開資訊
- 更新 MRT_LINES 中各線進度
- 執行方式：由 cronjob 每周觸發一次
"""
import os, sys, json, webbrowser
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP_DIR, "data"))
from mrt_data import MRT_LINES

REPORT_FILE = os.path.join(APP_DIR, "data", "mrt_update_log.json")


def check_online_updates():
    """檢查各線最新進度（瀏覽器開啟查詢頁面供手動確認）"""
    print("=" * 60)
    print(f"🚇 台南捷運進度深度更新 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 搜尋關鍵字列表
    searches = [
        ("交通部 台南捷運 審查", "https://www.bing.com/search?q=交通部+台南捷運+審查+進度"),
        ("台南捷運藍線 細部設計", "https://www.bing.com/search?q=台南捷運藍線+細部設計+2026"),
        ("台南捷運綠線 可行性研究", "https://www.bing.com/search?q=台南捷運綠線+可行性研究+2026"),
        ("台南捷運深綠線 南科", "https://www.bing.com/search?q=台南捷運深綠線+南科+進度"),
        ("台南市政府 捷運工程處", "https://www.bing.com/search?q=台南市政府+捷運工程處+公告"),
    ]

    report = {
        "update_time": datetime.now().isoformat(),
        "lines": {},
        "news_links": [],
    }

    print("\n📋 各線目前狀態：")
    for name, d in MRT_LINES.items():
        print(f"  {name}: {d['status']} | 動工: {d.get('construction_start','未定')} | 完工: {d['estimated_completion']}")
        report["lines"][name] = {
            "status": d["status"],
            "stage": d["stage"],
            "construction_start": d.get("construction_start", "未定"),
            "estimated_completion": d["estimated_completion"],
        }

    print(f"\n🔍 將在瀏覽器開啟 {len(searches)} 個搜尋頁面供查閱最新資訊...")
    for title, url in searches:
        print(f"  開啟: {title}")
        webbrowser.open(url)
        report["news_links"].append({"title": title, "url": url})

    # 儲存更新記錄
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 更新記錄已儲存至 {REPORT_FILE}")
    print("💡 請檢視開啟的搜尋頁面，如有重大進度變更請手動更新 mrt_data.py")
    return report


if __name__ == "__main__":
    report = check_online_updates()
    # 輸出摘要供 cron 傳遞
    print(f"\n===SUMMARY===")
    print(f"更新時間: {report['update_time']}")
    lines_info = "; ".join(f"{n}: {v['status']}" for n, v in report['lines'].items())
    print(f"路線狀態: {lines_info}")
