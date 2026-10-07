"""啟動器（app.py）：本機模式能把 web/ 資料夾送給瀏覽器，連不到線上版時判斷正確。"""
import os
import sys
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402


class LauncherTest(unittest.TestCase):
    def test_local_server_serves_web(self):
        port = app.free_port(0)
        httpd = app.make_server(port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = "http://127.0.0.1:%d/" % port
        with urllib.request.urlopen(base, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("房價分析", r.read().decode("utf-8"))
        with urllib.request.urlopen(base + "js/main.js", timeout=5) as r:      # 模組一定要是 JavaScript 類型，瀏覽器才肯執行
            self.assertIn("javascript", r.headers["Content-Type"])
        with urllib.request.urlopen(base + "data/meta.json", timeout=5) as r:
            self.assertIn("json", r.headers["Content-Type"])

    def test_offline_detection(self):
        self.assertFalse(app.online("http://127.0.0.1:1/", timeout=1))

    def test_busy_port_falls_back(self):
        port = app.free_port(0)
        httpd = app.make_server(port)
        self.addCleanup(httpd.server_close)
        self.assertNotEqual(app.free_port(port), port)


if __name__ == "__main__":
    unittest.main()
