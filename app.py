"""
deep_tainan_house — 台灣房價分析（全台 22 縣市；臺南有地形與捷運等最詳細的資料）

五個分頁：
  1. 3D 房價地圖：衛星影像／地形 + 各區房價柱 + 近半年走勢 + 預算與通勤篩選 + 風險疊圖
  2. 區域比較：2~3 個行政區並排比較
  3. 捷運與鐵路：各規劃線進度、時程、議會決議
  4. 開發與情資：大型商辦／園區／重劃區、議會、建商動向、市況
  5. 看屋清單：自己的候選物件，與實價登錄行情比較

只用 Python 標準函式庫 + tkinter，Windows 與 Android（Pydroid 3）都能直接執行：
    python app.py
"""
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.join(APP_DIR, "data"))

from core import errlog, geo, landmarks, prices, region, watchlist  # noqa: E402
from ui import kit  # noqa: E402
from ui.map_tab import MapTab  # noqa: E402
from ui.mrt_tab import MrtTab  # noqa: E402
from ui.intel_tab import IntelTab  # noqa: E402
from ui.compare_tab import CompareTab  # noqa: E402
from ui.watch_tab import WatchTab  # noqa: E402
from mrt_data import MRT_LINES, RAIL_PROJECTS, AS_OF as MRT_AS_OF  # noqa: E402
from house_data import SHANHUA_PROPERTIES, SEARCH_URLS, open_search  # noqa: E402

QUALITY = [("細緻", 1), ("標準", 2), ("省電", 3)]


