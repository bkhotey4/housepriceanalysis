"""內政部「不動產成交案件實際資訊資料供應系統」下載器（只用標準函式庫）。

下載三種檔案（都只取臺南市「不動產買賣」）：
  1. 季檔     DownloadSeason?season=115S2&fileName=D_lvr_land_A.csv      （約 2MB/季）
  2. 前期檔   DownloadHistory?type=history&fileName=20260911               （全國 zip，約 15MB/期）
  3. 本期檔   Download?fileName=D_lvr_land_A.csv                           （最新一旬）

季檔依「登記日期」切分且釋出較晚，所以最近 2~3 個月的交易要靠前期檔＋本期檔補齊。
查無檔案時伺服器回 HTTP 200 + HTML「系統訊息」頁，因此一律檢查內容而不是狀態碼。
"""
import datetime
import io
import os
import re
import ssl
import zipfile
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import prices
from .geo import load_districts

BASE_URL = "https://plvr.land.moi.gov.tw"
CITY_CODE = "D"  # 臺南市
UA = "Mozilla/5.0 (deep_tainan_house personal research tool)"
PLVR_DIR = os.path.join(prices.CACHE_DIR, "plvr")
MIN_SEASON_BYTES = 50000  # 小於這個大小的季檔快取視為不完整，重新下載
_BOM = b"\xef\xbb\xbf"
_HEAD = "鄉鎮市區".encode("utf-8")
# 各季「登記日期」的結束月日（S1: 3/10, S2: 6/10, S3: 9/10, S4: 12/10）
_SEASON_END = {1: (3, 10), 2: (6, 10), 3: (9, 10), 4: (12, 10)}


class CertError(Exception):
    """HTTPS 憑證驗證失敗。"""


class DownloadError(Exception):
    pass


def fetch(url, timeout=90, insecure=False, data=None, agent=None, headers=None):
    """抓一個網址。data 給 bytes 就改用 POST；agent 可換掉預設的 User-Agent；headers 是額外的標頭。"""
    hdr = {"User-Agent": agent or UA}
    hdr.update(headers or {})
    req = Request(url, data=data, headers=hdr)
    contexts = []
    if insecure:
        contexts.append(ssl._create_unverified_context())
    else:
        contexts.append(ssl.create_default_context())
        try:
            import certifi  # 可選：系統憑證不足時的備援
            contexts.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception:
            pass
    last_cert_error = None
    for ctx in contexts:
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError) or isinstance(e, ssl.SSLCertVerificationError):
                last_cert_error = e
                continue
            code = getattr(e, "code", None)             # HTTPError 才有：伺服器有回應，但拒絕或忙線
            what = ("HTTP %s %s" % (code, reason or "")).strip() if code else (reason or e)
            if code:
                try:                                    # 錯誤頁的前幾個字通常就寫了原因（忙線、太頻繁、被擋）
                    hint = re.sub(r"<[^>]+>|\s+", " ", e.read(600).decode("utf-8", "replace")).strip()
                    what = "%s（%s）" % (what, hint[:160]) if hint else what
                except Exception:
                    pass
            raise DownloadError("無法連線到 %s：%s" % (url.split("/")[2] if "//" in url else url, what))
        except ssl.SSLCertVerificationError as e:
            last_cert_error = e
            continue
        except (OSError, ValueError) as e:
            raise DownloadError("下載失敗：%s" % e)
    raise CertError(str(last_cert_error))


def looks_like_csv(b):
    head = b[:3 + len(_HEAD)]
    return head.startswith(_BOM + _HEAD) or head.startswith(_HEAD)


def season_name(roc_year, q):
    return "%dS%d" % (roc_year, q)


def season_candidates(today, count=9):
    """由今天所在的季往回列出候選季別（最新的可能尚未釋出）。"""
    roc, q = today.year - 1911, (today.month - 1) // 3 + 1
    out = []
    for _ in range(count):
        out.append((roc, q))
        q -= 1
        if q == 0:
            roc, q = roc - 1, 4
    return out


