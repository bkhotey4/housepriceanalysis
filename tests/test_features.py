"""新功能的核心邏輯測試：預售屋、路段行情、房貸試算、看屋清單、疊圖與高解析圖磚。"""
import io
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

from core import basemap, geo, landmarks, plvr, prices, roads, watchlist  # noqa: E402

FIXTURE_A = os.path.join(ROOT, "tests", "fixture_d_lvr_land_a.csv")
FIXTURE_B = os.path.join(ROOT, "tests", "fixture_d_lvr_land_b.csv")


def read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


class PresaleTest(unittest.TestCase):
    def test_parse_presale_file(self):
        """5 列真實的預售屋資料：3 筆有效，已解約與店面各 1 筆被排除（期望值由官方檔案另行計算）。"""
        txs = prices.parse_csv_text(read(FIXTURE_B))
        got = [(x["dist"], x["ym"], x["cat"], round(x["u"], 2), round(x["tw"]), x["proj"], x["kind"]) for x in txs]
        self.assertEqual(got, [("永康區", "2026-02", "apt", 43.77, 1300, "勝美AI", "presale"),
                               ("善化區", "2026-02", "apt", 21.28, 767, "鄉景尚品", "presale"),
                               ("後壁區", "2026-02", "house", 28.01, 1320, "樂活居", "presale")])
        self.assertNotIn("聯上豐實", [x["proj"] for x in txs])          # 已解約

    def test_presale_kept_out_of_all(self):
        sale = prices.parse_csv_text(read(FIXTURE_A))
        pre = prices.parse_csv_text(read(FIXTURE_B))
        self.assertTrue(all(x["kind"] == "sale" and x["proj"] == "" for x in sale))
        names = [d["name"] for d in geo.load_districts()]
        book = prices.PriceBook(prices.build_book(sale + pre, names, as_of="2026-06-10"))
        self.assertEqual(book.complete_through, "2026-05")            # 由成屋買賣件數決定
        self.assertEqual(book.cell(prices.CITY, "all")["y12"][0], 8)
        self.assertEqual(book.cell(prices.CITY, "apt")["y12"][0], 4)
        self.assertEqual(book.cell(prices.CITY, "presale")["y12"][0], 3)
        self.assertEqual(book.cell("永康區", "presale")["y12"], [1, 43.8, 1300])
        self.assertEqual(book.cell("永康區", "all")["y12"][0], 0)

    def test_snapshot_presale(self):
        book = prices.PriceBook(geo.load_json("price_snapshot.json"))
        self.assertEqual([c for c, _ in prices.CATS], ["all", "house", "apt", "presale"])
        self.assertEqual(book.cell("東區", "presale")["h6"], [223, 58.4, 2373])
        self.assertEqual(book.cell(prices.CITY, "presale")["h6"], [1113, 36.5, 1468])
        total = sum(book.cell(d, "presale")["y12"][0] for d in book.districts())
        self.assertEqual(total, book.cell(prices.CITY, "presale")["y12"][0])
        self.assertAlmostEqual(book.presale_gap("東區"), (58.4 - 26.1) / 26.1 * 100, places=6)
        self.assertIsNone(book.presale_gap("龍崎區"))

    def test_old_cache_gets_presale_from_snapshot(self):
        """舊版快取沒有預售屋類別時，從內建快照補上，不必先重新下載。"""
        snap = geo.load_json("price_snapshot.json")
        old = json.loads(json.dumps(snap))
        old["source"] = "live"
        for d in old["data"]:
            del old["data"][d]["presale"]
        with tempfile.TemporaryDirectory() as tmp:
            saved = prices.BOOK_CACHE_PATH
            prices.BOOK_CACHE_PATH = os.path.join(tmp, "pricebook.json")
            try:
                with open(prices.BOOK_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(old, f)
                book = prices.load_book()
                self.assertEqual(book.source, "live")
                self.assertEqual(book.cell("東區", "presale")["h6"][0], 223)
            finally:
                prices.BOOK_CACHE_PATH = saved


class RoadAndLoanTest(unittest.TestCase):
    def test_road_of(self):
        cases = [("臺南市善化區中山路１２３號", "善化區", "中山路"),
                 ("臺南市仁德區中正西路３５３巷７８之７號", "仁德區", "中正西路"),
                 ("臺南市北區正覺里西門路四段２０號", "北區", "西門路四段"),
                 ("臺南市歸仁區高鐵大道３１號六樓之８", "歸仁區", "高鐵大道"),
                 ("臺南市東區大同路二段１００號", "東區", "大同路二段"),
                 ("臺南市安平區國平路５９９號二十樓之８", "安平區", "國平路"),
                 ("臺南市七股區大埕里大埕１２３號", "七股區", "大埕"),
                 ("", "東區", "其他")]
        for addr, dist, want in cases:
            self.assertEqual(prices.road_of(addr, dist), want, addr)

    def test_road_stats(self):
        txs = prices.parse_csv_text(read(FIXTURE_A)) + prices.parse_csv_text(read(FIXTURE_B))
        rows = prices.road_stats(txs, "仁德區", "house", "2025-01")
        self.assertEqual(rows, [{"name": "中正西路", "n": 2, "u": 19.8, "t": 2025, "last": "2026-05-08"}])
        self.assertEqual(prices.road_stats(txs, "仁德區", "apt", "2025-01"), [])
        pre = prices.road_stats(txs, "永康區", "presale", "2025-01", min_n=1)
        self.assertEqual([r["name"] for r in pre], ["勝美AI"])                 # 預售屋以建案名稱分組
        self.assertEqual(prices.road_stats(txs, "仁德區", "house", "2026-06"), [])  # 期間外

    def test_monthly_payment(self):
        # 800 萬、年利率 2.2%、30 年，本息平均攤還
        r, n, p = 0.022 / 12, 360, 8000000.0
        self.assertAlmostEqual(prices.monthly_payment(800, 2.2, 30), p * r / (1 - (1 + r) ** -n), places=6)
        self.assertEqual(round(prices.monthly_payment(800, 2.2, 30)), 30376)
        self.assertAlmostEqual(prices.monthly_payment(1000, 0, 20), 10000000 / 240.0)
        self.assertEqual(prices.monthly_payment(0, 2, 30), 0.0)
        # 還款總額一定大於本金
        self.assertGreater(prices.monthly_payment(800, 2.2, 30) * 360, 8000000)

    def test_google_urls(self):
        u = geo.google_directions_url(23.132, 120.297, 23.101, 120.28)
        self.assertIn("origin=23.13200,120.29700", u)
        self.assertIn("destination=23.10100,120.28000", u)
        self.assertTrue(u.startswith("https://www.google.com/maps/dir/?api=1"))


class WatchlistTest(unittest.TestCase):
    def test_legacy_import_and_crud(self):
        import house_data
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "watchlist.json")
            w = watchlist.Watchlist(path).load(legacy=house_data.SHANHUA_PROPERTIES)
            self.assertEqual(len(w.items), 6)
            self.assertTrue(all(it["sample"] and it["district"] == "善化區" for it in w.items))
            self.assertEqual(w.items[0]["type"], "店面／透店")
            self.assertFalse(os.path.exists(path))                 # 匯入時還不寫檔
            it = w.add({"name": "測試透天", "district": "善化區", "type": "透天厝", "price": 1500, "ping": 40})
            self.assertTrue(os.path.exists(path))
            self.assertAlmostEqual(watchlist.unit_price(it), 37.5)
            w.update(it["id"], {"price": 1600, "lat": 23.13, "lng": 120.3})
            w.update("legacy0", {"name": "改過的"})
            again = watchlist.Watchlist(path).load(legacy=house_data.SHANHUA_PROPERTIES)
            self.assertEqual(len(again.items), 7)                  # 已有檔案就不再重複匯入
            self.assertEqual(again.get(it["id"])["price"], 1600)
            self.assertNotIn("sample", again.get("legacy0"))       # 編輯過就不再視為示意資料
            again.remove(it["id"])
            self.assertIsNone(watchlist.Watchlist(path).load().get(it["id"]))
        self.assertIsNone(watchlist.unit_price({"price": None, "ping": 30}))
        self.assertIsNone(watchlist.unit_price({"price": "abc", "ping": 30}))

    def test_workplaces_inside_map(self):
        t = geo.Terrain()
        places = [p for p in geo.load_json("workplaces.json")["places"] if p.get("county", "D") == "D"]
        self.assertGreaterEqual(len(places), 10)
        for p in places:
            self.assertTrue(t.south <= p["lat"] <= t.north and t.west <= p["lng"] <= t.east, p["name"])
            self.assertFalse(t.is_sea(p["lat"], p["lng"]), p["name"])