class App:
    def __init__(self, root, auto_download=True, watch_path=None, county=None):
        self.root = root
        self.auto_download = auto_download      # 測試時關閉，避免自動連網
        self._watch_path = watch_path
        self.settings = kit.load_settings()
        self.county = region.activate(county or self.settings.get("county") or region.DEFAULT)
        self.cinfo = region.info()
        root.title("deep_tainan_house — %s房價分析" % self.cinfo["short"])
        root.configure(bg=kit.PAGE)

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if kit.IS_ANDROID:
            self.win_w, self.win_h = sw, sh
            root.geometry("%dx%d+0+0" % (sw, sh))
        else:
            self.win_w, self.win_h = min(1440, sw - 40), min(900, sh - 90)
            root.geometry("%dx%d" % (self.win_w, self.win_h))
            root.minsize(900, 600)
        self.panel_width = min(440, max(330, int(self.win_w * 0.31)))
        self.chart_height = 215 if self.win_h >= 850 else (168 if self.win_h >= 720 else 132)

        default_size = 11 if self.win_h >= 800 else 10
        self.fonts = kit.Fonts(root, int(self.settings.get("font_size", default_size)))
        self.fonts.apply_ttk(root)

        # ---- 資料
        self.terrain = region.terrain()
        self.book, self.txs = region.load_book_and_txs()
        self.districts = region.load_districts(self.txs)
        self.dmap = {d["name"]: d for d in self.districts}
        self.mrt_lines = MRT_LINES
        self.rail_projects = RAIL_PROJECTS
        self.mrt_as_of = MRT_AS_OF
        # 地圖、比較、報告只用目前縣市的軌道資料（捷運資料目前只有臺南；其他縣市的捷運之後補）
        self.map_mrt = dict(self.mrt_lines) if self.county == "D" else {}
        self.map_mrt.update(region.transit_lines())      # 營運中的捷運、輕軌、高鐵（有 data/tw/transit.json 才有）
        self.map_rail = self.rail_projects if self.county == "D" else []
        intel = geo.load_json("intel.json")
        self.intel_as_of = intel.get("as_of", "")
        for i, it in enumerate(intel["items"]):
            it["id"] = i
        # 只顯示目前縣市的情資、上班地點、地標（沒有標縣市的舊資料都是臺南市）
        self.intel = [it for it in intel["items"] if it.get("county", "D") == self.county]
        self.intel_by_id = {it["id"]: it for it in self.intel}
        self.workplaces = [p for p in geo.load_json("workplaces.json")["places"] if p.get("county", "D") == self.county]
        self.landmarks = landmarks.load(county=self.county)
        self.watch = watchlist.Watchlist(watch_path).load(legacy=SHANHUA_PROPERTIES)

        # ---- 頂列
        top = tk.Frame(root, bg=kit.ACCENT, padx=12, pady=6)
        top.pack(fill="x")
        tk.Label(top, text="房價分析", bg=kit.ACCENT, fg="#ffffff", font=self.fonts.h2).pack(side="left")
        names = [n for _, n in region.choices()]
        self.v_county = tk.StringVar(value=self.cinfo["short"])
        cc = ttk.Combobox(top, textvariable=self.v_county, values=names, state="readonly", width=7, font=self.fonts.base)
        cc.pack(side="left", padx=(10, 0))
        cc.bind("<<ComboboxSelected>>", self._on_county)
        self.county_box = cc
        ttk.Button(top, text="資料說明", command=self.show_about).pack(side="right", padx=2)
        ttk.Button(top, text="字 ＋", width=5, command=lambda: self.change_font(1)).pack(side="right", padx=2)
        ttk.Button(top, text="字 －", width=5, command=lambda: self.change_font(-1)).pack(side="right", padx=2)
        self.v_quality = tk.StringVar()
        q = self.settings.get("quality", 2 if kit.IS_ANDROID else 1)
        self.v_quality.set(next((n for n, v in QUALITY if v == q), "細緻"))
        cb = ttk.Combobox(top, textvariable=self.v_quality, values=[n for n, _ in QUALITY], state="readonly", width=5,
                          font=self.fonts.base)
        cb.pack(side="right", padx=(2, 8))
        cb.bind("<<ComboboxSelected>>", self._on_quality)
        tk.Label(top, text="3D 畫質", bg=kit.ACCENT, fg="#d7ebe8", font=self.fonts.small).pack(side="right")

        # ---- 分頁
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True)
        self.map_tab = MapTab(self.nb, self)
        self.mrt_tab = MrtTab(self.nb, self)
        self.intel_tab = IntelTab(self.nb, self)
        self.compare_tab = CompareTab(self.nb, self)
        self.watch_tab = WatchTab(self.nb, self, SEARCH_URLS, open_search)
        self.nb.add(self.map_tab, text=" 3D 房價地圖 ")
        self.nb.add(self.compare_tab, text=" 區域比較 ")
        self.nb.add(self.mrt_tab, text=" 捷運與鐵路 " if self.county == "D" else " 台南捷運 ")
        self.nb.add(self.intel_tab, text=" 開發與情資 ")
        self.nb.add(self.watch_tab, text=" 看屋清單 ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ 跨分頁
    def show_mrt(self, name):
        if name not in self.mrt_lines:          # 營運中的路線（OpenStreetMap）沒有進度資料：在地圖上標出來就好
            self.nb.select(self.map_tab)
            self.map_tab.view.select("line", name)
            return
        self.nb.select(self.mrt_tab)
        self.mrt_tab.show(name)

    def show_intel(self, ident):
        self.nb.select(self.intel_tab)
        self.intel_tab.show(ident)

    def show_watch(self, ident):
        self.nb.select(self.watch_tab)
        self.watch_tab.show(ident)

    def add_to_compare(self, name):
        self.compare_tab.add(name)
        self.nb.select(self.compare_tab)

    def _on_tab(self, _e=None):
        """切到比較或看屋分頁時重新整理（房價資料或上班地點可能已經變了）。"""
        cur = self.nb.select()
        if cur == str(self.compare_tab):
            self.compare_tab.refresh()
        elif cur == str(self.watch_tab):
            self.watch_tab.refresh()

    def show_on_map(self, lat, lng, kind=None, ident=None, zoom=34.0):
        self.nb.select(self.map_tab)
        if kind == "marker":
            # 確保該標記沒有被影響度篩選隱藏
            self.map_tab.marker_min.set("全部")
            self.map_tab.show_markers.set(True)
            self.map_tab._layers()
            self.map_tab.refresh_markers()
            it = self.intel_by_id.get(ident)
            if it and it.get("build") and self.map_tab.show_projects.get():
                self.map_tab.refresh_landmarks()
                kind = "project"                # 這一項畫成 3D 圖案（不是菱形標記）
        elif kind == "line":
            self.map_tab.show_lines.set(True)
            self.map_tab._layers()
        self.map_tab.focus_point(lat, lng, kind, ident, zoom=zoom)

    def write_intel(self, t, it, compact=False):
        """把一筆情資寫進 RichText。"""
        t.line(it["name"], "h1")
        meta = [it["type"]]
        if it.get("district"):
            meta.append(it["district"])
        if it.get("impact_level"):
            meta.append("影響度 %d/5" % it["impact_level"])
        if it.get("confidence"):
            meta.append("可信度 %s" % it["confidence"])
        t.line(" | ".join(meta), "muted")
        t.line("現況", "h2")
        t.line(it.get("status") or "")
        for label, key in [("時程", "timeline"), ("主辦／開發商", "developer"), ("規模", "scale"), ("對周邊的可能影響", "impact")]:
            if it.get(key):
                t.line(label, "h2")
                t.line(str(it[key]))
        if it.get("change_pct") is not None:
            t.line("變動幅度", "h2")
            t.line("%+.2f%%" % it["change_pct"])
        if it.get("impact_level"):
            t.line("影響度為整理資料時的主觀評估，不是投資建議。", "muted")
        if not compact:
            t.sources(it.get("sources"))
        elif it.get("sources"):
            t.sources(it["sources"][:2])

    def reload_prices(self):
        self.book, self.txs = region.load_book_and_txs()
        if self.county != "D":
            # 第一次下載後才知道有哪些區（交易資料裡的區名）
            self.districts = region.load_districts(self.txs)
            self.dmap = {d["name"]: d for d in self.districts}
        self.map_tab.refresh_all()
        self.compare_tab.refresh()
        self.watch_tab.refresh()

    # ------------------------------------------------------------------ 切換縣市
    def _on_county(self, _e=None):
        code = next((c for c, n in region.choices() if n == self.v_county.get()), None)
        if not code or code == self.county:
            return
        if self.map_tab.busy():
            messagebox.showinfo("請稍候", "正在下載資料，完成後再切換縣市。", parent=self.root)
            self.v_county.set(self.cinfo["short"])
            return
        self.switch_county(code)

    def switch_county(self, code):
        """換縣市：記住選擇，整個畫面依新縣市重建（地圖原點、資料、分頁都重來，最不容易出錯）。"""
        self.settings["county"] = code
        kit.save_settings(self.settings)
        root = self.root
        # 停掉所有排定的工作（自動更新、輪詢下載…）；直接呼叫 Tcl 的 after cancel，
        # 不用 after_cancel（它會先刪掉回呼命令，接著 destroy 再刪一次就會出錯）
        for job in root.tk.splitlist(root.tk.call("after", "info")):
            try:
                root.tk.call("after", "cancel", job)
            except tk.TclError:
                pass
        for w in list(root.winfo_children()):
            w.destroy()
        return App(root, auto_download=self.auto_download, watch_path=self._watch_path, county=code)

    # ------------------------------------------------------------------ 設定
    def change_font(self, delta):
        size = max(8, min(22, self.fonts.size + delta))
        self.fonts.set_size(size)
        self.fonts.apply_ttk(self.root)
        kit.rescale_tables(self.fonts)
        self.map_tab.set_font_size(size)
        self.compare_tab.set_font_size(size)
        self.settings["font_size"] = size
        kit.save_settings(self.settings)

    def _on_quality(self, _e=None):
        q = dict(QUALITY)[self.v_quality.get()]
        self.map_tab.view.set_quality(q)
        self.settings["quality"] = q
        kit.save_settings(self.settings)

    def show_about(self):
        win = tk.Toplevel(self.root)
        win.title("資料說明")
        win.geometry("%dx%d" % (min(760, self.win_w - 60), min(620, self.win_h - 80)))
        frame, t = kit.scrolled(win, lambda p: kit.RichText(p, self.fonts))
        frame.pack(fill="both", expand=True)
        t.clear()
        t.line("地圖怎麼操作", "h1")
        t.line("左鍵拖曳移動地圖、右鍵拖曳旋轉（下方的「拖曳」按鈕可以對調）；滾輪會對著游標的位置放大縮小；地圖上方可以搜尋地址。"
               "點房價柱、地標、開發案或車站，地圖會自動滑到那裡並拉近；「全市總覽」回到整個縣市，「重置」連角度一起還原。")
        t.line("資料來源與限制", "h1")
        t.line("房價", "h2")
        t.line("內政部不動產交易實價查詢服務網的開放資料（臺南市用臺南的檔案，其他縣市用全國檔）。只統計住宅的房地交易，"
               "排除親友、持分、急買急賣等特殊交易，統計值為中位數。")
        t.line(self.book.describe_source(), "muted")
        t.line("內政部每月 1、11、21 日發布新一期；下載過一次逐筆資料後，開程式時會自動補抓新的一期（右下角「自動更新」可以關掉）。")
        t.line("實價登錄從成交到公開約有 1~2 個月時間差，所以最近一個月的件數會偏少（圖上以空心點表示），"
               "「近半年起伏」是用後 3 個月對前 3 個月的中位數比較，單區單月件數少時波動會很大。")
        t.line("透天厝的單價是用建物面積計算（價格含土地），不適合直接和大樓單價比較；看透天請以總價為主。")
        t.line("「預售屋」是實價登錄的預售屋申報資料，已解約的不計；「全部合併」只含成屋買賣，不含預售。"
               "「路段」分頁把近一年成交依門牌的路名歸類，2 件以上才列出。")
        t.line("路段房價", "h2")
        t.line("選了行政區之後，地圖上會把近一年有成交的路段依中位價上色（黃→橘→紫紅，越深越貴），放大可以看到路名與價格，"
               "點路段會列出該路段的逐筆成交。右側「路段」分頁可以用路名搜尋全市。需要先按過「更新實價登錄」取得逐筆資料。")
        t.line("實價登錄只公開門牌文字、沒有座標，所以道路的位置取自 OpenStreetMap（© OpenStreetMap 貢獻者），"
               "每個行政區第一次查看時下載一次。門牌若不是路名而是聚落名稱（例如「茄拔」），地圖上畫成圓點，位置是聚落的大概位置；"
               "少數在 OpenStreetMap 上找不到的路名只會出現在右側清單。不到 3 件的路段以 * 標示，僅供參考。")
        t.line("搜尋地址與門牌圖釘", "h2")
        t.line("地圖上方的搜尋框可以輸入地址或路名（例如「善化區中山路123號」），地圖會移到那一段並插上圖釘，"
               "右邊「成交」列出同門牌、同一條巷、整條路的價格；點「成交」清單的任何一列，也會用圖釘標出那一筆的大概位置。"
               "實價登錄沒有座標，圖釘位置是用 OpenStreetMap 的道路與巷口號碼推估的，圖釘周圍的虛線圈是誤差範圍，滑鼠移到圖釘上會說明準確度。")
        t.line("重大建設與年份滑桿", "h2")
        t.line("有時程的開發案畫成立體小圖案：原色是完工／營運中、旁邊有黃色塔吊是施工中、淡色是規劃中。"
               "地圖下方的「建設年份」可以拉到未來，看那一年各建設的狀態。年份依報導與官方說法整理，常會延後，只能當參考。")
        t.line("行情報告", "h2")
        t.line("選一個行政區或搜尋一個地址後按「行情報告」，會產生一頁可以列印成 PDF 的報告（存在 reports 資料夾），"
               "內容有重點數字、走勢、附近成交、重大建設與通勤距離，可以填房仲名稱與電話。")
        t.line("地標", "h2")
        t.line("地圖上的立體小圖案是各縣市的知名地標，方便辨認方位；是示意造型，不是建築物的精確模型，位置取自 OpenStreetMap。"
               "縮小時擠在一起的地標只顯示比較知名的，放大後其他的才會出現。")
        t.line("預算與通勤", "h2")
        t.line("預算篩選是拿你的預算和各區的中位總價比，代表「該區有一半的成交低於這個價格」，不代表買不到或一定買得到。"
               "房貸試算是本息平均攤還的算術結果，利率與成數請填銀行實際給的條件。"
               "通勤距離是行政區中心到上班地點的直線距離，實際車程請按「通勤路線」用 Google 地圖查。"
               "上班地點可以設 A、B 兩個；兩個都填了公里數時，要兩邊都在範圍內才算符合。")
        t.line("地形", "h2")
        t.line("%s。地形高度經過垂直誇張以便觀察，可用「地形誇張」滑桿調整。" % self.terrain.source)
        t.line("「Google 地形圖」按鈕會用瀏覽器開啟 Google 地圖的地形圖層並定位到所選行政區。")
        t.line("衛星影像底圖", "h2")
        t.line("內政部國土測繪中心的正射影像（航照圖），第一次使用時下載並存在 data/cache/basemap，之後離線可用。"
               "要把 Google 衛星圖放進 App 必須申請 Google Maps API 金鑰，所以 App 內改用這份政府開放圖資；"
               "衛星影像模式下地面是平的，要看起伏請切到「立體地形」。放大時會自動下載該處的高解析影像（存在 data/cache/tiles）。")
        t.line("疊圖：區界、路名、土壤液化、活動斷層", "h2")
        t.line("區界、路名與土壤液化潛勢來自國土測繪中心圖磚服務（液化資料屬經濟部地質調查及礦業管理中心與臺南市政府）；"
               "活動斷層與斷層地質敏感區來自地質調查及礦業管理中心。")
        t.line("土壤液化潛勢分高（紅）、中（黃）、低（綠）三級，表示強震時土壤可能液化的輕重程度，不是平時就有危險；"
               "公開圖資精度有限，不能代表每一塊土地，個別建物仍要看地質鑽探與基礎設計。"
               "圖層預設調淡以便看到底下的影像，可在「圖層」列用「液化濃淡」滑桿調整。")
        t.line("活動斷層線是斷層跡的大致位置（虛線為推測），不等於地震危險度高低；紅色帶狀是依地質法公告的斷層地質敏感區。")
        t.line("淹水潛勢圖沒有做進 App：官方圖資服務從外部連不上，而且依規定僅供防救災使用。"
               "請按「淹水潛勢↗」到國家災害防救科技中心的 3D 災害潛勢地圖查看。")
        t.line("捷運、開發案、議會與建商情資", "h2")
        t.line("整理自各縣市政府、交通部、議會與主流媒體的公開報導（查證日 %s），每一筆都附來源連結。"
               "所有捷運路線目前都還沒動工，時程可能再變動；站位與開發案位置為估算值，僅供示意。" % self.intel_as_of)
        t.line("提醒", "h2")
        t.line("本工具只整理公開資訊供自己看屋參考，不構成投資或購屋建議；實際價格、屋況與法規請以官方資料和專業人員為準。")
        t.line("程式與設計 © 全台房價即時動態分析，保留所有權利。未經授權請勿複製、轉載或改作本程式、介面設計與 3D 造型；房價、行政區、影像等資料依各來源的開放授權使用。", "muted")
        t.done()

    def on_close(self):
        kit.save_settings(self.settings)
        self.root.destroy()


def main():
    root = tk.Tk()
    errlog.install(root)           # 出錯時寫進 logs/app_errors.log
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