def season_end_date(roc_year, q):
    m, d = _SEASON_END[q]
    return "%04d%02d%02d" % (roc_year + 1911, m, d)


def parse_history_dates(html):
    dates = set(re.findall(r"發布日期\s*(\d{8})", html))
    dates.update(re.findall(r"downloadLast\(\s*['\"]?(\d{8})", html))
    return sorted(dates)


def extract_city_csv(zip_bytes, code=CITY_CODE, kind="a"):
    """由全國壓縮檔取出某縣市的檔案；kind：a=不動產買賣、b=預售屋。"""
    want = ("%s_lvr_land_%s.csv" % (code, kind)).lower()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if name.lower().split("/")[-1] == want:
                return z.read(name)
    raise DownloadError("壓縮檔中找不到 %s" % want)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _season_file(name, kind, insecure):
    """下載某季的買賣檔（A）或預售屋檔（B）；尚未釋出回傳 None。"""
    b = fetch("%s/DownloadSeason?season=%s&fileName=%s_lvr_land_%s.csv" % (BASE_URL, name, CITY_CODE, kind.upper()),
              insecure=insecure)
    return b if looks_like_csv(b) else None


def update(progress=None, include_history=True, insecure=False, seasons_wanted=5, today=None):
    """下載並重建房價資料（成屋買賣＋預售屋）。progress(done, total, message)。回傳 (PriceBook, 交易筆數)。"""
    today = today or datetime.date.today()

    def say(done, total, msg):
        if progress:
            progress(done, total, msg)

    os.makedirs(PLVR_DIR, exist_ok=True)
    total_steps = seasons_wanted + 2
    done = 0

    # ---- 1. 季檔（買賣 A，附帶同一季的預售屋 B）
    found = []
    for roc, q in season_candidates(today):
        name = season_name(roc, q)
        path = os.path.join(PLVR_DIR, "season_%s.csv" % name)
        path_b = os.path.join(PLVR_DIR, "season_%s_b.csv" % name)
        if os.path.exists(path) and os.path.getsize(path) > MIN_SEASON_BYTES:
            found.append((roc, q))
        else:
            say(done, total_steps, "下載季檔 %s …" % name)
            b = _season_file(name, "a", insecure)
            if b is not None:
                _write(path, b)
                found.append((roc, q))
            elif found:
                break  # 已有較新的季檔卻抓不到更舊的，視為到底
            else:
                continue  # 最新一季尚未釋出，往前一季找
        if not os.path.exists(path_b):
            try:
                b = _season_file(name, "b", insecure)
                if b is not None:
                    _write(path_b, b)
            except DownloadError:
                pass   # 預售檔抓不到不影響買賣資料
        done += 1
        say(done, total_steps, "季檔 %s 完成" % name)
        if len(found) >= seasons_wanted:
            break
    if not found:
        raise DownloadError("找不到任何可下載的季檔，可能是網站改版或暫時無法連線。")
    latest_end = season_end_date(*found[0])

    # ---- 2. 前期檔（補最近 2~3 個月；同一個壓縮檔內同時取出買賣與預售）
    if include_history:
        say(done, total_steps, "讀取前期發布清單 …")
        try:
            html = fetch(BASE_URL + "/DownloadHistory_ajax_list", timeout=40, insecure=insecure).decode("utf-8", "replace")
            dates = [d for d in parse_history_dates(html) if d > latest_end]
        except DownloadError:
            dates = []
        need = [d for d in dates if not (os.path.exists(os.path.join(PLVR_DIR, "hist_%s.csv" % d))
                                         and os.path.exists(os.path.join(PLVR_DIR, "hist_%s_b.csv" % d)))]
        total_steps = done + len(need) + 1
        for d in need:
            say(done, total_steps, "下載 %s 發布檔（約 15MB）…" % d)
            z = fetch("%s/DownloadHistory?type=history&fileName=%s" % (BASE_URL, d), timeout=300, insecure=insecure)
            if z[:2] == b"PK":
                _write(os.path.join(PLVR_DIR, "hist_%s.csv" % d), extract_city_csv(z))
                try:
                    _write(os.path.join(PLVR_DIR, "hist_%s_b.csv" % d), extract_city_csv(z, kind="b"))
                except DownloadError:
                    _write(os.path.join(PLVR_DIR, "hist_%s_b.csv" % d), b"")   # 該期沒有預售檔，記一個空檔避免重抓
            done += 1
            say(done, total_steps, "%s 完成" % d)
    else:
        total_steps = done + 1

    # ---- 3. 本期檔
    say(done, total_steps, "下載本期檔 …")
    b = fetch("%s/Download?fileName=%s_lvr_land_A.csv" % (BASE_URL, CITY_CODE), insecure=insecure)
    if looks_like_csv(b):
        _write(os.path.join(PLVR_DIR, "cur.csv"), b)
    try:
        b = fetch("%s/Download?fileName=%s_lvr_land_B.csv" % (BASE_URL, CITY_CODE), insecure=insecure)
        if looks_like_csv(b):
            _write(os.path.join(PLVR_DIR, "cur_b.csv"), b)
    except DownloadError:
        pass
    done += 1
    say(done, total_steps, "整理資料 …")

    book, n = rebuild_from_cache(today=today)
    say(total_steps, total_steps, "完成：%d 筆交易" % n)
    return book, n


