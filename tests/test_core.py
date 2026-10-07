"""核心邏輯測試（不需要視窗）。執行： python -m unittest discover -s tests -v"""
import datetime
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

from core import basemap, datacheck, geo, plvr, prices  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixture_d_lvr_land_a.csv")
FIXTURE_B = os.path.join(ROOT, "tests", "fixture_d_lvr_land_b.csv")


def fixture_bytes(path=FIXTURE):
    with open(path, "rb") as f:
        return f.read()


class ParseTest(unittest.TestCase):
    """用 11 列真實的實價登錄資料驗證解析結果（期望值由官方檔案另行計算）。"""

    def setUp(self):
        self.txs = prices.parse_csv_text(fixture_bytes().decode("utf-8-sig"))

    def test_filters(self):
        # 8 筆有效；親友交易、純車位、純土地各 1 筆被排除
        self.assertEqual(len(self.txs), 8)
        self.assertNotIn("北區", [x["dist"] for x in self.txs])
        self.assertNotIn("白河區", [x["dist"] for x in self.txs])

    def test_values(self):
        expected = [("新營區", "2026-05", "apt", 11.14, 400), ("中西區", "2026-05", "walkup", 14.08, 120),
                    ("安平區", "2026-05", "apt", 22.77, 250), ("歸仁區", "2026-05", "apt", 44.89, 2395),
                    ("仁德區", "2026-05", "house", 23.78, 1650), ("仁德區", "2026-05", "house", 15.79, 2400),
                    ("安平區", "2026-05", "apt", 18.87, 340), ("南區", "2026-05", "walkup", 11.39, 260)]
        got = [(x["dist"], x["ym"], x["cat"], round(x["u"], 2), round(x["tw"])) for x in self.txs]
        self.assertEqual(got, expected)

    def test_parking_excluded_from_unit_price(self):
        # 歸仁高鐵大道：總價 2395 萬含車位 400 萬，單價應為扣除車位後的 44.89 萬/坪
        x = next(t for t in self.txs if t["dist"] == "歸仁區")
        self.assertAlmostEqual(x["u"], (23950000 - 4000000) / (197.8 - 50.88) * prices.PING_M2 / 10000, places=1)

    def test_floor_and_parking(self):
        # 移轉層次轉成樓層數字；整棟（全）、地下室、跨層看不懂的不給樓層
        for text, want in (("五層", 5), ("十層", 10), ("十二層", 12), ("二十三層", 23), ("四十層", 40),
                           ("全", None), ("地下一層", None), ("四層，五層", None), ("", None)):
            self.assertEqual(prices.floor_of(text), want, text)
        self.assertEqual([x["fl"] for x in self.txs], [4, 5, 3, 6, None, None, 20, 5])
        # 歸仁高鐵大道：2 個車位、車位 50.88 平方公尺、400 萬
        x = next(t for t in self.txs if t["dist"] == "歸仁區")
        self.assertEqual(x["pk"], 2)
        self.assertAlmostEqual(x["pka"], 50.88 / prices.PING_M2, places=3)
        self.assertEqual(x["pkp"], 400)
        self.assertEqual(sum(t["pk"] for t in self.txs), 2)
        # 網頁版 tx.json 的最後五欄；舊快取沒有這些欄位時給預設值
        self.assertEqual(prices.tx_extra(x), [6, 2, round(50.88 / prices.PING_M2, 2), 400.0, prices.PARK_FLAT])
        self.assertEqual(prices.tx_extra({}), [])                               # 全是預設值：整段省略
        self.assertEqual(prices.tx_extra({"fl": 7}), [7])

    def test_parking_type_and_cancellations(self):
        # 車位類別：坡道平面＝平面（1）
        x = next(t for t in self.txs if t["dist"] == "歸仁區")
        self.assertEqual(x["pkt"], prices.PARK_FLAT)
        for text, want in (("坡道平面", 1), ("升降機械", 2), ("塔式車位", 2), ("一樓平面", 1), ("其他", 0), ("", 0)):
            self.assertEqual(prices.park_type_of(text), want, text)
        # 預售屋檔：已解約的平常會被排除；keep_cancelled=True 時帶 cancel 標記回傳，可以算建案解約率
        text = open(os.path.join(ROOT, "tests", "fixture_d_lvr_land_b.csv"), encoding="utf-8-sig").read()
        normal, everything = prices.parse_csv_text(text), prices.parse_csv_text(text, keep_cancelled=True)
        cancelled = [t for t in everything if t["cancel"]]
        self.assertEqual(len(everything), len(normal) + len(cancelled))
        self.assertTrue(cancelled)
        self.assertFalse(any(t["cancel"] for t in normal))
        dists = sorted({t["dist"] for t in everything})
        counts = prices.cancel_counts(cancelled, dists)
        self.assertEqual(sum(n for _d, _p, n in counts), len(cancelled))
        self.assertEqual(dists[counts[0][0]], cancelled[0]["dist"])

    def test_dedupe(self):
        self.assertEqual(len(prices.dedupe(self.txs + self.txs)), 8)


