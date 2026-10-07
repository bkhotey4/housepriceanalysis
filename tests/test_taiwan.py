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

from core import address, plvr, plvr_tw, prices, rent, taiwan  # noqa: E402
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
        files["d_lvr_land_c.csv"] = _read("fixture_d_lvr_land_c.csv")
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

    def test_flaky_downloads_keep_old_data(self):
        """前期清單、前期檔、本期檔下載失敗時：不中斷、不刪掉已下載的前期檔、不把空的本期檔標成完成。"""
        today = datetime.date(2026, 10, 2)
        plvr_tw.update(seasons_wanted=2, today=today, progress=lambda m: None)
        before = sorted(plvr_tw.folders())
        self.assertIn("hist_20260921", before)
        self.assertIn("cur", before)
        good = plvr.fetch

        def flaky(url, **kw):
            if "DownloadSeason" in url:
                return good(url, **kw)
            raise plvr.DownloadError("忙線")
        plvr.fetch = flaky
        plvr_tw.update(seasons_wanted=2, today=today + datetime.timedelta(days=5), progress=lambda m: None)
        self.assertEqual(sorted(plvr_tw.folders()), before)                       # 什麼都沒少
        with open(os.path.join(plvr_tw._dir("cur"), plvr_tw.DONE), encoding="utf-8") as f:
            self.assertEqual(f.read(), today.isoformat())                         # 本期檔還是上次的日期

    def test_cancelled_later_is_not_a_sale(self):
        """同一個編號：舊一期是有效成交、新一期標成解約 → 只算解約，不算成交。"""
        b = _read("fixture_d_lvr_land_b.csv").decode("utf-8-sig")
        import csv as _csv
        rows = list(_csv.reader(io.StringIO(b)))
        cancelled = [r for r in rows[2:] if len(r) > prices.C_CANCEL and r[prices.C_CANCEL].strip()]
        self.assertTrue(cancelled)
        valid_rows = [r[:prices.C_CANCEL] + [""] + r[prices.C_CANCEL + 1:] if r in cancelled else r for r in rows]
        for name, data in (("season_115S1", valid_rows), ("cur", rows)):
            os.makedirs(plvr_tw._dir(name), exist_ok=True)
            buf = io.StringIO()
            _csv.writer(buf).writerows(data)
            with open(os.path.join(plvr_tw._dir(name), "d_lvr_land_b.csv"), "w", encoding="utf-8") as f:
                f.write(buf.getvalue())
            plvr_tw._mark_done(name)
        cancels = []
        txs = plvr_tw.load_county("D", cancels)
        ids = {r[prices.C_ID] for r in cancelled}
        self.assertEqual({x["id"] for x in cancels}, ids)
        self.assertFalse(ids & {x["id"] for x in txs})

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
        # 租賃檔也一起展開
        rents = plvr_tw.load_county_rent("D")
        self.assertTrue(rents)
        self.assertEqual(plvr_tw.load_county_rent("A"), [])

    def test_old_cache_still_readable_and_refetched(self):
        """舊版下載的資料夾（只有 _done、沒有租賃檔）照樣讀得到；更新時會重抓一次補上租賃檔。"""
        plvr_tw.update(seasons_wanted=2, today=datetime.date(2026, 10, 2), progress=lambda m: None)
        for n in os.listdir(plvr_tw.CACHE):
            d = os.path.join(plvr_tw.CACHE, n)
            os.rename(os.path.join(d, plvr_tw.DONE), os.path.join(d, "_done"))
        self.assertTrue(plvr_tw.folders())
        self.assertTrue(plvr_tw.load_county("D"))
        before = len(self.calls)
        plvr_tw.update(seasons_wanted=2, today=datetime.date(2026, 10, 2), progress=lambda m: None)
        self.assertTrue(any("DownloadSeason" in u and "115S2" in u for u in self.calls[before:]))