@unittest.skipUnless(basemap.HAVE_PIL, "未安裝 Pillow，略過疊圖測試")
class LayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (plvr.fetch, basemap.CACHE_DIR, basemap.TILE_DIR)
        basemap.CACHE_DIR = os.path.join(self.tmp.name, "basemap")
        basemap.TILE_DIR = os.path.join(self.tmp.name, "tiles")

    def tearDown(self):
        plvr.fetch, basemap.CACHE_DIR, basemap.TILE_DIR = self.saved
        self.tmp.cleanup()

    @staticmethod
    def png(color, size=(256, 256), half=False):
        from PIL import Image
        im = Image.new("RGBA", size, (0, 0, 0, 0) if half else color)
        if half:
            im.paste(color, (0, 0, size[0] // 2, size[1]))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    def test_liquefaction_merges_two_sources(self):
        """中級液化圖在有資料的地方取代初級圖（不是疊色）。"""
        def fake(url, timeout=30, insecure=False):
            if "SoilLiquefaction2" in url:
                return self.png((255, 0, 0, 200), half=True)       # 只有左半有資料
            return self.png((0, 255, 0, 120))
        plvr.fetch = fake
        bm = basemap.download(z=12, layer="liq")
        self.assertTrue(bm.rgba)
        self.assertEqual(bm.image.getpixel((10, 10)), (255, 0, 0, 200))
        self.assertEqual(bm.image.getpixel((200, 10)), (0, 255, 0, 120))
        again = basemap.load(layer="liq")
        self.assertEqual(again.image.getpixel((10, 10)), (255, 0, 0, 200))
        self.assertEqual(basemap.cached_zooms("liq"), [12])
        self.assertEqual(basemap.cached_zooms("photo"), [])        # 各圖層的快取互不影響

    def test_fault_wms(self):
        urls = []

        def fake(url, timeout=30, insecure=False):
            urls.append(url)
            if "WIDTH=2048" in url:
                return b"<ServiceExceptionReport/>"                # 伺服器不接受大圖
            return self.png((230, 30, 30, 255), size=(1024, 880))
        plvr.fetch = fake
        bm = basemap.download(layer="fault")
        urls = [u for u in urls if "mapagent" in u]          # 前一項測試的背景圖磚執行緒可能還在跑，只看斷層 WMS 的請求
        self.assertEqual(len(urls), 2)
        self.assertIn("BBOX=120.02,22.87,120.66,23.42", urls[0])
        self.assertIn("25K_Geomap_fault_2021", urls[0])
        self.assertEqual((bm.width, bm.height), (1024, 880))
        self.assertEqual((bm.west, bm.east, bm.north, bm.south), (120.02, 120.66, 23.42, 22.87))
        self.assertIsNotNone(basemap.load(layer="fault"))
        plvr.fetch = lambda url, timeout=30, insecure=False: b"not an image"
        with self.assertRaises(plvr.DownloadError):
            basemap.download_fault()

    def test_plan_detail(self):
        z13 = basemap.px_per_km(13)
        self.assertAlmostEqual(z13, 56.85, delta=0.3)
        box = (120.20, 120.23, 23.01, 22.99)
        self.assertIsNone(basemap.plan_detail(z13, *box, base_z=13, max_z=19))       # 還沒放大到需要
        z, x0, x1, y0, y1 = basemap.plan_detail(200, *box, base_z=13, max_z=19)
        self.assertEqual(z, 15)                                                     # 15 級約 227 px/km
        self.assertLessEqual((x1 - x0 + 1) * (y1 - y0 + 1), 60)
        self.assertLessEqual(basemap.x_to_lng(x0, z), 120.20)
        self.assertGreaterEqual(basemap.x_to_lng(x1 + 1, z), 120.23)
        small = (120.210, 120.214, 23.002, 22.999)
        self.assertEqual(basemap.plan_detail(5000, *small, base_z=13, max_z=17)[0], 17)  # 不超過圖層上限
        self.assertEqual(basemap.plan_detail(5000, *box, base_z=13, max_z=17)[0], 16)    # 圖磚太多就退一級
        wide = basemap.plan_detail(900, 120.02, 120.66, 23.42, 22.87, base_z=13, max_z=19)
        self.assertTrue(wide is None or (wide[2] - wide[1] + 1) * (wide[4] - wide[3] + 1) <= 60)
        self.assertIsNone(basemap.plan_detail(300, 121.5, 121.6, 25.1, 25.0, base_z=13, max_z=19))  # 台南以外

    def test_detail_loader_and_stack(self):
        from PIL import Image
        calls = []

        def fake(url, timeout=30, insecure=False):
            calls.append(url)
            buf = io.BytesIO()
            Image.new("RGB", (256, 256), (250, 10, 10)).save(buf, "JPEG", quality=95)
            return buf.getvalue()
        plvr.fetch = fake
        stack = basemap.RasterStack()
        stack.base = basemap.Basemap(Image.new("RGB", (512, 512), (10, 120, 10)), 120.0, 120.7, 23.45, 22.85, 13)
        overlay = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        overlay.paste((0, 0, 255, 255), (0, 0, 512, 40))                       # 北緣一條藍帶
        stack.overlays["town"] = basemap.Basemap(overlay, 120.0, 120.7, 23.45, 22.85, 13)
        # 正上方視角、每公里 200 像素、畫面中心在台南市區
        import math
        x, y = geo.to_xy(23.0, 120.21)
        P = (200.0, 1.0, 0.0, math.sin(math.radians(89)), x, y, 300.0, 200.0)
        box = (120.195, 120.225, 23.01, 22.99)
        frame = stack.render((600, 400), P, (238, 241, 244), view_box=box)
        self.assertEqual(frame.mode, "RGB")
        self.assertEqual(frame.getpixel((300, 200)), (10, 120, 10))            # 只有底圖
        self.assertTrue(stack.request_detail(200.0, box))
        self.assertFalse(stack.request_detail(200.0, box))                     # 同樣的請求不重送
        for _ in range(200):
            if stack.poll() or not stack.loader.busy:
                break
            time.sleep(0.02)
        stack.poll()
        self.assertIn("photo", stack.patches)
        patch, key = stack.patches["photo"]
        self.assertEqual(key[0], 15)
        self.assertTrue(patch.rgba and patch.intersects(*box))
        n_tiles = (key[2] - key[1] + 1) * (key[4] - key[3] + 1)
        self.assertEqual(len(calls), n_tiles)
        frame = stack.render((600, 400), P, (238, 241, 244), view_box=box)
        r, g, b = frame.getpixel((300, 200))
        self.assertTrue(r > 200 and g < 60, (r, g, b))                         # 高解析補丁蓋在底圖上
        self.assertTrue(os.path.isdir(os.path.join(basemap.TILE_DIR, "PHOTO2", "15")))   # 圖磚有存到磁碟
        # 疊圖：開啟後才畫；關閉高解析後補丁不再使用
        stack.enabled.add("town")
        self.assertEqual(stack.active_overlays(), ["town"])
        self.assertIn("行政區界", stack.attribution())
        stack.detail = False
        frame = stack.render((600, 400), P, (238, 241, 244), view_box=box)
        self.assertEqual(frame.getpixel((300, 200)), (10, 120, 10))
        # 第二次要同一批圖磚時走記憶體／磁碟快取，不再連網
        calls.clear()
        stack.detail = True
        stack._last_plan.clear()
        stack.patches.clear()
        stack.request_detail(200.0, box)
        for _ in range(500):                     # 慢的電腦上背景執行緒比較晚開始：等到真的連過網、而且做完
            stack.poll()
            if calls and not stack.loader.busy:
                break
            time.sleep(0.02)
        self.assertEqual([u for u in calls if "PHOTO2" in u], [])
        self.assertTrue(calls and all("/TOWN/" in u for u in calls))           # 新開的區界疊圖才需要連網

    def test_flattened_overlays_match_layered_rendering(self):
        """疊圖預先合成到底圖（拖曳才順）之後，畫面要和逐層疊上去的結果一樣。"""
        import math
        from PIL import Image
        base = basemap.Basemap(Image.new("RGB", (512, 512), (10, 120, 10)), 120.0, 120.7, 23.45, 22.85, 13)
        liq = Image.new("RGBA", (512, 512), (0, 0, 0, 0)); liq.paste((255, 0, 52, 168), (128, 128, 384, 384))
        # 斷層圖的範圍與尺寸都和底圖不同（WMS 圖），合成時要換算到底圖的格線
        fault = Image.new("RGBA", (200, 100), (0, 0, 0, 0)); fault.paste((0, 0, 255, 255), (0, 40, 200, 60))
        stack = basemap.RasterStack()
        stack.loader = None
        stack.base = base
        stack.overlays["liq"] = basemap.Basemap(liq, 120.0, 120.7, 23.45, 22.85, 13)
        stack.overlays["fault"] = basemap.Basemap(fault, 120.1, 120.6, 23.35, 22.95, 0)
        self.assertIs(stack.flattened(), base)                                 # 沒開疊圖：就是底圖本身，不多佔記憶體
        x, y = geo.to_xy(23.15, 120.35)
        P = (20.0, 1.0, 0.0, math.sin(math.radians(89)), x, y, 300.0, 200.0)

        def layered():
            frame = base.render((600, 400), *P, fill=(238, 241, 244))
            for lid in stack.active_overlays():
                ov = stack.overlays[lid]
                img = basemap.Basemap(basemap.with_opacity(ov.image, stack.opacity_of(lid)), ov.west, ov.east, ov.north,
                                      ov.south, ov.z, pyramid=False).render((600, 400), *P)
                frame.paste(img, (0, 0), img)
            return frame

        stack.enabled.update(["liq", "fault"])
        flat = stack.flattened()
        self.assertIsNot(flat, base)
        self.assertIs(stack.flattened(), flat)                                 # 內容沒變就重複使用
        self.assertEqual(base.image.getpixel((256, 256)), (10, 120, 10))       # 原本的底圖沒有被改到
        a, b = stack.render((600, 400), P, (238, 241, 244)), layered()
        for pt in ((300, 200), (300, 140), (120, 200), (300, 260), (40, 40), (560, 380)):
            pa, pb = a.getpixel(pt), b.getpixel(pt)
            self.assertTrue(all(abs(u - w) <= 6 for u, w in zip(pa, pb)), (pt, pa, pb))
        mid = a.getpixel((300, 60))                                            # 只有液化圖層的地方
        self.assertTrue(40 < mid[0] < 140 and mid[1] > 60, mid)                # 液化圖層預設調淡，底圖看得見
        self.assertEqual(a.getpixel((300, 200)), (0, 0, 255))                  # 斷層帶（不透明藍）落在北緯 23.15 一帶
        # 調整濃淡、開關疊圖都會重新合成
        stack.set_opacity("liq", 1.0)
        self.assertIsNot(stack.flattened(), flat)
        strong = stack.render((600, 400), P, (238, 241, 244)).getpixel((300, 60))
        self.assertGreater(strong[0], mid[0] + 40)
        stack.enabled.discard("liq")
        self.assertEqual(stack.render((600, 400), P, (238, 241, 244)).getpixel((300, 60)), (10, 120, 10))
        stack.set_opacity("liq", 5)
        self.assertEqual(stack.opacity_of("liq"), 1.0)                         # 超出範圍的值會被限制在 0.1~1
        self.assertEqual(stack.opacity_of("town"), 1.0)

    def test_flattened_patch_keeps_overlays_on_top(self):
        """放大後的高解析影像補丁不能把疊圖蓋掉。"""
        import math
        from PIL import Image
        stack = basemap.RasterStack()
        stack.loader = None
        stack.base = basemap.Basemap(Image.new("RGB", (512, 512), (10, 120, 10)), 120.0, 120.7, 23.45, 22.85, 13)
        town = Image.new("RGBA", (512, 512), (0, 0, 0, 0)); town.paste((255, 255, 255, 255), (0, 250, 512, 262))
        stack.overlays["town"] = basemap.Basemap(town, 120.0, 120.7, 23.45, 22.85, 13)
        patch = Image.new("RGBA", (256, 256), (200, 30, 30, 255)); patch.paste((0, 0, 0, 0), (0, 0, 64, 256))
        stack.patches["photo"] = (basemap.Basemap(patch, 120.30, 120.40, 23.20, 23.10, 15, pyramid=False), (15, 0, 0, 0, 0))
        x, y = geo.to_xy(23.15, 120.35)
        P = (100.0, 1.0, 0.0, math.sin(math.radians(89)), x, y, 300.0, 200.0)   # 每公里 100 像素
        box = (120.25, 120.45, 23.25, 23.05)
        self.assertEqual(stack.render((600, 400), P, (0, 0, 0), view_box=box).getpixel((300, 200)), (200, 30, 30))
        stack.enabled.add("town")
        frame = stack.render((600, 400), P, (0, 0, 0), view_box=box)
        self.assertEqual(frame.getpixel((300, 200)), (255, 255, 255))          # 區界白線在北緯 23.15 一帶：補丁上面仍然看得到
        self.assertEqual(frame.getpixel((300, 50)), (200, 30, 30))             # 其他地方是高解析影像
        self.assertEqual(frame.getpixel((20, 50)), (10, 120, 10))              # 補丁沒有圖磚的地方（最左邊四分之一）露出底圖
        self.assertIs(stack.flattened_patch(100.0, box), stack.flattened_patch(100.0, box))
        self.assertIsNone(stack.flattened_patch(30.0, box))                    # 縮得很小時不用補丁
        stack.detail = False
        self.assertIsNone(stack.flattened_patch(100.0, box))

class RoadGeometryTest(unittest.TestCase):
    """路段位置：OpenStreetMap（Overpass API）的回應 -> 路名對到道路或聚落。測試用的是善化區真實回應的節錄。"""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "tests", "fixture_overpass_shanhua.json"), encoding="utf-8") as f:
            cls.raw = json.load(f)
        cls.data = roads.reduce(cls.raw)

    def test_reduce(self):
        d = self.data
        self.assertIn("陽光大道", d["roads"])
        self.assertEqual(len(d["roads"]["西拉雅大道"]), 5)                  # 一條路在 OSM 上是好幾段
        self.assertEqual(d["roads"]["成功新村"][0][0], [23.12808, 120.32109])
        for skipped in ("福爾摩沙高速公路", "山海圳綠道", "新萬香餐廳第一停車場"):   # 國道、自行車道、停車場不算路段
            self.assertNotIn(skipped, d["roads"])
        self.assertIn("陽光二路151巷", d["roads"])                          # 巷道是服務道路也要留
        self.assertEqual(d["places"]["坐駕"], [23.12375, 120.30189])        # 同名時取村落（village）而不是小聚落
        self.assertNotIn("善化區", d["places"])                             # 行政區本身不是聚落
        self.assertEqual(roads.reduce({"elements": []}), {"roads": {}, "places": {}})

    def test_locate(self):
        d = self.data
        main = roads.locate(d, "成功路")
        self.assertEqual((len(main["segments"]), len(main["lanes"])), (2, 1))  # 成功路 2 段；成功路53巷的 2 小段頭尾相接，接成 1 條
        self.assertEqual(len(d["roads"]["成功路53巷"]), 2)
        # 頭尾相接的小段會接起來（接點只出現一次）；三岔路口不接
        self.assertEqual(roads.merge_chains([[[0, 0], [0, 1]], [[0, 2], [0, 1]], [[5, 5], [6, 6]]]),
                         [[[5, 5], [6, 6]], [[0, 0], [0, 1], [0, 2]]])
        fork = [[[0, 0], [0, 1]], [[0, 1], [0, 2]], [[0, 1], [1, 1]]]
        self.assertEqual(len(roads.merge_chains(fork)), 3)
        self.assertIn(main["point"], [p for seg in main["segments"] for p in seg])
        self.assertEqual(roads.locate(d, "陽光二路")["segments"], [])        # 節錄裡只有它的巷子
        self.assertEqual(len(roads.locate(d, "陽光二路")["lanes"]), 1)
        village = roads.locate(d, "茄拔")
        self.assertEqual((village["segments"], village["point"]), ([], [23.13766, 120.32679]))
        self.assertEqual(roads.locate(d, "北子店")["point"], [23.13786, 120.31001])   # OSM 寫成「北仔店」
        self.assertEqual(len(roads.locate(d, "北子店")["lanes"]), 1)                    # 北子店116巷
        self.assertEqual(roads.locate(d, "西衛")["point"], [23.13472, 120.26183])     # OSM 上寫成異體字「西衚」
        self.assertEqual(roads.locate(d, "東勢宅")["point"], [23.15020, 120.29446])   # 不會配到隔壁的「東勢寮」
        self.assertIsNone(roads.locate(d, "東勢厝"))                                   # 差一個字的不同地名不亂配
        self.assertIsNone(roads.locate(d, "不存在的路"))
        self.assertIsNone(roads.locate(d, "中"))

    def test_prices_and_search(self):
        txs = prices.parse_csv_text(read(FIXTURE_A))
        rows = roads.road_prices(txs, "仁德區", "house", "2025-01")
        self.assertEqual(rows, [{"name": "中正西路", "n": 2, "u": 19.8, "t": 2025, "last": "2026-05-08", "low": True}])
        found, missing = roads.layer(txs, "仁德區", "house", "2025-01", {"roads": {"中正西路": [[[22.97, 120.25], [22.98, 120.26]]]}, "places": {}})
        self.assertEqual((found[0]["name"], found[0]["segments"], missing), ("中正西路", [[[22.97, 120.25], [22.98, 120.26]]], []))
        found, missing = roads.layer(txs, "仁德區", "house", "2025-01", {"roads": {}, "places": {}})
        self.assertEqual((found, missing), ([], ["中正西路"]))
        hits = roads.search(txs, "中正", "all", "2025-01")
        self.assertEqual([(r["dist"], r["name"], r["n"]) for r in hits], [("仁德區", "中正西路", 2)])
        self.assertEqual(roads.search(txs, "  ", "all", "2025-01"), [])
        self.assertEqual(roads.search(txs, "中正", "apt", "2025-01"), [])

    def test_download_asks_several_servers(self):
        """公開伺服器忙線很常見：同時問兩台，誰先回有效資料就用誰；都失敗有第二輪；原因記在紀錄檔。"""
        import threading
        saved = (plvr.fetch, roads.ROAD_DIR, roads.time.sleep)
        calls, lock = [], threading.Lock()
        body = json.dumps(self.raw).encode("utf-8")
        main, backup = roads.ENDPOINTS[0], roads.ENDPOINTS[1]

        def fake(url, timeout=30, insecure=False, data=None, agent=None, headers=None):
            with lock:
                calls.append((url, data, agent))
            if url.startswith(main):                    # 主站忙線時回的是 HTML 錯誤頁
                return b"<?xml version='1.0'?><html>Error: runtime error: The server is probably too busy</html>"
            return body
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            roads.ROAD_DIR = os.path.join(tmp, "roads")
            roads.time.sleep = lambda s: None
            plvr.fetch = fake
            try:
                self.assertIsNone(roads.load("善化區"))
                d = roads.download("善化區", progress=seen.append)
                hosts = sorted(c[0].split("/")[2] for c in calls)
                self.assertEqual(hosts, sorted(u.split("/")[2] for u in (main, backup)))      # 第一輪就成功，沒有第二輪
                self.assertTrue(all(c[1] and c[1].startswith(b"data=") for c in calls))
                self.assertTrue(all("deep_tainan_house" in c[2] for c in calls))    # 公開伺服器要求說明自己是誰
                from urllib.parse import unquote
                q = unquote(calls[0][1].decode("ascii")[5:])
                self.assertIn('["name"="臺南市"]["admin_level"="4"]', q)       # 限定在臺南市內，避免抓到其他縣市的同名行政區
                self.assertIn('["name"="善化區"]', q)
                self.assertEqual(len(seen), 1)
                self.assertIn("善化區", seen[0])
                self.assertEqual(d["district"], "善化區")
                self.assertIn("OpenStreetMap", d["attribution"])
                again = roads.load("善化區")
                self.assertEqual(again["roads"]["陽光大道"], d["roads"]["陽光大道"])
                log = open(os.path.join(roads.ROAD_DIR, "_log.txt"), encoding="utf-8").read()
                self.assertEqual(log.count("成功"), 1)
                self.assertIn(backup.split("/")[2], log)
                self.assertIsNone(roads.load("_log"))                       # 紀錄檔不會被當成某個行政區的資料
                # 每一台都忙線：兩輪都試過才放棄，訊息說得出原因，不留下空檔
                del calls[:]
                plvr.fetch = lambda url, timeout=30, insecure=False, data=None, agent=None, headers=None: (
                    calls.append((url, data, agent)), b"<html>too busy</html>")[1]
                with self.assertRaises(plvr.DownloadError) as cm:
                    roads.download("新市區")
                self.assertEqual(len(calls), sum(len(r) for r in roads._rounds()))
                self.assertIn("忙線", str(cm.exception))
                self.assertIsNone(roads.load("新市區"))
                self.assertGreaterEqual(open(os.path.join(roads.ROAD_DIR, "_log.txt"), encoding="utf-8").read().count("失敗"),
                                        len(calls))
                plvr.fetch = lambda url, timeout=30, insecure=False, data=None, agent=None, headers=None: \
                    json.dumps({"elements": []}).encode()
                with self.assertRaises(plvr.DownloadError):                # 回應正常但沒有任何道路：不存成空檔
                    roads.download("新市區")

                def down(url, timeout=30, insecure=False, data=None, agent=None, headers=None):
                    raise plvr.DownloadError("無法連線到 x：HTTP 429 Too Many Requests")
                plvr.fetch = down
                with self.assertRaises(plvr.DownloadError) as cm:
                    roads.download("新市區")
                self.assertIn("忙線", str(cm.exception))

                def bad_cert(url, timeout=30, insecure=False, data=None, agent=None, headers=None):
                    raise plvr.CertError("certificate verify failed")
                plvr.fetch = bad_cert
                with self.assertRaises(plvr.CertError):                    # 憑證問題要原樣往上丟，介面才能問要不要略過驗證
                    roads.download("新市區")
                # 最壞情況不讓人等超過兩分鐘
                self.assertLessEqual(sum(max(t for _u, _m, t in r) + 10 for r in roads._rounds()), 120)
            finally:
                plvr.fetch, roads.ROAD_DIR, roads.time.sleep = saved