class BookTest(unittest.TestCase):
    def test_complete_through_rule(self):
        # 2026-09-30 擷取時全市各月件數：8 月申報未齊（116 件）應被判定為不完整
        counts = {"2025-08": 542, "2025-09": 624, "2025-10": 730, "2025-11": 728, "2025-12": 740, "2026-01": 765,
                  "2026-02": 511, "2026-03": 828, "2026-04": 800, "2026-05": 895, "2026-06": 656, "2026-07": 494,
                  "2026-08": 116, "2026-09": 1}
        self.assertEqual(prices.find_complete_through(counts), "2026-07")

    def test_month_math(self):
        self.assertEqual(prices.ym_add("2026-01", -1), "2025-12")
        self.assertEqual(prices.ym_add("2025-11", 3), "2026-02")
        self.assertEqual(prices.ym_range("2025-11", "2026-02"), ["2025-11", "2025-12", "2026-01", "2026-02"])

    def test_median(self):
        self.assertEqual(prices.median([3, 1, 2]), 2)
        self.assertEqual(prices.median([4, 1, 2, 3]), 2.5)
        self.assertEqual(prices.median([]), 0)

    def test_build_book_from_fixture(self):
        txs = prices.parse_csv_text(fixture_bytes().decode("utf-8-sig"))
        names = [d["name"] for d in geo.load_districts()]
        raw = prices.build_book(txs, names, as_of="2026-06-10")
        book = prices.PriceBook(raw)
        self.assertEqual(book.complete_through, "2026-05")
        self.assertEqual(len(book.months), 12)
        cell = book.cell("仁德區", "house")
        self.assertEqual(cell["h6"][0], 2)
        self.assertEqual(cell["h6"][2], 2025)      # (1650+2400)/2
        self.assertEqual(book.cell(prices.CITY, "all")["h6"][0], 8)
        self.assertEqual(book.cell(prices.CITY, "apt")["h6"][0], 4)
        self.assertIsNone(book.trend("仁德區", "house"))   # 樣本不足不算漲跌

    def test_snapshot(self):
        with open(prices.SNAPSHOT_PATH, encoding="utf-8") as f:
            import json
            book = prices.PriceBook(json.load(f))
        self.assertEqual(len(book.data), 38)
        self.assertEqual(len(book.months), 13)
        city = book.cell(prices.CITY, "all")
        self.assertEqual(city["h6"], [4184, 25.6, 974])
        self.assertEqual(sum(city["n"][6:12]), 4184)          # 近半年 6 個月件數加總一致
        self.assertAlmostEqual(book.trend(prices.CITY, "all"), (25.5 - 25.8) / 25.8 * 100, places=6)
        # 各區件數加總 = 全市
        for cat in ("all", "house", "apt"):
            total = sum(book.cell(d, cat)["y12"][0] for d in book.districts())
            self.assertEqual(total, book.cell(prices.CITY, cat)["y12"][0], cat)
        self.assertEqual(set(book.districts()), set(d["name"] for d in geo.load_districts()))
        b = book.best("龍崎區", "all")
        self.assertIsNone(b["value"])
        b = book.best("大內區", "all")     # 近半年只有 3 件 -> 改用近一年並標示樣本少
        self.assertEqual((b["window"], b["low"]), ("y12", True))


