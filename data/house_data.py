"""
善化區房屋資料 — 深度追蹤591、永慶、信義等平台
"""
import webbrowser
import json
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 自行維護物件資料庫（可手動更新/由cron更新）
# ============================================================
SHANHUA_PROPERTIES = [
    {
        "id": "sh_001", "name": "善化中山路透店",
        "type": "透店", "address": "善化區中山路",
        "price": 2280, "ping": 45, "price_per_ping": 50.7,
        "rooms": "4房2廳3衛", "year": 1995, "floor": "3F",
        "source": "永慶房屋", "source_url": "https://www.yungching.com.tw/",
        "note": "正中山路商圈，人潮車流大，1F可作店面，2-3F自住",
        "analysis": "正中山路是善化最精華路段，近善化火車站、市場，適合飲料店/餐飲。總價較高但地段無可取代。深綠線捷運未來設站將再推升價值。",
        "score": 8.5, "recommend": True,
    },
    {
        "id": "sh_002", "name": "善化光復路店面透天",
        "type": "透店", "address": "善化區光復路",
        "price": 1880, "ping": 38, "price_per_ping": 49.5,
        "rooms": "3房2廳2衛", "year": 2002, "floor": "3F",
        "source": "信義房屋", "source_url": "https://www.sinyi.com.tw/",
        "note": "光復路商圈，近全聯、寶雅",
        "analysis": "次級商業區，總價較中山路低約400萬。光復路生活機能成熟，周邊停車較方便。適合預算有限但想兼顧店面效益的買家。",
        "score": 7.8, "recommend": True,
    },
    {
        "id": "sh_003", "name": "善化建國路新透天",
        "type": "透天", "address": "善化區建國路",
        "price": 1580, "ping": 42, "price_per_ping": 37.6,
        "rooms": "4房3廳3衛", "year": 2024, "floor": "4F",
        "source": "591房屋", "source_url": "https://www.591.com.tw/",
        "note": "新成屋，近善化糖廠園區",
        "analysis": "新成屋不用整理。建國路為新興住宅區，寧靜宜居。近深綠線規劃路線，未來增值潛力大。純住宅無店面效益，適合自住。",
        "score": 7.5, "recommend": True,
    },
    {
        "id": "sh_004", "name": "南科LM特區透天",
        "type": "透天", "address": "善化區LM特區",
        "price": 1980, "ping": 50, "price_per_ping": 39.6,
        "rooms": "5房2廳4衛", "year": 2023, "floor": "4F",
        "source": "台灣房屋", "source_url": "https://www.twhg.com.tw/",
        "note": "LM特區寧靜住宅區，近南科",
        "analysis": "LM特區為南科員工首選住宅區，大坪數適合家庭。距南科車程5分鐘，出租需求強。但非店面產品，純自住/投資出租。",
        "score": 8.0, "recommend": True,
    },
    {
        "id": "sh_005", "name": "善化中正路透店",
        "type": "透店", "address": "善化區中正路",
        "price": 1680, "ping": 35, "price_per_ping": 48.0,
        "rooms": "3房2廳2衛", "year": 1998, "floor": "3F",
        "source": "591房屋", "source_url": "https://www.591.com.tw/",
        "note": "中正路商圈，近善化市場",
        "analysis": "中正路為傳統商圈，店面效益穩定。總價1680萬是少見2000萬以下的透店產品，預算有限者值得考慮。屋齡較高需注意屋況。",
        "score": 7.2, "recommend": True,
    },
    {
        "id": "sh_006", "name": "善化中山路大地坪透店",
        "type": "透店", "address": "善化區中山路近車站",
        "price": 3680, "ping": 72, "price_per_ping": 51.1,
        "rooms": "6房3廳4衛", "year": 1990, "floor": "4F",
        "source": "永慶房屋", "source_url": "https://www.yungching.com.tw/",
        "note": "大地坪，近火車站，適合作店面+出租",
        "analysis": "稀有大地坪產品，1F店面+樓上可分租。中山路車站商圈核心，未來深綠線善化站預定地附近。總價高但土地價值高，具長期置產價值。",
        "score": 8.8, "recommend": True,
    },
]

# ============================================================
# 591 快速搜尋連結
# ============================================================
SEARCH_URLS = {
    "591 善化透天": "https://sale.591.com.tw/?regionid=6&sectionid=32&kind=1&pattern=4&price=1000_3000",
    "591 善化店面": "https://store.591.com.tw/?regionid=6&sectionid=32&pattern=4",
    "永慶善化透天": "https://www.yungching.com.tw/region/tainan/shanhua-house/sale/house?pattern=4",
    "信義善化房屋": "https://www.sinyi.com.tw/region/TO/50071000/list/",
    "台灣房屋善化": "https://www.twhg.com.tw/search?city=%E5%8F%B0%E5%8D%97%E5%B8%82&area=%E5%96%84%E5%8C%96%E5%8D%80",
}


def open_search(name):
    """在瀏覽器中開啟指定搜尋"""
    url = SEARCH_URLS.get(name)
    if url:
        webbrowser.open(url)
        return True
    return False
