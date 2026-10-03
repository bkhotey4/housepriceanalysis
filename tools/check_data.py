"""檢查 data/intel.json 與 data/mrt.json 的格式；更新情資後執行。

    python tools/check_data.py

格式正確時最後一行是「資料格式正確」，結束代碼 0；有問題會逐項列出，結束代碼 1。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import datacheck, geo  # noqa: E402

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    problems = datacheck.check_all()
    for p in problems:
        print("[問題] " + p)
    if problems:
        print("\n共 %d 個問題，請修正後再執行一次。" % len(problems))
        sys.exit(1)
    intel, mrt = geo.load_json("intel.json"), geo.load_json("mrt.json")
    print("情資 %d 筆（查證日 %s）、捷運 %d 條路線、鐵路計畫 %d 項（查證日 %s）" % (
        len(intel["items"]), intel["as_of"], len(mrt["lines"]), len(mrt.get("rail_projects", [])), mrt["as_of"]))
    print("資料格式正確")