class PlvrTest(unittest.TestCase):
    def test_season_candidates(self):
        c = plvr.season_candidates(datetime.date(2026, 9, 30))
        self.assertEqual(c[:4], [(115, 3), (115, 2), (115, 1), (114, 4)])
        self.assertEqual(plvr.season_name(115, 2), "115S2")
        self.assertEqual(plvr.season_end_date(115, 2), "20260610")

    def test_detection_and_history(self):
        self.assertTrue(plvr.looks_like_csv(fixture_bytes()))
        self.assertFalse(plvr.looks_like_csv(b"<table><tr><td>\xe7\xb3\xbb\xe7\xb5\xb1\xe8\xa8\x8a\xe6\x81\xaf</td></tr></table>"))
        html = "前期下載 發布日期 20260701 <a href=\"javaScript:downloadLast('20260711')\">下載</a> 發布日期 20260711"
        self.assertEqual(plvr.parse_history_dates(html), ["20260701", "20260711"])

    def test_extract_city_csv(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("a_lvr_land_a.csv", "x")
            z.writestr("d_lvr_land_a.csv", fixture_bytes())
        self.assertEqual(plvr.extract_city_csv(buf.getvalue()), fixture_bytes())

    def test_update_with_fake_server(self):
        """模擬官方伺服器：最新一季尚未釋出（回 HTML）、前期檔為 zip、本期檔為 CSV。"""
        html_msg = "<table><tr><td>系統訊息</td></tr></table>".encode("utf-8")
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("d_lvr_land_a.csv", fixture_bytes())
            z.writestr("d_lvr_land_b.csv", fixture_bytes(FIXTURE_B))
        calls = []

        def fake_fetch(url, timeout=90, insecure=False):
            calls.append(url)
            presale = "lvr_land_B" in url
            if "DownloadSeason" in url:
                return html_msg if "115S3" in url else fixture_bytes(FIXTURE_B if presale else FIXTURE)
            if "DownloadHistory_ajax_list" in url:
                return "發布日期 20260601 發布日期 20260701 發布日期 20260711".encode("utf-8")
            if "DownloadHistory?" in url:
                return zbuf.getvalue()
            return fixture_bytes(FIXTURE_B if presale else FIXTURE)

        with tempfile.TemporaryDirectory() as tmp:
            saved = (plvr.fetch, plvr.PLVR_DIR, prices.BOOK_CACHE_PATH, prices.TX_CACHE_PATH, plvr.MIN_SEASON_BYTES)
            plvr.fetch = fake_fetch
            plvr.MIN_SEASON_BYTES = 100      # 測試用的檔案很小
            plvr.PLVR_DIR = os.path.join(tmp, "plvr")
            prices.BOOK_CACHE_PATH = os.path.join(tmp, "pricebook.json")
            prices.TX_CACHE_PATH = os.path.join(tmp, "transactions.json")
            # save_book / save_transactions 以預設參數綁定路徑，這裡包一層
            orig_sb, orig_st = prices.save_book, prices.save_transactions
            prices.save_book = lambda raw, path=None: orig_sb(raw, prices.BOOK_CACHE_PATH)
            prices.save_transactions = lambda txs, path=None: orig_st(txs, prices.TX_CACHE_PATH)
            try:
                msgs = []
                book, n = plvr.update(progress=lambda d, t, m: msgs.append((d, t, m)), seasons_wanted=3,
                                      today=datetime.date(2026, 9, 30))
                self.assertEqual(n, 11)                      # 多個檔案內容相同，去重後是 8 筆買賣 + 3 筆預售
                self.assertEqual(book.source, "live")
                self.assertEqual(book.cell(prices.CITY, "all")["y12"][0], 8)       # 「全部合併」不含預售
                self.assertEqual(book.cell(prices.CITY, "presale")["y12"][0], 3)
                files = sorted(os.listdir(plvr.PLVR_DIR))
                self.assertEqual(files, ["cur.csv", "cur_b.csv", "hist_20260701.csv", "hist_20260701_b.csv",
                                         "hist_20260711.csv", "hist_20260711_b.csv",
                                         "season_114S4.csv", "season_114S4_b.csv", "season_115S1.csv",
                                         "season_115S1_b.csv", "season_115S2.csv", "season_115S2_b.csv"])
                self.assertFalse(any("20260601" in u for u in calls if "DownloadHistory?" in u))  # 已含在季檔內的期別不重抓
                self.assertTrue(msgs and msgs[-1][0] == msgs[-1][1])
                txs = prices.load_transactions(prices.TX_CACHE_PATH)
                self.assertEqual(len(txs), 11)
                self.assertEqual(txs[0]["ym"], txs[0]["date"][:7])
                self.assertEqual(sorted(set(x["kind"] for x in txs)), ["presale", "sale"])
                self.assertIn("勝美AI", [x["proj"] for x in txs])
                # 第二次更新：季檔與前期檔都已快取，只會再探測最新一季 + 清單 + 本期檔
                calls.clear()
                plvr.update(seasons_wanted=3, today=datetime.date(2026, 9, 30))
                self.assertEqual(len(calls), 4)              # 探測新一季、前期清單、本期買賣檔、本期預售檔
            finally:
                (plvr.fetch, plvr.PLVR_DIR, prices.BOOK_CACHE_PATH, prices.TX_CACHE_PATH,
                 plvr.MIN_SEASON_BYTES) = saved
                prices.save_book, prices.save_transactions = orig_sb, orig_st


class BasemapTileMathTest(unittest.TestCase):
    def test_tile_range_and_bounds(self):
        self.assertEqual(basemap.tile_range(13), (6827, 6841, 3547, 3561))     # 15 x 15 = 225 張
        self.assertEqual(basemap.tile_range(12), (3413, 3420, 1773, 1780))     # 8 x 8 = 64 張
        x0, x1, y0, y1 = basemap.tile_range(13)
        self.assertLessEqual(basemap.x_to_lng(x0, 13), basemap.WEST)
        self.assertGreaterEqual(basemap.x_to_lng(x1 + 1, 13), basemap.EAST)
        self.assertGreaterEqual(basemap.y_to_lat(y0, 13), basemap.NORTH)
        self.assertLessEqual(basemap.y_to_lat(y1 + 1, 13), basemap.SOUTH)
        # 來回轉換
        self.assertAlmostEqual(basemap.y_to_lat(basemap.lat_to_y(23.0, 13), 13), 23.0, places=9)
        self.assertAlmostEqual(basemap.x_to_lng(basemap.lng_to_x(120.2, 13), 13), 120.2, places=9)
        # 2026-09-30 在瀏覽器實際確認過有影像的圖磚：z12 / y1778 / x3415（台南市區）
        self.assertEqual((int(basemap.lng_to_x(120.2, 12)), int(basemap.lat_to_y(23.0, 12))), (3415, 1778))


@unittest.skipUnless(basemap.HAVE_PIL, "未安裝 Pillow，略過衛星底圖測試")
class BasemapTest(unittest.TestCase):
    def _jpeg(self, color):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), color).save(buf, "JPEG", quality=95)
        return buf.getvalue()

    def test_download_mosaic_and_reload(self):
        calls = []

        def fake_fetch(url, timeout=30, insecure=False):
            calls.append(url)
            z, y, x = [int(v) for v in url.rsplit("/", 3)[1:]]
            return self._jpeg((x % 2 * 200 + 20, y % 2 * 200 + 20, 60))

        with tempfile.TemporaryDirectory() as tmp:
            saved = (plvr.fetch, basemap.CACHE_DIR)
            plvr.fetch, basemap.CACHE_DIR = fake_fetch, tmp
            try:
                msgs = []
                bm = basemap.download(z=12, progress=lambda d, t, m: msgs.append((d, t)))
                self.assertEqual(len(calls), 64)
                self.assertEqual(bm.image.size, (2048, 2048))
                self.assertEqual(msgs[-1], (64, 64))
                self.assertTrue(bm.west <= basemap.WEST and bm.east >= basemap.EAST)
                # 第 (0,0) 張與第 (1,0) 張顏色不同，確認圖磚貼在正確位置
                x0, _x1, y0, _y1 = basemap.tile_range(12)
                r0 = bm.image.getpixel((128, 128))[0]
                r1 = bm.image.getpixel((256 + 128, 128))[0]
                self.assertGreater(abs(r0 - r1), 100)
                self.assertEqual(r0 > 120, x0 % 2 == 1)
                self.assertEqual(basemap.cached_zooms(), [12])
                again = basemap.load()
                self.assertEqual((again.z, again.image.size), (12, (2048, 2048)))
                self.assertAlmostEqual(again.north, bm.north, places=9)
            finally:
                plvr.fetch, basemap.CACHE_DIR = saved

    def test_download_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = (plvr.fetch, basemap.CACHE_DIR)
            basemap.CACHE_DIR = tmp
            try:
                def broken(url, timeout=30, insecure=False):
                    raise plvr.DownloadError("離線")
                plvr.fetch = broken
                with self.assertRaises(plvr.DownloadError):
                    basemap.download(z=12)
                self.assertEqual(basemap.cached_zooms(), [])      # 失敗不留下半成品

                def bad_cert(url, timeout=30, insecure=False):
                    raise plvr.CertError("cert")
                plvr.fetch = bad_cert
                with self.assertRaises(plvr.CertError):
                    basemap.download(z=12)
                self.assertIsNone(basemap.load())
            finally:
                plvr.fetch, basemap.CACHE_DIR = saved

    def test_affine_matches_projection(self):
        """影像的仿射變換必須與 3D 視圖的投影互為反函數（否則底圖和柱子會對不起來）。"""
        import math
        from PIL import Image
        bm = basemap.Basemap(Image.new("RGB", (1024, 1024)), 120.0, 120.7, 23.45, 22.85, 12)
        for az, pitch, zoom, tx, ty in [(-24, 40, 11, -6, -3), (0, 89, 14, 0, 0), (135, 25, 30, -12, -14)]:
            a, p = math.radians(az), math.radians(pitch)
            ca, sa, sp = math.cos(a), math.sin(a), math.sin(p)
            w2, h2 = 500.0, 380.0
            co = bm.affine(zoom, ca, sa, sp, tx, ty, w2, h2)
            for d in geo.load_districts()[:12]:
                x, y = geo.to_xy(d["lat"], d["lng"])
                dx, dy = x - tx, y - ty
                sx = w2 + (dx * ca - dy * sa) * zoom                 # 與 View3D.project 相同（z=0）
                sy = h2 - (dx * sa + dy * ca) * sp * zoom
                px, py = co[0] * sx + co[1] * sy + co[2], co[3] * sx + co[4] * sy + co[5]
                ex, ey = bm.pixel_of(d["lat"], d["lng"])
                self.assertAlmostEqual(px, ex, places=6)
                self.assertAlmostEqual(py, ey, places=6)
        self.assertEqual(bm.level_for(1000)[0], 1.0)             # 放很大：用原圖
        self.assertLess(bm.level_for(2)[0], 1.0)                 # 縮很小：用縮小版


