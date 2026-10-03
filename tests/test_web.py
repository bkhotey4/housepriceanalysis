"""網頁版（web/）的瀏覽器測試：用 Playwright 開手機與電腦尺寸，操作一遍主要功能，
並確認網頁版的地址解析、門牌位置推估、路段行情和桌面版的 Python 結果一致。

需要 playwright（pip install playwright && playwright install chromium）；沒有就自動略過。
先執行 python tools/export_web.py 產生 web/data。
"""
import functools
import http.server
import json
import os
import sys
import threading
import unittest
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WEB = os.path.join(ROOT, "web")

try:
    from playwright.sync_api import sync_playwright
except ImportError:          # 沒裝 Playwright
    sync_playwright = None

ADDRS = ["善化區中正路667巷5號", "善化區中正路300號", "善化區小新營102之15號", "中西區大同路一段46巷50號",
         "北區實踐街103巷25弄20號", "永康區永安路288號", "安平區國平北路88號", "東區崇德二十一街67號"]


@unittest.skipIf(sync_playwright is None, "沒有安裝 playwright")
@unittest.skipIf(not os.path.exists(os.path.join(WEB, "data", "meta.json")), "還沒執行 tools/export_web.py")
class WebAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=WEB)
        handler.log_message = lambda *a: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/" % cls.httpd.server_address[1]
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def open(self, phone=True):
        kw = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True) if phone \
            else dict(viewport={"width": 1366, "height": 820})
        ctx = self.browser.new_context(**kw)
        ctx.route("https://wmts.nlsc.gov.tw/**", lambda r: r.abort())      # 測試不連外網
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(self.url)
        pg.wait_for_function("window.__app && window.__app.D.txs", timeout=30000)
        pg.wait_for_timeout(300)
        self.addCleanup(ctx.close)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return pg

    def test_same_results_as_python(self):
        from core import address, geo, prices, roads
        pg = self.open(phone=False)
        names = [d["name"] for d in geo.load_districts()]
        book = prices.load_book()
        txs = prices.load_transactions()
        for a in ADDRS:
            q = address.parse(a, names)
            js = pg.evaluate("a => __app.L.parseAddress(a, __app.D.districts.map(d => d.name))", a)
            self.assertEqual({k: js[k] for k in ("district", "road", "lane", "alley", "num", "sub")},
                             {k: q[k] for k in ("district", "road", "lane", "alley", "num", "sub")}, a)
            data = roads.load(q["district"]) if q["district"] else None
            if data:
                py = address.position(data, q)
                jp = pg.evaluate("""async q => { const d = await (await fetch('data/roads/' + encodeURIComponent(q.district) + '.json')).json();
                                    return __app.L.position(d, q); }""", q)
                if py is None:
                    self.assertIsNone(jp, a)
                else:
                    self.assertEqual(jp["precision"], py["precision"], a)
                    self.assertLess(geo.dist_km(py["lat"], py["lng"], jp["lat"], jp["lng"]), 0.02, a)
        if book.source != "live":
            return                      # 這台電腦沒有逐筆成交快取：只比對地址解析與門牌位置
        # 路段行情：善化區近一年各路段的件數與中位價
        since = book.windows["y12"][0]
        py = roads.road_prices(txs, "善化區", "all", since)
        js = pg.evaluate("s => __app.L.roadPrices(__app.D.txs, '善化區', 'all', s)", since)
        self.assertEqual([(r["name"], r["n"], r["u"], r["t"]) for r in py[:30]], [(r["name"], r["n"], r["u"], r["t"]) for r in js[:30]])
        # 各區統計
        for d in ("善化區", "東區", "台南市"):
            for cat in ("all", "house", "apt", "presale"):
                b = book.best(d, cat, "u")
                jb = pg.evaluate("([d, c]) => __app.D.book.best(d, c, 'u')", [d, cat])
                self.assertEqual((jb["value"], jb["n"]), (b["value"], b["n"]), (d, cat))
                self.assertEqual(pg.evaluate("([d, c]) => __app.D.book.trend(d, c, 'u')", [d, cat]), book.trend(d, cat, "u"))

    def test_phone_flow(self):
        pg = self.open(phone=True)
        # 點房價柱 -> 選到那一區、地圖滑過去
        hit = pg.evaluate("""(() => { const v = __app.view, h = v.hits.find(h => h.kind === 'district' && h.id === '善化區');
            for (let y = h.y1 - 4; y > h.y0; y -= 3) for (let x = h.x0 + 4; x < h.x1; x += 3) {
              const p = v.pick(x, y); if (p && p[0] === 'district' && p[1] === '善化區') return [x, y]; }
            return null; })()""")
        self.assertIsNotNone(hit)
        pg.touchscreen.tap(hit[0], hit[1] + 52)          # 畫布在頂列下方
        pg.wait_for_timeout(700)
        self.assertEqual(pg.evaluate("__app.S.current"), "善化區")
        self.assertIn("善化區", pg.inner_text("#d-name"))
        # 搜尋地址
        pg.fill("#q", "善化區中正路667巷5號")
        pg.press("#q", "Enter")
        pg.wait_for_timeout(900)
        st = pg.evaluate("({tab: __app.S.tab, pin: !!__app.S.pin, prec: __app.S.pin && __app.S.pin.note})")
        self.assertEqual(st["tab"], "tx")
        self.assertTrue(st["pin"])
        self.assertIn("巷內", st["prec"])
        self.assertIn("整條路", pg.inner_text("#tab-body"))
        # 點成交清單一列 -> 圖釘移到那一筆
        before = pg.evaluate("__app.S.pin.lat")
        pg.click("#tab-body tr[data-tx='1']")
        pg.wait_for_timeout(500)
        self.assertNotEqual(pg.evaluate("__app.S.pin.lat"), before)
        # 好幾區都有的路名：列出讓使用者挑
        self.assertEqual(pg.evaluate("__app.search('中山路')"), "choose")
        pg.wait_for_timeout(300)
        rows = pg.locator("#tab-body tr[data-road='中山路']")
        self.assertGreater(rows.count(), 3)
        rows.first.click()
        pg.wait_for_timeout(800)
        self.assertNotEqual(pg.evaluate("__app.S.current"), "台南市")
        self.assertEqual(pg.evaluate("__app.S.addr.road"), "中山路")
        # 建設：年份滑桿改變狀態
        pg.click("#tabs button[data-tab='projects']")
        pg.evaluate("__app.selectDistrict('台南市')")
        pg.click("#tabs button[data-tab='projects']")
        y0 = pg.evaluate("__app.S.year")
        n_done0 = pg.evaluate("__app.view.models.filter(m => m.hit === 'project' && m.state === '完工').length")
        pg.fill("#year", str(y0 + 9))
        pg.dispatch_event("#year", "input")
        pg.wait_for_timeout(400)
        n_done1 = pg.evaluate("__app.view.models.filter(m => m.hit === 'project' && m.state === '完工').length")
        self.assertGreater(n_done1, n_done0)
        pg.click("#tab-body tr[data-proj]")
        pg.wait_for_timeout(400)
        self.assertEqual(pg.evaluate("__app.S.tab"), "detail")
        self.assertIn("時程", pg.inner_text("#tab-body"))
        # 看屋清單：新增、存在瀏覽器裡，重新整理後還在
        pg.click("#tabs button[data-tab='watch']")
        pg.click("[data-act='watch-add']")
        pg.fill("dialog input[name='name']", "測試透天")
        pg.select_option("dialog select[name='district']", "永康區")
        pg.select_option("dialog select[name='type']", "透天厝")
        pg.fill("dialog input[name='price']", "1,500")
        pg.fill("dialog input[name='ping']", "40")
        pg.click("dialog button[value='ok']")
        pg.wait_for_timeout(300)
        self.assertIn("測試透天", pg.inner_text("#tab-body"))
        pg.reload()
        pg.wait_for_function("window.__app && window.__app.D.txs", timeout=30000)
        self.assertEqual(pg.evaluate("__app.S.watch.map(w => [w.name, w.price, w.ping])"), [["測試透天", 1500, 40]])
        # 設定：預算篩選
        pg.click("#btn-menu")
        pg.fill("[data-set='budget']", "1000")
        pg.dispatch_event("[data-set='budget']", "change")
        pg.wait_for_timeout(300)
        self.assertGreater(pg.evaluate("__app.view.bars.filter(b => b.dim).length"), 5)

    def test_desktop_mouse(self):
        pg = self.open(phone=False)
        v0 = pg.evaluate("[__app.view.tx, __app.view.ty, __app.view.zoom, __app.view.az]")
        pg.mouse.move(500, 400); pg.mouse.down(); pg.mouse.move(600, 450, steps=6); pg.mouse.up()
        v1 = pg.evaluate("[__app.view.tx, __app.view.ty, __app.view.zoom, __app.view.az]")
        self.assertNotEqual(v1[:2], v0[:2])                 # 左鍵拖曳：平移
        self.assertEqual(v1[3], v0[3])
        before = pg.evaluate("__app.view.screenToLatLng(300, 300)")
        pg.mouse.move(300, 352); pg.mouse.wheel(0, -300); pg.wait_for_timeout(200)
        after = pg.evaluate("__app.view.screenToLatLng(300, 300)")
        self.assertGreater(pg.evaluate("__app.view.zoom"), v1[2])
        self.assertAlmostEqual(before[0], after[0], places=4)   # 對著游標縮放
        pg.mouse.move(500, 400); pg.mouse.down(button="right"); pg.mouse.move(560, 420, steps=5); pg.mouse.up(button="right")
        self.assertNotEqual(pg.evaluate("__app.view.az"), v0[3])   # 右鍵拖曳：旋轉


    def test_buildings_commute_links(self):
        pg = self.open(phone=True)
        pg.wait_for_function("__app.D.txs")
        # 社區／大樓：同門牌歸成一棟，至少 2 筆
        res = pg.evaluate("(() => { const a = __app; return a.L.buildings(a.D.txs, '善化區', 'all', a.D.book.windows.y12[0]); })()")
        self.assertTrue(res)
        self.assertTrue(all(r["n"] >= 2 for r in res))
        pg.evaluate("__app.selectDistrict('善化區')")
        pg.click("#tabs button[data-tab='bldg']")
        pg.evaluate("document.querySelector('#tab-body tr.click').click()")
        pg.wait_for_timeout(800)
        self.assertIn("找這個社區正在賣的房子", pg.inner_text("#tab-body"))
        links = pg.evaluate("[...document.querySelectorAll('#tab-body .links a')].map(a => a.href)")
        self.assertTrue(any("sale.591.com.tw" in unquote(u) for u in links))
        # 通勤：時間估計單調、範圍內行政區數隨上限增加
        m = pg.evaluate("[__app.L.commuteMin(5, 'car'), __app.L.commuteMin(10, 'car'), __app.L.commuteMin(10, 'bike')]")
        self.assertLess(m[0], m[1]); self.assertLess(m[1], m[2])
        self.assertAlmostEqual(pg.evaluate("__app.L.kmFor(__app.L.commuteMin(12, 'scooter'), 'scooter')"), 12, delta=0.5)
        pg.evaluate("__app.selectDistrict('台南市', false)")
        pg.click("#tabs button[data-tab='commute']")
        pg.select_option("#tab-body select[data-set='work']", "南科台南園區")
        counts = []
        for v in (15, 30):
            pg.evaluate(f"(() => {{ const i = document.querySelector('#commute-min'); i.value = {v}; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")
            pg.wait_for_timeout(300)
            counts.append(pg.evaluate("__app.D.districts.filter(d => !__app.view.bars.find(b => b.id === d.name).dim).length"))
        self.assertLess(counts[0], counts[1])
        # 地標：面板切到地標所在的行政區
        self.assertEqual(pg.evaluate("__app.search('赤崁樓')"), "landmark")
        self.assertEqual(pg.evaluate("__app.S.current"), "中西區")


    def test_poi_nearby(self):
        import json as _json, re as _re
        from urllib.parse import unquote as _uq
        pg = self.open(phone=True)
        def handle(route):
            m = _re.search(r"around:\d+,([\d.]+),([\d.]+)", _uq(route.request.post_data or ""))
            lat, lng = float(m.group(1)), float(m.group(2))
            els = [{"type": "node", "id": 1, "lat": lat + 0.001, "lon": lng, "tags": {"shop": "convenience", "name": "超商A"}},
                   {"type": "node", "id": 2, "lat": lat + 0.0015, "lon": lng, "tags": {"amenity": "fuel", "name": "加油站B"}},
                   {"type": "node", "id": 3, "lat": lat + 0.03, "lon": lng, "tags": {"amenity": "hospital", "name": "太遠的醫院"}},
                   {"type": "way", "id": 4, "center": {"lat": lat - 0.004, "lon": lng}, "tags": {"landuse": "cemetery"}}]
            route.fulfill(status=200, content_type="application/json", body=_json.dumps({"elements": els}))
        pg.route("**/api/interpreter", handle)
        pg.wait_for_function("__app.D.txs")
        pg.fill("#q", "善化區成功路169巷10號"); pg.press("#q", "Enter"); pg.wait_for_timeout(1200)
        pg.click("[data-act='poi']"); pg.wait_for_timeout(1200)
        text = pg.inner_text("#tab-body")
        self.assertIn("超商A", text); self.assertIn("加油站B", text); self.assertNotIn("太遠的醫院", text)
        self.assertEqual(pg.evaluate("__app.S.tab"), "poi")
        self.assertEqual(pg.evaluate("__app.view.pois.length"), 3)

        # 行情報告：含周邊與地址統計
        pg.click("#tab-body [data-act='report']")
        pg.fill("#rep-dlg input[name='name']", "王小明")
        pg.fill("#rep-dlg input[name='client']", "陳先生")
        with pg.expect_popup() as pop:
            pg.click("#rep-dlg button[value='ok']")
        rep = pop.value
        rep.wait_for_load_state()
        body = rep.inner_text("body")
        for want in ("房價行情報告", "王小明", "給 陳先生", "同一條巷", "周邊生活機能與嫌惡設施", "超商A", "附近的重大建設"):
            self.assertIn(want, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
