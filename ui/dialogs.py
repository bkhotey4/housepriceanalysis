"""對話框：房貸試算、看屋物件編輯。"""
import tkinter as tk
from tkinter import messagebox, ttk

from core import prices, watchlist
from . import kit


def _num(text):
    try:
        v = float(str(text).replace(",", "").strip())
    except ValueError:
        return None
    return v


class MortgageDialog(tk.Toplevel):
    """房貸試算（本息平均攤還）。只做算術，不是貸款建議；利率請填銀行實際報價。"""

    def __init__(self, master, app, price, on_apply=None):
        super().__init__(master)
        self.app, self.on_apply = app, on_apply
        f = app.fonts
        st = app.settings
        self.title("房貸試算")
        self.configure(bg=kit.SURFACE, padx=16, pady=12)
        self.resizable(False, False)
        self.v_price = tk.StringVar(value="%g" % price)
        self.v_ltv = tk.StringVar(value="%g" % st.get("loan_pct", 80))
        self.v_rate = tk.StringVar(value="%g" % st.get("loan_rate", 2.3))
        self.v_years = tk.StringVar(value="%g" % st.get("loan_years", 30))
        self.v_agent = tk.StringVar(value="%g" % st.get("agent_pct", 2))
        rows = [("房屋總價", self.v_price, "萬"), ("貸款成數", self.v_ltv, "%"),
                ("年利率", self.v_rate, "%"), ("貸款年限", self.v_years, "年"), ("仲介費", self.v_agent, "%")]
        for i, (label, var, unit) in enumerate(rows):
            tk.Label(self, text=label, bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Entry(self, textvariable=var, width=10, font=f.base, justify="right")
            e.grid(row=i, column=1, padx=8, pady=3)
            e.bind("<KeyRelease>", lambda ev: self.recalc())
            tk.Label(self, text=unit, bg=kit.SURFACE, fg=kit.MUTED, font=f.base).grid(row=i, column=2, sticky="w")
        tk.Label(self, text="利率與成數請填銀行實際給你的條件；跟建商買預售屋、新成屋，仲介費填 0。", bg=kit.SURFACE, fg=kit.MUTED, font=f.small
                 ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 8))
        box = tk.Frame(self, bg="#f6f7f9", padx=12, pady=10, highlightthickness=1, highlightbackground=kit.BORDER)
        box.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.out = {}
        for i, (key, label) in enumerate([("down", "自備款"), ("loan", "貸款金額"), ("monthly", "每月應繳"),
                                          ("interest", "利息總額"), ("income", "月收入參考"),
                                          ("fees", "稅費與雜支"), ("cash", "交屋前要準備")]):
            tk.Label(box, text=label, bg="#f6f7f9", fg=kit.MUTED, font=f.base, anchor="w").grid(row=i, column=0, sticky="w", pady=2)
            v = tk.Label(box, text="—", bg="#f6f7f9", fg=kit.INK, font=f.h2 if key == "monthly" else f.bold, anchor="e")
            v.grid(row=i, column=1, sticky="e", padx=(24, 0), pady=2)
            self.out[key] = v
        box.columnconfigure(1, weight=1)
        self.fee_detail = tk.Label(self, text="", bg=kit.SURFACE, fg=kit.MUTED, font=f.small, justify="left")
        self.fee_detail.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(self, text="每月應繳以本息平均攤還計算，未含寬限期、稅費與保險。\n「月收入參考」是以月付不超過月收入三分之一的常見審核原則反推，僅供試算。\n"
                 "稅費以房屋評定現值≈總價 10%、土地公告現值≈總價 25% 粗估，實際以稅單或代書試算為準。",
                 bg=kit.SURFACE, fg=kit.MUTED, font=f.small, justify="left").grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 8))
        btns = tk.Frame(self, bg=kit.SURFACE)
        btns.grid(row=9, column=0, columnspan=3, sticky="e")
        ttk.Button(btns, text="關閉", command=self.destroy).pack(side="right", padx=2)
        if on_apply:
            ttk.Button(btns, text="把總價設為地圖預算", command=self._apply).pack(side="right", padx=2)
        self.recalc()
        self.transient(master.winfo_toplevel())

    def values(self):
        price, ltv, rate, years = (_num(v.get()) for v in (self.v_price, self.v_ltv, self.v_rate, self.v_years))
        if None in (price, ltv, rate, years) or price <= 0 or not 0 <= ltv <= 100 or rate < 0 or years <= 0:
            return None
        return price, ltv, rate, years

    def recalc(self):
        vals = self.values()
        if not vals:
            for v in self.out.values():
                v.config(text="—")
            self.fee_detail.config(text="")
            return None
        price, ltv, rate, years = vals
        loan = price * ltv / 100.0
        monthly = prices.monthly_payment(loan, rate, years)
        interest = monthly * years * 12 - loan * 10000
        self.out["down"].config(text="%s 萬" % kit.fmt_num(price - loan))
        self.out["loan"].config(text="%s 萬" % kit.fmt_num(loan))
        self.out["monthly"].config(text="%s 元" % kit.fmt_num(monthly))
        self.out["interest"].config(text="%s 萬" % kit.fmt_num(interest / 10000.0))
        self.out["income"].config(text="約 %.1f 萬以上" % (monthly * 3 / 10000.0))
        agent = _num(self.v_agent.get())
        agent = agent if agent is not None and 0 <= agent <= 6 else 2.0
        c = prices.purchase_costs(price, 100 - ltv, agent_pct=agent)
        self.out["fees"].config(text="約 %.1f 萬" % c["fees"])
        self.out["cash"].config(text="約 %s 萬" % kit.fmt_num(c["total"]))
        parts = ["%s %.1f 萬" % (label.split("、")[0], v) for k, label, v, _n in c["items"] if k not in ("down", "reno") and v >= 0.05]
        self.fee_detail.config(text="稅費明細：" + "、".join(parts) + "\n另外建議預留 6 個月房貸約 %.0f 萬。" % (monthly * 6 / 10000.0))
        st = self.app.settings
        st["loan_pct"], st["loan_rate"], st["loan_years"], st["agent_pct"] = ltv, rate, years, agent
        return monthly

    def _apply(self):
        vals = self.values()
        if vals:
            kit.save_settings(self.app.settings)
            self.on_apply(vals[0])
            self.destroy()