def load_cached_transactions():
    txs = []
    if not os.path.isdir(PLVR_DIR):
        return txs
    for name in sorted(os.listdir(PLVR_DIR)):
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(PLVR_DIR, name), "rb") as f:
            text = f.read().decode("utf-8-sig", "replace")
        if text.strip():
            txs.extend(prices.parse_csv_text(text))     # 由表頭自動分辨買賣檔與預售屋檔
    return prices.dedupe(txs)


def latest_download_date():
    """最近一次下載本期檔的日期（顯示為「某日下載」）。"""
    cur = os.path.join(PLVR_DIR, "cur.csv")
    if os.path.exists(cur):
        return datetime.date.fromtimestamp(os.path.getmtime(cur)).isoformat()
    return datetime.date.today().isoformat()


RELEASE_DAYS = (1, 11, 21)   # 內政部每月 1、11、21 日發布新一期實價登錄


def last_release(today=None):
    """今天以前（含今天）最近一次發布日。"""
    today = today or datetime.date.today()
    for day in reversed(RELEASE_DAYS):
        if today.day >= day:
            return today.replace(day=day)
    prev = today.replace(day=1) - datetime.timedelta(days=1)
    return prev.replace(day=RELEASE_DAYS[-1])


def next_release(today=None):
    """今天以後（不含今天）下一次發布日。"""
    today = today or datetime.date.today()
    for day in RELEASE_DAYS:
        if today.day < day:
            return today.replace(day=day)
    nxt = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt.replace(day=RELEASE_DAYS[0])


def has_live_cache():
    """之前是否下載過逐筆資料（自動更新只做「補抓新的一期」，第一次的完整下載要使用者自己按）。"""
    return os.path.exists(os.path.join(PLVR_DIR, "cur.csv"))


def needs_update(today=None):
    """手上的資料是否比最近一次發布還舊。"""
    if not has_live_cache():
        return False
    cur = os.path.join(PLVR_DIR, "cur.csv")
    got = datetime.date.fromtimestamp(os.path.getmtime(cur))
    return got < last_release(today)


def rebuild_from_cache(today=None):
    today = today or datetime.date.today()
    txs = load_cached_transactions()
    if not txs:
        raise DownloadError("快取中沒有可用的交易資料。")
    names = [d["name"] for d in load_districts()]
    raw = prices.build_book(
        txs, names, as_of=latest_download_date(), source="live",
        note="內政部不動產交易實價查詢服務網開放資料，由本程式下載彙整。",
        today_ym=today.strftime("%Y-%m"))
    prices.save_book(raw)
    prices.save_transactions(txs)
    return prices.PriceBook(raw), len(txs)