class AddressTest(unittest.TestCase):
    """地址搜尋：拆地址、依門牌遠近排序、推估門牌在地圖上的位置。"""
    names = ["中西區", "東區", "北區", "安平區", "善化區", "新市區", "永康區", "仁德區"]

    def test_parse(self):
        from core import address
        cases = {
            "臺南市中西區大同路一段４６巷５０號五樓之３": ("中西區", "大同路一段", 46, None, 50, None),
            "700台南市中西區民族路二段212號": ("中西區", "民族路二段", None, None, 212, None),
            "善化中山路": ("善化區", "中山路", None, None, None, None),              # 省略「區」
            "安平路": (None, "安平路", None, None, None, None),                    # 不能被當成安平區
            "北區實踐街103巷25弄20號": ("北區", "實踐街", 103, 25, 20, None),
            "善化區茄拔 31之2號": ("善化區", "茄拔", None, None, 31, 2),            # 聚落式門牌
            "中華東路二段167": (None, "中華東路二段", None, None, 167, None),
        }
        for text, want in cases.items():
            q = address.parse(text, self.names)
            self.assertEqual((q["district"], q["road"], q["lane"], q["alley"], q["num"], q["sub"]), want, text)
        self.assertIsNone(address.parse("新市區", self.names)["road"])
        self.assertEqual(address.describe(address.parse("北區實踐街103巷25弄20號", self.names)), "實踐街 103 巷 25 弄 20 號")

    def test_rank_and_summary(self):
        from core import address

        def tx(addr, u, tw, date):
            return {"dist": "中西區", "addr": "臺南市中西區" + addr, "u": u, "tw": tw, "date": date}
        rows = [tx("大同路一段２２巷５５號", 26.0, 400, "2025-09-22"),
                tx("大同路一段４６巷５０號二樓之８", 43.0, 430, "2026-06-04"),
                tx("大同路一段４６巷５０號五樓之３", 42.4, 425, "2026-07-31"),
                tx("大同路一段４６巷２７號", 30.6, 600, "2026-05-15"),
                tx("大同路一段４６巷５３號", 31.6, 500, "2024-01-01"),
                tx("大同路一段２３０號", 23.1, 700, "2025-12-17")]
        q = address.parse("中西區大同路一段46巷50號", self.names)
        ranked = address.rank(rows, q)
        self.assertEqual([lv for lv, _x in ranked], [3, 3, 2, 2, 1, 1])
        self.assertEqual(ranked[0][1]["date"], "2026-07-31")                    # 同門牌：新的在前
        self.assertIn("５３號", ranked[2][1]["addr"])                            # 同巷：號碼近的在前（53 比 27 近）
        st = address.summary(ranked)
        self.assertEqual((st["exact"]["n"], st["lane"]["n"], st["road"]["n"]), (2, 4, 6))
        self.assertEqual(st["exact"]["t"], 428)
        only_road = address.rank(rows, address.parse("大同路一段", self.names))
        self.assertEqual({lv for lv, _x in only_road}, {1})
        self.assertEqual(only_road[0][1]["date"], "2026-07-31")
        self.assertEqual(address.summary([])["road"], {"n": 0, "u": None, "t": None})

    def _street(self):
        """一條東西向 2 公里的「測試路」，往東號碼越大，10、50、90 巷的巷口照比例排；50 巷裡有一條 5 弄。"""
        from core.geo import KM_PER_DEG_LAT, KM_PER_DEG_LNG
        lat0, lng0 = 23.0, 120.2
        dlng = 1.0 / KM_PER_DEG_LNG                 # 1 公里的經度差
        dlat = 1.0 / KM_PER_DEG_LAT

        def east(km):
            return lng0 + km * dlng
        roads_ = {"測試路": [[[lat0, east(0)], [lat0, east(1.0)]], [[lat0, east(1.0)], [lat0, east(2.0)]]]}
        for n in (10, 50, 90):
            x = east(0.2 + n * 0.02)               # 每號 20 公尺的刻度：10 巷在 0.4 公里、50 巷在 1.2、90 巷在 2.0
            roads_["測試路%d巷" % n] = [[[lat0 + 0.0001 * dlat, x], [lat0 + 0.3 * dlat, x]]]
        x50 = east(0.2 + 50 * 0.02)
        roads_["測試路50巷5弄"] = [[[lat0 + 0.02 * dlat, x50], [lat0 + 0.02 * dlat, x50 + 0.2 * dlng]]]
        return {"roads": roads_, "places": {"小新營": [23.1, 120.3]}}, lat0, east, dlat

    def test_position(self):
        from core import address, geo
        data, lat0, east, dlat = self._street()
        chains, anchors = address.lane_anchors(data, "測試路")
        self.assertEqual(len(chains), 1)                                        # 頭尾相接的兩段接成一條
        self.assertEqual(sorted(n for n, _c, _s, _l in anchors), [10, 50, 90])

        def at(text):
            return address.position(data, address.parse(text, self.names) if isinstance(text, str) else text)
        p = at("測試路30號")                                                    # 10 巷與 50 巷中間 -> 0.8 公里處
        self.assertEqual(p["precision"], "interp")
        self.assertLess(geo.dist_km(p["lat"], p["lng"], lat0, east(0.8)), 0.01)
        p = at("測試路50巷8號")                                                 # 巷內：從巷口往北走 8 × 2.5 = 20 公尺
        self.assertEqual(p["precision"], "lane")
        self.assertLess(geo.dist_km(p["lat"], p["lng"], lat0 + 0.02 * dlat, east(1.2)), 0.006)
        p = at("測試路50巷5弄40號")                                             # 弄裡：沿著弄往東走 100 公尺
        self.assertEqual(p["precision"], "lane")
        self.assertLess(geo.dist_km(p["lat"], p["lng"], lat0 + 0.02 * dlat, east(1.3)), 0.006)
        p = at("測試路50巷9弄3號")                                              # OpenStreetMap 沒有這條弄：標在弄口
        self.assertEqual(p["precision"], "alley_mouth")
        p = at("測試路70巷3號")                                                 # 沒有這條巷：用巷號推估巷口
        self.assertEqual(p["precision"], "lane_mouth")
        self.assertLess(geo.dist_km(p["lat"], p["lng"], lat0, east(1.6)), 0.01)
        self.assertEqual(at("測試路")["precision"], "road")                     # 只有路名：路的中段
        self.assertEqual(at("測試路900號")["precision"], "road")                # 推出路的範圍太遠就不信
        self.assertEqual(at("小新營102之15號")["precision"], "settlement")
        self.assertIsNone(at("不存在路5號"))
        self.assertIsNone(address.position(None, address.parse("測試路30號", self.names)))
        # 巷號跟位置對不起來（號碼忽前忽後）：不做內插
        bad = {"roads": dict(data["roads"])}
        bad["roads"]["測試路90巷"], bad["roads"]["測試路50巷"] = data["roads"]["測試路50巷"], data["roads"]["測試路90巷"]
        self.assertEqual(address.position(bad, address.parse("測試路30號", self.names))["precision"], "near_lane")
        for k in address.PRECISION_NOTE:
            self.assertIn(k, address.PRECISION_RADIUS_KM)


