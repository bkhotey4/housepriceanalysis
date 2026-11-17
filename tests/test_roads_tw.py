"""全台道路位置：同一區好幾天都抓不到（例如烏坵在 OpenStreetMap 上幾乎沒有道路）就存成空檔，不再每次重試。"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import fetch_roads_tw as F  # noqa: E402

COUNTY = {"code": "W", "name": "金門縣", "short": "金門縣"}


class GiveUpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = [mock.patch.object(F, "OUT", os.path.join(self.tmp, "web")),
                  mock.patch.object(F, "FAILS", os.path.join(self.tmp, "fail.json")),
                  mock.patch.object(F, "COUNTIES", [COUNTY]),
                  mock.patch.object(F, "load_towns", lambda: {"W": [{"name": "烏坵鄉"}, {"name": "金城鎮"}]}),
                  mock.patch.object(F.time, "sleep", lambda s: None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        shutil.rmtree(self.tmp)

    def run_day(self, day):
        def fetch(county, town):
            if town == "烏坵鄉":
                raise RuntimeError("The read operation timed out")
            return {"roads": {"民權路": [[(118.3, 24.4), (118.31, 24.41)]]}, "places": {}, "fetched": day}
        with mock.patch.object(F, "fetch_one", fetch), mock.patch.object(F.time, "strftime", lambda fmt: day), \
                mock.patch.object(sys, "argv", ["x", "--minutes", "5"]):
            F.main()

    def test_give_up_after_days(self):
        wuqiu = F.out_path("W", "烏坵鄉")
        self.run_day("2026-11-13")
        self.run_day("2026-11-13")                 # 同一天跑兩次只算一天
        with open(F.FAILS, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"金門縣烏坵鄉": ["2026-11-13"]})
        self.assertTrue(os.path.exists(F.out_path("W", "金城鎮")))
        for d in ("2026-11-14", "2026-11-15"):
            self.run_day(d)
        self.assertFalse(os.path.exists(wuqiu))
        self.run_day("2026-11-16")                 # 第 4 天：存成空檔、清掉失敗紀錄
        with open(wuqiu, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["roads"], {})
        self.assertEqual(data["fetched"], "2026-11-16")
        with open(F.FAILS, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {})

    def test_success_clears(self):
        fails = {"金門縣金城鎮": ["2026-11-10"]}
        F.save_fails(fails)
        self.run_day("2026-11-13")
        with open(F.FAILS, encoding="utf-8") as f:
            self.assertNotIn("金門縣金城鎮", json.load(f))


if __name__ == "__main__":
    unittest.main()
