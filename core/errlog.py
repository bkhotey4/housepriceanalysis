"""桌面版的錯誤紀錄：程式出錯時把錯誤寫進 logs/app_errors.log（本機），方便之後知道錯在哪。

不會自動上傳（裡面可能有電腦的路徑）；要回報時打開這個檔案，把內容貼到 GitHub Issue 或給維護者就好。
"""
import datetime
import os
import sys
import traceback

from .geo import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "app_errors.log")
MAX_BYTES = 1_000_000


def write(where, exc_type=None, exc=None, tb=None):
    """記一筆錯誤；exc 為 None 時記目前正在處理的例外。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        if exc is None:
            exc_type, exc, tb = sys.exc_info()
        text = "".join(traceback.format_exception(exc_type, exc, tb)) if exc else "(沒有例外資訊)\n"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("==== %s｜%s\n%s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), where, text))
    except OSError:
        pass


def install(root=None):
    """接上 Python 與 Tk 的錯誤處理：沒被接住的例外都會記下來（原本的行為不變）。"""
    old = sys.excepthook

    def hook(t, e, tb):
        write("未處理的錯誤", t, e, tb)
        old(t, e, tb)
    sys.excepthook = hook
    if root is not None:
        old_cb = root.report_callback_exception

        def cb(t, e, tb):
            write("介面操作時出錯", t, e, tb)
            old_cb(t, e, tb)
        root.report_callback_exception = cb