class AutoUpdateTest(unittest.TestCase):
    """實價登錄每月 1、11、21 日發布：判斷手上的資料是不是比最近一期舊。"""

    def test_release_dates(self):
        import datetime as dt
        from core import plvr
        D = dt.date
        self.assertEqual(plvr.last_release(D(2026, 10, 2)), D(2026, 10, 1))
        self.assertEqual(plvr.last_release(D(2026, 10, 11)), D(2026, 10, 11))
        self.assertEqual(plvr.last_release(D(2026, 10, 25)), D(2026, 10, 21))
        self.assertEqual(plvr.last_release(D(2026, 3, 1)), D(2026, 3, 1))
        self.assertEqual(plvr.next_release(D(2026, 10, 2)), D(2026, 10, 11))
        self.assertEqual(plvr.next_release(D(2026, 10, 21)), D(2026, 11, 1))
        self.assertEqual(plvr.next_release(D(2026, 12, 25)), D(2027, 1, 1))
        # 1 月 1 日之前的最近一期是前一年的 12/21
        self.assertEqual(plvr.last_release(D(2027, 1, 1)), D(2027, 1, 1))

    def test_needs_update(self):
        import datetime as dt
        import time as _time
        from core import plvr
        saved = plvr.PLVR_DIR
        with tempfile.TemporaryDirectory() as tmp:
            plvr.PLVR_DIR = tmp
            try:
                self.assertFalse(plvr.has_live_cache())
                self.assertFalse(plvr.needs_update(dt.date(2026, 10, 2)))       # 沒下載過：不自動下載（第一次要使用者按）
                cur = os.path.join(tmp, "cur.csv")
                open(cur, "w").close()
                t = _time.mktime(dt.date(2026, 9, 30).timetuple()) + 3600
                os.utime(cur, (t, t))
                self.assertTrue(plvr.has_live_cache())
                self.assertTrue(plvr.needs_update(dt.date(2026, 10, 2)))        # 9/30 下載，10/1 有新一期
                self.assertFalse(plvr.needs_update(dt.date(2026, 9, 30)))
                t = _time.mktime(dt.date(2026, 10, 1).timetuple()) + 3600
                os.utime(cur, (t, t))
                self.assertFalse(plvr.needs_update(dt.date(2026, 10, 10)))      # 10/1 已經抓過，下一期是 10/11
                self.assertTrue(plvr.needs_update(dt.date(2026, 10, 11)))
            finally:
                plvr.PLVR_DIR = saved


