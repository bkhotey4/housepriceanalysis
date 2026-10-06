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

        # 1. 桌面版輸入地址並按 Enter 直接搜尋
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

if __name__ == "__main__":
    unittest.main()

