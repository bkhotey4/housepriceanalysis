"""介面煙霧測試：實際建立視窗，把每個分頁、每個行政區、每筆情資都點過一遍。

需要有螢幕（Windows / Pydroid 3 直接執行即可；Linux 無螢幕時會自動略過）。
"""
import gc
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

try:
    import tkinter as tk
except ImportError:      # 這個 Python 沒有附 tkinter
    tk = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))


class UiSmokeTest(unittest.TestCase):
    """測試一律用內建快照與空白設定，不讀也不寫使用者電腦上的快取、設定與看屋清單，也不連網。"""

    @classmethod
    def setUpClass(cls):
        if tk is None:
            raise unittest.SkipTest("這個 Python 沒有 tkinter")
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:
            raise unittest.SkipTest("沒有可用的螢幕：%s" % e)
        import app as appmod
        from core import basemap, plvr, prices, roads
        from ui import kit
        cls.kit = kit
        cls.prices = prices
        cls.plvr = plvr
        cls.tmp_dir = tempfile.mkdtemp()
        cls._saved = (kit.save_settings, kit.load_settings, kit.open_url, basemap.load, basemap.TILE_DIR,
                      basemap.CACHE_DIR, plvr.fetch, prices.BOOK_CACHE_PATH)
        cls._saved_roads = (roads.ROAD_DIR, roads.download)
        from core import view3d
        cls._saved_animate = view3d.View3D.animate
        view3d.View3D.animate = False                       # 過場動畫關掉，點了之後的結果才是立即的（動畫另外有一項測試）
        roads.ROAD_DIR = os.path.join(cls.tmp_dir, "roads")             # 不讀使用者電腦上的道路快取

        def no_roads(district, insecure=False, progress=None):
            raise plvr.DownloadError("測試不連網")
        roads.download = no_roads
        font = os.environ.get("DTH_TEST_FONT")
        kit.load_settings = lambda: ({"font_size": int(font)} if font else {})
        kit.save_settings = lambda d: None                  # 不改動使用者設定
        cls.opened = []
        kit.open_url = lambda url: cls.opened.append(url)   # 不真的開瀏覽器
        basemap.load = lambda z=None, layer="photo": None   # 當作還沒下載過任何圖資
        basemap.TILE_DIR = os.path.join(cls.tmp_dir, "tiles")
        basemap.CACHE_DIR = os.path.join(cls.tmp_dir, "basemap")
        prices.BOOK_CACHE_PATH = os.path.join(cls.tmp_dir, "pricebook.json")   # 不存在 -> 用內建快照

        def no_network(url, timeout=30, insecure=False):
            raise plvr.DownloadError("測試不連網")
        plvr.fetch = no_network
        cls.watch_path = os.path.join(cls.tmp_dir, "watchlist.json")
        cls.app = appmod.App(cls.root, auto_download=False, watch_path=cls.watch_path, county="D")
        cls.root.geometry("1280x800+0+0")
        cls.pump(10)

    @classmethod
    def tearDownClass(cls):
        from core import basemap, plvr, prices, roads
        (cls.kit.save_settings, cls.kit.load_settings, cls.kit.open_url, basemap.load, basemap.TILE_DIR,
         basemap.CACHE_DIR, plvr.fetch, prices.BOOK_CACHE_PATH) = cls._saved
        roads.ROAD_DIR, roads.download = cls._saved_roads
        from core import view3d
        view3d.View3D.animate = cls._saved_animate
        loader = cls.app.map_tab.view.raster.loader
        for _ in range(40):                      # 等背景的圖磚執行緒收工，再刪暫存資料夾
            if not (loader and loader.busy):
                break
            time.sleep(0.05)
        cls.root.destroy()
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def tearDown(self):
        gc.collect()        # 讓關掉的對話框在主執行緒回收，避免背景執行緒回收 Tk 變數時印出雜訊

    def dialogs(self, klass):
        out = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, klass):
                    out.append(c)
                walk(c)
        walk(self.root)
        return out

    def click(self, x, y, button=1):
        v = self.app.map_tab.view
        v.event_generate("<ButtonPress-%d>" % button, x=x, y=y)
        v.event_generate("<ButtonRelease-%d>" % button, x=x, y=y)
        self.pump()

    @classmethod
    def pump(cls, n=3, dt=0.03):
        for _ in range(n):
            cls.root.update_idletasks()
            cls.root.update()
            time.sleep(dt)

    def test_01_map_has_all_layers(self):
        v = self.app.map_tab.view
        self.assertEqual(self.app.book.source, "snapshot")
        self.assertEqual(self.app.map_tab.base.get(), "terrain")     # 沒有圖資快取時以立體地形開場
        v.redraw()
        self.assertEqual(len(v.bars), 37)
        self.assertGreaterEqual(len(v.lines), 5)
        projects = [lm for lm in v.landmarks if lm.get("hit") == "project"]
        self.assertGreater(len(v.markers) + len(projects), 20)              # 有時程的建設畫成 3D 圖案，其餘是菱形
        self.assertGreater(len(projects), 15)
        self.assertGreater(len(v.find_all()), 500)
        kinds = set(h[0] for h in v._hit)
        self.assertIn("district", kinds)
        self.assertIn("marker", kinds)
        self.assertIn("project", kinds)

    def test_02_every_district_and_mode(self):
        m = self.app.map_tab
        for cat in ("all", "house", "apt", "presale"):
            for metric in ("u", "t"):
                for mode in ("price", "trend"):
                    m.cat.set(cat)
                    m.metric.set(metric)
                    m.color_mode.set(mode)
                    m.refresh_all()
        for d in self.app.districts:
            m.select_district(d["name"], focus=True)
        self.pump()
        self.assertEqual(m.lbl_name.cget("text"), self.app.districts[-1]["name"])
        m.cat.set("all"); m.metric.set("u"); m.color_mode.set("price")
        m.select_district("台南市")
        m.refresh_all()
        self.assertEqual(m.kpi["u"][0].cget("text"), "25.6")
        self.assertEqual(m.kpi["n"][0].cget("text"), "4,184")

    def test_03_click_bar_selects_district(self):
        """點房價柱：選到那一區，而且地圖會把那一區拉到畫面中央、拉近到看得出區內道路的大小。"""
        from ui import map_tab
        m = self.app.map_tab
        v = m.view
        v.reset_view()
        self.pump(12, 0.05)                          # 等完整畫面（含標籤）畫完
        hit = next(h for h in v._hit if h[0] == "district" and h[1] == "白河區")
        x, y = int((hit[2] + hit[4]) / 2), int((hit[3] + hit[5]) / 2)
        self.assertEqual(v.pick(x, y)[0], "district")
        self.assertLess(v.zoom, map_tab.DISTRICT_ZOOM)
        v.event_generate("<ButtonPress-1>", x=x, y=y)
        v.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.pump(6, 0.04)
        self.assertEqual(m.current, "白河區")
        self.assertEqual(m.lbl_name.cget("text"), m.current)
        d = self.app.dmap["白河區"]
        lat, lng = v.screen_to_latlng(*self.view_center(v))
        self.assertAlmostEqual(lat, d["lat"], places=3)
        self.assertAlmostEqual(lng, d["lng"], places=3)
        self.assertAlmostEqual(v.zoom, map_tab.DISTRICT_ZOOM, places=3)
        # 已經拉得比較近時，換一區只移動、不會把畫面縮回去
        v.zoom_by(3.0); self.pump(3)
        z = v.zoom
        m.select_district("東區"); self.pump(3)
        self.assertAlmostEqual(v.zoom, z, places=3)
        lat, lng = v.screen_to_latlng(*self.view_center(v))
        self.assertAlmostEqual(lat, self.app.dmap["東區"]["lat"], places=3)
        # 全市總覽：滑回整個臺南市
        m.select_district(self.prices.CITY); self.pump(6, 0.04)
        self.assertAlmostEqual(v.tx, v.DEFAULT["tx"], places=3)
        self.assertLess(v.zoom, map_tab.DISTRICT_ZOOM)
        self.assertTrue(v._auto_zoom)                # 之後改變視窗大小，仍會自動配合

    @staticmethod
    def view_center(v):
        """地圖的「畫面中央」：扣掉左邊圖例之後的中心點。"""
        return (v.winfo_width() + v._legend_inset()) / 2.0, v.winfo_height() * 0.54

    def drag(self, v, button, path):
        (x0, y0), rest = path[0], path[1:]
        v.event_generate("<ButtonPress-%d>" % button, x=x0, y=y0)
        for x, y in rest:
            v.event_generate("<B%d-Motion>" % button, x=x, y=y)
        v.event_generate("<ButtonRelease-%d>" % button, x=rest[-1][0], y=rest[-1][1])
        self.pump(4, 0.03)

    def test_04_drag_pans_and_rotates(self):
        """左鍵拖曳是平移（地面跟著游標走）、右鍵拖曳是旋轉；「拖曳」按鈕可以把兩者對調。"""
        m = self.app.map_tab
        v = m.view
        v.reset_view(); self.pump(6, 0.04)
        self.assertEqual(m.btn_mode.cget("text"), "拖曳：平移")
        az0, pitch0, tx0, ty0 = v.az, v.pitch, v.tx, v.ty
        path = [(500 + 12 * k, 400 + 6 * k) for k in range(8)]
        under = v.screen_to_latlng(*path[0])
        self.drag(v, 1, path)
        self.assertEqual((v.az, v.pitch), (az0, pitch0))
        self.assertNotAlmostEqual(v.tx, tx0, places=2)
        after = v.screen_to_latlng(*path[-1])           # 原本在游標下的地面，拖完還在游標下
        self.assertAlmostEqual(after[0], under[0], places=4)
        self.assertAlmostEqual(after[1], under[1], places=4)
        tx1, ty1 = v.tx, v.ty
        self.drag(v, 3, path)                           # 右鍵：旋轉，中心不動
        self.assertNotAlmostEqual(v.az, az0, places=1)
        self.assertNotAlmostEqual(v.pitch, pitch0, places=1)
        self.assertEqual((v.tx, v.ty), (tx1, ty1))
        m._toggle_mode()                                # 對調：左鍵旋轉、右鍵平移
        self.assertEqual(m.btn_mode.cget("text"), "拖曳：旋轉")
        az1 = v.az
        self.drag(v, 1, path)
        self.assertNotAlmostEqual(v.az, az1, places=1)
        self.assertEqual((v.tx, v.ty), (tx1, ty1))
        self.drag(v, 3, path)
        self.assertNotAlmostEqual(v.tx, tx1, places=2)
        m._toggle_mode()
        self.assertEqual(v.drag_mode, "pan")
        z0 = v.zoom
        v.zoom_by(1.3)
        self.assertGreater(v.zoom, z0)
        v.top_view(); self.pump(); v.reset_view(); self.pump()

    def test_04b_wheel_zooms_toward_cursor(self):
        """滾輪：對著游標的位置縮放（游標底下的地面不動），所以把游標移到想看的地方再滾就能過去。"""
        v = self.app.map_tab.view
        v.reset_view(); self.pump(6, 0.04)
        for at in ((300, 200), (900, 600), (640, 380)):
            before = v.screen_to_latlng(*at)
            z0, c0 = v.zoom, (v.tx, v.ty)
            v.zoom_by(1.2 ** 3, at=at)
            self.assertAlmostEqual(v.zoom, z0 * 1.2 ** 3, places=6)
            after = v.screen_to_latlng(*at)
            self.assertAlmostEqual(after[0], before[0], places=5)
            self.assertAlmostEqual(after[1], before[1], places=5)
            self.assertNotEqual((v.tx, v.ty), c0)
        z = v.zoom
        v.zoom_by(1 / 1.2, at=(300, 200))
        self.assertLess(v.zoom, z)
        # 傾斜、旋轉過的視角也一樣
        v.rotate_by(d_az=70, d_pitch=-15)
        before = v.screen_to_latlng(820, 300)
        v.zoom_by(2.0, at=(820, 300))
        after = v.screen_to_latlng(820, 300)
        self.assertAlmostEqual(after[0], before[0], places=5)
        self.assertAlmostEqual(after[1], before[1], places=5)
        # 不給位置（按鈕的放大縮小）：對著畫面中央
        c = (v.tx, v.ty)
        v.zoom_by(1.3)
        self.assertEqual((v.tx, v.ty), c)
        v.reset_view(); self.pump(4)

    def test_04c_animation(self):
        """過場動畫：點了之後畫面是滑過去的（中途經過中間位置），最後準確停在目標；使用者一動手就停。"""
        v = self.app.map_tab.view
        self.app.nb.select(self.app.map_tab)
        v.reset_view(); self.pump(6, 0.04)
        type(v).animate = True
        seen = []
        real_redraw = v.redraw

        def spy(fast=False):
            seen.append((v.tx, v.zoom, fast))
            real_redraw(fast=fast)
        v.redraw = spy
        try:
            z0 = v.zoom
            v.fly_to(22.9972, 120.2027, zoom=60.0, ms=900)         # 動畫照時間走：慢的裝置格數少，但一樣準時到
            self.assertIsNotNone(v._fly)
            t_end = time.time() + 8.0
            while v._fly and time.time() < t_end:
                self.pump(1, 0.01)
            self.assertIsNone(v._fly)
            frames = [(x, z) for x, z, _f in seen]
            self.assertGreater(len(set(frames)), 2)                # 真的有中間畫面
            self.assertTrue(all(z0 - 1e-6 <= z <= 60.0 + 1e-6 for _x, z in frames))
            self.assertTrue(all(f for _x, _z, f in seen[:-1]))     # 途中只畫簡化畫面，停下來才畫完整的
            lat, lng = v.screen_to_latlng(*self.view_center(v))
            self.assertAlmostEqual(lat, 22.9972, places=4)
            self.assertAlmostEqual(lng, 120.2027, places=4)
            self.assertAlmostEqual(v.zoom, 60.0, places=4)
            # 滾輪：分幾格滑到目標倍率，游標底下的地面不動
            before = v.screen_to_latlng(400, 300)
            v.zoom_by(1.2 ** 2, at=(400, 300))
            self.assertLess(v.zoom, 60.0 * 1.2 ** 2)               # 還沒到，正在滑
            self.assertGreater(v.zoom, 60.0)
            t_end = time.time() + 8.0
            while v._zoom_target is not None and time.time() < t_end:
                self.pump(1, 0.01)
            self.assertAlmostEqual(v.zoom, 60.0 * 1.2 ** 2, places=4)
            after = v.screen_to_latlng(400, 300)
            self.assertAlmostEqual(after[0], before[0], places=5)
            self.assertAlmostEqual(after[1], before[1], places=5)
            # 連滾兩格：目標累加，不會因為動畫還沒跑完就少算一格
            v.zoom_by(1.2, at=(400, 300)); v.zoom_by(1.2, at=(400, 300))
            self.assertAlmostEqual(v._zoom_target, 60.0 * 1.2 ** 4, places=4)
            # 動畫途中按下滑鼠：立刻停在當下的位置，不會跟使用者搶
            v.event_generate("<ButtonPress-1>", x=500, y=400)
            self.assertIsNone(v._zoom_target)
            v.event_generate("<ButtonRelease-1>", x=900, y=700)
            v.fly_to(23.3, 120.4, zoom=20.0, ms=20000)
            self.assertIsNotNone(v._fly)
            v.event_generate("<ButtonPress-1>", x=500, y=400)
            self.assertIsNone(v._fly)
            v.event_generate("<B1-Motion>", x=520, y=410)
            v.event_generate("<ButtonRelease-1>", x=520, y=410)
            here = (v.tx, v.ty, v.zoom)
            self.pump(6, 0.03)
            self.assertEqual((v.tx, v.ty, v.zoom), here)
        finally:
            del v.redraw
            type(v).animate = False
            self.app.map_tab.select_district(self.prices.CITY)
            v.reset_view(); self.pump(4)

    def test_05_mrt_tab(self):
        a = self.app
        a.nb.select(a.mrt_tab)
        for iid in a.mrt_tab.tree.get_children():
            a.mrt_tab.tree.selection_set(iid)
            self.pump(1, 0.01)
            self.assertGreater(len(a.mrt_tab.text.get("1.0", "end")), 40)
        a.show_mrt("深綠線（南科線）")
        self.pump()
        self.assertIn("深綠線", a.mrt_tab.text.get("1.0", "2.0"))
        a.mrt_tab._to_map()
        self.pump()
        self.assertEqual(a.map_tab.view.selected, ("line", "深綠線（南科線）"))

    def test_06_intel_tab(self):
        a = self.app
        a.nb.select(a.intel_tab)
        self.assertEqual(len(a.intel_tab.tree.get_children()), len(a.intel))
        for it in a.intel:
            a.intel_tab.tree.selection_set(str(it["id"]))
            self.pump(1, 0.0)
            self.assertIn(it["name"], a.intel_tab.text.get("1.0", "end"))
        a.intel_tab.v_dist.set("善化區"); a.intel_tab._fill()
        n_shanhua = len(a.intel_tab.tree.get_children())
        self.assertTrue(0 < n_shanhua < len(a.intel))
        for col in ("name", "type", "dist", "lvl", "conf", "lvl"):
            a.intel_tab._sort_by(col)
        a.intel_tab.v_kw.set("台積電"); a.intel_tab._fill()
        a.intel_tab.v_kw.set(""); a.intel_tab.v_dist.set("全部行政區"); a.intel_tab._fill()
        geo_item = next(it for it in a.intel if it.get("lat") is not None and (it.get("impact_level") or 0) < 3
                        and not it.get("build"))
        a.show_intel(geo_item["id"]); self.pump()
        a.intel_tab._to_map(); self.pump()
        self.assertEqual(a.map_tab.view.selected, ("marker", geo_item["id"]))
        self.assertIn(geo_item["id"], [m["id"] for m in a.map_tab.view.markers])   # 低影響度項目也會被顯示出來
        built = next(it for it in a.intel if it.get("build") and (it.get("impact_level") or 0) < 3)
        a.show_intel(built["id"]); self.pump()
        a.intel_tab._to_map(); self.pump()
        self.assertEqual(a.map_tab.view.selected, ("project", built["id"]))       # 有時程的建設：選到 3D 圖案
        self.assertIn(built["id"], [lm["id"] for lm in a.map_tab.view.landmarks if lm.get("hit") == "project"])

    def test_07_font_quality_about(self):
        a = self.app
        for tab in (a.compare_tab, a.watch_tab, a.map_tab):
            a.nb.select(tab); self.pump()
        size = a.fonts.size
        a.change_font(2); self.pump()
        self.assertEqual(a.fonts.size, size + 2)
        a.change_font(-2); self.pump()
        for name in ("省電", "標準", "細緻"):
            a.v_quality.set(name); a._on_quality(); self.pump()
        a.show_about(); self.pump()
        for w in a.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()

    def test_08_update_flow(self):
        """模擬「更新實價登錄」：執行緒、進度列、完成後重新載入。"""
        from tkinter import messagebox
        from core import plvr
        a, m = self.app, self.app.map_tab
        a.nb.select(m)
        saved = (messagebox.askyesno, messagebox.showinfo, messagebox.showerror, plvr.update, a.reload_prices)
        shown, reloaded = [], []

        def fake_update(progress=None, insecure=False, **kw):
            for k in range(4):
                progress(k, 4, "下載測試檔 %d" % k)
                time.sleep(0.05)
            return a.book, 1234

        messagebox.askyesno = lambda *x, **k: True
        messagebox.showinfo = lambda *x, **k: shown.append(("info", x))
        messagebox.showerror = lambda *x, **k: shown.append(("error", x))
        plvr.update = fake_update
        a.reload_prices = lambda: reloaded.append(True)
        try:
            m.start_update()
            self.assertEqual(str(m.btn_update.cget("state")), "disabled")
            for _ in range(60):
                self.pump(1, 0.05)
                if m._queue is None:
                    break
            self.assertIsNone(m._queue)
            self.assertEqual(str(m.btn_update.cget("state")), "normal")
            self.assertEqual(reloaded, [True])
            self.assertEqual(shown[0][0], "info")

            def failing_update(progress=None, insecure=False, **kw):
                raise plvr.DownloadError("測試用錯誤")
            plvr.update = failing_update
            m.start_update()
            for _ in range(60):
                self.pump(1, 0.05)
                if m._queue is None:
                    break
            self.assertEqual(shown[-1][0], "error")
            self.assertEqual(str(m.btn_update.cget("state")), "normal")
        finally:
            messagebox.askyesno, messagebox.showinfo, messagebox.showerror, plvr.update, a.reload_prices = saved

    def test_09_satellite_basemap(self):
        """衛星底圖：切換、下載成功／失敗／憑證錯誤三種流程（不連網，用假資料）。"""
        from tkinter import messagebox
        from core import basemap, plvr
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m)
        m.base.set("terrain"); m._on_base(); v.set_basemap(None)
        if not basemap.HAVE_PIL:
            shown = []
            saved = messagebox.showinfo
            messagebox.showinfo = lambda *x, **k: shown.append(x)
            try:
                m.base.set("satellite"); m._on_base()
            finally:
                messagebox.showinfo = saved
            self.assertEqual(m.base.get(), "terrain")        # 沒有 Pillow：提示後留在地形
            self.assertTrue(shown)
            return
        from PIL import Image
        fake = basemap.Basemap(Image.new("RGB", (1024, 1024), (40, 90, 60)), 120.0, 120.7, 23.45, 22.85, 12, "影像：測試")
        saved = (basemap.download, messagebox.askyesno, messagebox.showerror, messagebox.showinfo)
        shown = []
        messagebox.showerror = lambda *x, **k: shown.append(("error", x))
        messagebox.showinfo = lambda *x, **k: shown.append(("info", x))
        messagebox.askyesno = lambda *x, **k: shown.append(("ask", x)) or False

        def wait():
            for _ in range(80):
                self.pump(1, 0.03)
                if m._bm_queue is None:
                    break
            self.assertIsNone(m._bm_queue)

        try:
            # 1) 下載失敗 -> 留在地形並顯示錯誤
            def fail(z=13, progress=None, insecure=False, **kw):
                raise plvr.DownloadError("測試：沒有網路")
            basemap.download = fail
            m.base.set("satellite"); m._on_base(); wait()
            self.assertEqual((m.base.get(), v.flat), ("terrain", False))
            self.assertEqual(shown[-1][0], "error")
            # 2) 憑證錯誤 -> 詢問是否略過驗證（這裡答否）
            def cert(z=13, progress=None, insecure=False, **kw):
                raise plvr.CertError("測試")
            basemap.download = cert
            m.base.set("satellite"); m._on_base(); wait()
            self.assertEqual(shown[-1][0], "ask")
            self.assertEqual(m.base.get(), "terrain")
            # 3) 下載成功 -> 自動切到衛星影像，地面變平
            def ok(z=13, progress=None, insecure=False, **kw):
                for k in range(5):
                    progress(k + 1, 5, "下載衛星底圖 %d/5" % (k + 1))
                return fake
            basemap.download = ok
            m.base.set("satellite"); m._on_base(); wait()
            self.pump(6, 0.05)
            self.assertEqual((m.base.get(), v.flat), ("satellite", True))
            self.assertEqual(v.ground_z(23.18, 120.60), 0.0)
            self.assertTrue(v.find_withtag("basemap"))
            self.assertTrue(any(h[0] == "district" for h in v._hit))       # 房價柱仍然畫在影像上
            # 拖曳、縮放在衛星模式下照常運作
            v.rotate_by(d_az=30, d_pitch=-10); v.zoom_by(2.0); self.pump(10, 0.05)
            self.assertTrue(v.find_withtag("basemap"))
            # 4) 切回立體地形
            m.base.set("terrain"); m._on_base(); self.pump(6, 0.05)
            self.assertFalse(v.flat)
            self.assertGreater(v.ground_z(23.18, 120.60), 0.5)
            self.assertFalse(v.find_withtag("basemap"))
            # 5) 再切回衛星：已有影像，不需再下載
            basemap.download = fail
            m.base.set("satellite"); m._on_base(); self.pump(6, 0.05)
            self.assertTrue(v.flat)
        finally:
            basemap.download, messagebox.askyesno, messagebox.showerror, messagebox.showinfo = saved
            m.base.set("terrain"); v.set_base_mode("terrain"); v.set_basemap(None)

    # ------------------------------------------------------------------ 新功能
    def test_10_budget_and_commute_filter(self):
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m)
        m.cat.set("all"); m.metric.set("u"); m.color_mode.set("price")
        m.select_district("台南市"); m.clear_filters()
        self.assertFalse(m.filters_active())
        self.assertEqual(m.lbl_match.cget("text"), "")
        self.assertFalse(any(b["dim"] for b in v.bars))
        self.assertEqual(tuple(m.rank.cget("displaycolumns")), ("d", "u", "t", "n", "tr"))
        # 只設預算
        m.v_budget.set("1000"); m.apply_filters()
        want = [d["name"] for d in a.districts if (a.book.best(d["name"], "all", "t")["value"] or 1e9) <= 1000]
        self.assertTrue(0 < len(want) < 37)
        self.assertEqual(sorted(b["name"] for b in v.bars if not b["dim"]), sorted(want))
        self.assertEqual(m.lbl_match.cget("text"), "符合 %d 區" % len(want))
        self.assertIn("符合 %d 區" % len(want), m.btn_cond.cget("text"))          # 條件列收著也看得到
        self.assertEqual(a.settings["budget"], 1000)
        v._setup_projection()
        heights = {}
        for b in v.bars:
            box = v._bar_polys(b)[2]
            heights.setdefault(bool(b["dim"]), []).append(box[3] - box[1])
        self.assertLess(max(heights[True]), min(heights[False]))                # 不符合的只剩貼地的小方塊
        # 加上通勤圈
        m.v_work.set("南科台南園區"); m.v_km.set("10"); m._on_work()
        w = m.work_place()
        self.assertEqual(w["name"], "南科台南園區")
        both = [n for n in want if m.distance_to_work(n) <= 10]
        self.assertEqual(sorted(both), ["安定區", "新化區", "新市區"])
        self.assertEqual(sorted(b["name"] for b in v.bars if not b["dim"]), sorted(both))
        self.assertEqual([p["id"] for p in v.pins if p["kind"] == "work"], ["work"])
        self.assertEqual([(r["km"], r["lat"]) for r in v.rings], [(10.0, w["lat"])])
        self.assertEqual(tuple(m.rank.cget("displaycolumns")), ("d", "u", "t", "km", "tr"))
        first = m.rank.get_children()[:len(both)]
        self.assertEqual(sorted(first), sorted(both))                       # 符合的排在前面
        self.assertIn("符合條件的有%d區" % len(both), m.lbl_insight.cget("text"))
        v.reset_view(); self.pump(8, 0.04)
        self.assertIn("pin", set(h[0] for h in v._hit))
        # 選一區：重點列出預算與距離；點上班圖釘列出最近的區
        m.select_district("善化區")
        text = m.lbl_insight.cget("text")
        self.assertIn("預算 1,000 萬", text)
        self.assertIn("距南科台南園區約", text)
        m.on_pick("pin", "work")
        self.assertIn("最近的行政區", m.pick_text.get("1.0", "end"))
        # 通勤路線按鈕
        del self.opened[:]
        m._google_route()
        self.assertIn("/maps/dir/?api=1&origin=", self.opened[-1])
        # 不是數字的輸入不會讓程式出錯，也不算條件
        m.v_budget.set("abc"); m.v_km.set("-3"); m.apply_filters()
        self.assertFalse(m.filters_active())
        m.clear_filters(); m.select_district("台南市")
        self.assertEqual((v.rings, [p for p in v.pins if p["kind"] == "work"]), ([], []))
        self.assertFalse(any(b["dim"] for b in v.bars))

    def test_11_mortgage_dialog(self):
        from core import prices
        from ui.dialogs import MortgageDialog
        m = self.app.map_tab
        m.clear_filters(); m.select_district("善化區")
        m.open_mortgage(); self.pump()
        dlg = self.dialogs(MortgageDialog)[-1]
        self.assertEqual(float(dlg.v_price.get()), self.app.book.best("善化區", m.cat.get(), "t")["value"])
        dlg.v_price.set("1000"); dlg.v_ltv.set("80"); dlg.v_rate.set("2.2"); dlg.v_years.set("30")
        monthly = dlg.recalc()
        self.assertEqual(round(monthly), 30376)
        self.assertAlmostEqual(monthly, prices.monthly_payment(800, 2.2, 30))
        self.assertEqual(dlg.out["down"].cget("text"), "200 萬")
        self.assertEqual(dlg.out["loan"].cget("text"), "800 萬")
        self.assertEqual(dlg.out["monthly"].cget("text"), "30,376 元")
        self.assertEqual(dlg.out["interest"].cget("text"), "294 萬")          # 30,376 x 360 - 800 萬
        c = prices.purchase_costs(1000, 20, agent_pct=2)
        self.assertEqual(dlg.out["cash"].cget("text"), "約 %s 萬" % "{:,}".format(int(round(c["total"]))))
        self.assertIn("契稅", dlg.fee_detail.cget("text"))
        dlg.v_agent.set("0"); dlg.recalc()
        self.assertEqual(dlg.out["fees"].cget("text"), "約 %.1f 萬" % prices.purchase_costs(1000, 20, agent_pct=0)["fees"])
        dlg.v_agent.set("2")
        for bad in ("", "abc", "-5"):
            dlg.v_rate.set(bad)
            self.assertIsNone(dlg.recalc())
            self.assertEqual(dlg.out["monthly"].cget("text"), "—")
        dlg.v_rate.set("2.2"); dlg.v_ltv.set("120")
        self.assertIsNone(dlg.recalc())                                        # 成數超過 100% 不計算
        dlg.v_ltv.set("80"); dlg._apply(); self.pump()
        self.assertEqual(m.v_budget.get(), "1000")
        self.assertTrue(m.filters_active())
        self.assertEqual(self.dialogs(MortgageDialog), [])
        m.clear_filters(); m.select_district("台南市")

    def test_12_presale_and_compare(self):
        a, m, c = self.app, self.app.map_tab, self.app.compare_tab
        a.nb.select(m)
        m.cat.set("presale"); m._on_cat(); m.select_district("東區")
        self.assertEqual(m.kpi["u"][0].cget("text"), "58.4")
        self.assertEqual(m.kpi["n"][0].cget("text"), "223")
        self.assertIn("預售屋單價比中古大樓高 124%", m.lbl_insight.cget("text"))
        self.assertEqual(m.road.heading("name")["text"], "建案")
        m.cat.set("all"); m._on_cat()
        # 區域比較
        self.assertEqual(c.chosen(), ["善化區", "新市區", "永康區"])
        m.select_district("安南區"); m._add_compare(); self.pump()
        self.assertEqual(a.nb.select(), str(c))
        self.assertEqual(c.chosen(), ["善化區", "新市區", "安南區"])
        m._add_compare()                                                     # 已在清單就不重複
        self.assertEqual(c.chosen(), ["善化區", "新市區", "安南區"])
        rows = dict(c.rows())
        self.assertEqual(len(rows["【全部合併】中位單價"]), 3)
        b = a.book.best("善化區", "all", "u")
        self.assertTrue(rows["【全部合併】中位單價"][0].startswith("%.1f 萬/坪（%d 件" % (b["value"], b["n"])))
        self.assertEqual(rows["所屬生活圈"][0], a.dmap["善化區"]["zone"])
        self.assertEqual(len(c.chart.series), 3)
        self.assertEqual(len(c.table.get_children()), len(rows))
        from ui.compare_tab import NONE
        c.vars[2].set(NONE); c.refresh(); self.pump()
        self.assertEqual(c.chosen(), ["善化區", "新市區"])
        self.assertEqual(tuple(c.table.cget("displaycolumns")), ("k", "a", "b"))
        c.vars[1].set("善化區"); c.refresh()                                  # 選到同一區只算一次
        self.assertEqual(c.chosen(), ["善化區"])
        for cat in ("house", "apt", "presale", "all"):
            for metric in ("t", "u"):
                c.cat.set(cat); c.metric.set(metric); c.refresh()
        self.pump()
        # 設了上班地點，比較表會多一列距離
        m.v_work.set("南科台南園區"); m.apply_filters()
        self.assertIn("距南科台南園區（直線）", dict(c.rows()))
        m.clear_filters()
        c.vars[1].set("新市區"); c.vars[2].set("永康區"); c.refresh()
        m.select_district("台南市")
        self.assertEqual(str(m.btn_compare.cget("state")), "disabled")

    def test_13_watchlist(self):
        from tkinter import messagebox
        from ui.dialogs import WatchDialog
        a, t, m, v = self.app, self.app.watch_tab, self.app.map_tab, self.app.map_tab.view
        a.nb.select(t); self.pump()
        self.assertEqual(len(t.tree.get_children()), 6)                       # 舊 house_data.py 的示意物件
        self.assertTrue(t.banner.winfo_ismapped())
        self.assertLessEqual(int(t.banner.cget("wraplength")), t.banner.winfo_width())     # 說明文字太長時會換行
        self.assertGreater(int(t.banner.cget("wraplength")), 150)
        self.assertFalse(os.path.exists(self.watch_path))
        for iid in t.tree.get_children():
            t.tree.selection_set(iid); self.pump(1, 0.0)
            self.assertIn("與實價登錄行情比較", t.text.get("1.0", "end"))
        saved = (messagebox.askyesno, messagebox.showwarning)
        warned = []
        messagebox.showwarning = lambda *x, **k: warned.append(x)
        try:
            # 新增：格式錯誤時提示、不存檔
            t.add(); self.pump()
            dlg = self.dialogs(WatchDialog)[-1]
            dlg.vars["name"].set("測試大樓"); dlg.vars["district"].set("永康區"); dlg.vars["type"].set("大樓／華廈")
            dlg.vars["address"].set("永康區中華路100號"); dlg.vars["price"].set("一千"); dlg.vars["ping"].set("30")
            dlg._save()
            self.assertEqual(len(warned), 1)
            self.assertEqual(len(a.watch.items), 6)
            dlg.vars["price"].set("1,200"); dlg.note.insert("1.0", "三房，近市場")
            dlg._save(); self.pump()
            self.assertEqual(len(a.watch.items), 7)
            it = a.watch.items[-1]
            self.assertEqual((it["name"], it["district"], it["price"], it["ping"], it["note"]),
                             ("測試大樓", "永康區", 1200, 30, "三房，近市場"))
            self.assertTrue(os.path.exists(self.watch_path))
            self.assertEqual(t.tree.selection(), (it["id"],))
            # 與行情比較：1200 萬對永康區大樓中位總價
            bt = a.book.best("永康區", "apt", "t")
            c = t.compare(it)
            self.assertAlmostEqual(c["unit"], 40.0)
            self.assertAlmostEqual(c["vs_total"], (1200 - bt["value"]) / bt["value"] * 100)
            self.assertIn(t._pct(c["vs_total"]), t.tree.item(it["id"], "values")[-1])
            # 編輯
            t.edit(); self.pump()
            dlg = self.dialogs(WatchDialog)[-1]
            self.assertEqual(dlg.vars["price"].get(), "1200")
            dlg.vars["price"].set("1100"); dlg._save(); self.pump()
            self.assertEqual(a.watch.get(it["id"])["price"], 1100)
            # 在地圖上標位置：切到地圖、點一下，圖釘出現
            self.assertEqual(str(t.btn_map.cget("state")), "disabled")
            t.pin(); self.pump(8, 0.04)
            self.assertEqual(a.nb.select(), str(m))
            self.assertIsNotNone(v.pick_location)
            self.click(v.winfo_width() // 2 + 30, v.winfo_height() // 2)
            self.assertIsNone(v.pick_location)
            it = a.watch.get(it["id"])
            d = a.dmap["永康區"]
            self.assertLess(abs(it["lat"] - d["lat"]) + abs(it["lng"] - d["lng"]), 0.08)   # 點在永康區附近
            self.assertIn(it["id"], [p["id"] for p in v.pins])
            self.assertEqual(v.selected, ("pin", it["id"]))
            # 點圖釘 -> 跳到看屋清單並選取該物件
            m.on_pick("pin", it["id"]); self.pump()
            self.assertEqual(a.nb.select(), str(t))
            self.assertEqual(t.tree.selection(), (it["id"],))
            self.assertEqual(str(t.btn_map.cget("state")), "normal")
            t.to_map(); self.pump()
            self.assertEqual(a.nb.select(), str(m))
            m.show_watch.set(False); m.refresh_pins()
            self.assertEqual(v.pins, [])
            m.show_watch.set(True); m.refresh_pins()
            # 刪除：先答「否」不刪，再答「是」
            a.nb.select(t); self.pump()
            t.tree.selection_set(it["id"]); self.pump()
            messagebox.askyesno = lambda *x, **k: False
            t.delete()
            self.assertEqual(len(a.watch.items), 7)
            messagebox.askyesno = lambda *x, **k: True
            t.delete(); self.pump()
            self.assertEqual(len(a.watch.items), 6)
            self.assertEqual(v.pins, [])
            self.assertEqual(str(t.btn_edit.cget("state")), "disabled")
        finally:
            messagebox.askyesno, messagebox.showwarning = saved
            for d in self.dialogs(WatchDialog):
                d.destroy()
            a.nb.select(m)

    def test_14_pick_work_location_on_map(self):
        from ui.map_tab import NO_WORK, PICK_ON_MAP
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m); v.reset_view(); self.pump(8, 0.04)
        # 螢幕座標 <-> 經緯度互為反函數（任何視角）
        for az, pitch, zoom in ((0, 89, 20), (35, 40, 12), (-120, 25, 60)):
            v.az, v.pitch, v.zoom = az, pitch, zoom
            v._setup_projection()
            for lat, lng in ((23.0, 120.2), (23.35, 120.5), (22.9, 120.1)):
                from core.geo import to_xy
                sx, sy, _ = v.project(*to_xy(lat, lng), 0.0)
                lat2, lng2 = v.screen_to_latlng(sx, sy)
                self.assertAlmostEqual(lat, lat2, places=6)
                self.assertAlmostEqual(lng, lng2, places=6)
        v.reset_view(); self.pump(8, 0.04)
        # 右鍵取消
        m.v_work.set(PICK_ON_MAP); m._on_work(); self.pump()
        self.assertIsNotNone(v.pick_location)
        self.click(400, 300, button=3)
        self.assertIsNone(v.pick_location)
        self.assertEqual(m.v_work.get(), NO_WORK)
        self.assertIsNone(m.custom_work)
        # 點地圖 -> 自訂位置
        m.v_work.set(PICK_ON_MAP); m._on_work(); self.pump()
        want = v.screen_to_latlng(400, 300)
        self.click(400, 300)
        self.assertEqual(m.v_work.get(), "自訂位置")
        self.assertAlmostEqual(m.custom_work[0], want[0], places=4)
        self.assertAlmostEqual(m.custom_work[1], want[1], places=4)
        self.assertIn("自訂位置", m.cb_work.cget("values"))
        self.assertEqual(m.work_place()["lat"], m.custom_work[0])
        self.assertIsNotNone(m.distance_to_work("東區"))
        # 拖曳不算點擊：選點模式中拖曳仍然只是轉動地圖
        m.v_work.set(PICK_ON_MAP); m._on_work(); self.pump()
        v.event_generate("<ButtonPress-1>", x=500, y=400)
        for k in range(1, 6):
            v.event_generate("<B1-Motion>", x=500 + 15 * k, y=400)
        v.event_generate("<ButtonRelease-1>", x=575, y=400)
        self.pump()
        self.assertIsNotNone(v.pick_location)
        self.click(400, 300, button=3)
        m.custom_work = None
        m.cb_work.config(values=m._work_values())
        m.clear_filters(); v.reset_view(); self.pump(6, 0.04)

    def test_15_road_tab_with_transactions(self):
        """有逐筆成交資料時：路段行情 -> 點路段 -> 成交明細只列該路段。"""
        from core import prices
        a, m = self.app, self.app.map_tab
        here = os.path.dirname(os.path.abspath(__file__))
        txs = []
        for name in ("fixture_d_lvr_land_a.csv", "fixture_d_lvr_land_b.csv"):
            with open(os.path.join(here, name), encoding="utf-8-sig") as f:
                txs += prices.parse_csv_text(f.read())
        a.nb.select(m)
        m.select_district("仁德區")
        self.assertIn("更新實價登錄", m.lbl_road.cget("text"))                 # 還沒有逐筆資料時的說明
        a.txs = txs
        try:
            m.cat.set("house"); m._on_cat(); m.select_district("仁德區"); self.pump()
            rows = [m.road.item(i, "values") for i in m.road.get_children()]
            # 欄位：行政區、路段（* 表示不到 3 件）、件數、萬/坪、總價、最近成交年/月
            self.assertEqual([tuple(map(str, r)) for r in rows], [("仁德區", "中正西路*", "2", "19.8", "2,025", "26/05")])
            self.assertEqual(tuple(m.road.cget("displaycolumns")), ("name", "n", "u", "t", "last"))
            n_all = len(m.tx.get_children())
            m.road.selection_set("0"); self.pump()
            self.assertEqual(m._road_filter, "中正西路")
            self.assertEqual(m.sub.select(), str(m._tx_tab))
            self.assertEqual(len(m.tx.get_children()), 2)
            self.assertTrue(m.btn_tx_all.winfo_manager())
            m._clear_road_filter(); self.pump()
            self.assertEqual(len(m.tx.get_children()), n_all)
            self.assertFalse(m.btn_tx_all.winfo_manager())
            m.cat.set("presale"); m._on_cat(); m.select_district("永康區"); self.pump()
            self.assertEqual(m.road.heading("name")["text"], "建案")
            self.assertEqual(len(m.tx.get_children()), 1)
            self.assertIn("勝美AI", m.tx.item(m.tx.get_children()[0], "values")[2])
            m.select_district("台南市")
            self.assertIn("先選一個行政區", m.lbl_road.cget("text"))
        finally:
            a.txs = []
            m.cat.set("all"); m._on_cat(); m.select_district("台南市")

    def test_16_overlays_and_hires(self):
        """疊圖與高解析影像：下載、開關、圖例、放大後補上高解析圖磚（全部用假資料，不連網）。"""
        from tkinter import messagebox
        from core import basemap, plvr
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m)
        shown = []
        saved = (basemap.download, messagebox.showinfo, messagebox.showerror, plvr.fetch)
        messagebox.showinfo = lambda *x, **k: shown.append(("info", x))
        messagebox.showerror = lambda *x, **k: shown.append(("error", x))
        try:
            m.base.set("terrain"); m._on_base(); v.set_basemap(None)
            m.ov_vars["liq"].set(True); m._toggle_overlay("liq")
            self.assertFalse(m.ov_vars["liq"].get())                           # 沒有 Pillow 或沒有衛星底圖：提示後不開
            self.assertEqual(shown[-1][0], "info")
            if not basemap.HAVE_PIL:
                return
            import io
            from PIL import Image
            v.set_basemap(basemap.Basemap(Image.new("RGB", (1024, 1024), (40, 90, 60)), 120.0, 120.7, 23.45, 22.85, 12, "影像：測試"))
            asked = []

            def fake_download(z=13, progress=None, insecure=False, layer="photo", **kw):
                asked.append((layer, z))
                if layer == "fault":
                    raise plvr.DownloadError("測試：伺服器沒有回應")
                img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
                img.paste((255, 40, 80, 150), (300, 300, 700, 700))
                return basemap.Basemap(img, 120.0, 120.7, 23.45, 22.85, z, basemap.LAYERS[layer]["attribution"])
            basemap.download = fake_download

            def wait():
                for _ in range(80):
                    self.pump(1, 0.03)
                    if m._bm_queue is None:
                        break
                self.assertIsNone(m._bm_queue)

            m.ov_vars["liq"].set(True); m._toggle_overlay("liq"); wait(); self.pump(6, 0.04)
            self.assertEqual(asked, [("liq", 12)])                             # 疊圖用和底圖相同的層級
            self.assertEqual((m.base.get(), v.flat), ("satellite", True))      # 開疊圖會自動切到衛星影像
            self.assertTrue(m.ov_vars["liq"].get())
            self.assertEqual(v.raster.active_overlays(), ["liq"])
            self.assertEqual(a.settings["overlays"], ["liq"])
            self.assertIn("土壤液化", v.raster.attribution())
            # 疊圖真的畫進影像：疊圖中心的顏色偏紅，關掉後恢復底圖的綠
            v.top_view(); self.pump(8, 0.05)
            P = (v.zoom, v._ca, v._sa, v._sp, v.tx, v.ty, v._w2, v._h2)
            from core.geo import to_xy
            sx, sy, _ = v.project(*to_xy(23.15, 120.35), 0.0)
            size = (v.winfo_width(), v.winfo_height())
            on = v.raster.render(size, P, (238, 241, 244), view_box=v.view_box()).getpixel((int(sx), int(sy)))
            m.ov_vars["liq"].set(False); m._toggle_overlay("liq")
            off = v.raster.render(size, P, (238, 241, 244), view_box=v.view_box()).getpixel((int(sx), int(sy)))
            self.assertEqual(off, (40, 90, 60))
            # 液化圖層預設調淡（濃淡 0.55）：紅色 = 40 + (255-40) x 150/255 x 0.55
            self.assertAlmostEqual(m.liq_opacity.get(), 0.55)
            self.assertAlmostEqual(on[0], 40 + 215 * 150 / 255.0 * 0.55, delta=4)
            m.ov_vars["liq"].set(True); m._toggle_overlay("liq")
            m.liq_opacity.set(1.0); m._on_opacity()
            for _ in range(20):
                self.pump(1, 0.03)
                if m._opacity_job is None:
                    break
            strong = v.raster.render(size, P, (238, 241, 244), view_box=v.view_box()).getpixel((int(sx), int(sy)))
            self.assertAlmostEqual(strong[0], 40 + 215 * 150 / 255.0, delta=4)      # 調到最濃 = 圖層原本的透明度
            self.assertEqual(a.settings["liq_opacity"], 1.0)
            m.liq_opacity.set(0.55); m._apply_opacity()
            m.ov_vars["liq"].set(False); m._toggle_overlay("liq")
            self.assertEqual((v.raster.active_overlays(), a.settings["overlays"]), ([], []))
            # 第二次開：已經有了，不再下載
            m.ov_vars["liq"].set(True); m._toggle_overlay("liq")
            self.assertEqual(len(asked), 1)
            self.assertEqual(v.raster.active_overlays(), ["liq"])
            # 下載失敗：顯示錯誤、勾選取消。斷層圖是單一張大圖，下載中進度列是來回跑的動畫
            m.ov_vars["fault"].set(True); m._toggle_overlay("fault")
            self.assertEqual(str(m.progress.cget("mode")), "indeterminate")
            wait()
            self.assertEqual(str(m.progress.cget("mode")), "determinate")
            self.assertEqual(shown[-1][0], "error")
            self.assertFalse(m.ov_vars["fault"].get())
            self.assertEqual(v.raster.active_overlays(), ["liq"])
            for lid in ("town", "roads"):
                m.ov_vars[lid].set(True); m._toggle_overlay(lid); wait()
            self.assertEqual(v.raster.active_overlays(), ["liq", "town", "roads"])
            v.reset_view(); self.pump(8, 0.05)
            self.assertTrue(v.find_withtag("basemap"))
            # 高解析：放大後背景抓圖磚，抓到後補丁蓋上去
            calls = []

            def fake_fetch(url, timeout=30, insecure=False):
                calls.append(url)
                buf = io.BytesIO()
                if "PHOTO2" in url:
                    Image.new("RGB", (256, 256), (200, 30, 30)).save(buf, "JPEG", quality=95)
                else:
                    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, "PNG")
                return buf.getvalue()
            plvr.fetch = fake_fetch
            m.hires.set(False); m._on_hires()
            v.focus(23.0, 120.21, zoom=220.0); self.pump(10, 0.05)
            self.assertEqual(calls, [])                                        # 關掉高解析就不抓
            m.hires.set(True); m._on_hires()
            for _ in range(100):
                self.pump(1, 0.05)
                if "photo" in v.raster.patches and not v.raster.loader.busy:
                    break
            self.assertIn("photo", v.raster.patches)
            self.assertTrue(any("/PHOTO2/" in u for u in calls))
            self.assertGreaterEqual(v.raster.patches["photo"][1][0], 14)
            self.pump(6, 0.05)
            cx, cy, _ = v.project(*to_xy(23.0, 120.21), 0.0)
            P = (v.zoom, v._ca, v._sa, v._sp, v.tx, v.ty, v._w2, v._h2)
            for lid in ("liq", "town", "roads"):
                m.ov_vars[lid].set(False); m._toggle_overlay(lid)
            px = v.raster.render((v.winfo_width(), v.winfo_height()), P, (238, 241, 244), view_box=v.view_box()).getpixel((int(cx), int(cy)))
            self.assertTrue(px[0] > 150 and px[1] < 80, px)                    # 畫面中心已換成高解析圖磚的顏色
            # 拖曳、旋轉時照常運作
            v.rotate_by(d_az=40, d_pitch=-20); v.zoom_by(0.5); self.pump(8, 0.05)
            self.assertTrue(v.find_withtag("basemap"))
        finally:
            basemap.download, messagebox.showinfo, messagebox.showerror, plvr.fetch = saved
            for lid in m.ov_vars:
                m.ov_vars[lid].set(False); v.enable_overlay(lid, False); v.set_overlay(lid, None)
            v.raster.patches.clear(); v.raster._last_plan.clear()
            a.settings["overlays"] = []
            m.base.set("terrain"); v.set_base_mode("terrain"); v.set_basemap(None)
            v.reset_view(); self.pump(4)

    def test_17_flood_link_and_google_buttons(self):
        from ui.map_tab import FLOOD_URL
        m = self.app.map_tab
        self.assertTrue(FLOOD_URL.startswith("https://dmap.ncdr.nat.gov.tw/"))
        del self.opened[:]
        m.select_district("善化區")
        m._google("terrain"); m._google("satellite")
        self.assertIn("basemap=terrain", self.opened[0])
        self.assertIn("basemap=satellite", self.opened[1])
        from tkinter import messagebox
        saved, shown = messagebox.showinfo, []
        messagebox.showinfo = lambda *x, **k: shown.append(x)
        try:
            m.clear_filters(); m._google_route()                               # 沒設上班地點：提示而不是出錯
        finally:
            messagebox.showinfo = saved
        self.assertEqual(len(shown), 1)
        self.assertEqual(len(self.opened), 2)
        m.select_district("台南市")

    def test_18_two_workplaces(self):
        from ui.map_tab import NO_WORK, PICK_ON_MAP
        a, m, v, c = self.app, self.app.map_tab, self.app.map_tab.view, self.app.compare_tab
        a.nb.select(m); m.clear_filters(); v.reset_view(); self.pump(6, 0.04)
        A, B = "南科台南園區", "沙崙科學城／高鐵台南站"
        m.v_work.set(A); m.v_km.set("15"); m._on_work(0)
        only_a = sorted(b["name"] for b in v.bars if not b["dim"])
        m.v_work2.set(B); m.v_km2.set("15"); m._on_work(1)
        self.assertEqual([(i, tag, w["name"], km) for i, tag, w, km in m.work_places()], [(0, "A", A, 15.0), (1, "B", B, 15.0)])
        both = sorted(b["name"] for b in v.bars if not b["dim"])
        want = sorted(d["name"] for d in a.districts
                      if m.distance_to_work(d["name"], 0) <= 15 and m.distance_to_work(d["name"], 1) <= 15)
        self.assertEqual(both, want)
        self.assertTrue(0 < len(both) < len(only_a))                            # 兩邊都要在範圍內，比只設一個少
        self.assertEqual([(p["id"], p["label"]) for p in v.pins if p["kind"] == "work"],
                         [("work", "上班A：" + A), ("work2", "上班B：" + B)])
        self.assertEqual(len(v.rings), 2)
        self.assertNotEqual(v.rings[0]["color"], v.rings[1]["color"])
        self.assertEqual(tuple(m.rank.cget("displaycolumns")), ("d", "u", "t", "km", "km2", "tr"))
        self.assertEqual((m.rank.heading("km")["text"], m.rank.heading("km2")["text"]), ("距A", "距B"))
        row = m.rank.set(both[0])
        self.assertEqual(row["km"], "%.1f" % m.distance_to_work(both[0], 0))
        self.assertEqual(row["km2"], "%.1f" % m.distance_to_work(both[0], 1))
        m._sort_by("km2"); self.pump()
        first = m.rank.get_children()[0]
        self.assertEqual(first, min(both, key=lambda n: m.distance_to_work(n, 1)))   # 依到 B 的距離由近到遠
        m._sort_by("u")
        self.assertEqual((a.settings["work"], a.settings["work2"], a.settings["work2_km"]), (A, B, 15.0))
        # 重點、比較表、通勤路線都列出兩個地點
        m.select_district(both[0])
        text = m.lbl_insight.cget("text")
        self.assertIn("距%s約" % A, text); self.assertIn("距%s約" % B, text)
        rows = dict(c.rows())
        self.assertIn("距%s（直線）" % A, rows); self.assertIn("距%s（直線）" % B, rows)
        del self.opened[:]
        m._google_route()
        self.assertEqual(len(self.opened), 2)
        m.on_pick("pin", "work2")
        self.assertIn("上班地點 B：" + B, m.pick_text.get("1.0", "end"))
        # 只留 B：標籤不再寫 A、B，排行只有一欄距離
        m.v_work.set(NO_WORK); m._on_work(0)
        self.assertEqual([(p["id"], p["label"]) for p in v.pins if p["kind"] == "work"], [("work2", "上班：" + B)])
        self.assertEqual(tuple(m.rank.cget("displaycolumns")), ("d", "u", "t", "km2", "tr"))
        self.assertEqual(m.rank.heading("km2")["text"], "距離")
        self.assertEqual(len(v.rings), 1)
        # B 也可以在地圖上點
        m.v_work2.set(PICK_ON_MAP); m._on_work(1); self.pump()
        self.assertIn("上班地點 B", m.lbl_source.cget("text"))
        self.click(420, 320)
        self.assertEqual(m.v_work2.get(), "自訂位置")
        self.assertIsNotNone(m.works[1]["pos"])
        self.assertIsNone(m.works[0]["pos"])
        self.assertEqual(a.settings["work2_pos"], m.works[1]["pos"])
        m.works[1]["pos"] = None
        m.cb_work2.config(values=m._work_values(1))
        m.clear_filters(); m.select_district("台南市")
        self.assertEqual((m.work_places(), v.rings), ([], []))
        self.assertEqual(m.btn_cond.cget("text"), "篩選 " + ("▲" if m._panels["cond"][3] else "▼"))

    def test_19_toolbar_panels_and_legend(self):
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m); self.pump(4)
        # 圖層、條件兩列可以收合，狀態會記住
        for name in ("layers", "cond"):
            outer, btn = m._panels[name][0], m._panels[name][1]
            if m._panels[name][3]:
                m._toggle_panel(name)
            self.pump(3)
            self.assertEqual(outer.winfo_manager(), "")
            self.assertTrue(btn.cget("text").endswith("▼"))
            h0 = v.winfo_height()
            m._toggle_panel(name); self.pump(4)
            self.assertEqual(outer.winfo_manager(), "pack")
            self.assertTrue(btn.cget("text").endswith("▲"))
            self.assertTrue(a.settings["panel_" + name])
            self.assertLess(v.winfo_height(), h0)                               # 展開會佔掉一些地圖高度
            m._toggle_panel(name); self.pump(4)
            self.assertFalse(a.settings["panel_" + name])
            self.assertEqual(v.winfo_height(), h0)
        # 視窗變窄時工具列自動換行，沒有元件被切到外面
        m._toggle_panel("layers"); m._toggle_panel("cond")
        try:
            for width in (1280, 900):
                self.root.geometry("%dx800+0+0" % width); self.pump(8, 0.04)
                for flow in m._flows:
                    for w, _right in flow._items:
                        self.assertLessEqual(w.winfo_x() + w.winfo_reqwidth(), flow.winfo_width() + 1,
                                             "%s 在寬度 %d 被切掉" % (w, width))
            self.assertGreaterEqual(m._flows[0].rows, 2)                        # 900 寬時主列一定要換行
            a.change_font(3); self.pump(10, 0.04)                               # 字放大後也要重新排過
            for flow in m._flows:
                for w, _right in flow._items:
                    self.assertLessEqual(w.winfo_x() + w.winfo_reqwidth(), flow.winfo_width() + 1, "字放大後 %s 被切掉" % w)
                self.assertGreaterEqual(flow.winfo_height(), max(w.winfo_y() + w.winfo_reqheight() for w, _r in flow._items))
            # 表格欄寬跟著字級放大，數字欄不會被截掉
            widths = {t: t.column(t["columns"][1], "width") for t in (a.mrt_tab.tree, a.intel_tab.tree, a.watch_tab.tree, a.compare_tab.table)}
            a.change_font(-3); self.pump(10, 0.04)
            for t, wide in widths.items():
                self.assertLess(t.column(t["columns"][1], "width"), wide)
        finally:
            self.root.geometry("1280x800+0+0"); self.pump(8, 0.04)
            m._toggle_panel("layers"); m._toggle_panel("cond"); self.pump(3)
        # 右側面板：字放得很大時走勢圖收進分頁，清單才有空間；字改回來就恢復
        if not m.compact_panel:
            self.assertTrue(m.chart.winfo_manager())
            self.assertEqual(m.sub.tab(m.chart_tab, "state"), "hidden")
            a.change_font(8); self.pump(10, 0.04)
            self.assertTrue(m.compact_panel)
            self.assertEqual(m.chart.winfo_manager(), "")
            self.assertEqual(m.sub.tab(m.chart_tab, "state"), "normal")
            self.assertEqual(m.sub.select(), str(m.chart_tab))
            self.assertEqual(m.chart_tab.series, m.chart.series)
            a.change_font(-8); self.pump(10, 0.04)
            self.assertFalse(m.compact_panel)
            self.assertEqual(m.sub.tab(m.chart_tab, "state"), "hidden")
        else:
            self.assertEqual(m.sub.tab(m.chart_tab, "state"), "normal")
        # 狀態列在最下方，文字完整
        self.assertEqual(m.lbl_source.cget("text"), a.book.describe_source())
        self.assertGreaterEqual(m.lbl_source.winfo_width(), m.lbl_source.winfo_reqwidth())
        # 圖例：點一下收合成小標籤，場景不再讓位；再點一下展開
        if not v.show["legend"]:
            v.toggle_legend()
        self.pump(4)
        box = v._legend_box
        self.assertTrue(box.winfo_ismapped())
        wide = box.winfo_reqwidth()
        self.assertGreater(v._legend_inset(), 100)
        box.event_generate("<ButtonRelease-1>", x=5, y=5); self.pump(4)
        self.assertFalse(v.show["legend"]); self.assertFalse(m.show_legend.get())
        self.assertFalse(a.settings["legend"])
        self.assertEqual(v._legend_inset(), 0)
        self.assertLess(box.winfo_reqwidth(), wide / 2)
        n_items = len(box.find_all())
        v.rotate_by(d_az=10); self.pump(4)
        self.assertEqual(len(box.find_all()), n_items)                          # 轉動地圖不會重畫圖例
        box.event_generate("<ButtonRelease-1>", x=5, y=5); self.pump(4)
        self.assertTrue(v.show["legend"] and m.show_legend.get() and a.settings["legend"])
        v.reset_view(); self.pump(4)

    def test_21_tables_show_every_column(self):
        """各分頁的表格：左側面板要夠寬，最右邊的欄位不能被切掉。"""
        a = self.app
        for tab, tree in ((a.mrt_tab, a.mrt_tab.tree), (a.intel_tab, a.intel_tab.tree), (a.watch_tab, a.watch_tab.tree)):
            a.nb.select(tab); self.pump(6, 0.04)
            total = sum(tree.column(c, "width") for c in tree["columns"])
            self.assertLessEqual(total, tree.winfo_width() + 2, "%s 的欄位超出表格寬度" % tab.__class__.__name__)
        a.nb.select(a.map_tab); self.pump(3)

    def test_20_labels_do_not_overlap(self):
        """放大到市區時，站名、開發案、行政區標籤統一排版：互不重疊，也不蓋到比例尺與指北針。"""
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m)
        m.marker_min.set("全部"); m.refresh_markers()
        v.focus(22.995, 120.215, zoom=60.0); self.pump(12, 0.05)
        boxes = [(h[0], h[2], h[3], h[4], h[5]) for h in v._hit if h[6] < -1800]       # 文字標籤的方框（深度有特別標記）
        self.assertGreater(len(boxes), 12)
        self.assertIn("station", set(b[0] for b in boxes))
        w, h = v.winfo_width(), v.winfo_height()
        reserved = v._reserved_boxes(w, h)
        clash = 0
        for i, (k1, x0, y0, x1, y1) in enumerate(boxes):
            self.assertTrue(x0 >= -1 and x1 <= w + 1, (k1, x0, x1))             # 不被畫面左右切掉
            for (k2, a0, b0, a1, b1) in boxes[i + 1:]:
                if not (x1 < a0 or x0 > a1 or y1 < b0 or y0 > b1) and "district" not in (k1, k2) and "pin" not in (k1, k2):
                    clash += 1
            for (a0, b0, a1, b1) in reserved:
                if not (x1 < a0 or x0 > a1 or y1 < b0 or y0 > b1) and k1 not in ("district", "pin"):
                    clash += 1
        self.assertEqual(clash, 0)
        m.marker_min.set("影響 3 以上"); m.refresh_markers()
        v.reset_view(); self.pump(6, 0.04)

    def test_22_road_prices_on_map(self):
        """路段房價：選了行政區，地圖上依各路段的中位價上色；可點、可搜尋；道路位置第一次要下載（這裡用假資料）。"""
        from core import plvr, prices, roads
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "fixture_d_lvr_land_a.csv"), encoding="utf-8-sig") as f:
            txs = prices.parse_csv_text(f.read())
        d = a.dmap["仁德區"]
        fake = {"district": "仁德區", "attribution": roads.ATTRIBUTION, "places": {},
                "roads": {"中正西路": [[[d["lat"], d["lng"] - 0.01], [d["lat"] + 0.002, d["lng"]], [d["lat"], d["lng"] + 0.01]]],
                          "中正西路353巷": [[[d["lat"] + 0.002, d["lng"]], [d["lat"] + 0.006, d["lng"]]]]}}
        saved = roads.download
        a.nb.select(m); m.clear_filters()
        m.cat.set("house"); m.metric.set("u"); m._on_cat()
        m.select_district("仁德區"); self.pump(4)
        self.assertEqual(v.roads, [])                                           # 沒有逐筆資料就沒有路段圖層
        a.txs = txs
        try:
            # 1) 道路位置下載失敗：地圖不畫、清單照常，狀態列說明，不會一直重試
            calls = []

            def failing(district, insecure=False, progress=None):
                calls.append(district)
                raise plvr.DownloadError("伺服器忙線")
            roads.download = failing
            m.show_roads.set(True); m._on_show_roads()
            for _ in range(40):
                self.pump(1, 0.03)
                if m._road_queue is None:
                    break
            self.assertEqual(calls, ["仁德區"])
            self.assertIn("道路位置下載失敗", m.lbl_source.cget("text"))
            self.assertEqual(v.roads, [])
            m.show_district("仁德區"); self.pump(4)
            self.assertEqual(calls, ["仁德區"])
            self.assertEqual(len(m.road.get_children()), 1)                     # 右側清單不受影響
            # 2) 重新勾選 -> 再下載一次，成功後畫到地圖上
            roads.download = lambda district, insecure=False, progress=None: (calls.append(district), dict(fake))[1]
            m.show_roads.set(False); m._on_show_roads()
            m.show_roads.set(True); m._on_show_roads()
            for _ in range(40):
                self.pump(1, 0.03)
                if m._road_queue is None:
                    break
            self.assertEqual(calls, ["仁德區", "仁德區"])
            self.assertEqual([(r["id"], r["label"], r["dot"]) for r in v.roads], [("中正西路", "中正西路 19.8*", False)])
            self.assertEqual((len(v.roads[0]["_segs"]), len(v.roads[0]["_lanes"])), (1, 1))
            self.assertIn("OpenStreetMap", v.extra_attribution[0])
            self.assertEqual(v.legend_extra[0], ("title", "路段房價：仁德區（中位單價）"))
            # 3) 放大後路段可以點：成交明細只列這條路
            v.focus(d["lat"], d["lng"], zoom=120.0); self.pump(10, 0.05)
            hits = [h for h in v._hit if h[0] == "road"]
            self.assertGreater(len(hits), 2)
            box = [h for h in hits if h[4] - h[2] < 30][0]
            self.click(int((box[2] + box[4]) / 2), int((box[3] + box[5]) / 2))
            self.assertEqual(m._road_filter, "中正西路")
            self.assertEqual(v.selected, ("road", "中正西路"))
            self.assertEqual(len(m.tx.get_children()), 2)
            self.assertEqual(m.sub.select(), str(m._tx_tab))
            self.assertEqual(m.road.selection(), ("0",))
            v.redraw(); self.pump(3)
            self.assertIn("road", [h[0] for h in v._hit if h[6] < -1800])         # 選到的路段一定有標籤
            m._clear_road_filter(); self.pump(3)
            self.assertEqual(v.selected, ("district", "仁德區"))
            # 4) 柱高切到總價：路段標籤跟著改成總價；關掉圖層就不畫
            m.metric.set("t"); m.refresh_all(); self.pump(3)
            self.assertEqual(v.roads[0]["label"], "中正西路 2,025*")
            m.show_roads.set(False); m._on_show_roads(); self.pump(3)
            self.assertEqual((v.roads, v.extra_attribution, v.legend_extra), ([], [], []))
            self.assertFalse(a.settings["roads"])
            m.show_roads.set(True); m._on_show_roads(); self.pump(3)
            self.assertEqual(len(v.roads), 1)                                   # 已經下載過，不用再抓
            self.assertEqual(len(calls), 2)
            # 5) 在全市總覽用路名搜尋 -> 點結果跳到該區並選到那條路
            m.metric.set("u"); m.select_district("台南市"); self.pump(3)
            self.assertEqual(v.roads, [])
            m.v_road_kw.set("中正"); m._fill_roads(m.current)
            self.assertEqual(tuple(m.road.cget("displaycolumns")), ("dist", "name", "n", "u", "t", "last"))
            self.assertEqual([m.road.item(i, "values")[0] for i in m.road.get_children()], ["仁德區"])
            m.road.selection_set("0"); self.pump(6, 0.04)
            self.assertEqual(m.current, "仁德區")
            self.assertEqual((m._road_filter, v.selected), ("中正西路", ("road", "中正西路")))
            self.assertEqual(m.v_road_kw.get(), "")
            # 預售屋沒有門牌路名（以建案分組），地圖上不畫路段
            m.cat.set("presale"); m._on_cat(); self.pump(3)
            self.assertEqual(v.roads, [])
        finally:
            roads.download = saved
            a.txs = []
            m._road_data.clear()
            m.v_road_kw.set("")
            m.cat.set("all"); m.metric.set("u"); m._on_cat(); m.select_district("台南市")
            v.reset_view(); self.pump(4)
        self.assertEqual(v.roads, [])

    def test_23_landmarks(self):
        """知名地標的立體圖案：畫在地圖上、可以點、可以關掉；縮小時擠在一起的只留比較知名的。"""
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m); v.reset_view(); self.pump(8, 0.04)
        self.assertEqual(len([lm for lm in v.landmarks if lm.get("hit") != "project"]), len(a.landmarks))
        far = set(h[1] for h in v._hit if h[0] == "landmark")
        self.assertGreater(len(far), 8)
        self.assertLess(len(far), len(a.landmarks))                             # 市中心一帶擠在一起，縮小時不會全部畫出來
        ids = {lm["name"]: lm["id"] for lm in a.landmarks}
        self.assertIn(ids["赤崁樓"], far)
        n_items = len(v.find_all())
        # 放大到市中心：原本被省略的地標出現，而且有名稱標籤
        v.focus(22.994, 120.203, zoom=260.0); self.pump(10, 0.05)
        near = set(h[1] for h in v._hit if h[0] == "landmark")
        for name in ("赤崁樓", "臺南孔廟", "林百貨", "臺南車站"):
            self.assertIn(ids[name], near, name)
        self.assertNotIn(ids["臺南市美術館 2 館"], near)                       # 和林百貨只隔一百公尺，仍然擠在一起
        v.select("landmark", ids["臺南市美術館 2 館"]); self.pump(4)            # 被選取的地標一定畫出來
        self.assertIn(ids["臺南市美術館 2 館"], set(h[1] for h in v._hit if h[0] == "landmark"))
        v.select(None, None); self.pump(4)
        self.assertTrue(any(h[0] == "landmark" and h[6] < -1800 for h in v._hit))
        # 點地標 -> 右側顯示說明，並可連到該區房價
        hit = next(h for h in v._hit if h[0] == "landmark" and h[1] == ids["赤崁樓"] and h[6] > -1800)
        x, y = int((hit[2] + hit[4]) / 2), int((hit[3] + hit[5]) / 2)
        self.assertEqual(v.pick(x, y), ("landmark", ids["赤崁樓"]))
        self.click(x, y)
        self.assertEqual(v.selected, ("landmark", ids["赤崁樓"]))
        text = m.pick_text.get("1.0", "end")
        self.assertIn("赤崁樓", text); self.assertIn("普羅民遮城", text); self.assertIn("看中西區的房價", text)
        self.assertEqual(m.sub.select(), str(m._pick_tab))
        # 模型是由多邊形拼成的：每個面都在畫面附近，沒有飛出去的頂點
        lm = next(x for x in v.landmarks if x["id"] == ids["赤崁樓"])
        v._setup_projection()
        faces, bbox, center, size = v._landmark_polys(lm)
        self.assertGreater(len(faces), 8)
        self.assertLess(bbox[2] - bbox[0], size * 1.6)
        self.assertLess(bbox[3] - bbox[1], size * 1.6)
        self.assertTrue(bbox[0] <= center[0] <= bbox[2])
        # 關掉「地標」就不畫
        m.show_landmarks.set(False); m._on_show_landmarks(); self.pump(4)
        self.assertEqual([h for h in v._hit if h[0] == "landmark"], [])
        self.assertFalse(a.settings["landmarks"])
        m.show_landmarks.set(True); m._on_show_landmarks()
        v.select(None, None); v.reset_view(); self.pump(6, 0.04)
        self.assertGreater(n_items, 300)


    def test_24_address_search_and_pins(self):
        """地址搜尋：地圖滑到那一段並插上圖釘，右邊列出同門牌、同巷、整條路的價格；點成交清單的一列也會標出位置。"""
        import copy
        from core import prices, roads
        from ui import map_tab
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "fixture_d_lvr_land_a.csv"), encoding="utf-8-sig") as f:
            txs = prices.parse_csv_text(f.read())
        base = next(x for x in txs if x["dist"] == "仁德區")
        for addr, tw in (("臺南市仁德區中正西路１２０號", 1500), ("臺南市仁德區中正西路３５３巷１０號", 1300)):
            x = copy.deepcopy(base); x["addr"], x["tw"] = addr, tw; x["id"] = x["id"] + addr; txs.append(x)
        other = copy.deepcopy(base)                                         # 安平區也有一條「中正西路」
        other.update({"dist": "安平區", "addr": "臺南市安平區中正西路５號", "id": "other"})
        txs.append(other)
        d = a.dmap["仁德區"]
        lat, lng = d["lat"], d["lng"]
        fake = {"district": "仁德區", "attribution": roads.ATTRIBUTION, "places": {},
                "roads": {"中正西路": [[[lat, lng - 0.02], [lat, lng + 0.02]]],
                          "中正西路100巷": [[[lat, lng - 0.012], [lat + 0.004, lng - 0.012]]],
                          "中正西路353巷": [[[lat, lng + 0.006], [lat + 0.006, lng + 0.006]]]}}
        calls, saved = [], roads.download
        roads.download = lambda district, insecure=False, progress=None: (calls.append(district), dict(fake))[1]
        a.nb.select(m); m.clear_filters(); m.cat.set("all"); m._on_cat()
        m.select_district(prices.CITY); v.reset_view(); self.pump(4)

        def settle():
            for _ in range(60):
                self.pump(1, 0.02)
                if m._road_queue is None:
                    break
            self.pump(3)
        try:
            # 搜尋框放在地圖上方、圖例右邊；平常顯示提示字
            self.assertTrue(m.search_box.winfo_ismapped())
            m.v_search.set(""); m._search_focus_out()                      # 測試期間有人點了搜尋框也一樣
            self.assertEqual(m.v_search.get(), map_tab.SEARCH_HINT)
            self.assertEqual(m.search_address(), "none")                   # 只有提示字：不做事
            self.assertEqual(m.search_address("仁德區中正西路353巷78號"), "none")
            self.assertIn("更新實價登錄", m.lbl_source.cget("text"))        # 沒有逐筆資料要先下載
            a.txs = txs
            # 1) 完整門牌：滑到那一區、下載道路位置、插上圖釘、價格依門牌遠近排
            self.assertEqual(m.search_address("仁德區中正西路353巷78號"), "address")
            settle()
            self.assertEqual(calls, ["仁德區"])
            self.assertEqual(m.current, "仁德區")
            self.assertEqual(m.sub.select(), str(m._tx_tab))
            rows = m.tx.get_children()
            self.assertEqual(len(rows), 4)
            self.assertEqual([m.tx.item(r, "tags")[0] if m.tx.item(r, "tags") else "" for r in rows],
                             ["exact", "exact", "lane", ""])                # 同門牌 2、同巷 1、同路段 1
            text = m.lbl_tx.cget("text")
            self.assertIn("同門牌 2 筆", text)
            self.assertIn("整條路 4 筆", text)
            pin = next(p for p in v.pins if p["id"] == "search")
            self.assertIn("巷內", pin["tip"])                               # 那條巷在 OpenStreetMap 上：沿著巷子推估
            self.assertTrue(any(abs(r["km"] - 0.05) < 1e-9 for r in v.rings))   # 誤差範圍的圈
            c = v.screen_to_latlng(*self.view_center(v))
            self.assertAlmostEqual(c[0], pin["lat"], places=4)
            self.assertAlmostEqual(c[1], pin["lng"], places=4)
            self.assertAlmostEqual(v.zoom, v._zoom_limit(map_tab.PIN_ZOOM["lane"]), places=4)   # 立體地形最多放大到 260
            self.assertIn("已標出", m.lbl_source.cget("text"))
            v.redraw(); self.pump(2)
            self.assertIn("pin", [h[0] for h in v._hit])
            # 2) 點成交清單的一列：圖釘移到那一筆的位置
            row = next(r for r in rows if "１２０號" in m.tx.item(r, "values")[2])
            m.tx.selection_set(row); self.pump(4)
            pin2 = next(p for p in v.pins if p["id"] == "search")
            self.assertIn("1,500萬", pin2["label"])
            self.assertIn("巷口的號碼推估", pin2["tip"])                    # 用 100 巷、353 巷的巷口內插
            self.assertGreater(abs(pin2["lng"] - pin["lng"]), 0.005)
            self.assertEqual(len(m.tx.get_children()), 4)                    # 清單不會被重排
            self.assertEqual(calls, ["仁德區"])                              # 已經下載過，不用再抓
            # 點地圖上的圖釘：移回圖釘、切到成交分頁
            m.sub.select(m._road_tab); m.on_pick("pin", "search"); self.pump(2)
            self.assertEqual(m.sub.select(), str(m._tx_tab))
            # 3) 換房型仍然看同一個地址
            m.cat.set("house"); m._on_cat(); self.pump(3)
            self.assertIn("同門牌 2 筆", m.lbl_tx.cget("text"))
            m.cat.set("all"); m._on_cat(); self.pump(3)
            # 4) 換區：圖釘與門牌排序都拿掉
            m.select_district("東區"); self.pump(3)
            self.assertFalse([p for p in v.pins if p["id"] == "search"])
            self.assertIsNone(m._addr)
            # 5) 沒寫行政區、好幾區都有這條路：列出來讓使用者挑
            self.assertEqual(m.search_address("中正西路"), "choose")
            self.assertEqual(m.current, prices.CITY)
            self.assertEqual(m.sub.select(), str(m._road_tab))
            dists = [m.road.item(i, "values")[0] for i in m.road.get_children()]
            self.assertEqual(sorted(dists), ["仁德區", "安平區"])
            m.road.selection_set(str(dists.index("仁德區"))); self.pump(6, 0.04)
            self.assertEqual(m.current, "仁德區")
            self.assertEqual((m._addr or {}).get("road"), "中正西路")
            self.assertTrue([p for p in v.pins if p["id"] == "search"])
            # 只有一區有：直接過去
            self.assertEqual(m.search_address("中正西路353巷"), "address")
            self.assertEqual(m.current, "仁德區")
            # 6) 行政區、地標、看不懂的字
            self.assertEqual(m.search_address("安平"), "district")
            self.assertEqual(m.current, "安平區")
            lm = a.landmarks[0]
            self.assertEqual(m.search_address(lm["name"]), "landmark")
            self.assertEqual(v.selected, ("landmark", lm["id"]))
            self.assertEqual(m.search_address("？？"), "none")
            # 7) 道路位置下載失敗：價格清單照常，狀態列說明
            m._road_data.clear()

            def failing(district, insecure=False, progress=None):
                raise self.plvr.DownloadError("忙線")
            roads.download = failing
            shutil.rmtree(roads.ROAD_DIR, ignore_errors=True)
            self.assertEqual(m.search_address("仁德區中正西路120號"), "address")
            settle()
            self.assertIn("下載失敗", m.lbl_source.cget("text"))
            self.assertEqual(len(m.tx.get_children()), 4)
            self.assertFalse([p for p in v.pins if p["id"] == "search"])
        finally:
            roads.download = saved
            a.txs = []
            m._road_data.clear()
            m._drop_search()
            m.v_road_kw.set(""); m.v_search.set(""); m._search_focus_out()
            m.cat.set("all"); m._on_cat(); m.select_district(prices.CITY)
            v.reset_view(); self.pump(4)

    def test_25_projects_year_slider(self):
        """重大建設：畫成 3D 圖案（不再重複畫菱形）；年份滑桿改變狀態；點了列出時程；可以關掉。"""
        from core import landmarks
        a, m, v = self.app, self.app.map_tab, self.app.map_tab.view
        a.nb.select(m); m.clear_filters(); m.marker_min.set("全部"); m.refresh_markers()
        m.show_projects.set(True); m._on_show_projects()
        v.reset_view(); self.pump(8, 0.04)
        projs = [lm for lm in v.landmarks if lm.get("hit") == "project"]
        self.assertGreaterEqual(len(projs), 30)
        built = {it["id"] for it in a.intel if it.get("build")}
        self.assertFalse([mk for mk in v.markers if mk["id"] in built])      # 3D 圖案取代菱形
        self.assertTrue(v.markers)                                            # 其他情資照常是菱形
        self.assertIn(("title", "重大建設（%d 年的狀態）" % m.year_min), v._legend_rows())
        # 年份滑桿：拉到最後一年，預計在那之前完工的建設變成「完工」
        it = next(x for x in a.intel if x.get("build") and x["build"].get("done") and
                  m.year_min < x["build"]["done"] <= m.year_max and x["build"]["phase"] != "完工")
        state_now = next(lm for lm in v.landmarks if lm.get("hit") == "project" and lm["id"] == it["id"])["state"]
        self.assertNotEqual(state_now, "完工")
        m.year_scale.set(m.year_max); self.pump(3)
        self.assertEqual(m.build_year.get(), m.year_max)
        self.assertEqual(m.lbl_year.cget("text"), "%d 年" % m.year_max)
        later = next(lm for lm in v.landmarks if lm.get("hit") == "project" and lm["id"] == it["id"])
        self.assertEqual(later["state"], "完工")
        self.assertEqual(later["state"], landmarks.build_state(it["build"], m.year_max))
        # 點 3D 圖案：地圖滑過去、右邊列出時程與所在區房價
        v.redraw(); self.pump(2)
        hits = [h for h in v._hit if h[0] == "project"]
        self.assertTrue(hits)
        m.on_pick("project", it["id"]); self.pump(3)
        self.assertEqual(v.selected, ("project", it["id"]))
        self.assertEqual(m.sub.select(), str(m._pick_tab))
        text = m.pick_text.get("1.0", "end")
        self.assertIn("時程", text)
        self.assertIn("拉到 %d 年：完工" % m.year_max, text)
        c = v.screen_to_latlng(*self.view_center(v))
        self.assertAlmostEqual(c[0], it["lat"], places=4)
        v.redraw(); self.pump(2)
        self.assertIn("project", [h[0] for h in v._hit if h[6] < -1800])     # 選到的建設一定有標籤
        # 從「開發與情資」分頁按「在地圖上看」也會選到 3D 圖案
        a.show_on_map(it["lat"], it["lng"], "marker", it["id"]); self.pump(3)
        self.assertEqual(v.selected, ("project", it["id"]))
        # 關掉「重大建設 3D」：恢復成菱形標記
        m.show_projects.set(False); m._on_show_projects(); self.pump(3)
        self.assertFalse([lm for lm in v.landmarks if lm.get("hit") == "project"])
        self.assertTrue([mk for mk in v.markers if mk["id"] in built])
        self.assertFalse(a.settings["projects"])
        m.show_projects.set(True); m._on_show_projects()
        m.year_scale.set(m.year_min); self.pump(2)
        m.marker_min.set("影響 3 以上"); m.refresh_markers(); m.refresh_landmarks()
        v.select(None, None); v.reset_view(); self.pump(4)

    def test_26_auto_update_and_report(self):
        """自動更新：有新一期就在背景補抓、不跳視窗；失敗當天不再試。行情報告：存成 HTML。"""
        import datetime as dt
        from core import plvr, prices, report
        a, m = self.app, self.app.map_tab
        saved = (plvr.has_live_cache, plvr.needs_update, plvr.update, a.reload_prices, a.auto_download, report.REPORT_DIR)
        reloads = []
        try:
            a.auto_download = True
            a.reload_prices = lambda: reloads.append(1)
            plvr.has_live_cache = lambda: True
            plvr.needs_update = lambda today=None: True
            plvr.update = lambda progress=None, insecure=False: (progress(1, 2, "下載本期檔 …"), (a.book, 123))[1]
            today = dt.date.today()          # 失敗時程式記的是「今天」，測試也要用今天（寫死日期隔天就會失敗）
            self.assertTrue(m.check_auto_update(today))
            for _ in range(40):
                self.pump(1, 0.03)
                if m._queue is None:
                    break
            self.assertEqual(reloads, [1])
            self.assertIn("已自動更新實價登錄", m.lbl_source.cget("text"))
            self.assertEqual(str(m.btn_update.cget("state")), "normal")
            # 已經是最新：不下載
            plvr.needs_update = lambda today=None: False
            self.assertFalse(m.check_auto_update(today))
            # 下載失敗：狀態列說明、不跳視窗，當天不再試
            plvr.needs_update = lambda today=None: True

            def fail(progress=None, insecure=False):
                raise plvr.DownloadError("連不上")
            plvr.update = fail
            self.assertTrue(m.check_auto_update(today))
            for _ in range(40):
                self.pump(1, 0.03)
                if m._queue is None:
                    break
            self.assertIn("自動更新實價登錄沒有成功", m.lbl_source.cget("text"))
            self.assertEqual(a.settings.get("auto_update_failed"), today.isoformat())
            self.assertFalse(m.check_auto_update(today))
            self.assertTrue(m.check_auto_update(today + dt.timedelta(days=1)) or m._queue is not None)
            for _ in range(40):
                self.pump(1, 0.03)
                if m._queue is None:
                    break
            # 關掉「自動更新」就不檢查；第一次（沒下載過）也不自動下載
            m.auto_update.set(False); m._on_auto_update()
            self.assertFalse(m.check_auto_update(today + dt.timedelta(days=2)))
            m.auto_update.set(True)
            plvr.has_live_cache = lambda: False
            a.settings.pop("auto_update_failed", None)
            self.assertFalse(m.check_auto_update(today))
            # 行情報告：全市總覽沒有對象；選了行政區就產生
            report.REPORT_DIR = os.path.join(self.tmp_dir, "reports")
            m.select_district(prices.CITY); self.pump(2)
            self.assertIsNone(m.make_report(open_it=False))
            self.assertEqual(str(m.btn_report.cget("state")), "disabled")
            m.select_district("善化區"); self.pump(2)
            self.assertEqual(str(m.btn_report.cget("state")), "normal")
            path = m.make_report({"name": "測試房仲"}, open_it=False)
            self.assertTrue(path.startswith(report.REPORT_DIR) and os.path.exists(path))
            html_text = open(path, encoding="utf-8").read()
            self.assertIn("善化區 房價行情報告", html_text)
            self.assertIn("測試房仲", html_text)
            self.assertIn("已產生行情報告", m.lbl_source.cget("text"))
        finally:
            (plvr.has_live_cache, plvr.needs_update, plvr.update, a.reload_prices, a.auto_download,
             report.REPORT_DIR) = saved
            if m._auto_job:
                m.after_cancel(m._auto_job)
                m._auto_job = None
            a.settings.pop("auto_update_failed", None)
            m.select_district(prices.CITY); self.pump(3)

    def test_27_watch_district_filter_and_clear_samples(self):
        """看屋清單：可以依行政區篩選；「到房仲平台找物件」跟著選的區；示意資料可以一鍵清除。"""
        from tkinter import messagebox
        from ui import watch_tab
        a, t = self.app, self.app.watch_tab
        a.nb.select(t); self.pump()
        n_all = len(a.watch.items)
        a.watch.add({"name": "永康測試", "district": "永康區", "type": "大樓／華廈", "price": 1200, "ping": 30})
        t.refresh(); self.pump()
        values = list(t.cb_dist.cget("values"))
        self.assertEqual(values[0], watch_tab.ALL_DIST)
        self.assertIn("永康區（1）", values)
        self.assertIn("安平區", values)                                       # 清單裡沒有的區也能選
        self.assertEqual(len(t.tree.get_children()), n_all + 1)
        t.v_dist.set("永康區（1）"); t.refresh(); self.pump()
        self.assertEqual([t.tree.item(i, "values")[0] for i in t.tree.get_children()], ["永康測試"])
        self.assertIn("永康區 共 1 筆", t.lbl_count.cget("text"))
        self.assertEqual(t.mb_search.cget("text"), "到房仲平台找永康區物件")
        t._fill_search_menu()
        labels = [t.menu_search.entrycget(k, "label") for k in range(t.menu_search.index("end") + 1)
                  if t.menu_search.type(k) == "command"]
        self.assertIn("591 房屋交易：永康區", labels)
        url = watch_tab.platform_search_url("sale.591.com.tw", "永康區")
        self.assertTrue(url.startswith("https://www.google.com/search?q="))
        self.assertIn("%E6%B0%B8%E5%BA%B7%E5%8D%80", url)                    # 「永康區」
        t.v_dist.set("安平區"); t.refresh(); self.pump()
        self.assertEqual(t.tree.get_children(), ())
        t.v_dist.set(watch_tab.ALL_DIST); t.refresh(); self.pump()
        # 清除示意資料：先答「否」不刪，再答「是」；自己新增的留著
        saved = messagebox.askyesno
        try:
            messagebox.askyesno = lambda *x, **k: False
            t.clear_samples()
            self.assertEqual(len(a.watch.items), n_all + 1)
            messagebox.askyesno = lambda *x, **k: True
            t.clear_samples(); self.pump()
        finally:
            messagebox.askyesno = saved
        self.assertEqual([it["name"] for it in a.watch.items], ["永康測試"])
        self.assertFalse(any(it.get("sample") for it in a.watch.items))
        self.assertIn("新增物件", t.banner.cget("text")) if not a.watch.items else self.assertFalse(t.banner_box.winfo_ismapped())
        from core import watchlist
        again = watchlist.Watchlist(self.watch_path).load(legacy=[{"name": "x", "address": "善化"}])
        self.assertEqual([it["name"] for it in again.items], ["永康測試"])     # 存檔後重開也不會再匯入示意資料
        a.watch.remove(a.watch.items[0]["id"]); t.refresh(); self.pump()
        self.assertTrue(t.banner_box.winfo_ismapped())
        self.assertIn("清單是空的", t.banner.cget("text"))

    def test_30_switch_county(self):
        """電腦版選縣市：切到台北市（假的全國快取），行政區、房價柱、情資、地標都換成台北；再切回台南一切照舊。"""
        from core import plvr_tw, region, taiwan
        a = self.app
        saved = (plvr_tw.CACHE, region.COUNTY_CACHE, taiwan.TOWNS_PATH, region.WEB_TW, region.TRANSIT_PATH)
        cache = os.path.join(self.tmp_dir, "plvr_tw")
        os.makedirs(os.path.join(cache, "cur"))
        with open(os.path.join(ROOT, "tests", "fixture_d_lvr_land_a.csv"), encoding="utf-8-sig") as f:
            text = f.read()
        text = text.replace("臺南市", "臺北市")
        for old, new in [("安平區", "大安區"), ("仁德區", "信義區"), ("新營區", "士林區"), ("中西區", "中正區"),
                         ("歸仁區", "內湖區"), ("白河區", "北投區"), ("南區", "萬華區"), ("北區", "中山區")]:
            text = text.replace(old, new)
        with open(os.path.join(cache, "cur", "a_lvr_land_a.csv"), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(cache, "cur", "_done"), "w", encoding="utf-8") as f:
            f.write("2026-10-01")
        towns = {"towns": {"A": [{"name": "大安區", "lat": 25.026, "lng": 121.543}, {"name": "信義區", "lat": 25.033, "lng": 121.567},
                                 {"name": "士林區", "lat": 25.093, "lng": 121.525}, {"name": "北投區", "lat": 25.132, "lng": 121.501}]}}
        tp = os.path.join(self.tmp_dir, "towns.json")
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(towns, f, ensure_ascii=False)
        plvr_tw.CACHE, region.COUNTY_CACHE, taiwan.TOWNS_PATH = cache, os.path.join(self.tmp_dir, "county"), tp
        region.WEB_TW = os.path.join(self.tmp_dir, "web_tw")
        from tools import build_transit
        try:
            from test_taiwan import _transit_fixture
        except ImportError:
            from tests.test_taiwan import _transit_fixture
        region.TRANSIT_PATH = os.path.join(self.tmp_dir, "transit.json")
        with open(region.TRANSIT_PATH, "w", encoding="utf-8") as f:
            json.dump({"lines": build_transit.build(_transit_fixture(), towns["towns"])}, f, ensure_ascii=False)
        try:
            b = a.switch_county("A"); self.pump(10)
            self.assertEqual(b.county, "A")
            self.assertIn("台北市", self.root.title())
            self.assertEqual(b.book.source, "live")
            self.assertIn("大安區", b.dmap)
            self.assertIn("中正區", b.dmap)                                   # 交易裡有、位置清單沒有：約略位置
            self.assertEqual(b.dmap["中正區"]["zone"], "位置約略")
            self.assertTrue(b.book.best("大安區", "apt")["n"] >= 1 or b.book.best("大安區", "house")["n"] >= 1)
            self.assertTrue(all(it.get("county") == "A" for it in b.intel))
            self.assertTrue(b.landmarks and all(lm["county"] == "A" for lm in b.landmarks))
            self.assertIn("淡水信義線", b.map_mrt)                          # 營運中的捷運（OpenStreetMap）
            self.assertNotIn("藍線（第一期）", b.map_mrt)                   # 台南的規劃線不畫在台北
            self.assertIn("淡水信義線", [ln["name"] for ln in b.map_tab.view.lines])
            b.map_tab.on_pick("station", ("淡水信義線", "中山站")); self.pump()
            b.show_mrt("淡水信義線"); self.pump()
            self.assertTrue(b.map_tab.view.bars)                              # 房價柱畫出來了
            from core import geo, prices, roads
            self.assertAlmostEqual(geo.LAT0, 25.03, delta=0.1)
            self.assertEqual(prices.CITY, "台北市")
            self.assertEqual(roads.COUNTY, "臺北市")
            b.map_tab.select_district("大安區"); self.pump()
            self.assertEqual(b.map_tab.current, "大安區")
            b.map_tab.select_district(prices.CITY); self.pump()
            from ui import watch_tab
            self.assertIn("%E5%8F%B0%E5%8C%97", watch_tab.platform_search_url("sale.591.com.tw", "大安區"))   # 「台北」
            # 再切回台南
            c = b.switch_county("D"); self.pump(10)
            type(self).app = c
            self.assertEqual(prices.CITY, "台南市")
            self.assertAlmostEqual(geo.LAT0, 23.145)
            self.assertEqual(roads.ROAD_DIR, os.path.join(self.tmp_dir, "roads"))   # 切回來還原測試設定的道路快取
            self.assertIn("永康區", c.dmap)
            self.assertTrue(c.map_mrt)
        finally:
            plvr_tw.CACHE, region.COUNTY_CACHE, taiwan.TOWNS_PATH, region.WEB_TW, region.TRANSIT_PATH = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