class ProjectTest(unittest.TestCase):
    """重大建設：時程欄位、某一年的狀態、3D 圖案。"""

    def test_build_state(self):
        from core.landmarks import build_state
        b = {"phase": "施工中", "start": 2026, "done": 2028}
        self.assertEqual([build_state(b, y) for y in (2026, 2027, 2028, 2030)], ["施工中", "施工中", "完工", "完工"])
        plan = {"phase": "規劃中", "start": 2027, "done": 2032}
        self.assertEqual([build_state(plan, y) for y in (2026, 2027, 2031, 2032)], ["規劃中", "施工中", "施工中", "完工"])
        self.assertEqual(build_state({"phase": "規劃中", "start": None, "done": None}, 2035), "規劃中")   # 年份未定：一直是規劃中
        self.assertEqual(build_state({"phase": "施工中", "start": None, "done": None}, 2035), "施工中")
        self.assertEqual(build_state({"phase": "完工", "start": None, "done": None}, 2026), "完工")

    def test_project_faces(self):
        from core import landmarks
        done = landmarks.project_faces("tower", "完工")
        building = landmarks.project_faces("tower", "施工中")
        planned = landmarks.project_faces("tower", "規劃中")
        self.assertEqual(len(done), len(planned))
        self.assertGreater(len(building), len(done))                          # 施工中多一座塔吊
        self.assertIn("#f2b632", [c for _p, c, _n in building])
        light = lambda faces: sum(int(c[k:k + 2], 16) for _p, c, _n in faces for k in (1, 3, 5)) / (3.0 * len(faces))
        self.assertGreater(light(planned), light(done) + 15)                   # 規劃中比較淡
        self.assertEqual(landmarks.faces_for({"model": "tower", "state": "施工中"}), building)
        self.assertEqual(landmarks.faces_for({"model": "tower"}), landmarks.faces_of("tower"))
        for name in ("tower", "dome", "blocks", "sheds", "interchange", "rail", "metro", "housing"):
            faces = landmarks.faces_of(name)
            self.assertGreater(len(faces), 4, name)
            zs = [p[2] for pts, _c, _n in faces for p in pts]
            self.assertGreaterEqual(min(zs), -1e-9, name)
            self.assertLessEqual(max(zs), 2.5, name)

    def test_intel_builds(self):
        from core import datacheck, geo, landmarks
        d = geo.load_json("intel.json")
        items = [it for it in d["items"] if it.get("build")]
        self.assertGreaterEqual(len(items), 30)
        self.assertEqual(datacheck.check_intel(d), [])
        for it in items:
            self.assertIn(it["build"]["model"], landmarks.MODELS)
        bad = dict(d)
        bad["items"] = [dict(items[0], build=dict(items[0]["build"], phase="蓋好了", start=2030, done=2028))] + d["items"][1:]
        errs = datacheck.check_intel(bad)
        self.assertTrue(any("phase" in e for e in errs))
        self.assertTrue(any("晚於" in e for e in errs))


