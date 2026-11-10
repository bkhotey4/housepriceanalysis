"""預售屋建案備查：解析內政部 zip（含欄位夾逗號的列、個人起造人）、產生網頁用清單、下載失敗時用快取。"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import buildcase, plvr, plvr_tw  # noqa: E402
from tools import build_buildcase  # noqa: E402

HEAD = "鄉鎮市區,建案名稱,坐落街道,起造人,層棟戶數,使用分區,主要用途,主要建材,申報備查日期,銷售期間,坐落基地,建照核發日期,建造執照,第1次登記日期,編號\n" \
       "TOWN,project name,street,builder,units,zone,use,material,date,period,land,permit date,permit,first reg,serial number\n"
ROWS = [
    "東區,甲案,崇學路,好建設股份有限公司 負責人:王Ｏ明,120,住宅區,住家用,鋼筋混凝土造,1151008,自售:1151010~,大同段1地號,1150801,(115)南工造字第1號,,ID1",
    "東區,乙案,林森路,黃大明,6,住宅區,住家用,鋼筋混凝土造,1150105,,大同段2地號,1141201,(114)南工造字第2號,1150301,ID2",
    "北區,丙案,西門路,北建設有限公司,40,住宅區,住家用,停車空間,鋼筋混凝土造,1150720,自售,北段3地號,1150601,(115)南工造字第3號,,ID3",   # 主要用途夾逗號：16 欄
]
LANDS = "編號,土地位置\nserial number,land\nID1,大同段1地號\nID1,大同段1-1地號\nID3,北段3地號\n"


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("d_lvr_buildcase.csv", ("﻿" + HEAD + "\n".join(ROWS) + "\n").encode("utf-8"))
        z.writestr("d_lvr_buildingland.csv", ("﻿" + LANDS).encode("utf-8"))
    return buf.getvalue()


class BuildcaseTest(unittest.TestCase):
    def test_parse(self):
        books, fixed = buildcase.parse_zip(make_zip())
        self.assertEqual(list(books), ["D"])
        self.assertEqual(fixed["D"], 1)
        d = books["D"]
        self.assertEqual(d["dists"], ["北區", "東區"])
        rows = {r[1]: r for r in d["rows"]}
        self.assertEqual(rows["甲案"][3], "好建設股份有限公司")         # 去掉負責人姓名
        self.assertEqual(rows["乙案"][3], "個人")                       # 個人起造人不公開姓名
        self.assertEqual(rows["甲案"][6], "2026-10-08")
        self.assertEqual(rows["甲案"][9:], ["大同段1地號", 2])
        self.assertEqual(rows["乙案"][8], "2026-03-01")
        self.assertEqual(rows["丙案"][6], "2026-07-20")                 # 夾逗號的列：報備日期照樣找得到
        self.assertEqual(rows["丙案"][4], 40)
        self.assertEqual([r[1] for r in d["rows"]], ["甲案", "丙案", "乙案"])    # 報備日期新的在前

    def test_build_and_cache_fallback(self):
        tmp = tempfile.mkdtemp()
        old = (build_buildcase.WEB_TW, plvr_tw.CACHE, plvr.fetch)
        build_buildcase.WEB_TW, plvr_tw.CACHE = os.path.join(tmp, "web"), os.path.join(tmp, "cache")
        try:
            plvr.fetch = lambda url, **kw: make_zip()
            build_buildcase.main()
            path = os.path.join(build_buildcase.WEB_TW, "D", "buildcase.json")
            with open(path, encoding="utf-8") as f:
                out = json.load(f)
            self.assertEqual(out["latest"], "2026-10-08")
            self.assertEqual(len(out["rows"]), 3)
            os.remove(path)

            def down(url, **kw):
                raise plvr.DownloadError("忙線")
            plvr.fetch = down                                            # 這次抓不到：用上次的 zip
            build_buildcase.main()
            self.assertTrue(os.path.exists(path))
        finally:
            build_buildcase.WEB_TW, plvr_tw.CACHE, plvr.fetch = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
