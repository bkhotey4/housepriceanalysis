import functools
import http.server
import os
import sys
import threading
import time
import unittest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

class SearchAutocompleteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=WEB)
        handler.log_message = lambda *a: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/?tw=0"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def test_instant_autocomplete_and_navigation(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 輸入「東區」：即時出現選單，並包含行政區「東區」
        page.fill("#q", "東區")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("東區" in it["title"] and "行政區" in it["badge"] for it in items), f"Expected '東區' in {items}")
        self.assertFalse(page.eval_on_selector("#btn-clear", "el => el.hidden"))

        # 2. 測試鍵盤 ArrowDown 與 Enter 選取
        page.keyboard.press("ArrowDown")
        active_title = page.eval_on_selector("#search-sug .sug-item.active .sug-title", "e => e.innerText")
        self.assertTrue(len(active_title) > 0)
        page.keyboard.press("Enter")
        # 選單應立即收合
        self.assertTrue(page.eval_on_selector("#search-sug", "el => el.hidden"))
        # 應立即切換至選取的行政區
        page.wait_for_timeout(300)
        current = page.evaluate("__app.S.current")
        self.assertEqual(current, "東區")

        # 3. 測試清除按鈕
        page.click("#btn-clear")
        self.assertEqual(page.eval_on_selector("#q", "el => el.value"), "")
        self.assertTrue(page.eval_on_selector("#btn-clear", "el => el.hidden"))
        self.assertTrue(page.eval_on_selector("#search-sug", "el => el.hidden"))

        # 4. 輸入地標「成大」：應透過別名即時命中「國立成功大學」
        page.fill("#q", "成大")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        page.wait_for_timeout(200)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("成功大學" in it["title"] and "地標" in it["badge"] for it in items), f"Expected '成功大學' in {items}")

        # 清除並重設
        page.click("#btn-clear")
        page.wait_for_timeout(100)

        # 5. 輸入明星學區「後甲」：應即時命中「後甲國民中學」
        page.fill("#q", "後甲")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        page.wait_for_timeout(200)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("後甲" in it["title"] and "明星學區" in it["badge"] for it in items), f"Expected '後甲' in {items}")

        # 點擊該學區選單項目
        page.click("#search-sug .sug-item:has-text('後甲國民中學')")
        self.assertTrue(page.eval_on_selector("#search-sug", "el => el.hidden"))
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.tab"), "detail")

        # 6. 輸入熱門路段「中華東路」：應即時提示實價路段
        page.click("#btn-clear")
        page.fill("#q", "中華東路")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        page.wait_for_timeout(200)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("中華東路" in it["title"] and "路段" in it["badge"] for it in items), f"Expected '中華東路' in {items}")

        # 點擊路段，地圖應立即插圖釘並顯示成交紀錄
        page.click("#search-sug .sug-item:has-text('中華東路')")
        page.wait_for_timeout(400)
        pin = page.evaluate("__app.S.pin")
        self.assertIsNotNone(pin)
        self.assertIn("中華東路", pin["label"])

        ctx.close()

    def test_desktop_and_direct_address(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 820})
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 寬螢幕：輸入地址並按 Enter 直接搜尋
        page.fill("#q", "善化區中山路123號")
        page.press("#q", "Enter")
        page.wait_for_timeout(500)
        self.assertEqual(page.evaluate("__app.S.current"), "善化區")
        pin = page.evaluate("__app.S.pin")
        self.assertIsNotNone(pin)
        self.assertIn("中山路", pin["label"])

        # 2. 搜尋建設「平實」
        page.fill("#q", "平實")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        page.wait_for_timeout(200)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("平實" in it["title"] and "重大建設" in it["badge"] for it in items), f"Expected '平實' in {items}")
        page.click("#search-sug .sug-item:has-text('平實')")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.tab"), "detail")

        ctx.close()

    def test_zero_typing_landmark_shortcuts_and_category_chips(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 點擊/聚焦搜尋框時，在無輸入狀態下應自動展開「熱門生活地標捷徑」面板
        page.click("#q")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-chips", timeout=3000)
        chips = page.eval_on_selector_all("#search-sug .sug-chip", "els => els.map(e => e.innerText.trim())")
        self.assertTrue(any("核心商圈" in c for c in chips), f"Expected 核心商圈 in chips: {chips}")
        self.assertTrue(any("知名夜市" in c for c in chips), f"Expected 知名夜市 in chips: {chips}")
        self.assertTrue(any("醫療中心" in c for c in chips), f"Expected 醫療中心 in chips: {chips}")

        # 下方應同時列出預先推薦的熱門地標
        rec_items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => e.querySelector('.sug-title').innerText)")
        self.assertTrue(len(rec_items) >= 5, f"Expected at least 5 recommended landmarks, got {len(rec_items)}")

        # 2. 點擊「知名夜市」快捷標籤，搜尋框應自動填入「夜市」並列出知名夜市
        page.click("#search-sug .sug-chip:has-text('知名夜市')")
        page.wait_for_timeout(200)
        self.assertEqual(page.eval_on_selector("#q", "el => el.value"), "夜市")
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        titles = [it["title"] for it in items]
        self.assertTrue(any("花園夜市" in t for t in titles), f"Expected 花園夜市 in {titles}")
        self.assertTrue(any("大東夜市" in t for t in titles), f"Expected 大東夜市 in {titles}")
        self.assertTrue(any("武聖夜市" in t for t in titles), f"Expected 武聖夜市 in {titles}")

        # 點擊「花園夜市」應立即導航並打開詳情
        page.click("#search-sug .sug-item:has-text('花園夜市')")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.tab"), "detail")
        detail_text = page.eval_on_selector("#tab-body", "el => el.innerText")
        self.assertIn("花園夜市", detail_text)
        self.assertIn("北區", detail_text)

        ctx.close()

    def test_landmark_search_and_detail_navigation(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 820})
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 搜尋「三井」應命中 MITSUI OUTLET PARK 台南
        page.fill("#q", "三井")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("MITSUI OUTLET" in it["title"] or "三井" in it["title"] for it in items))

        # 2. 搜尋「好市多」應命中 好市多台南店
        page.click("#btn-clear")
        page.fill("#q", "好市多")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("好市多" in it["title"] for it in items))

        # 點擊好市多
        page.click("#search-sug .sug-item:has-text('好市多')")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.tab"), "detail")
        detail_text = page.eval_on_selector("#tab-body", "el => el.innerText")
        self.assertIn("好市多", detail_text)

        # 3. 搜尋「成大醫院」應命中成大醫院
        page.fill("#q", "成大醫院")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("成大醫院" in it["title"] and "醫療中心" in it["badge"] for it in items))

        ctx.close()

    def test_other_county_search_protection_and_scenario_cards(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 820})
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 搜尋「台中市政府」：即時選單應標註外縣市未收錄，且不應誤匹配台南
        page.fill("#q", "台中市政府")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText, sub: e.querySelector('.sug-sub').innerText }))")
        self.assertTrue(any("台中" in it["title"] and ("未收錄" in it["badge"] or "其他縣市" in it["badge"]) for it in items), f"Expected 台中 and 未收錄 in {items}")
        # 不應出現台南市政府
        self.assertFalse(any("臺南市政府" in it["title"] for it in items))

        # 點擊台中市政府選單項目，應跳出台南專版提示，不改變台南視角
        page.click("#search-sug .sug-item:has-text('臺中市政府')")
        page.wait_for_timeout(300)
        toast_text = page.eval_on_selector("#toast:not([hidden])", "e => e.innerText")
        self.assertIn("台南房價專版", toast_text)
        self.assertEqual(page.evaluate("__app.S.current"), "台南市")

        # 2. 直接按 Enter 搜尋「台中市政府」
        page.fill("#q", "台中市政府")
        page.press("#q", "Enter")
        page.wait_for_timeout(300)
        toast_text = page.eval_on_selector("#toast:not([hidden])", "e => e.innerText")
        self.assertIn("非台南地區", toast_text)
        self.assertEqual(page.evaluate("__app.S.current"), "台南市")

        # 3. 直接按 Enter 搜尋「台北101」
        page.click("#btn-clear")
        page.fill("#q", "台北101")
        page.press("#q", "Enter")
        page.wait_for_timeout(300)
        toast_text = page.eval_on_selector("#toast:not([hidden])", "e => e.innerText")
        self.assertIn("非台南地區", toast_text)

        # 4. 搜尋「臺南市政府」應正常定位台南市政府
        page.click("#btn-clear")
        page.fill("#q", "臺南市政府")
        page.press("#q", "Enter")
        page.wait_for_timeout(400)
        self.assertEqual(page.evaluate("__app.S.tab"), "detail")
        detail_text = page.eval_on_selector("#tab-body", "e => e.innerText")
        self.assertIn("臺南市政府", detail_text)

        # 5. 測試買房情境快捷導航卡 (Scenario Quick Cards)
        page.evaluate("__app.selectDistrict('台南市')")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.current"), "台南市")
        page.wait_for_selector(".scenario-card[data-scenario='nanke']", timeout=3000)
        # 點擊「南科通勤生活圈」卡片
        page.click(".scenario-card[data-scenario='nanke']")
        page.wait_for_timeout(400)
        self.assertEqual(page.evaluate("__app.S.current"), "善化區")

        # 6. 測試常用坪數快速帶入膠囊 (Ping Chips)
        page.click("button[data-tab='value']")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.tab"), "value")
        page.wait_for_selector(".ping-chip[data-ping='30']", timeout=3000)
        page.click(".ping-chip[data-ping='30']")
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("__app.S.settings.val.ping"), "30")

        ctx.close()

if __name__ == "__main__":
    unittest.main()