class ReportTest(unittest.TestCase):
    """行情報告：產生一頁可以列印的 HTML。"""

    def test_build_and_save(self):
        import datetime as dt
        from core import address, geo, prices, report
        book = prices.PriceBook(geo.load_json("price_snapshot.json"))
        names = [d["name"] for d in geo.load_districts()]
        txs = [{"dist": "善化區", "addr": "臺南市善化區中正路６６７巷５號", "date": "2026-05-01", "cat": "house", "btype": "透天厝",
                "tw": 1200, "u": 30.0, "ping": 40.0, "built": 2010},
               {"dist": "善化區", "addr": "臺南市善化區中正路３００號", "date": "2026-06-01", "cat": "apt", "btype": "華廈",
                "tw": 800, "u": 25.0, "ping": 32.0, "built": None}]
        intel = geo.load_json("intel.json")["items"]
        q = address.parse("善化區中正路667巷5號", names)
        d = next(x for x in geo.load_districts() if x["name"] == "善化區")
        text = report.build(book, txs, intel, "善化區", "all", q=q, point=(d["lat"], d["lng"]),
                            agent={"name": "王<b>小明</b>", "phone": "0912", "client": "林先生", "note": "週六\n下午"},
                            works=[("南科台南園區", 3.8)], today=dt.date(2026, 10, 2))
        self.assertIn("善化區 中正路 667 巷 5 號 房價行情報告", text)
        self.assertIn("王&lt;b&gt;小明&lt;/b&gt;", text)                       # 使用者輸入一律跳脫
        self.assertNotIn("王<b>小明", text)
        self.assertIn("同門牌（同一棟）", text)
        self.assertIn("善化區中正路667巷5號", text)
        self.assertIn("<svg", text)
        self.assertIn("附近的重大建設", text)
        self.assertIn("南科特定區", text)                                       # 5 公里內的建設
        self.assertIn("約 3.8 公里", text)
        self.assertIn("週六<br>下午", text)
        self.assertIn("不構成投資或購屋建議", text)
        no_tx = report.build(book, [], intel, "永康區", "apt", today=dt.date(2026, 10, 2))
        self.assertIn("更新實價登錄", no_tx)
        saved = report.REPORT_DIR
        with tempfile.TemporaryDirectory() as tmp:
            report.REPORT_DIR = os.path.join(tmp, "reports")
            try:
                path = report.save(text, "善化區 中正路/667巷", today=dt.date(2026, 10, 2))
                self.assertTrue(path.endswith("20261002_善化區中正路667巷.html"))
                self.assertEqual(open(path, encoding="utf-8").read(), text)
            finally:
                report.REPORT_DIR = saved


