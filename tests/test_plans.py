"""規劃中的公共建設（採購公告）：篩選標案名稱、取預算與地點、同一案合併、週末跳過、被限流時留到下次。"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import plans, plvr  # noqa: E402
from tools import build_plans  # noqa: E402

TOWNS = {"D": ["永康區", "新營區", "東區", "中西區"], "E": ["前鎮區"], "A": ["中正區"]}


def rec(title, typ="公開招標公告", cat="勞務類8672-工程服務", unit="臺南市政府交通局", job="J1", date=20261110, uid="3.1"):
    return {"date": date, "brief": {"type": typ, "title": title, "category": cat}, "unit_id": uid, "unit_name": unit,
            "job_number": job, "url": "/index/case/%s/%s/%d/x" % (uid, job, date)}


def tender(budget=None, award=None, loc="", winner=""):
    d = {}
    if budget:
        d["採購資料:預算金額"] = budget
    if award:
        d["決標資料:總決標金額"] = award
    if loc:
        d["其他:履約地點（含地區）"] = loc
    if winner:
        d["決標品項:第1品項:得標廠商1:得標廠商"] = winner
    return {"records": [{"date": 20261110, "detail": d}]}


class PlansTest(unittest.TestCase):
    def test_candidate(self):
        self.assertTrue(plans.candidate(rec("國道1號新營交流道新增太子路匝道可行性評估")))
        self.assertTrue(plans.candidate(rec("臺南市永康區西灣立體停車場（統包）新建工程")))
        self.assertFalse(plans.candidate(rec("新營區停五立體停車場新建工程（統包）第一次變更設計")))   # 變更設計
        self.assertFalse(plans.candidate(rec("三角公園無障礙公廁新建工程")))                          # 小設施
        self.assertFalse(plans.candidate(rec("國道1號匝道可行性評估", typ="無法決標公告")))           # 流標不收
        self.assertFalse(plans.candidate(rec("辦公室影印機採購")))
        self.assertFalse(plans.candidate(rec("2027月津港燈節燈區及光環境規劃設計執行案")))
        self.assertFalse(plans.candidate(rec("堤防新建工程碳足跡盤查作業")))
        self.assertEqual(plans.stage_of("縣道200線道路拓建工程環境影響評估委託技術服務"), "環評")

    def test_item(self):
        r = rec("國道1號新營交流道新增太子路匝道可行性評估")
        it = plans.item_from(r, tender("3,500,000元", loc="臺南市－新營區"), TOWNS)
        self.assertEqual((it["county"], it["district"], it["stage"], it["budget_wan"], it["status"]), ("D", "新營區", "可行性評估", 350.0, "招標中"))
        self.assertIsNone(plans.item_from(r, tender("500,000元"), TOWNS))                          # 委託案 100 萬以下不收
        w = rec("前鎮區體育館新建工程", typ="決標公告", cat="工程類5139-其他土木工程", unit="高雄市政府工務局")
        self.assertIsNone(plans.item_from(w, tender("30,000,000元"), TOWNS))                       # 工程 5,000 萬以下不收
        it = plans.item_from(w, tender("90,000,000元", "88,000,000元", winner="某營造"), TOWNS)
        self.assertEqual((it["county"], it["district"], it["award_wan"], it["winner"], it["status"]), ("E", "前鎮區", 8800.0, "某營造", "已決標"))
        self.assertEqual(plans.town_in("中正路拓寬工程可行性評估", TOWNS["A"]), "")                  # 路名不算行政區

    def test_merge(self):
        a = dict(plans.item_from(rec("永康區停車場新建工程", cat="工程類", job="J9", date=20261001), tender("80,000,000元"), TOWNS))
        b = dict(plans.item_from(rec("永康區停車場新建工程", typ="決標公告", cat="工程類", job="J9-1", date=20261105), tender("80,000,000元", "70,000,000元"), TOWNS))
        out = plans.merge([a], [b])
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["first"], out[0]["last"], out[0]["status"], out[0]["award_wan"]), ("20261001", "20261105", "已決標", 7000.0))

    def test_run(self):
        tmp = tempfile.mkdtemp()
        old = (plvr.fetch, build_plans.WEB_TW)
        build_plans.WEB_TW = os.path.join(tmp, "web")
        calls = []
        good = rec("國道1號新營交流道新增太子路匝道可行性評估", job="OK", date=20261110)
        busy = rec("永康區西灣立體停車場（統包）新建工程", cat="工程類", job="BUSY", date=20261110)

        def fetch(url, **kw):
            calls.append(url)
            if "listbydate" in url:
                if "20261110" in url:
                    return ('{"records": [%s, %s]}' % tuple(__import__("json").dumps(r, ensure_ascii=False) for r in (good, busy))).encode("utf-8")
                if "20261109" in url:
                    raise plvr.DownloadError("HTTP 500")                  # 國定假日之類：下次再試
                return b'{"records": []}'
            if "BUSY" in url:
                raise plvr.DownloadError("HTTP 429 Too Many Requests")
            return __import__("json").dumps(tender("3,500,000元", loc="臺南市－新營區")).encode("utf-8")
        try:
            plvr.fetch = fetch
            today = datetime.date(2026, 11, 11)           # 週三
            st, s = build_plans.run({"through": "20261105", "pending": [], "items": []}, today, TOWNS, sleep=lambda x: None)
            self.assertFalse(any("20261107" in u or "20261108" in u for u in calls))     # 週末不抓
            self.assertEqual(st["through"], "20261110")
            self.assertEqual(st["missing"], ["20261109"])
            self.assertEqual([it["key"] for it in st["items"]], ["3.1|OK"])
            self.assertEqual([r["job_number"] for r in st["pending"]], ["BUSY"])            # 被限流的留到下次
            build_plans.write_web(st, today)
            self.assertTrue(os.path.exists(os.path.join(build_plans.WEB_TW, "D", "plans.json")))
        finally:
            plvr.fetch, build_plans.WEB_TW = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
