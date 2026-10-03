"""全台版的資料管線：縣市名稱判斷、全國實價登錄下載（用假的伺服器回應）、鄉鎮清單整理。"""
import datetime
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import address, plvr, plvr_tw, prices, taiwan  # noqa: E402
from tools import export_tw  # noqa: E402

FIX = os.path.join(ROOT, "tests")


def _read(name):
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


def _as_taipei(b):
    """把台南的範例檔改成臺北市的樣子（門牌換縣市、行政區換成大安區、編號加前綴避免去重）。"""
    t = b.decode("utf-8-sig")
    t = t.replace("臺南市", "臺北市").replace("善化區", "大安區").replace("中西區", "大安區")
    lines = t.split("\n")
    out = lines[:2] + [ln.replace(",RPQ", ",TPQ") if ln else ln for ln in lines[2:]]
    return ("﻿" + "\n".join(out)).encode("utf-8")


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class CountyNameTest(unittest.TestCase):
    def test_split(self):
        cases = {"臺北市大安區信義路": ("A", "大安區信義路"), "台南善化區中山路": ("D", "善化區中山路"),
                 "桃園區中正路": (None, "桃園區中正路"), "基隆路一段": (None, "基隆路一段"),
                 "新竹縣竹北市": ("J", "竹北市"), "台中西屯區": ("B", "西屯區"), "嘉義市東區": ("I", "東區")}
        for text, (code, rest) in cases.items():
            c, r = taiwan.split_county(text)
            self.assertEqual((c and c["code"], r), (code, rest), text)
        self.assertEqual(len(taiwan.COUNTIES), 22)
        self.assertEqual(len({c["code"] for c in taiwan.COUNTIES}), 22)

    def test_address_any_county(self):
        self.assertEqual(address.normalize("臺北市大安區信義路三段１００號"), "大安區信義路三段100號")
        self.assertEqual(prices.road_of("高雄市苓雅區四維三路2號", "苓雅區"), "四維三路")
        self.assertEqual(prices.road_of("臺南市善化區中山路１２３號", "善化區"), "中山路")


class NationalDownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = plvr_tw.CACHE
        plvr_tw.CACHE = os.path.join(self.tmp, "plvr_tw")
        self.calls = []
        a, b = _read("fixture_d_lvr_land_a.csv"), _read("fixture_d_lvr_land_b.csv")
        files = {}
        for c in taiwan.COUNTIES:
            code = c["code"].lower()
            files["%s_lvr_land_a.csv" % code] = _as_taipei(a) if code == "a" else (a if code == "d" else a[:a.index(b"\n", a.index(b"\n") + 1) + 1])
            files["%s_lvr_land_b.csv" % code] = b if code == "d" else b[:b.index(b"\n", b.index(b"\n") + 1) + 1]
        self.zip = _zip(files)

        def fake_fetch(url, timeout=90, insecure=False, data=None, agent=None, headers=None):
            self.calls.append(url)
            if "DownloadSeason" in url:
                return self.zip if ("115S2" in url or "115S1" in url) else b"<html>\xe7\xb3\xbb\xe7\xb5\xb1\xe8\xa8\x8a\xe6\x81\xaf</html>"
            if "DownloadHistory_ajax_list" in url:
                return "發布日期 20260911 downloadLast('20260921')".encode("utf-8")
            if "DownloadHistory" in url or "Download?type=zip" in url:
                return self.zip
            return b"<html></html>"
        self.orig = plvr.fetch
        plvr.fetch = fake_fetch
        self.sleep = plvr_tw.time.sleep
        plvr_tw.time.sleep = lambda s: None

    def tearDown(self):
        plvr.fetch = self.orig
        plvr_tw.time.sleep = self.sleep
        plvr_tw.CACHE = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_and_load(self):
        names = plvr_tw.update(seasons_wanted=2, today=datetime.date(2026, 10, 2), progress=lambda m: None)
        self.assertIn("cur", names)
        self.assertTrue(any(n.startswith("season_115S2") for n in names))
        self.assertTrue(any(n.startswith("hist_2026092") for n in names))
        tn = plvr_tw.load_county("D")
        tp = plvr_tw.load_county("A")
        self.assertTrue(tn and tp)
        self.assertTrue(all(x["addr"].startswith("臺北市") for x in tp))
        self.assertIn("大安區", {x["dist"] for x in tp})
        # 再跑一次：季檔與前期檔不重抓，只重抓本期
        before = len(self.calls)
        plvr_tw.update(seasons_wanted=2, today=datetime.date(2026, 10, 2), progress=lambda m: None)
        again = self.calls[before:]
        self.assertFalse(any("DownloadSeason" in u and "115S2" in u for u in again))
        self.assertTrue(any("Download?type=zip" in u for u in again))


class TownListTest(unittest.TestCase):
    def test_town_list_adds_missing_and_uses_tx_spelling(self):
        county = taiwan.BY_CODE["V"]
        osm = [{"name": "台東市", "lat": 22.75, "lng": 121.14}]
        txs = [{"dist": "臺東市"}, {"dist": "臺東市"}, {"dist": "卑南鄉"}]
        out = export_tw.town_list(county, osm, txs)
        names = [t["name"] for t in out]
        self.assertEqual(names[0], "臺東市")            # 用實價登錄的寫法
        self.assertIn("卑南鄉", names)
        self.assertTrue([t for t in out if t["name"] == "卑南鄉"][0]["approx"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