class LandmarkTest(unittest.TestCase):
    def test_models(self):
        import math
        self.assertGreaterEqual(len(landmarks.MODELS), 20)
        for name in landmarks.MODELS:
            faces = landmarks.faces_of(name)
            self.assertGreater(len(faces), 5, name)
            for pts, color, n in faces:
                self.assertGreaterEqual(len(pts), 3, name)
                self.assertRegex(color, r"^#[0-9a-fA-F]{6}$")
                self.assertAlmostEqual(math.sqrt(sum(c * c for c in n)), 1.0, places=6)
                self.assertTrue(0.7 <= landmarks.brightness(n) <= 1.0)
                for x, y, z in pts:
                    self.assertTrue(-1.6 <= x <= 1.6 and -1.4 <= y <= 1.4 and -0.01 <= z <= 2.4, (name, x, y, z))
            self.assertTrue(any(n[2] > 0.5 for _p, _c, n in faces), name)        # 每個模型都有朝上的面
        # 方塊的五個面都朝外
        normals = [n for _p, _c, n in landmarks.faces_of("__沒有這個模型__")]
        self.assertEqual(sorted(tuple(round(c) + 0 for c in n) for n in normals),
                         sorted([(0, 0, 1), (0, -1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0)]))

    def test_data(self):
        t = geo.Terrain()
        items = landmarks.load()
        self.assertGreaterEqual(len(items), 20)
        self.assertEqual(len(set(it["id"] for it in items)), len(items))
        self.assertEqual(len(set(it["name"] for it in items)), len(items))
        districts = [d["name"] for d in geo.load_districts()]
        for it in items:
            self.assertIn(it["model"], landmarks.MODELS, it["name"])
            self.assertTrue(t.south <= it["lat"] <= t.north and t.west <= it["lng"] <= t.east, it["name"])
            self.assertIn(it["rank"], (1, 2, 3))
            self.assertTrue(it["note"].strip())
            self.assertTrue(any(d in it["district"] for d in districts), it["name"])
            landmarks.faces_of(it["model"], **it.get("params", {}))             # 自訂顏色等參數不會出錯


if __name__ == "__main__":
    unittest.main(verbosity=2)
