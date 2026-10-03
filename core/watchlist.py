"""看屋清單：使用者自己的候選物件，存在 data/watchlist.json。"""
import json
import os
import time

from .geo import DATA_DIR

PATH = os.path.join(DATA_DIR, "watchlist.json")
TYPES = ["透天厝", "大樓／華廈", "公寓", "預售屋", "店面／透店", "土地", "其他"]
# 物件類型 -> 拿來比較行情的房型類別
TYPE_CAT = {"透天厝": "house", "店面／透店": "house", "大樓／華廈": "apt", "公寓": "all", "預售屋": "presale"}
FIELDS = ["name", "district", "address", "type", "price", "ping", "year", "url", "note", "lat", "lng"]


def _new_id():
    return "w%d" % int(time.time() * 1000)


class Watchlist:
    def __init__(self, path=None):
        self.path = path or PATH
        self.items = []
        self.imported_sample = False

    def load(self, legacy=None):
        """讀取清單；檔案不存在時，把舊版 house_data.py 的清單匯入一次（標示為示意資料）。"""
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.items = d.get("items", [])
            self.imported_sample = bool(d.get("imported_sample"))
        except (OSError, ValueError):
            self.items = []
            for i, p in enumerate(legacy or []):
                kind = "店面／透店" if "店" in str(p.get("type", "")) else "透天厝"
                note = "；".join(x for x in (p.get("note"), p.get("analysis")) if x)
                addr = p.get("address", "")
                self.items.append({
                    "id": "legacy%d" % i, "name": p.get("name", ""), "district": "善化區" if "善化" in addr else "",
                    "address": addr, "type": kind, "price": p.get("price"), "ping": p.get("ping"),
                    "year": p.get("year"), "url": p.get("source_url", ""), "note": note, "lat": None, "lng": None,
                    "sample": True})
            self.imported_sample = bool(self.items)
        return self

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"imported_sample": self.imported_sample, "items": self.items}, f, ensure_ascii=False, indent=1)
            return True
        except OSError:
            return False

    def remove_samples(self):
        """刪掉從舊版帶過來的示意物件；回傳刪了幾筆。之後不會再匯入（imported_sample 維持 True）。"""
        before = len(self.items)
        self.items = [it for it in self.items if not it.get("sample")]
        n = before - len(self.items)
        if n:
            self.save()
        return n

    def get(self, ident):
        for it in self.items:
            if it["id"] == ident:
                return it
        return None

    def add(self, data):
        it = {k: data.get(k) for k in FIELDS}
        it["id"] = _new_id()
        while self.get(it["id"]):
            it["id"] += "x"
        self.items.append(it)
        self.save()
        return it

    def update(self, ident, data):
        it = self.get(ident)
        if it:
            for k in FIELDS:
                if k in data:
                    it[k] = data[k]
            it.pop("sample", None)
            self.save()
        return it

    def remove(self, ident):
        self.items = [it for it in self.items if it["id"] != ident]
        self.save()


def unit_price(item):
    """物件單價（萬/坪）；資料不足回傳 None。"""
    try:
        price, ping = float(item.get("price") or 0), float(item.get("ping") or 0)
    except (TypeError, ValueError):
        return None
    return price / ping if price > 0 and ping > 0 else None