class RentTest(unittest.TestCase):
    def setUp(self):
        self.items = rent.parse_rent_csv(_read("fixture_d_lvr_land_c.csv").decode("utf-8-sig"))

    def test_parse(self):
        ids = {x["id"] for x in self.items}
        self.assertEqual(len(self.items), 22)
        for bad in ("RPCFX0023", "RPCFX0024", "RPCFX0025", "RPCFX0026"):     # 親友、辦公、只有車位、日期錯
            self.assertNotIn(bad, ids)
        cats = {x["id"]: x["cat"] for x in self.items}
        self.assertEqual(cats["RPCFX0019"], "house")
        self.assertEqual(cats["RPCFX0020"], "room")      # 獨立套房
        self.assertEqual(cats["RPCFX0021"], "room")      # 分租雅房（雖然是公寓）
        park = next(x for x in self.items if x["id"] == "RPCFX0022")
        self.assertEqual(park["rent"], 22000)            # 扣掉車位 3000

    def test_header_by_name(self):
        """欄位順序換了也讀得到（依表頭名稱找欄位）。"""
        import csv as _csv
        rows = list(_csv.reader(io.StringIO(_read("fixture_d_lvr_land_c.csv").decode("utf-8-sig"))))
        order = list(range(len(rows[0])))[::-1]
        buf = io.StringIO()
        _csv.writer(buf).writerows([[r[i] for i in order] for r in rows])
        # 第一欄必須是「鄉鎮市區」才認得表頭：把它移回最前面
        text = buf.getvalue()
        rows2 = list(_csv.reader(io.StringIO(text)))
        k = rows2[0].index("鄉鎮市區")
        rows2 = [[r[k]] + r[:k] + r[k + 1:] for r in rows2]
        buf2 = io.StringIO()
        _csv.writer(buf2).writerows(rows2)
        self.assertEqual(len(rent.parse_rent_csv(buf2.getvalue())), 22)
        self.assertEqual(rent.parse_rent_csv("鄉鎮市區,交易標的\n東區,建物\n"), [])     # 缺必要欄位

    def test_book_and_yield(self):
        b = rent.build_rent_book(self.items, ["東區", "中西區", "永康區"], "2026-08", "臺南市")
        self.assertEqual(b["window"], ["2025-09", "2026-08"])
        east = b["data"]["東區"]
        self.assertEqual(east["apt"][0], 13)
        self.assertEqual(east["apt"][1], 22000)
        self.assertIn("s", east["rooms"])
        self.assertNotIn("永康區", b["data"])            # 沒有租賃就不列
        self.assertAlmostEqual(rent.gross_yield(733, 30), 733 * 12 / 300000 * 100)
        self.assertIsNone(rent.gross_yield(None, 30))


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
    def test_main_keeps_old_tra_when_tra_fails(self):
        """台鐵那幾區查詢失敗：捷運照常更新，台鐵沿用上一次的資料。"""
        import json as _json
        from unittest import mock
        from tools import build_transit as bt
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        out, web, rep = (os.path.join(tmp, n) for n in ("transit.json", "web/transit.json", "web/report.json"))
        old_tra = {"name": "台鐵", "kind": "台鐵", "color": "#5b6b7c", "counties": ["D"], "segments": [[23.0, 120.2, 23.1, 120.2]],
                   "stations": [["臺南站", 23.0, 120.2]], "operating": True, "approved": True}
        with open(out, "w", encoding="utf-8") as f:
            _json.dump({"as_of": "2026-01-01", "v": 3, "lines": [old_tra]}, f)

        def fake_ask(ql):
            if 'way["railway"="rail"]' in ql:
                raise RuntimeError("502")
            return _transit_fixture() if "subway" in ql else {"elements": []}
        towns = {"A": [{"name": "信義區", "lat": 25.033, "lng": 121.567}]}
        with mock.patch.object(bt, "ask", fake_ask), mock.patch.object(bt, "OUT", out), mock.patch.object(bt, "WEB_OUT", web), \
                mock.patch.object(bt, "REPORT", rep), mock.patch.object(bt.time, "sleep", lambda s: None), \
                mock.patch.object(bt, "load_towns", lambda: towns), mock.patch.object(sys, "argv", ["build_transit.py"]):
            bt.main()
        with open(out, encoding="utf-8") as f:
            new = _json.load(f)
        self.assertEqual(new["v"], bt.VERSION)
        kinds = {ln["name"]: ln.get("kind") for ln in new["lines"]}
        self.assertIn("淡水信義線", kinds)
        self.assertEqual(kinds.get("台鐵"), "台鐵")
        self.assertTrue(os.path.exists(web))

    def test_build_tra(self):
        """台鐵：抓軌道與車站合成一條；高鐵、糖鐵的軌道與捷運、高鐵車站都不算。"""
        from tools import build_transit
        towns = {"D": [{"name": "東區", "lat": 22.98, "lng": 120.22}], "E": [{"name": "左營區", "lat": 22.68, "lng": 120.30}]}
        g = lambda *pts: [{"lat": a, "lon": b} for a, b in pts]
        els = [
            {"type": "way", "id": 1, "tags": {"railway": "rail", "name": "縱貫線", "gauge": "1067"}, "geometry": g((22.997, 120.212), (22.98, 120.22))},
            {"type": "way", "id": 2, "tags": {"railway": "rail", "name": "縱貫線"}, "geometry": g((22.98, 120.22), (22.70, 120.30))},
            {"type": "way", "id": 3, "tags": {"railway": "rail", "highspeed": "yes", "name": "台灣高速鐵路"}, "geometry": g((22.92, 120.28), (22.68, 120.31))},
            {"type": "way", "id": 4, "tags": {"railway": "rail", "gauge": "762", "name": "烏樹林線"}, "geometry": g((23.3, 120.3), (23.31, 120.31))},
            {"type": "node", "id": 10, "lat": 22.9972, "lon": 120.2125, "tags": {"railway": "station", "name": "臺南"}},
            {"type": "node", "id": 11, "lat": 22.70, "lon": 120.3005, "tags": {"railway": "station", "name": "新左營", "operator": "臺灣鐵路"}},
            {"type": "node", "id": 12, "lat": 22.70, "lon": 120.3008, "tags": {"railway": "station", "name": "左營", "station": "subway"}},
            {"type": "node", "id": 13, "lat": 22.687, "lon": 120.307, "tags": {"railway": "station", "name": "左營", "operator": "台灣高鐵"}},
            {"type": "node", "id": 14, "lat": 23.5, "lon": 120.5, "tags": {"railway": "station", "name": "很遠的站"}},
        ]
        ln = build_transit.build_tra(els, towns)
        self.assertEqual(ln["name"], "台鐵")
        self.assertEqual(ln["kind"], "台鐵")
        self.assertEqual(sorted(s[0] for s in ln["stations"]), ["新左營站", "臺南站"])
        self.assertEqual(len(ln["segments"]), 1)                     # 兩段縱貫線接成一條；高鐵、糖鐵不算
        self.assertEqual(ln["counties"], ["D", "E"])
        self.assertIsNone(build_transit.build_tra([els[2], els[3]], towns))
        self.assertFalse(build_transit.is_tra_way({"railway": "rail", "operator": "台灣高鐵"}))
        self.assertTrue(build_transit.is_tra_way({"railway": "rail", "operator": "國營臺灣鐵路股份有限公司"}))

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



class CiReportTest(unittest.TestCase):
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
