"""全台實價登錄下載器（給 GitHub Actions／桌面版的全台模式用；只用標準函式庫）。

和 plvr.py（只抓臺南市）同樣的三種檔案，但一次拿全國：
  1. 季檔     DownloadSeason?season=115S2&type=zip&fileName=lvr_landcsv.zip   （全國 zip）
             抓不到 zip 時改成逐縣市 DownloadSeason?season=…&fileName=A_lvr_land_A.csv
  2. 前期檔   DownloadHistory?type=history&fileName=20260911                    （本來就是全國 zip）
  3. 本期檔   Download?type=zip&fileName=lvr_landcsv.zip                       （全國 zip；失敗改逐縣市）

下載後一律展開成「一期一個資料夾、每縣市兩個檔」：
  data/cache/plvr_tw/season_115S2/a_lvr_land_a.csv、a_lvr_land_b.csv、b_lvr_land_a.csv …
資料夾裡有 _done 檔才算完整；季檔與前期檔不會變，下載過就不再下載；本期檔每次重抓。
"""
import datetime
import io
import os
import shutil
import time
import zipfile

from . import plvr, prices
from .taiwan import COUNTIES

CACHE = os.path.join(prices.CACHE_DIR, "plvr_tw")
BASE_URL = plvr.BASE_URL
KINDS = ("a", "b")                     # a=不動產買賣、b=預售屋
CODES = [c["code"].lower() for c in COUNTIES]


def _say(progress, msg):
    if progress:
        progress(msg)
    else:
        print(msg, flush=True)


def _dir(name):
    return os.path.join(CACHE, name)


def is_done(name):
    return os.path.exists(os.path.join(_dir(name), "_done"))


def _mark_done(name, note=""):
    with open(os.path.join(_dir(name), "_done"), "w", encoding="utf-8") as f:
        f.write(note or datetime.datetime.now().isoformat())


def _extract_zip(z_bytes, name):
    """把全國 zip 裡各縣市的買賣檔、預售屋檔展開到資料夾；回傳展開了幾個檔。"""
    d = _dir(name)
    os.makedirs(d, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(z_bytes)) as z:
        for member in z.namelist():
            base = member.split("/")[-1].lower()
            for code in CODES:
                for kind in KINDS:
                    if base == "%s_lvr_land_%s.csv" % (code, kind):
                        with open(os.path.join(d, base), "wb") as f:
                            f.write(z.read(member))
                        n += 1
    return n


def _per_county(name, url_for, progress, insecure=False):
    """逐縣市下載（全國 zip 抓不到時的備案）；回傳拿到幾個縣市的買賣檔。"""
    d = _dir(name)
    os.makedirs(d, exist_ok=True)
    got = 0
    for i, c in enumerate(COUNTIES):
        if i == 3 and got == 0:
            break                          # 前幾個縣市都沒有：這一期根本還沒釋出，不必再問
        for kind in KINDS:
            try:
                b = plvr.fetch(url_for(c["code"], kind.upper()), insecure=insecure)
            except plvr.DownloadError as e:
                _say(progress, "  %s %s %s 失敗：%s" % (name, c["short"], kind, e))
                continue
            if plvr.looks_like_csv(b):
                with open(os.path.join(d, "%s_lvr_land_%s.csv" % (c["code"].lower(), kind)), "wb") as f:
                    f.write(b)
                if kind == "a":
                    got += 1
            time.sleep(0.5)
    return got