class WatchDialog(tk.Toplevel):
    """新增或編輯一筆看屋物件。"""

    def __init__(self, master, app, item=None, on_save=None):
        super().__init__(master)
        self.app, self.item, self.on_save = app, item or {}, on_save
        f = app.fonts
        self.title("編輯物件" if item else "新增物件")
        self.configure(bg=kit.SURFACE, padx=16, pady=12)
        self.vars = {}
        it = self.item
        districts = [d["name"] for d in app.districts]

        def text_row(r, key, label, width=34, unit=""):
            tk.Label(self, text=label, bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="w").grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value="" if it.get(key) in (None, "") else str(it.get(key)))
            ttk.Entry(self, textvariable=v, width=width, font=f.base).grid(row=r, column=1, sticky="w", padx=8, pady=3)
            if unit:
                tk.Label(self, text=unit, bg=kit.SURFACE, fg=kit.MUTED, font=f.base).grid(row=r, column=2, sticky="w")
            self.vars[key] = v

        def combo_row(r, key, label, values, default):
            tk.Label(self, text=label, bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="w").grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=it.get(key) or default)
            ttk.Combobox(self, textvariable=v, values=values, state="readonly", width=14, font=f.base).grid(row=r, column=1, sticky="w", padx=8, pady=3)
            self.vars[key] = v

        text_row(0, "name", "名稱")
        combo_row(1, "district", "行政區", districts, getattr(master, "default_district", None) or "善化區")
        text_row(2, "address", "地址／路段")
        combo_row(3, "type", "類型", watchlist.TYPES, "透天厝")
        text_row(4, "price", "總價", 10, "萬")
        text_row(5, "ping", "建坪", 10, "坪")
        text_row(6, "year", "完工年（西元）", 10)
        text_row(7, "url", "物件網址")
        tk.Label(self, text="備註", bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="w").grid(row=8, column=0, sticky="nw", pady=3)
        self.note = tk.Text(self, width=36, height=4, font=f.base, wrap="word", relief="solid", bd=1)
        self.note.grid(row=8, column=1, columnspan=2, sticky="w", padx=8, pady=3)
        self.note.insert("1.0", it.get("note") or "")
        btns = tk.Frame(self, bg=kit.SURFACE)
        btns.grid(row=9, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=2)
        ttk.Button(btns, text="儲存", command=self._save).pack(side="right", padx=2)
        self.transient(master.winfo_toplevel())

    def collect(self):
        """讀取表單；格式有誤回傳 (None, 錯誤訊息)。"""
        data = {k: v.get().strip() for k, v in self.vars.items()}
        data["note"] = self.note.get("1.0", "end").strip()
        if not data["name"]:
            return None, "請填名稱。"
        for key, label in (("price", "總價"), ("ping", "建坪"), ("year", "完工年")):
            if data[key] == "":
                data[key] = None
                continue
            v = _num(data[key])
            if v is None or v <= 0:
                return None, "「%s」請填正數，或留空。" % label
            data[key] = int(v) if key == "year" or v == int(v) else v
        if data["year"] is not None and not 1900 <= data["year"] <= 2100:
            return None, "完工年請填西元年（例如 2015）。"
        return data, None

    def _save(self):
        data, err = self.collect()
        if err:
            messagebox.showwarning("請檢查", err, parent=self)
            return
        if self.on_save:
            self.on_save(data)
        self.destroy()


