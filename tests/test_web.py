"""網頁版（web/）的瀏覽器測試：用 Playwright 開手機與電腦尺寸，操作一遍主要功能，
並確認網頁版的地址解析、門牌位置推估、路段行情和 Python（core/）算出來的結果一致。

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
from urllib.parse import quote, unquote

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

    def open(self, phone=True, query="?tw=0"):
        kw = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True) if phone \
            else dict(viewport={"width": 1366, "height": 820})
        ctx = self.browser.new_context(**kw)
        ctx.route("https://wmts.nlsc.gov.tw/**", lambda r: r.abort())      # 測試不連外網
        # 路線伺服器也不連：預設回失敗（程式退回直線距離估算）；要測道路時間的測試在頁面上另外 route
        ctx.route("https://routing.openstreetmap.de/**", lambda r: r.abort())
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(self.url + query)
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
        # 房貸試算：和電腦版的 prices.monthly_payment 算出一樣的月付金額
        for price, down, rate, years in ((1000, 20, 2.2, 30), (1580, 30, 2.06, 40), (600, 0, 0, 20)):
            js = pg.evaluate("a => __app.L.mortgage(...a)", [price, down, rate, years, 0])
            self.assertAlmostEqual(js["monthly"], prices.monthly_payment(price * (1 - down / 100), rate, years), places=4)
        g = pg.evaluate("a => __app.L.mortgage(...a)", [1000, 20, 2.2, 30, 3])
        self.assertAlmostEqual(g["graceMonthly"], 800 * 10000 * 0.022 / 12, places=4)          # 寬限期只繳利息
        self.assertAlmostEqual(g["monthly"], prices.monthly_payment(800, 2.2, 27), places=4)   # 之後 27 年攤還
        # 交屋前現金：和電腦版的 prices.purchase_costs 算出一樣的稅費
        for price, down, opt in ((1000, 20, {}), (2380, 30, {"hv": "120", "lv": "500", "agent": "1", "reno": "80"}), (800, 100, {"agent": 0})):
            js = pg.evaluate("a => __app.L.purchaseCosts(...a)", [price, down, opt])
            py = prices.purchase_costs(price, down, house_val=float(opt["hv"]) if "hv" in opt else None,
                                       land_val=float(opt["lv"]) if "lv" in opt else None, agent_pct=float(opt.get("agent", 2)),
                                       reno=float(opt.get("reno", 0)))
            self.assertAlmostEqual(js["total"], py["total"], places=6)
            self.assertEqual([round(i[2], 6) for i in js["items"]], [round(i[2], 6) for i in py["items"]])
        self.assertIsNone(pg.evaluate("__app.L.purchaseCosts(0, 20)"))
        # 買房 vs 租房：房租超便宜時租方永遠比較多；房租很貴時買方較早划算
        cheap = pg.evaluate("__app.L.rentVsBuy({price: 1500, down: 20, rate: 2.2, loanYears: 30, rent: 5000, cash: 350, g: 0})")
        dear = pg.evaluate("__app.L.rentVsBuy({price: 1500, down: 20, rate: 2.2, loanYears: 30, rent: 80000, cash: 350})")
        self.assertIsNone(cheap["breakeven"]); self.assertLess(cheap["end"]["buy"], cheap["end"]["rent"])
        self.assertIsNotNone(dear["breakeven"]); self.assertGreater(dear["end"]["buy"], dear["end"]["rent"])
        self.assertEqual(len(dear["years"]), 20)
        self.assertIsNone(pg.evaluate("__app.L.rentVsBuy({price: 1500, down: 20, rate: 2.2, loanYears: 30, rent: 0})"))
        # 概況分頁有房貸試算，改利率後結果跟著更新
        pg.evaluate("__app.selectDistrict('善化區')"); pg.wait_for_timeout(200)
        self.assertIn("房貸試算", pg.inner_text("#tab-body"))
        before = pg.inner_text("#loan-out")
        pg.fill("input[data-loan='rate']", "3"); pg.wait_for_timeout(100)
        self.assertNotEqual(pg.inner_text("#loan-out"), before)
        # 合理價估算：用 JS 估一次，結果的區間要包住中間值；估價分頁顯示區間、比對的成交與開價判斷
        e = pg.evaluate("""() => __app.L.estimate(__app.D.txs, {dist: '善化區', cat: 'house', ping: 45, age: 10,
                            todayYm: __app.D.book.months[__app.D.book.months.length - 1]})""")
        if e["ok"]:
            self.assertLessEqual(e["uLo"], e["uMid"]); self.assertLessEqual(e["uMid"], e["uHi"])
            self.assertTrue(all(c["dist"] == "善化區" and not c["presale"] for c in e["comps"]))
        pg.evaluate("""() => { __app.S.settings.val = {dist: '東區', cat: 'apt', ping: '35', age: '15', addr: '', price: '99999'};
                               __app.selectDistrict('東區'); }""")
        pg.click("#tabs button[data-tab='value']"); pg.wait_for_timeout(200)
        body = pg.inner_text("#tab-body")
        self.assertIn("合理總價約", body)
        self.assertIn("高於合理區間", body)
        self.assertGreater(pg.locator("#tab-body tr.click").count(), 2)
        # 看屋清單附近的新成交：上次看過的日期很早 → 重新整理後出現「新成交」，按「我看過了」就清掉
        pg.evaluate("""() => { localStorage.setItem('dth_v1', JSON.stringify({settings: {}, watch: [
            {id: 'w1', name: '東區測試', district: '東區', type: '大樓／華廈', address: '', seen: '2000-01-01', lat: null, lng: null}]})); }""")
        pg.reload(); pg.wait_for_function("window.__app && window.__app.D.txs"); pg.wait_for_timeout(300)
        n = pg.evaluate("(__app.S.watchNews || {}).w1 ? __app.S.watchNews.w1.length : -1")
        self.assertGreater(n, 0)
        pg.evaluate("__app.S.tab = 'watch'; __app.S.watchSel = 'w1'; __app.selectDistrict('東區')")
        pg.evaluate("__app.S.tab = 'watch'"); pg.evaluate("document.querySelector('#tabs [data-tab=watch]').click()"); pg.wait_for_timeout(200)
        pg.evaluate("document.querySelector('#tab-body tr[data-watch=w1]').click()"); pg.wait_for_timeout(200)
        self.assertIn("新成交", pg.inner_text("#tab-body"))
        pg.evaluate("document.querySelector(`#tab-body [data-act='watch-seen']`).click()"); pg.wait_for_timeout(200)
        self.assertEqual(pg.evaluate("__app.S.watchNews.w1.length"), 0)
        pg.evaluate("localStorage.removeItem('dth_v1')")
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
        # 實際道路的通勤時間：路線伺服器回應後改用道路時間（假回應：每一區都 600 秒），結果存在裝置上，換交通方式才再查
        import json as _json
        calls = []
        def fake_table(route):
            calls.append(route.request.url)
            n = route.request.url.split("/driving/")[1].split("?")[0].count(";")
            route.fulfill(status=200, content_type="application/json",
                          headers={"Access-Control-Allow-Origin": "*"},
                          body=_json.dumps({"code": "Ok", "durations": [[0] + [600] * n]}))
        pg.route("https://routing.openstreetmap.de/**", fake_table)          # 頁面的 route 優先於 context 的
        pg.evaluate("localStorage.removeItem('dth_route_v1')")
        pg.reload()                                                            # 上班地點已經記住：載入時自動查一次
        pg.wait_for_function("window.__app && window.__app.D.txs", timeout=30000)
        pg.click("#tabs button[data-tab='commute']")
        pg.wait_for_function("document.querySelector('#tab-body').innerText.includes('OpenStreetMap 道路')", timeout=8000)
        self.assertEqual(len(calls), 1)
        self.assertIn("/routed-car/table/v1/driving/", calls[0])
        mins = pg.evaluate("__app.D.districts.map(d => __app.minsTo(d.lat, d.lng))")
        self.assertEqual(set(mins), {round(600 / 60 * 1.25 + 3)})           # 10 分鐘 × 尖峰 1.25 ＋ 3 分鐘
        pg.click("#tabs button[data-tab='rank']"); pg.click("#tabs button[data-tab='commute']")
        pg.wait_for_timeout(1500)
        self.assertEqual(len(calls), 1)                                        # 已經查過的不再查
        # 房價所得比：總價 ÷ 家庭年收入
        self.assertAlmostEqual(pg.evaluate("__app.L.priceIncomeRatio(1440, 100000)"), 12.0)
        self.assertIsNone(pg.evaluate("__app.L.priceIncomeRatio(1440, 0)"))
        pg.evaluate("__app.S.settings.incomeMonthly = '100000'")
        pg.click("#tabs button[data-tab='rank']")
        self.assertIn("不吃不喝幾年", pg.inner_text("#tab-body"))
        pg.evaluate("__app.S.settings.incomeMonthly = ''; localStorage.removeItem('dth_route_v1')")
        # 地標：面板切到地標所在的行政區
        self.assertEqual(pg.evaluate("__app.search('赤崁樓')"), "landmark")
        self.assertEqual(pg.evaluate("__app.S.current"), "中西區")


    def test_sell_trip_notes(self):
        """賣屋／換屋試算、看屋行程（排順序＋Google 導航）、看屋筆記與並排比較。"""
        pg = self.open(phone=False)
        r = pg.evaluate("__app.L.sellHouse({sell: 1800, buy: 1200, years: 8, self: true, loan: 500, agent: 4, landTax: 20})")
        self.assertAlmostEqual(r["tax"], 17)                       # (600 - 30) - 400 = 170 萬 × 10%
        self.assertAlmostEqual(r["net"], 1800 - 500 - 72 - 1.5 - 17 - 20)
        r = pg.evaluate("__app.L.sellHouse({sell: 1800, buy: 1200, years: 1.5, self: true})")
        self.assertEqual(r["rate"], 45)
        self.assertFalse(pg.evaluate("__app.L.sellHouse({sell: 1800, buy: 1200, years: 9, bought: 106}).old"))   # 民國年 106＝2017
        self.assertTrue(pg.evaluate("__app.L.sellHouse({sell: 1800, bought: 103}).old"))
        url = pg.evaluate("__app.L.tripUrl(Array.from({length: 12}, (_, i) => ({lat: 23 + i / 100, lng: 120.3})))")
        self.assertEqual(url.count("%7C"), 8)                       # 9 個中途點
        self.assertIn("destination=23.100000", url)                 # 終點是第 11 間（沒有跳過中間的）
        self.assertAlmostEqual(pg.evaluate("__app.L.rebuyRefund(100, 1800, 900)"), 50)
        pg.evaluate("__app.S.tab = 'overview'; __app.selectDistrict('善化區')")
        pg.evaluate("document.querySelector(`details[data-det='sellOpen'] > summary`).click()")
        pg.fill("input[data-sell='sell']", "1800"); pg.fill("input[data-sell='buy']", "1200"); pg.fill("input[data-sell='years']", "8")
        out = pg.inner_text("#sell-out")
        self.assertIn("賣掉後實際拿回", out); self.assertIn("自住優惠", out); self.assertIn("換到總價", out)
        self.assertTrue(pg.evaluate("document.querySelector('#sell-old').hidden"))
        pg.fill("input[data-sell='bought']", "2012")
        self.assertFalse(pg.evaluate("document.querySelector('#sell-old').hidden"))
        self.assertIn("舊制", pg.inner_text("#sell-out"))
        # 看屋行程：三間有位置、一間沒有
        pg.evaluate("""() => { const S = __app.S;
            S.watch = [{id: 'a', name: '甲', district: '善化區', type: '透天厝', lat: 23.13, lng: 120.30, trip: true},
                       {id: 'b', name: '乙', district: '新市區', type: '透天厝', lat: 23.07, lng: 120.29, trip: true},
                       {id: 'c', name: '丙', district: '善化區', type: '透天厝', lat: 23.125, lng: 120.305, trip: true},
                       {id: 'd', name: '丁', district: '善化區', type: '透天厝', lat: null, lng: null, trip: true}];
            S.tab = 'watch'; __app.selectDistrict('善化區'); }""")
        body = pg.inner_text("#tab-body")
        self.assertIn("看屋行程（4 間）", body); self.assertIn("丁 還沒標位置", body)
        order = pg.evaluate("[...document.querySelectorAll('#tab-body ol.trip li')].map(li => li.textContent.slice(0, 1))")
        self.assertEqual(order, ["甲", "丙", "乙"])                 # 甲、丙相鄰，乙在南邊最後
        href = pg.get_attribute("#tab-body a.btn.primary[href*='google.com/maps/dir']", "href")
        self.assertIn("waypoints=", href)
        pg.evaluate("document.querySelector(`#tab-body [data-trip='b']`).click()")
        self.assertFalse(pg.evaluate("__app.S.watch.find(w => w.id === 'b').trip"))
        self.assertIsNone(pg.evaluate("__app.S.watchSel || null"))      # 勾選框不會選到那一列
        # 看屋筆記：選一間、填檢查表與評分 → 分數與要注意的項目
        pg.evaluate("document.querySelector(`#tab-body tr[data-watch='a'] td:nth-child(2)`).click()")
        pg.select_option("select[data-wcheck='light']", "2"); pg.select_option("select[data-wcheck='noise']", "0")
        pg.select_option("select[data-wnote='rating']", "4")
        # 優點打完直接按「編輯」：一次就打開（不會被重畫吃掉）
        pg.fill("textarea[data-wnote='pros']", "邊間採光好")
        pg.click("#tab-body [data-act='watch-edit']")
        self.assertTrue(pg.evaluate("!!document.querySelector('dialog[open]')"))
        pg.evaluate("document.querySelector('dialog[open]').close()")
        self.assertEqual(pg.evaluate("__app.S.watch.find(w => w.id === 'a').pros"), "邊間採光好")
        body = pg.inner_text("#tab-body")
        self.assertIn("得分 50%", body); self.assertIn("要注意：噪音", body)
        self.assertEqual(pg.evaluate("__app.S.watch.find(w => w.id === 'a').rating"), 4)
        pg.evaluate("__app.S.watch.find(w => w.id === 'c').rating = 3; __app.S.watchSel = null; __app.selectDistrict('善化區')")
        pg.evaluate("document.querySelector(`#tab-body [data-act='wnote-cmp']`).click()")
        self.assertIn("並排比較", pg.inner_text("#tab-body"))
        self.assertIn("✗ 差", pg.inner_text("#tab-body table.cmp"))

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
                   {"type": "way", "id": 4, "center": {"lat": lat - 0.004, "lon": lng}, "tags": {"landuse": "cemetery"}},
                   # 高壓電線：兩段同名，只算一條；距離量到線上最近一點（約 110 公尺），不是線的中心
                   {"type": "way", "id": 5, "tags": {"power": "line", "name": "高壓線C"},
                    "geometry": [{"lat": lat + 0.001, "lon": lng - 0.02}, {"lat": lat + 0.001, "lon": lng}]},
                   {"type": "way", "id": 6, "tags": {"power": "line", "name": "高壓線C"},
                    "geometry": [{"lat": lat + 0.001, "lon": lng}, {"lat": lat + 0.001, "lon": lng + 0.02}]},
                   {"type": "way", "id": 7, "tags": {"railway": "subway", "tunnel": "yes"},
                    "geometry": [{"lat": lat, "lon": lng - 0.01}, {"lat": lat, "lon": lng + 0.01}]}]
            route.fulfill(status=200, content_type="application/json", body=_json.dumps({"elements": els}))
        pg.route("**/api/interpreter", handle)
        pg.wait_for_function("__app.D.txs")
        pg.fill("#q", "善化區成功路169巷10號"); pg.press("#q", "Enter"); pg.wait_for_timeout(1200)
        pg.click("[data-act='poi']"); pg.wait_for_timeout(1200)
        text = pg.inner_text("#tab-body")
        self.assertIn("超商A", text); self.assertIn("加油站B", text); self.assertNotIn("太遠的醫院", text)
        self.assertEqual(pg.evaluate("__app.S.tab"), "poi")
        self.assertEqual(pg.evaluate("__app.view.pois.length"), 4)
        self.assertIn("高壓線C", text); self.assertNotIn("鐵路、高架捷運（噪音、震動）\t1", text)      # 地下捷運不算
        self.assertEqual(pg.evaluate("__app.S.poi.res.byCat.hvline.n"), 1)
        self.assertLess(abs(pg.evaluate("__app.S.poi.res.byCat.hvline.nearest.d") - 111), 5)

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



def _make_tw_fixture(root):
    """把 web/ 複製到暫存資料夾，加上一個假的「臺北市」（3 區、幾十筆成交、一條路），測全台版的切換流程。"""
    import shutil
    import random
    from core import prices
    from tools import export_tw
    web = os.path.join(root, "web")
    shutil.copytree(WEB, web)
    export_tw.OUT = os.path.join(web, "data", "tw")
    rnd = random.Random(7)
    towns = [{"name": "大安區", "lat": 25.0263, "lng": 121.5434}, {"name": "信義區", "lat": 25.0330, "lng": 121.5654},
             {"name": "中正區", "lat": 25.0324, "lng": 121.5199}]
    txs = []
    for i in range(90):
        t = towns[i % 3]
        num = 100 + (i % 9) * 10
        m = 1 + i % 12
        txs.append({"id": "T%d" % i, "dist": t["name"], "ym": "2026-%02d" % min(m, 8), "date": "2026-%02d-15" % min(m, 8),
                    "cat": "apt", "btype": "住宅大樓", "addr": "臺北市%s信義路三段%d號%d樓" % (t["name"], num, 3 + i % 9),
                    "tw": 2500 + rnd.random() * 2000, "u": 90 + rnd.random() * 40, "ping": 30 + rnd.random() * 10,
                    "built": 2005, "floors": "", "note": "", "kind": "sale", "proj": ""})
    os.makedirs(os.path.join(export_tw.OUT, "A", "roads"), exist_ok=True)
    raw = prices.build_book(txs, [t["name"] for t in towns], as_of="2026-10-02", total="台北市", today_ym="2026-10")
    export_tw._dump("A/book.json", raw)
    export_tw._dump("A/districts.json", {"districts": towns})
    export_tw.export_tx("A", txs, [t["name"] for t in towns])
    from core import rent as rentmod                # 租金行情：大安區、信義區各幾十筆租賃
    rents = []
    for i in range(60):
        t = towns[i % 2]
        ping = 20 + (i % 4) * 8
        rents.append({"id": "R%d" % i, "dist": t["name"], "ym": "2026-%02d" % (1 + i % 8), "cat": "room" if i % 10 == 0 else "apt",
                      "rent": ping * (1100 + rnd.random() * 300), "ping": ping, "unit": 0, "rooms": 1 + i % 4, "built": 2005})
        rents[-1]["unit"] = rents[-1]["rent"] / ping
    export_tw._dump("A/rent.json", rentmod.build_rent_book(rents, [t["name"] for t in towns], raw["complete_through"], "台北市"))
    from core import longterm                       # 長期走勢：大安區近 5 年每月 20 筆，單價每月 +0.3
    old = []
    for k in range(66):
        y, m = 2021 + (3 + k) // 12, (3 + k) % 12 + 1
        for j in range(20):
            old.append({"id": "L%d_%d" % (k, j), "dist": "大安區", "ym": "%04d-%02d" % (y, m), "cat": "apt", "kind": "sale",
                        "u": 80 + k * 0.3 + j * 0.05, "tw": 2500 + k * 10})
    months = prices.ym_range("2021-04", raw["complete_through"])
    export_tw._dump("A/long.json", longterm.long_book(longterm.summarize(old, "台北市"), months, raw, raw["months"][0]))
    from tools import build_population             # 人口：大安區近 5 年增加、信義區減少
    pop = {"years": [110, 111, 112, 113, 114], "month": "11508", "mig_months": ["114%02d" % m for m in range(9, 13)] + ["115%02d" % m for m in range(1, 9)], "counties": {"A": {
        "大安區": {"pop": {str(y): 300000 + (y - 110) * 2000 for y in range(110, 115)}, "now": 308500, "hh": 120000,
                 "age": [30000, 30000, 90000, 90000, 68500], "in12": 9000, "out12": 7000},
        "信義區": {"pop": {str(y): 220000 - (y - 110) * 3000 for y in range(110, 115)}, "now": 208000, "hh": 90000,
                 "age": [20000, 20000, 50000, 60000, 58000], "in12": 5000, "out12": 6500}}}}
    old_web = build_population.WEB_TW
    build_population.WEB_TW = export_tw.OUT
    try:
        build_population.write_web(pop)
    finally:
        build_population.WEB_TW = old_web
    line = [25.0335, 121.5300, 25.0337, 121.5400, 25.0339, 121.5500]
    export_tw._dump("A/roads/大安區.json", {"roads": {"信義路三段": [line]}, "places": {}, "fetched": "2026-10-02"})
    # 全台首頁的統計：原本的臺南市＋假的臺北市
    tn = prices.load_transactions()
    nat = prices.build_book([dict(x, dist="台南市") for x in tn] + [dict(x, dist="台北市") for x in txs], ["台北市", "台南市"],
                            as_of="2026-10-02", total="全台", today_ym="2026-10")
    export_tw._dump("book.json", nat)
    with open(os.path.join(WEB, "data", "tw", "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    for c in index["counties"]:
        if c["code"] == "A":
            c.update(has_data=True, towns=3, town_names=[t["name"] for t in towns], roads=["大安區"], tx_count=len(txs))
    export_tw._dump("index.json", index)
    from tools import build_transit                 # 營運中的捷運：用 test_taiwan 的假 Overpass 回傳
    try:
        from test_taiwan import _transit_fixture
    except ImportError:
        from tests.test_taiwan import _transit_fixture
    tl = build_transit.build(_transit_fixture(), {"A": [{"name": "信義區", "lat": 25.033, "lng": 121.567}]})
    with open(os.path.join(web, "data", "tw", "transit.json"), "w", encoding="utf-8") as f:
        json.dump({"as_of": "2026-10-04", "lines": tl}, f, ensure_ascii=False)
    return web


@unittest.skipIf(sync_playwright is None, "沒有安裝 playwright")
@unittest.skipIf(not os.path.exists(os.path.join(WEB, "data", "tw", "index.json")) or not os.path.exists(
    os.path.join(ROOT, "data", "cache", "transactions.json")), "沒有全台版資料或台南逐筆快取")
class TaiwanWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        web = _make_tw_fixture(cls.tmp)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=web)
        handler.log_message = lambda *a: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/" % cls.httpd.server_address[1]
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_nation_and_counties(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        ctx.route("https://wmts.nlsc.gov.tw/**", lambda r: r.abort())
        ctx.route("https://geomap.gsmma.gov.tw/**", lambda r: r.abort())
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(self.url)
        pg.wait_for_function("window.__app && __app.D.tw")
        self.assertEqual(pg.evaluate("__app.S.current"), "全台")
        self.assertEqual(pg.evaluate("__app.D.districts.length"), 22)
        # 跨縣市比較：台北大安區 vs 台南東區
        pg.evaluate("__app.S.settings.cmp = []")
        pg.evaluate("__app.enterCounty('A')"); pg.wait_for_function("__app.D.county && __app.D.county.code === 'A'")
        pg.evaluate("__app.selectDistrict('大安區')"); pg.wait_for_timeout(200)
        pg.evaluate("__app.S.tab = 'overview'"); pg.evaluate("__app.selectDistrict('大安區')")
        # 租金行情、交屋前現金、買房 vs 租房
        body = pg.inner_text("#tab-body")
        for want in ("租金行情", "毛租金報酬率", "交屋前要準備多少現金", "買房還是租房比較划算"):
            self.assertIn(want, body)
        pg.evaluate("document.querySelector(`details[data-det='rvbOpen'] > summary`).click()")
        self.assertIn("年後：買房約", pg.inner_text("#rvb-out"))
        before = pg.inner_text("#rvb-out")
        pg.fill("input[data-rvb='rent']", "200000"); pg.wait_for_timeout(100)
        self.assertNotEqual(pg.inner_text("#rvb-out"), before)
        self.assertTrue(pg.evaluate("__app.S.settings.rvbOpen"))
        pg.fill("input[data-rvb='rent']", ""); pg.evaluate("document.querySelector(`details[data-det='rvbOpen'] > summary`).click()")
        pg.evaluate("document.querySelector(`details[data-det='costOpen'] > summary`).click()")
        self.assertIn("契稅", pg.inner_text("#cost-out"))
        t1 = pg.inner_text("#cost-out .total"); pg.fill("input[data-cost='agent']", "0"); pg.wait_for_timeout(100)
        self.assertNotEqual(pg.inner_text("#cost-out .total"), t1)
        pg.fill("input[data-cost='agent']", "2"); pg.evaluate("document.querySelector(`details[data-det='costOpen'] > summary`).click()")
        pg.evaluate("__app.selectDistrict('中正區')")
        self.assertIn("近一年沒有這一區的租賃登錄", pg.inner_text("#tab-body"))
        pg.evaluate("__app.selectDistrict('大安區')")
        pg.evaluate("document.querySelector(`#tab-body [data-act='cmp-add']`).click()"); pg.wait_for_timeout(200)
        pg.evaluate("__app.enterCounty('D')"); pg.wait_for_function("__app.D.county && __app.D.county.code === 'D'")
        pg.evaluate("__app.S.tab = 'overview'"); pg.evaluate("__app.selectDistrict('東區')"); pg.wait_for_timeout(200)
        pg.evaluate("document.querySelector(`#tab-body [data-act='cmp-add']`).click()")
        pg.wait_for_function("document.querySelectorAll('#tab-body table.cmp thead th').length === 3")
        heads = pg.inner_text("#tab-body table.cmp thead")
        self.assertIn("台北 大安區", heads); self.assertIn("台南 東區", heads)
        self.assertIn("中位單價", pg.inner_text("#tab-body table.cmp"))
        self.assertIn("毛租金報酬率", pg.inner_text("#tab-body table.cmp"))
        self.assertRegex(pg.inner_text("#tab-body table.cmp"), r"\d\.\d%")              # 大安區有租金資料
        pg.evaluate("document.querySelector(`#tab-body [data-cmpdel='0']`).click()"); pg.wait_for_timeout(200)
        self.assertEqual(pg.locator("#tab-body table.cmp thead th").count(), 2)
        pg.evaluate("__app.S.settings.cmp = []; __app.enterNation()")
        # 全台營運中的捷運：畫在地圖上，點車站看得到路線名稱
        pg.wait_for_function("__app.D.transit && __app.D.transit.length")
        self.assertIn("淡水信義線", pg.evaluate("__app.view.lines.map(l => l.name)"))
        pg.evaluate("__app.pick(['station', ['淡水信義線', '中山站']])")
        pg.wait_for_timeout(200)
        self.assertIn("營運中", pg.inner_text("#tab-body"))
        self.assertIn("先在地圖上點一個縣市", pg.evaluate("(() => { __app.S.tab = 'tx'; return 'x'; })()") and
                      (pg.click("#tabs button[data-tab='tx']") or pg.inner_text("#tab-body")))
        # 地址有縣市：自動切到臺北市、插圖釘
        self.assertEqual(pg.evaluate("__app.search('台北市大安區信義路三段120號')"), "address")
        pg.wait_for_timeout(600)
        st = pg.evaluate("({c: __app.D.county.code, cur: __app.S.current, pin: !!__app.S.pin, n: __app.D.txs.length})")
        self.assertEqual((st["c"], st["cur"], st["pin"], st["n"]), ("A", "大安區", True, 90))
        self.assertIn("台北市大安區", pg.evaluate("__app.L.platformLinks('大安區', '信義路三段')[0][1]").replace("%E5%8F%B0%E5%8C%97%E5%B8%82", "台北市").replace("%E5%A4%A7%E5%AE%89%E5%8D%80", "大安區"))
        # 回全台、點台南市的柱子（selectDistrict）→ 進到臺南市
        pg.click("#btn-nation"); pg.wait_for_timeout(300)
        self.assertIsNone(pg.evaluate("__app.D.county"))
        pg.evaluate("__app.selectDistrict('台南市')")
        pg.wait_for_function("__app.D.county && __app.D.county.code === 'D' && __app.D.txs")
        self.assertEqual(pg.evaluate("__app.D.districts.length"), 37)
        # 在臺南市搜尋另一縣市的地址
        self.assertEqual(pg.evaluate("__app.search('臺北市信義區')"), "district")
        self.assertEqual(pg.evaluate("[__app.D.county.code, __app.S.current]"), ["A", "信義區"])
        # 全台首頁只打鄉鎮名稱：唯一的縣市就切過去
        pg.evaluate("__app.enterNation()")
        self.assertEqual(pg.evaluate("__app.search('中正區')"), "district")
        self.assertEqual(pg.evaluate("__app.D.county.code"), "A")
        # 重新開啟：回到上次看的縣市
        pg.reload(); pg.wait_for_function("window.__app && __app.D.county && __app.D.txs")
        self.assertEqual(pg.evaluate("__app.D.county.code"), "A")
        # 點臺南市的地標 → 切到臺南市
        pg.evaluate("__app.pick(['landmark', __app.D.landmarks[0].id])")
        pg.wait_for_function("__app.D.county.code === 'D' && __app.S.tab === 'detail'")
        # 還沒預先整理道路的區：在裝置上向 OpenStreetMap 查（這裡用假的回應），之後就能插圖釘
        import json as _json
        geo = [{"lat": 25.0330, "lon": 121.5600}, {"lat": 25.0332, "lon": 121.5650}, {"lat": 25.0334, "lon": 121.5700}]
        fake = {"elements": [{"type": "way", "id": 1, "tags": {"highway": "primary", "name": "信義路三段"}, "geometry": geo[:2]},
                             {"type": "way", "id": 2, "tags": {"highway": "primary", "name": "信義路三段"}, "geometry": geo[1:]}]}
        ctx.route("**/api/interpreter", lambda r: r.fulfill(status=200, content_type="application/json", body=_json.dumps(fake)))
        self.assertEqual(pg.evaluate("__app.search('台北市信義區信義路三段120號')"), "address")
        pg.wait_for_function("__app.S.pin && __app.S.current === '信義區'", timeout=10000)
        self.assertEqual(pg.evaluate("__app.view.roads.length >= 0"), True)
        # 錯誤紀錄與回報：記在這台裝置，選單裡可以帶著內容開 GitHub Issue
        pg.evaluate("__app.logError('測試', new Error('假的錯誤'))")
        self.assertTrue(pg.evaluate("document.querySelector('#btn-menu').classList.contains('has-err')"))
        pg.click("#btn-menu")
        self.assertIn("假的錯誤", pg.inner_text("#menu-body"))
        ctx.route("https://github.com/**", lambda r: r.fulfill(status=200, body="ok"))
        with pg.expect_popup() as pop:
            pg.click("[data-act='err-report']")
        url = unquote(pop.value.url)
        self.assertIn("github.com/bkhotey4/housepriceanalysis/issues/new", url)
        self.assertIn("假的錯誤", url)
        self.assertEqual(errors, [])

    def test_long_trend(self):
        """近 5 年走勢：概況可切換近 1 年／近 5 年，顯示 5 年、3 年漲跌；排行多一欄 5 年。"""
        ctx = self.browser.new_context(viewport={"width": 1200, "height": 800})
        ctx.route("https://wmts.nlsc.gov.tw/**", lambda r: r.abort())
        ctx.route("https://geomap.gsmma.gov.tw/**", lambda r: r.abort())
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(self.url + "?c=A&d=" + quote("大安區"))
        pg.wait_for_function("window.__app && __app.D.county && __app.D.long && __app.S.current === '大安區'")
        pg.evaluate("__app.S.cat = 'apt'; __app.S.tab = 'overview'; __app.selectDistrict('大安區')")
        body = pg.inner_text("#tab-body")
        self.assertIn("近 5 年", body)
        self.assertRegex(body, r"近 5 年單價漲 \d+\.\d%")
        pg.evaluate("document.querySelector(`#tab-body [data-act='span'][data-span='5']`).click()")
        self.assertIn("每季中位單價", pg.inner_text("#tab-body h2"))
        self.assertEqual(pg.evaluate("__app.S.settings.span"), 5)
        # 房價時光機：縣市總覽拉到第一季 → 柱子變成那一季的價格、圖例顯示季別；按「回到現在」恢復
        pg.evaluate("__app.S.tab = 'overview'; __app.selectDistrict(__app.L.CITY)")
        self.assertIn("房價時光機", pg.inner_text("#tab-body"))
        now_label = pg.evaluate("__app.view.bars.find(b => b.id === '大安區').label")
        pg.evaluate("(() => { const r = document.querySelector('#tm-range'); r.value = 0; r.dispatchEvent(new Event('input', {bubbles: true})); })()")
        self.assertIn("⏳ 2021 年第 2 季", pg.inner_text("#legend"))
        old_label = pg.evaluate("__app.view.bars.find(b => b.id === '大安區').label")
        self.assertNotEqual(old_label, now_label)
        self.assertRegex(old_label, r"大安區 8\d\.\d")                 # 2021 年的單價約 80 出頭
        self.assertEqual(pg.evaluate("__app.view.bars.find(b => b.id === '中正區').value"), None)
        pg.evaluate("document.querySelector('#tm-play').click()"); pg.wait_for_timeout(1600)
        self.assertGreater(pg.evaluate("__app.S.tm.i"), 0)
        # 播放中換成總價：下一格用總價的表（不會跳回單價）
        pg.evaluate("document.querySelector(`#chips [data-metric='t']`).click()"); pg.wait_for_timeout(900)
        self.assertGreater(pg.evaluate("__app.view.bars.find(b => b.id === '大安區').value || 0"), 1000)
        pg.evaluate("document.querySelector(`#chips [data-metric='u']`).click()")
        # 播放中點一個區：時光機停止、柱子回到現在
        pg.evaluate("__app.selectDistrict('大安區')")
        self.assertIsNone(pg.evaluate("__app.S.tm"))
        self.assertNotIn("⏳", pg.inner_text("#legend"))
        pg.evaluate("__app.S.tab = 'overview'; __app.selectDistrict(__app.L.CITY)")
        pg.evaluate("document.querySelector('#tm-play').click()"); pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('#tm-stop').click()")
        self.assertIsNone(pg.evaluate("__app.S.tm"))
        self.assertNotIn("⏳", pg.inner_text("#legend"))
        pg.evaluate("__app.selectDistrict('大安區')")
        # 人口與年齡結構
        body = pg.inner_text("#tab-body")
        self.assertIn("人口與年齡結構", body); self.assertIn("308,500", body); self.assertRegex(body, r"近 4 年 \+2\.7%")
        self.assertIn("遷入比遷出多 2,000 人", body)
        pg.evaluate("__app.S.settings.color = 'pop'; __app.selectDistrict('大安區')")
        self.assertIn("近 5 年人口增減", pg.inner_text("#legend"))
        pg.evaluate("document.querySelector(`#tabs [data-tab='rank']`).click()")
        self.assertIn("5 年", pg.inner_text("#tab-body thead"))
        self.assertRegex(pg.inner_text("#tab-body"), r"\+\d+%")
        self.assertEqual(errors, [])

    def test_share_link(self):
        """分享連結：網址帶縣市、區域、房型、分頁、比較清單，打開就是同一個畫面；畫面一變網址列跟著變。"""
        ctx = self.browser.new_context(viewport={"width": 1200, "height": 800})
        ctx.route("https://wmts.nlsc.gov.tw/**", lambda r: r.abort())
        ctx.route("https://geomap.gsmma.gov.tw/**", lambda r: r.abort())
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(self.url + "?c=A&d=" + quote("信義區") + "&cat=apt&m=t&tab=rank")
        pg.wait_for_function("window.__app && __app.D.county && __app.S.current === '信義區'")
        st = pg.evaluate("({cat: __app.S.cat, m: __app.S.metric, tab: __app.S.tab})")
        self.assertEqual(st, {"cat": "apt", "m": "t", "tab": "rank"})
        # 柱子也要換成「大樓總價」（不能還是全部合併的單價）
        bar = pg.evaluate("__app.view.bars.find(b => b.id === '信義區').value")
        self.assertEqual(bar, pg.evaluate("__app.D.book.best('信義區', 'apt', 't').value"))
        self.assertEqual(pg.evaluate("document.querySelector('#chips [data-cat=apt]').getAttribute('aria-checked')"), "true")
        self.assertIn("d=%E4%BF%A1%E7%BE%A9%E5%8D%80", pg.evaluate("location.search"))
        pg.evaluate("__app.selectDistrict('大安區')")
        self.assertIn(quote("大安區"), pg.evaluate("location.search"))
        url = pg.evaluate("__app.shareUrl()")
        self.assertIn("c=A", url); self.assertIn("tab=rank", url); self.assertIn("cat=apt", url)
        # 比較清單跟著連結走
        pg.goto(self.url + "?c=A&tab=cmp&cmp=" + quote("A:大安區,D:東區"))
        pg.wait_for_function("window.__app && __app.D.county && document.querySelectorAll('#tab-body table.cmp thead th').length === 3")
        self.assertIn("台南 東區", pg.inner_text("#tab-body table.cmp thead"))
        # 分享按鈕：沒有 navigator.share 時複製連結
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        pg.evaluate("delete navigator.share")
        pg.click("#map-tools [data-act='share']"); pg.wait_for_timeout(200)
        self.assertIn("已複製連結", pg.inner_text("#toast"))
        self.assertIn("cmp=", pg.evaluate("navigator.clipboard.readText()"))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