def _season(name, progress, insecure):
    """下載某一季；尚未釋出回傳 False。"""
    if is_done("season_" + name):
        return True
    _say(progress, "下載季檔 %s（全國）…" % name)
    try:
        z = plvr.fetch("%s/DownloadSeason?season=%s&type=zip&fileName=lvr_landcsv.zip" % (BASE_URL, name),
                       timeout=600, insecure=insecure)
    except plvr.DownloadError as e:
        z = b""
        _say(progress, "  全國 zip 失敗：%s，改逐縣市下載" % e)
    if z[:2] == b"PK" and _extract_zip(z, "season_" + name) >= len(CODES):
        _mark_done("season_" + name, "zip")
        return True
    got = _per_county("season_" + name, lambda code, kind: "%s/DownloadSeason?season=%s&fileName=%s_lvr_land_%s.csv" % (
        BASE_URL, name, code, kind), progress, insecure)
    if got >= len(CODES) - 2:          # 離島偶爾整季沒有檔案
        _mark_done("season_" + name, "per-county %d" % got)
        return True
    shutil.rmtree(_dir("season_" + name), ignore_errors=True)
    return False


def update(progress=None, seasons_wanted=5, insecure=False, today=None):
    """下載（或補齊）全台資料。回傳資料夾清單。"""
    today = today or datetime.date.today()
    os.makedirs(CACHE, exist_ok=True)
    found = []
    for roc, q in plvr.season_candidates(today):
        name = plvr.season_name(roc, q)
        if is_done("season_" + name) or _season(name, progress, insecure):
            found.append((roc, q))
        elif found:
            break
        if len(found) >= seasons_wanted:
            break
    if not found:
        raise plvr.DownloadError("找不到任何可下載的季檔（全國）。")
    latest_end = plvr.season_end_date(*found[0])
    keep = {"season_" + plvr.season_name(*f) for f in found}

    # 前期檔：比最新季檔還新的才需要
    try:
        html = plvr.fetch(BASE_URL + "/DownloadHistory_ajax_list", timeout=60, insecure=insecure).decode("utf-8", "replace")
        dates = [d for d in plvr.parse_history_dates(html) if d > latest_end]
    except plvr.DownloadError as e:
        _say(progress, "讀取前期發布清單失敗：%s" % e)
        dates = []
    for d in dates:
        name = "hist_" + d
        keep.add(name)
        if is_done(name):
            continue
        _say(progress, "下載前期檔 %s（全國）…" % d)
        z = plvr.fetch("%s/DownloadHistory?type=history&fileName=%s" % (BASE_URL, d), timeout=600, insecure=insecure)
        if z[:2] == b"PK" and _extract_zip(z, name):
            _mark_done(name)

    # 本期檔：每次重抓
    _say(progress, "下載本期檔（全國）…")
    shutil.rmtree(_dir("cur"), ignore_errors=True)
    try:
        z = plvr.fetch("%s/Download?type=zip&fileName=lvr_landcsv.zip" % BASE_URL, timeout=600, insecure=insecure)
    except plvr.DownloadError:
        z = b""
    if not (z[:2] == b"PK" and _extract_zip(z, "cur") >= len(CODES)):
        _per_county("cur", lambda code, kind: "%s/Download?fileName=%s_lvr_land_%s.csv" % (BASE_URL, code, kind),
                    progress, insecure)
    _mark_done("cur", today.isoformat())
    keep.add("cur")

    # 清掉用不到的舊資料夾（被新季檔涵蓋的前期檔、太舊的季檔）
    for name in os.listdir(CACHE):
        if os.path.isdir(_dir(name)) and name not in keep:
            shutil.rmtree(_dir(name), ignore_errors=True)
    return sorted(keep)


def folders():
    if not os.path.isdir(CACHE):
        return []
    return sorted(n for n in os.listdir(CACHE) if os.path.isdir(_dir(n)) and is_done(n))


def load_county(code):
    """某縣市的所有交易（買賣＋預售），已去重。"""
    code = code.lower()
    txs = []
    for name in folders():
        for kind in KINDS:
            path = os.path.join(_dir(name), "%s_lvr_land_%s.csv" % (code, kind))
            if not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                text = f.read().decode("utf-8-sig", "replace")
            if text.strip():
                txs.extend(prices.parse_csv_text(text))
    return prices.dedupe(txs)


def as_of():
    p = os.path.join(_dir("cur"), "_done")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()[:10]
    except OSError:
        return datetime.date.today().isoformat()
