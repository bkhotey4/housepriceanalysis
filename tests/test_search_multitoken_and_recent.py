import functools
import http.server
import os
import threading
import unittest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

class SearchMultiTokenAndRecentTest(unittest.TestCase):
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

    def test_multitoken_and_space_search(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 820})
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 1. 複合字搜尋「善化 國小」：應透過行政區+類型命中「小新國民小學」，且標註標籤正確包裹
        page.fill("#q", "善化 國小")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, titleHtml: e.querySelector('.sug-title').innerHTML, badge: e.querySelector('.sug-badge').innerText, sub: e.querySelector('.sug-sub') ? e.querySelector('.sug-sub').innerText : '', subHtml: e.querySelector('.sug-sub') ? e.querySelector('.sug-sub').innerHTML : '' }))")
        self.assertTrue(any("小新" in it["title"] and "明星學區" in it["badge"] and "善化" in it["sub"] for it in items), f"Expected 小新國民小學 in {items}")
        # 確認 sub 或 title 中有標註 <mark>
        self.assertTrue(any("<mark>" in it["subHtml"] or "<mark>" in it["titleHtml"] for it in items), f"Expected <mark> in results {items}")

        # 2. 複合字搜尋「東區 崇明」：應命中「崇明路」或「崇明國民中學」
        page.click("#btn-clear")
        page.fill("#q", "東區 崇明")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, badge: e.querySelector('.sug-badge').innerText }))")
        self.assertTrue(any("崇明" in it["title"] for it in items), f"Expected 崇明 in {items}")

        # 3. 複合字跨縣市搜尋「台中 歌劇院」：應命中「臺中國家歌劇院」，且標籤 highlight 支援「臺/台」1:1 對齊
        page.click("#btn-clear")
        page.fill("#q", "台中 歌劇院")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        items = page.eval_on_selector_all("#search-sug .sug-item", "els => els.map(e => ({ title: e.querySelector('.sug-title').innerText, titleHtml: e.querySelector('.sug-title').innerHTML, badge: e.querySelector('.sug-badge').innerText }))")
        opera = next((it for it in items if "歌劇院" in it["title"]), None)
        self.assertIsNotNone(opera, f"Expected 歌劇院 in {items}")
        self.assertIn("<mark>臺中</mark>", opera["titleHtml"])
        self.assertIn("<mark>歌劇院</mark>", opera["titleHtml"])

        ctx.close()

    def test_recent_search_history_and_clear(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 確保初始 localstorage 為空
        page.evaluate("localStorage.removeItem('house_recent_searches_v1')")

        # 1. 搜尋並選取「東區」
        page.fill("#q", "東區")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item", timeout=3000)
        page.click("#search-sug .sug-item:has-text('東區')")
        page.wait_for_timeout(300)

        # 2. 清空搜尋框後點擊，應出現「🕒 最近搜尋」與「東區」
        page.fill("#q", "")
        page.click("#q")
        page.wait_for_selector("#search-sug:not([hidden]) .sug-item-recent", timeout=3000)
        recent_titles = page.eval_on_selector_all(".sug-item-recent .sug-title", "els => els.map(e => e.innerText)")
        self.assertTrue(any("東區" in t for t in recent_titles), f"Expected 東區 in {recent_titles}")

        # 3. 點擊單筆刪除按鈕 ✕
        page.click(".sug-item-recent .sug-remove-btn")
        page.wait_for_timeout(300)
        has_recent = page.evaluate("() => !!document.querySelector('.sug-item-recent')")
        self.assertFalse(has_recent, "Expected recent searches to be empty after remove")

        ctx.close()

    def test_tx_incremental_loading(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 820})
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts && __app.D.txs")

        # 切換到「成交」分頁
        page.evaluate("__app.openTab('tx')")
        page.wait_for_selector("#tab-body tr[data-tx]", timeout=3000)
        initial_count = page.eval_on_selector_all("#tab-body tr[data-tx]", "els => els.length")
        self.assertLessEqual(initial_count, 60, f"Expected initial rows <= 60, got {initial_count}")

        # 若筆數有超過 60，應有載入更多按鈕
        more_btn = page.query_selector("[data-act='tx-more']")
        if more_btn:
            more_btn.click()
            page.wait_for_timeout(300)
            loaded_count = page.eval_on_selector_all("#tab-body tr[data-tx]", "els => els.length")
            self.assertGreater(loaded_count, initial_count, f"Expected loaded count > {initial_count}, got {loaded_count}")

        ctx.close()

    def test_bottom_sheet_snap_and_velocity(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("window.__app && __app.D.districts")

        # 初始狀態應為 peek
        s0 = page.evaluate("() => __app.S.sheet")
        self.assertEqual(s0, "peek")

        # 1. 點擊把手（無明顯滑動）：切換至 half
        handle = page.query_selector("#sheet-handle")
        box = handle.bounding_box()
        self.assertIsNotNone(box)
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)
        s1 = page.evaluate("() => __app.S.sheet")
        self.assertEqual(s1, "half")

        # 2. 模擬大幅度往上快速划動 (dy < -140)：從 half 或 peek 直通 full
        page.evaluate("__app.sheet('peek')")
        page.wait_for_timeout(200)
        hx = box["x"] + box["width"] / 2
        hy = box["y"] + box["height"] / 2

        # 透過 dispatchEvent 模擬 pointerdown, pointermove (dy = -160), pointerup
        page.evaluate("""() => {
            const h = document.querySelector('#sheet-handle');
            const rect = h.getBoundingClientRect();
            const y0 = rect.top + rect.height / 2;
            h.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientY: y0, pointerId: 1 }));
            h.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientY: y0 - 160, pointerId: 1 }));
            h.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientY: y0 - 160, pointerId: 1 }));
        }""")
        page.wait_for_timeout(300)
        s_full = page.evaluate("() => __app.S.sheet")
        self.assertEqual(s_full, "full", f"Expected sheet to snap to full on large upward swipe, got {s_full}")

        # 3. 模擬大幅度往下划動 (dy > 140)：從 full 直接縮回 peek
        page.evaluate("""() => {
            const h = document.querySelector('#sheet-handle');
            const rect = h.getBoundingClientRect();
            const y0 = rect.top + rect.height / 2;
            h.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientY: y0, pointerId: 1 }));
            h.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientY: y0 + 160, pointerId: 1 }));
            h.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientY: y0 + 160, pointerId: 1 }));
        }""")
        page.wait_for_timeout(300)
        s_peek = page.evaluate("() => __app.S.sheet")
        self.assertEqual(s_peek, "peek", f"Expected sheet to snap back to peek on large downward swipe, got {s_peek}")

        ctx.close()

if __name__ == "__main__":
    unittest.main()
