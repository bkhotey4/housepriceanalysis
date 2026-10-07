"""房價分析的啟動器：用瀏覽器打開網頁版（只用 Python 標準函式庫）。

    python app.py            有網路：開線上版（全台資料、每月自動更新）；沒網路：在本機開 web/ 資料夾
    python app.py --local    一律在本機開 web/ 資料夾（離線、或測試自己改過的程式）
    python app.py --port 8000

本機模式會在 127.0.0.1 開一個只有這台電腦連得到的小伺服器，關掉這個視窗（或按 Ctrl+C）就停止。
本機的 web/data 預設只有臺南市；要全台資料請先執行 python tools/export_tw.py --update。
"""
import argparse
import functools
import http.server
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

ONLINE_URL = "https://bkhotey4.github.io/housepriceanalysis/"
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def online(url=ONLINE_URL, timeout=4):
    """線上版連得到嗎？"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def free_port(preferred):
    """preferred 被佔用時讓系統挑一個空的埠。"""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise SystemExit("找不到可用的連接埠")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """不在畫面上印每一個請求；.json、.js 用正確的類型（舊版 Windows 的登錄檔有時會給錯）。"""
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".json": "application/json", ".webmanifest": "application/manifest+json"}

    def log_message(self, *args):
        pass


def make_server(port, directory=WEB_DIR):
    handler = functools.partial(QuietHandler, directory=directory)
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve_local(port, open_browser=True):
    if not os.path.exists(os.path.join(WEB_DIR, "index.html")):
        raise SystemExit("找不到 web/index.html，請確認是在專案資料夾裡執行。")
    port = free_port(port)
    httpd = make_server(port)
    url = "http://127.0.0.1:%d/" % port
    print("房價分析（本機模式）：%s" % url)
    print("關掉這個視窗或按 Ctrl+C 結束。")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="用瀏覽器打開房價分析")
    ap.add_argument("--local", action="store_true", help="不連線上版，直接在本機開 web/ 資料夾")
    ap.add_argument("--port", type=int, default=8000, help="本機模式的連接埠（預設 8000，被佔用時自動換）")
    ap.add_argument("--no-browser", action="store_true", help="只開伺服器，不自動開瀏覽器")
    args = ap.parse_args(argv)
    if not args.local:
        print("檢查網路…")
        if online():
            print("開啟線上版：%s" % ONLINE_URL)
            if not args.no_browser:
                webbrowser.open(ONLINE_URL)
            return 0
        print("連不到線上版，改用本機的資料。")
    serve_local(args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
