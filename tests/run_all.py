"""一次跑完所有測試。在電腦或平板（Pydroid 3）上直接執行這個檔案即可：

    python tests/run_all.py

結果除了顯示在畫面上，也會存到 tests/last_result.txt，有問題時把那個檔案的內容貼出來即可。
"""
import os
import platform
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
RESULT_PATH = os.path.join(HERE, "last_result.txt")


class Tee:
    """同時寫到畫面與檔案。"""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text):
        try:
            self.stream.write(text)
        except Exception:
            pass
        self.log.write(text)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            pass
        self.log.flush()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # 舊式主控台遇到無法顯示的字不要中斷
        except Exception:
            pass
    try:
        log = open(RESULT_PATH, "w", encoding="utf-8")
    except OSError:
        log = open(os.devnull, "w")
    out = Tee(sys.stderr, log)
    try:
        import PIL
        pillow = PIL.__version__
    except Exception:
        pillow = "未安裝"
    out.write("%s | Python %s | %s | Pillow %s\n\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), platform.python_version(), platform.platform(), pillow))
    suite = unittest.defaultTestLoader.discover(HERE)
    t0 = time.time()
    result = unittest.TextTestRunner(stream=out, verbosity=2).run(suite)
    summary = "\n結果：%s（執行 %d 項，失敗 %d，錯誤 %d，略過 %d，%.0f 秒）\n" % (
        "全部通過" if result.wasSuccessful() else "有問題，請把上面的訊息（或 tests/last_result.txt）貼給我",
        result.testsRun, len(result.failures), len(result.errors), len(result.skipped), time.time() - t0)
    log.write(summary)
    log.close()
    print(summary)
