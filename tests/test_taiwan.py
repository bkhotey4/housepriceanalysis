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


def _transit_fixture():
    """假的 Overpass 回傳：同一條線兩個方向（兩段路線接起來）＋另一個城市同名的「綠線」。"""
    g1 = [{"lat": 25.033, "lon": 121.565}, {"lat": 25.041, "lon": 121.557}, {"lat": 25.052, "lon": 121.544}]
    g2 = [{"lat": 25.052, "lon": 121.544}, {"lat": 25.063, "lon": 121.526}]
    els = [
        {"type": "relation", "id": 1, "tags": {"route": "subway", "name": "臺北捷運淡水信義線：象山 → 淡水", "colour": "#E3002C", "network": "臺北捷運"},
         "members": [{"type": "way", "ref": 11, "role": "", "geometry": g1}, {"type": "way", "ref": 12, "role": "", "geometry": g2},
                     {"type": "node", "ref": 101, "role": "stop", "lat": 25.033, "lon": 121.565},
                     {"type": "node", "ref": 102, "role": "stop_entry_only", "lat": 25.063, "lon": 121.526}]},
        {"type": "relation", "id": 2, "tags": {"route": "subway", "name": "臺北捷運淡水信義線：淡水 → 象山", "colour": "#E3002C"},
         "members": [{"type": "way", "ref": 12, "role": "", "geometry": g2[::-1]}, {"type": "node", "ref": 101, "role": "stop", "lat": 25.033, "lon": 121.565}]},
        {"type": "relation", "id": 3, "tags": {"route": "subway", "name": "綠線", "network": "臺北捷運"},
         "members": [{"type": "way", "ref": 21, "role": "", "geometry": g1}]},
        {"type": "relation", "id": 4, "tags": {"route": "light_rail", "name": "綠線", "network": "臺中捷運", "colour": "bad"},
         "members": [{"type": "way", "ref": 31, "role": "", "geometry": [{"lat": 24.16, "lon": 120.64}, {"lat": 24.17, "lon": 120.66}]},
                     {"type": "node", "ref": 301, "role": "stop", "lat": 24.16, "lon": 120.64}]},
        {"type": "node", "id": 101, "tags": {"name": "台北101/世貿"}},
        {"type": "node", "id": 102, "tags": {"name": "中山站"}},
        {"type": "node", "id": 301, "tags": {"name": "北屯總站"}},
    ]
    return {"elements": els}