class GeoTest(unittest.TestCase):
    def test_terrain(self):
        t = geo.Terrain()
        self.assertEqual((t.nx, t.ny), (60, 52))
        self.assertTrue(all(len(r) == 60 for r in t.rows))
        self.assertTrue(t.is_sea(23.40, 120.03))            # 北門外海
        self.assertGreater(t.elev(23.18, 120.60), 300)      # 楠西以東山區
        self.assertLess(t.elev(22.99, 120.20), 30)          # 府城平原
        for d in geo.load_districts():
            self.assertFalse(t.is_sea(d["lat"], d["lng"]), d["name"])

    def test_projection(self):
        x, y = geo.to_xy(geo.LAT0, geo.LNG0)
        self.assertEqual((x, y), (0.0, 0.0))
        self.assertAlmostEqual(geo.dist_km(23.0, 120.2, 23.1, 120.2), 11.057, places=2)

    def test_data_files(self):
        import mrt_data
        self.assertGreaterEqual(len(mrt_data.MRT_LINES), 5)
        blue = mrt_data.MRT_LINES["藍線（第一期）"]
        self.assertGreaterEqual(len(blue["stations"]), 2)
        self.assertGreaterEqual(len(blue["segments"]), 1)
        t = geo.Terrain()
        for name, ln in mrt_data.MRT_LINES.items():
            for s, lat, lng in ln["stations"]:
                self.assertTrue(t.south <= lat <= t.north and t.west <= lng <= t.east, (name, s))
        self.assertEqual(datacheck.check_all(), [])          # intel.json、mrt.json 的格式

    def test_datacheck_catches_mistakes(self):
        """情資更新（手動或排程）寫壞檔案時，檢查工具要抓得出來。"""
        import copy
        good = geo.load_json("intel.json")
        self.assertEqual(datacheck.check_intel(good), [])

        def broken(change, n_items=None):
            d = copy.deepcopy(good)
            if n_items is not None:
                d["items"] = d["items"][:n_items]
            else:
                change(d["items"][0])
            return datacheck.check_intel(d)

        self.assertTrue(broken(None, n_items=5))                                   # 大量資料不見
        self.assertTrue(broken(lambda it: it.update(type="八卦")))
        self.assertTrue(broken(lambda it: it.update(lat=25.03, lng=121.56)))       # 台北的座標
        self.assertTrue(broken(lambda it: it.update(lat=None)))                    # 只有一邊是 null
        self.assertTrue(broken(lambda it: it.update(impact_level=9)))
        self.assertTrue(broken(lambda it: it.update(sources=[])))                  # 沒有來源
        self.assertTrue(broken(lambda it: it["sources"][0].update(url="見新聞")))
        self.assertTrue(broken(lambda it: it.update(name="")))
        self.assertTrue(broken(lambda it: it.update(confidence="很高")))
        self.assertTrue(broken(lambda it: it.update(district="高雄市左營區")))
        self.assertTrue(datacheck.check_intel({"items": "x"}))
        mrt = geo.load_json("mrt.json")
        self.assertEqual(datacheck.check_mrt(mrt), [])
        bad = copy.deepcopy(mrt); bad["lines"][0]["color"] = "blue"
        self.assertTrue(datacheck.check_mrt(bad))
        bad = copy.deepcopy(mrt); bad["lines"][0]["stations"][0] = ["站", 25.0, 121.5]
        self.assertTrue(datacheck.check_mrt(bad))
        bad = copy.deepcopy(mrt); bad["lines"] = bad["lines"][:2]
        self.assertTrue(datacheck.check_mrt(bad))
        bad = copy.deepcopy(mrt); del bad["lines"][1]["short"]
        self.assertTrue(datacheck.check_mrt(bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)
