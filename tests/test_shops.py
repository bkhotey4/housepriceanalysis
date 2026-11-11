"""各區生活機能（稅籍登記）：地址拆出行政區、同門牌只算一家、加盟主登記不算店面、下載失敗用快取。"""
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

from core import plvr, plvr_tw, shops  # noqa: E402
from tools import build_shops  # noqa: E402

TOWNS = {"D": ["東區", "永康區", "南區"], "A": ["大安區"]}
HEAD = "營業地址,統一編號,總機構統一編號,營業人名稱,資本額,設立日期,組織別名稱,使用統一發票,行業代號,名稱,行業代號1,名稱1,行業代號2,名稱2,行業代號3,名稱3\n" \
       "11-NOV-26,,,,,,,,,,,,,,,\n"
ROWS = [
    '"臺南市永康區五王里015鄰中華路１號一樓",1,,"甲早餐",1,1100101,獨資,N,561111,早餐店,,,,,,',
    '"臺南市永康區中華路1號二樓",2,,"乙早餐",1,1100101,獨資,N,561111,早餐店,,,,,,',          # 同門牌：只算一家
    '"臺南市永康區中華路3號",3,,"超商直營",1,1100101,股份有限公司,Y,471112,便利商店,,,,,,',
    '"臺南市永康區忠孝路8巷2號",4,,"加盟主",1,1100101,獨資,N,471114,便利商店,,,,,,',        # 加盟主登記：不算
    '"台南市東區崇學路10號",5,,"麵店",1,1100101,獨資,N,561113,麵店、小吃店,,,,,,',
    '"臺南市東區崇學路12號",6,,"建設公司",1,1100101,股份有限公司,Y,411000,建築,561115,餐廳,,,,',  # 只看主要行業
    '"臺北市大安區信義路三段1號",7,,"咖啡",1,1100101,獨資,Y,563112,咖啡館,,,,,,',
    '"臺南市不存在區某路1號",8,,"對不上",1,1100101,獨資,N,561111,早餐店,,,,,,',
]


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BGMOPEN1.csv", (HEAD + "\n".join(ROWS) + "\n").encode("utf-8"))
    return buf.getvalue()


def idx(key):
    return [k for k, _, _ in shops.CATS].index(key)


class ShopsTest(unittest.TestCase):
    def test_split_address(self):
        self.assertEqual(shops.split_address("臺南市永康區五王里015鄰成功路１７２巷５０號三樓", TOWNS), ("D", "永康區", "成功路172巷50號"))
        self.assertEqual(shops.split_address("台南市東區崇學路1號", TOWNS), ("D", "東區", "崇學路1號"))
        self.assertIsNone(shops.split_address("臺南市不存在區某路1號", TOWNS))

    def test_count(self):
        out, date, miss = shops.parse_zip(make_zip(), TOWNS)
        self.assertEqual(date, "2026-11-11")
        self.assertEqual(miss, 1)
        yk, east = out["D"]["永康區"], out["D"]["東區"]
        self.assertEqual(yk[idx("breakfast")], 1)
        self.assertEqual(yk[idx("conv")], 1)
        self.assertEqual(east[idx("eat")], 1)
        self.assertEqual(east[idx("rest")], 0)
        self.assertEqual(out["A"]["大安區"][idx("cafe")], 1)

    def test_build_and_cache_fallback(self):
        tmp = tempfile.mkdtemp()
        old = (build_shops.WEB_TW, plvr_tw.CACHE, plvr.fetch, build_shops.taiwan.load_towns)
        build_shops.WEB_TW, plvr_tw.CACHE = os.path.join(tmp, "web"), os.path.join(tmp, "cache")
        build_shops.taiwan.load_towns = lambda: {c: [{"name": t} for t in v] for c, v in TOWNS.items()}
        try:
            plvr.fetch = lambda url, **kw: make_zip()
            build_shops.main()
            path = os.path.join(build_shops.WEB_TW, "D", "shops.json")
            with open(path, encoding="utf-8") as f:
                out = json.load(f)
            self.assertEqual(out["as_of"], "2026-11-11")
            self.assertEqual(out["total"][idx("breakfast")], 1)
            with open(os.path.join(build_shops.WEB_TW, "shops.json"), encoding="utf-8") as f:
                self.assertEqual(sorted(json.load(f)["data"]), ["台北市", "台南市"])
            os.remove(path)

            def down(url, **kw):
                raise plvr.DownloadError("忙線")
            plvr.fetch = down                                            # 這次抓不到：用上次的 zip
            build_shops.main()
            self.assertTrue(os.path.exists(path))
        finally:
            build_shops.WEB_TW, plvr_tw.CACHE, plvr.fetch, build_shops.taiwan.load_towns = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