class TransitTest(unittest.TestCase):
    def test_build_merges_directions(self):
        from tools import build_transit
        towns = {"A": [{"name": "信義區", "lat": 25.033, "lng": 121.567}], "B": [{"name": "北屯區", "lat": 24.18, "lng": 120.69}]}
        lines = build_transit.build(_transit_fixture(), towns)
        names = [ln["name"] for ln in lines]
        self.assertIn("淡水信義線", names)                       # 兩個方向合併成一條，名稱去掉「臺北捷運」與起迄站
        ln = next(x for x in lines if x["name"] == "淡水信義線")
        self.assertEqual(ln["color"], "#e3002c")
        self.assertEqual(ln["counties"], ["A"])
        self.assertEqual(len(ln["segments"]), 1)                 # 兩段頭尾相接 → 一條
        self.assertEqual(sorted(s[0] for s in ln["stations"]), ["中山站", "台北101/世貿站"])
        greens = [x for x in lines if "綠線" in x["name"]]
        self.assertEqual(sorted(x["name"] for x in greens), ["臺中捷運綠線"])     # 台北的假「綠線」沒有車站、又不認得：略過
        tc = next(x for x in lines if x["counties"] == ["B"])
        self.assertTrue(tc["color"].startswith("#") and len(tc["color"]) == 7)   # 顏色格式不對就用預設
        self.assertEqual(tc["kind"], "輕軌")
        for x in lines:
            for seg in x["segments"]:
                self.assertEqual(len(seg) % 2, 0)
        # OSM 實際的寫法：方向、支線放在括號裡
        k = build_transit.line_key
        self.assertEqual(k({"name": "台北捷運中和新蘆線(蘆洲逆向)"}), k({"name": "台北捷運中和新蘆線(迴龍順向)"}))
        self.assertEqual(build_transit.short_name(k({"name": "台北捷運松山新店線(順向)"})), "松山新店線")
        self.assertEqual(build_transit.short_name(k({"name": "南港-板橋-土城線"})), "板南線")
        # OSM 上實際的各種寫法都要歸到同一條線
        same = {
            "淡水信義線": ["臺北捷運 淡水線-信義線 (南向)", "淡水信義線", "臺北捷運淡水信義線：象山 → 淡水"],
            "松山新店線": ["台北捷運松山新店線(順向)", "台電大樓 => 松山", "松山 => 台電大樓"],
            "環狀線": ["臺北捷運環狀線（大坪林->新北產業園區）", "新北捷運環狀線（新北產業園區->大坪林）"],
            "桃園機場捷運": ["桃園機場捷運 普通車 台北車站 → 老街溪", "桃園國際機場捷運 直達車 機場第二航廈 → 台北車站"],
            "高雄捷運紅線": ["高雄捷運紅線 小港-岡山車站", "高雄捷運紅線 岡山車站-小港"],
            "高雄環狀輕軌": ["高雄環狀輕軌 (順行)", "高雄環狀輕軌 (逆行)"],
            "台灣高鐵": ["台灣高鐵 603 南港->左營", "台灣高鐵 1602 左營->南港", "台灣高鐵 598 左營->台中"],
            "新北投支線": ["捷運紅線 (新北投支線) MRT red line (Xinbeitou Branch Line)"],
            "淡海輕軌": ["淡海輕軌藍海線", "淡海輕軌 紅樹林-崁頂 (上行)"],
            "安坑輕軌": ["安坑輕軌(東向)", "安坑輕軌(西向)"],
            "臺中捷運綠線": ["臺中捷運綠線高鐵台中站方向", "臺中捷運綠線北屯總站方向"],
        }
        for want, names in same.items():
            for n in names:
                self.assertEqual(build_transit.short_name(k({"name": n})), want, n)
        # 觀光五分車不算高鐵
        raw = {"elements": [{"type": "relation", "id": 9, "tags": {"route": "train", "name": "蒜頭蔗埕文化園區五分車 (五分車高鐵站方向)"},
                             "members": [{"type": "way", "ref": 99, "role": "", "geometry": [{"lat": 23.5, "lon": 120.3}, {"lat": 23.51, "lon": 120.31}]}]}]}
        self.assertEqual(build_transit.build(raw, towns), [])


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



class ErrorLogTest(unittest.TestCase):
    def test_desktop_errlog(self):
        from core import errlog
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old = errlog.LOG_DIR, errlog.LOG_PATH
        errlog.LOG_DIR, errlog.LOG_PATH = tmp, os.path.join(tmp, "app_errors.log")
        try:
            try:
                1 / 0
            except ZeroDivisionError:
                errlog.write("測試")
        finally:
            path = errlog.LOG_PATH
            errlog.LOG_DIR, errlog.LOG_PATH = old
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("測試", text)
        self.assertIn("ZeroDivisionError", text)

    def test_ci_report(self):
        import subprocess
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(tmp, "tools"))
        os.makedirs(os.path.join(tmp, "logs", "ci", "raw"))
        with open(os.path.join(tmp, "logs", "ci", "steps.tsv"), "w", encoding="utf-8") as f:
            f.write("plvr\t全台實價登錄\t1\t12\t0\ncheck\t資料檢查\t0\t1\t1\n")
        with open(os.path.join(tmp, "logs", "ci", "raw", "plvr.log"), "w", encoding="utf-8") as f:
            f.write("下載季檔…\nDownloadError: 找不到任何可下載的季檔\n")
        env = dict(os.environ)
        env.pop("GH_TOKEN", None)
        r = subprocess.run([sys.executable, os.path.join(tmp, "tools", "ci_report.py"), "schedule"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)                 # 非必要步驟失敗：照樣部署
        with open(os.path.join(tmp, "web", "data", "status.json"), encoding="utf-8") as f:
            st = __import__("json").load(f)
        self.assertFalse(st["ok"])
        self.assertEqual(st["failed"], ["全台實價登錄"])
        with open(os.path.join(tmp, "logs", "ci", "latest.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("找不到任何可下載的季檔", md)
        # 必要步驟失敗：結束代碼 1（這次不部署）
        with open(os.path.join(tmp, "logs", "ci", "steps.tsv"), "w", encoding="utf-8") as f:
            f.write("check\t資料檢查\t1\t1\t1\n")
        r = subprocess.run([sys.executable, os.path.join(tmp, "tools", "ci_report.py"), "push"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