class ReportDialog(tk.Toplevel):
    """行情報告：填房仲名稱、電話（會記住）與客戶稱呼、備註，按「產生報告」存成 HTML 並用瀏覽器打開（可列印成 PDF）。"""

    def __init__(self, master, app, title, on_make):
        super().__init__(master)
        self.app, self.on_make = app, on_make
        f = app.fonts
        st = app.settings
        self.title("行情報告")
        self.configure(bg=kit.SURFACE, padx=16, pady=12)
        self.resizable(False, False)
        tk.Label(self, text="報告內容：%s" % title, bg=kit.SURFACE, fg=kit.INK, font=f.bold, anchor="w"
                 ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.v = {"name": tk.StringVar(value=st.get("agent_name", "")), "phone": tk.StringVar(value=st.get("agent_phone", "")),
                  "client": tk.StringVar(value="")}
        for i, (key, label) in enumerate([("name", "製作人／房仲"), ("phone", "聯絡電話"), ("client", "給（客戶稱呼）")]):
            tk.Label(self, text=label, bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="w").grid(row=i + 1, column=0, sticky="w", pady=3)
            ttk.Entry(self, textvariable=self.v[key], width=26, font=f.base).grid(row=i + 1, column=1, padx=8, pady=3, sticky="w")
        tk.Label(self, text="備註", bg=kit.SURFACE, fg=kit.INK, font=f.base, anchor="nw").grid(row=4, column=0, sticky="nw", pady=3)
        self.note = tk.Text(self, width=34, height=4, font=f.base, relief="solid", bd=1)
        self.note.grid(row=4, column=1, padx=8, pady=3, sticky="w")
        tk.Label(self, text="都可以留空。名稱與電話會記住，下次不用再填。\n報告會存在程式資料夾的 reports，用瀏覽器打開後可以列印或存成 PDF。",
                 bg=kit.SURFACE, fg=kit.MUTED, font=f.small, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 8))
        btns = tk.Frame(self, bg=kit.SURFACE)
        btns.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="產生報告", command=self.make).pack(side="right", padx=6)
        self.transient(master)
        try:                                            # 開在主視窗中間（不要跑到螢幕左上角）
            self.update_idletasks()
            top = master.winfo_toplevel()
            x = top.winfo_rootx() + max(0, (top.winfo_width() - self.winfo_reqwidth()) // 2)
            y = top.winfo_rooty() + max(0, (top.winfo_height() - self.winfo_reqheight()) // 3)
            self.geometry("+%d+%d" % (x, y))
        except tk.TclError:
            pass

    def values(self):
        return {"name": self.v["name"].get().strip(), "phone": self.v["phone"].get().strip(),
                "client": self.v["client"].get().strip(), "note": self.note.get("1.0", "end").strip()}

    def make(self):
        agent = self.values()
        self.app.settings["agent_name"], self.app.settings["agent_phone"] = agent["name"], agent["phone"]
        kit.save_settings(self.app.settings)
        self.destroy()
        self.on_make(agent)
