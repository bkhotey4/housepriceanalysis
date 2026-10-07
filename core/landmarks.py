"""知名地標的立體小模型。

每個模型用幾個簡單的幾何體（方塊、斜屋頂、柱體、圓錐）拼出「一眼認得出是哪一類建築」的造型，
是示意用的圖案，不是建築物的精確模型。座標：x 向東、y 向北、z 向上，模型大約落在 ±1 的範圍內。

一個面 = (頂點清單 [(x, y, z), ...], 顏色)。頂點一律從外面看是逆時針，繪製時可以剔除背面。
"""
import math

from .geo import load_json

STONE, BRICK, RED, WHITE = "#b9b2a6", "#a8553a", "#c8473a", "#f4f1ea"
TILE_ORANGE, TILE_YELLOW, TILE_GRAY = "#d98a3d", "#e3ad3b", "#6f757b"
GREEN, DARK_GREEN, WATER, GLASS = "#5f9d57", "#3f8048", "#4f9bd6", "#cfdbe4"


def box(x0, y0, z0, x1, y1, z1, color, top=None):
    top = top or color
    return [
        ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], top),
        ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], color),      # 南
        ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], color),      # 東
        ([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], color),      # 北
        ([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], color),      # 西
    ]


def roof(x0, y0, x1, y1, z0, tx0, ty0, tx1, ty1, z1, color, top=None):
    """四坡屋頂：底部矩形 (x0,y0)-(x1,y1) 收到頂部矩形 (tx0,ty0)-(tx1,ty1)；頂部可以退化成一條屋脊或一個尖頂。"""
    faces = [
        ([(x0, y0, z0), (x1, y0, z0), (tx1, ty0, z1), (tx0, ty0, z1)], color),
        ([(x1, y0, z0), (x1, y1, z0), (tx1, ty1, z1), (tx1, ty0, z1)], color),
        ([(x1, y1, z0), (x0, y1, z0), (tx0, ty1, z1), (tx1, ty1, z1)], color),
        ([(x0, y1, z0), (x0, y0, z0), (tx0, ty0, z1), (tx0, ty1, z1)], color),
    ]
    if tx1 - tx0 > 1e-6 and ty1 - ty0 > 1e-6:
        faces.append(([(tx0, ty0, z1), (tx1, ty0, z1), (tx1, ty1, z1), (tx0, ty1, z1)], top or color))
    return faces


def prism(cx, cy, r0, z0, r1, z1, n, color, top=None, squash=1.0, phase=0.0):
    """n 邊形柱體；r1 < r0 是圓台，r1 = 0 是圓錐。squash 把 y 方向壓扁（橢圓）。"""
    faces = []
    ring0 = [(cx + r0 * math.cos(phase + 2 * math.pi * k / n), cy + r0 * squash * math.sin(phase + 2 * math.pi * k / n), z0)
             for k in range(n)]
    ring1 = [(cx + r1 * math.cos(phase + 2 * math.pi * k / n), cy + r1 * squash * math.sin(phase + 2 * math.pi * k / n), z1)
             for k in range(n)]
    for k in range(n):
        k2 = (k + 1) % n
        if r1 > 1e-6:
            faces.append(([ring0[k], ring0[k2], ring1[k2], ring1[k]], color))
        else:
            faces.append(([ring0[k], ring0[k2], (cx, cy, z1)], color))
    if r1 > 1e-6:
        faces.append((ring1, top or color))
    return faces


def flat(points, z, color):
    """貼在高度 z 的平面多邊形（頂點逆時針）。"""
    return [([(x, y, z) for x, y in points], color)]


def disc(cx, cy, r, z, n, color, squash=1.0):
    return flat([(cx + r * math.cos(2 * math.pi * k / n), cy + r * squash * math.sin(2 * math.pi * k / n)) for k in range(n)],
                z, color)


# ------------------------------------------------------------------ 各類地標
def pavilion(roof_color=TILE_ORANGE, wall=RED):
    """兩層樓閣（歇山式重簷）。"""
    f = box(-1.05, -0.75, 0, 1.05, 0.75, 0.22, STONE)
    f += box(-0.78, -0.5, 0.22, 0.78, 0.5, 0.78, wall)
    f += roof(-1.0, -0.72, 1.0, 0.72, 0.78, -0.56, -0.34, 0.56, 0.34, 1.12, roof_color)
    f += box(-0.5, -0.3, 1.12, 0.5, 0.3, 1.48, wall)
    f += roof(-0.78, -0.52, 0.78, 0.52, 1.48, -0.42, 0.0, 0.42, 0.0, 1.95, roof_color)
    return f


def temple(roof_color=TILE_YELLOW, wall="#b23a2e"):
    """廟宇：前有三川殿、後有正殿。"""
    f = box(-1.1, -0.95, 0, 1.1, 0.8, 0.12, STONE)
    f += box(-0.6, -0.85, 0.12, 0.6, -0.5, 0.5, wall)
    f += roof(-0.8, -0.98, 0.8, -0.38, 0.5, -0.5, -0.68, 0.5, -0.68, 0.82, roof_color)
    f += box(-0.85, -0.2, 0.12, 0.85, 0.6, 0.75, wall)
    f += roof(-1.08, -0.38, 1.08, 0.78, 0.75, -0.6, 0.2, 0.6, 0.2, 1.3, roof_color)
    return f


def fort():
    """城堡遺址：紅磚臺基上的白色瞭望塔。"""
    f = box(-1.0, -1.0, 0, 1.0, 1.0, 0.42, BRICK, top="#b9906f")
    f += box(-0.68, -0.68, 0.42, 0.68, 0.68, 0.78, BRICK, top="#c4a07f")
    f += box(-0.5, -0.2, 0.78, 0.0, 0.3, 1.05, "#e8e2d4")
    f += roof(-0.56, -0.26, 0.06, 0.36, 1.05, -0.25, 0.05, -0.25, 0.05, 1.3, RED)
    f += prism(0.32, 0.1, 0.2, 0.78, 0.17, 1.85, 8, WHITE)
    f += prism(0.32, 0.1, 0.28, 1.85, 0.0, 2.3, 8, RED)
    return f


def bastion():
    """西式砲臺：護城河、方形紅磚城牆、四角稜堡。"""
    f = flat([(-1.25, -1.25), (1.25, -1.25), (1.25, 1.25), (-1.25, 1.25)], 0.02, WATER)
    f += box(-0.95, -0.95, 0.02, 0.95, 0.95, 0.32, BRICK, top="#8f4a35")
    f += flat([(-0.72, -0.72), (0.72, -0.72), (0.72, 0.72), (-0.72, 0.72)], 0.33, GREEN)
    for sx in (-1, 1):
        for sy in (-1, 1):
            f += prism(sx * 0.95, sy * 0.95, 0.26, 0.02, 0.26, 0.4, 4, BRICK, top="#8f4a35")
    f += box(-0.16, -1.08, 0.02, 0.16, -0.95, 0.5, "#c9b79a")
    return f


def museum():
    """西式博物館：長形主體、中央山牆門廊與圓頂。"""
    f = box(-1.15, -0.5, 0, 1.15, 0.5, 0.16, "#d2ccbd")
    f += box(-1.05, -0.4, 0.16, 1.05, 0.4, 0.85, "#f1ede2", top="#c9c4b6")
    f += box(-0.36, -0.64, 0.16, 0.36, -0.4, 0.8, "#e7e1d1")
    f += roof(-0.4, -0.66, 0.4, -0.36, 0.8, 0.0, -0.66, 0.0, -0.36, 1.05, "#c9c4b6")
    f += prism(0, 0, 0.34, 0.85, 0.34, 1.1, 10, "#e7e1d1")
    f += prism(0, 0, 0.36, 1.1, 0.24, 1.38, 10, "#8fa6b2")
    f += prism(0, 0, 0.24, 1.38, 0.0, 1.62, 10, "#8fa6b2")
    return f


def station():
    """老火車站：白色兩層站房、中央較高的門廳與雨庇。"""
    f = box(-1.05, -0.4, 0, 1.05, 0.4, 0.7, WHITE, top=TILE_GRAY)
    f += box(-0.42, -0.5, 0, 0.42, 0.45, 0.95, WHITE, top=TILE_GRAY)
    f += box(-0.55, -0.78, 0.3, 0.55, -0.5, 0.37, "#b7bbc0")
    f += flat([(-1.3, 0.5), (1.3, 0.5), (1.3, 0.78), (-1.3, 0.78)], 0.03, "#7b7f85")
    return f


def hsr():
    """高鐵車站：長形玻璃站體與弧形屋頂。"""
    f = flat([(-1.5, -0.12), (1.5, -0.12), (1.5, 0.12), (-1.5, 0.12)], 0.36, "#9aa1a8")
    f += box(-1.15, -0.42, 0, 1.15, 0.42, 0.5, GLASS)
    f += box(-1.17, -0.44, 0.2, 1.17, 0.44, 0.27, "#f08a24")
    f += roof(-1.28, -0.55, 1.28, 0.55, 0.5, -1.28, -0.18, 1.28, 0.18, 0.78, "#9fb0bd", top="#b9c6d0")
    return f


def campus():
    """大學校園：紅磚校舍與大榕樹。"""
    f = box(-1.0, -0.32, 0, 0.15, 0.32, 0.55, "#b5533c")
    f += roof(-1.06, -0.38, 0.21, 0.38, 0.55, -0.8, 0.0, -0.05, 0.0, 0.85, TILE_GRAY)
    f += prism(0.62, -0.05, 0.09, 0, 0.07, 0.5, 6, "#7a5a3a")
    f += prism(0.62, -0.05, 0.42, 0.42, 0.56, 0.75, 8, DARK_GREEN)
    f += prism(0.62, -0.05, 0.56, 0.75, 0.3, 1.12, 8, GREEN, top="#74b06a")
    return f


def artmuseum():
    """現代美術館：錯落堆疊的白色方盒與五角形大遮棚。"""
    f = box(-0.95, -0.7, 0, 0.9, 0.7, 0.34, "#f3f3f0")
    f += box(-0.6, -0.5, 0.34, 0.75, 0.6, 0.68, "#fafaf8")
    f += box(-0.35, -0.3, 0.68, 0.5, 0.4, 0.98, "#f3f3f0")
    f += prism(0.05, 0.0, 1.15, 1.2, 1.15, 1.27, 5, "#c2c9d0", top="#d5dbe1", phase=math.pi / 2)
    return f


def store():
    """老百貨公司：米色方正樓房、轉角塔樓。"""
    f = box(-0.62, -0.62, 0, 0.62, 0.62, 1.25, "#d8c9a8", top="#bfae8a")
    f += box(-0.66, -0.66, 0.26, 0.66, 0.66, 0.33, "#b39f78")
    f += box(-0.62, -0.62, 1.25, -0.12, -0.12, 1.68, "#d8c9a8", top="#bfae8a")
    f += box(0.2, 0.2, 1.25, 0.45, 0.45, 1.4, "#c0623a")
    return f


def saltmountain():
    f = prism(0, 0, 1.05, 0, 0.3, 1.05, 10, "#f7f7f4", top="#ffffff")
    f += prism(0, 0, 0.3, 1.05, 0.0, 1.22, 10, "#ffffff")
    return f


def lighthouse():
    f = box(-0.5, -0.3, 0, -0.05, 0.3, 0.35, WHITE, top=RED)
    f += prism(0.25, 0, 0.24, 0, 0.15, 1.7, 8, WHITE)
    f += prism(0.25, 0, 0.19, 1.7, 0.19, 1.92, 8, "#2b2f33")
    f += prism(0.25, 0, 0.22, 1.92, 0.0, 2.15, 8, RED)
    return f


def reservoir():
    """水庫：湖面、土石壩與取水塔。"""
    f = disc(0, 0.1, 1.1, 0.03, 10, WATER, squash=0.75)
    f += roof(-0.95, -0.95, 0.95, -0.6, 0, -0.95, -0.8, 0.95, -0.74, 0.3, "#8a9a6b", top="#a9b48c")
    f += prism(0.45, -0.35, 0.1, 0.03, 0.1, 0.55, 6, "#d9d4c7")
    f += prism(0.45, -0.35, 0.15, 0.55, 0.0, 0.75, 6, RED)
    f += prism(-0.5, 0.25, 0.2, 0.03, 0.0, 0.3, 6, DARK_GREEN)
    return f


def lake():
    """埤塘風景區：湖面、小島與涼亭。"""
    f = disc(0, 0, 1.1, 0.03, 10, WATER, squash=0.7)
    f += disc(0.25, 0.05, 0.38, 0.06, 8, GREEN, squash=0.8)
    f += box(0.1, -0.08, 0.06, 0.4, 0.18, 0.3, RED)
    f += roof(0.02, -0.16, 0.48, 0.26, 0.3, 0.25, 0.05, 0.25, 0.05, 0.58, TILE_ORANGE)
    f += box(-0.6, -0.04, 0.05, 0.02, 0.04, 0.1, "#c0623a")
    return f


def hotspring():
    """山區溫泉：山丘、泥漿溫泉池與蒸氣。"""
    f = prism(-0.5, 0.35, 0.75, 0, 0.0, 1.0, 7, "#5f8f5a")
    f += prism(0.55, 0.4, 0.6, 0, 0.0, 0.75, 7, "#6c9c64")
    f += disc(0.05, -0.4, 0.5, 0.04, 8, "#9aa4a8", squash=0.6)
    for dx, z in ((-0.14, 0.22), (0.1, 0.42), (-0.03, 0.66)):          # 蒸氣：往上飄的小白點
        f += prism(0.05 + dx, -0.4, 0.1, z, 0.0, z + 0.2, 4, "#ffffff")
    return f


def mangrove():
    """紅樹林水道：綠色隧道與小船。"""
    f = flat([(-1.2, -0.2), (1.2, -0.2), (1.2, 0.2), (-1.2, 0.2)], 0.03, WATER)
    for k in range(5):
        x = -1.0 + k * 0.5
        f += prism(x, 0.42, 0.3, 0.05, 0.14, 0.62, 6, DARK_GREEN, top=GREEN)
        f += prism(x + 0.25, -0.42, 0.3, 0.05, 0.14, 0.58, 6, GREEN, top="#74b06a")
    f += box(-0.2, -0.07, 0.04, 0.2, 0.07, 0.13, "#8a5a36")
    return f


def cityhall():
    """市政中心：寬闊的辦公大樓與中央塔樓。"""
    f = box(-1.05, -0.36, 0, 1.05, 0.36, 0.85, "#cfd6dc", top="#aeb7bf")
    f += box(-0.32, -0.44, 0, 0.32, 0.44, 1.25, "#e6ebef", top="#aeb7bf")
    f += box(-0.6, -0.7, 0, 0.6, -0.44, 0.08, STONE)
    return f


def fab():
    """科學園區的晶圓廠：大型廠房、屋頂機房與排氣塔。"""
    f = box(-1.05, -0.62, 0, 0.42, 0.62, 0.55, "#dde3e8", top="#c1cad2")
    f += box(0.48, -0.5, 0, 1.05, 0.3, 0.38, "#cfd8df", top="#b4bec7")
    f += box(-0.8, -0.35, 0.55, -0.2, 0.35, 0.68, "#9aa5ae")
    f += prism(0.0, 0.3, 0.07, 0.55, 0.07, 1.0, 6, "#b9c1c8")
    f += prism(0.2, 0.3, 0.07, 0.55, 0.07, 0.9, 6, "#b9c1c8")
    return f


def saltfield():
    """瓦盤鹽田：格狀鹽田與小鹽堆。"""
    f = flat([(-1.1, -0.8), (1.1, -0.8), (1.1, 0.8), (-1.1, 0.8)], 0.02, "#c9b99a")
    for i in range(3):
        for j in range(2):
            x0, y0 = -1.0 + i * 0.7, -0.7 + j * 0.75
            f += flat([(x0, y0), (x0 + 0.6, y0), (x0 + 0.6, y0 + 0.62), (x0, y0 + 0.62)], 0.04, "#e6dfd0" if (i + j) % 2 else "#d9e4ea")
            f += prism(x0 + 0.3, y0 + 0.31, 0.16, 0.04, 0.0, 0.28, 6, "#ffffff")
    return f


def farm():
    """休閒農場：草原、紅色穀倉與筒倉。"""
    f = disc(0, 0, 1.1, 0.02, 10, "#8cc276", squash=0.75)
    f += box(-0.55, -0.25, 0.02, 0.15, 0.25, 0.45, "#c0453a")
    f += roof(-0.6, -0.3, 0.2, 0.3, 0.45, -0.6, 0.0, 0.2, 0.0, 0.75, WHITE)
    f += prism(0.45, 0.1, 0.15, 0.02, 0.15, 0.6, 8, "#d9dde1")
    f += prism(0.45, 0.1, 0.16, 0.6, 0.0, 0.78, 8, "#9aa5ae")
    return f


def lotus():
    """蓮花：荷葉與花朵。"""
    f = disc(0, 0, 1.0, 0.03, 10, "#4f9a5c", squash=0.75)
    f += disc(-0.45, 0.25, 0.4, 0.05, 8, "#62ad6c", squash=0.75)
    f += prism(0.2, -0.05, 0.42, 0.06, 0.6, 0.38, 8, "#f29ac0")
    f += prism(0.2, -0.05, 0.3, 0.2, 0.12, 0.62, 8, "#f7b6d2", top="#f5d76e")
    return f


def badlands():
    """惡地地形：光禿的泥岩山脊。"""
    f = prism(-0.45, 0.2, 0.7, 0, 0.0, 0.95, 5, "#b9b2a0")
    f += prism(0.4, 0.3, 0.55, 0, 0.0, 0.7, 5, "#c7c0ae", phase=0.6)
    f += prism(0.1, -0.4, 0.5, 0, 0.0, 0.55, 5, "#aaa392", phase=1.1)
    f += prism(-0.75, -0.45, 0.35, 0, 0.0, 0.4, 5, "#c7c0ae", phase=0.3)
    return f


# ------------------------------------------------------------------ 全台各縣市的招牌地標（和臺南的鹽山、稜堡一樣，一眼認得出是哪裡）
def _arc_xz(cx, cy, r, z0, k0, k1, n, half_w, thick, color, depth=0.06):
    """在 xz 平面上，用 n 段小方塊拼一道半圓拱（k0~k1 是角度範圍，弧度）。"""
    f = []
    for k in range(n):
        a = k0 + (k1 - k0) * (k + 0.5) / n
        x, z = cx + r * math.cos(a), z0 + r * math.sin(a)
        f += box(x - half_w, cy - depth, z - thick, x + half_w, cy + depth, z + thick, color)
    return f


def _fit_height(f, top=2.35):
    """摩天大樓整體等比例壓到模型高度上限（2.4）以內。"""
    k = top / max(p[2] for pts, _c in f for p in pts)
    return [([(x, y, z * k) for x, y, z in pts], c) for pts, c in f]


def taipei101():
    """台北101：裙樓上 8 節往上張開的「竹節」與尖塔。"""
    f = box(-0.8, -0.65, 0, 0.8, 0.65, 0.3, "#9fb4c3", top="#8aa0af")
    f += prism(0, 0, 0.42, 0.3, 0.32, 0.9, 4, "#5f8fa8", phase=math.pi / 4)
    z = 0.9
    for _ in range(8):
        f += prism(0, 0, 0.26, z, 0.36, z + 0.22, 4, "#6f9fb8", top="#4f7f98", phase=math.pi / 4)
        z += 0.22
    f += prism(0, 0, 0.2, z, 0.14, z + 0.22, 4, "#4f7f98", phase=math.pi / 4)
    f += prism(0, 0, 0.04, z + 0.22, 0.0, z + 0.62, 4, "#d9e1e6")
    return _fit_height(f)


def tower85():
    """高雄 85 大樓：兩支塔腳在半空會合成「高」字形，中央往上一座塔樓與天線。"""
    c, top = "#8faac0", "#6f8aa0"
    f = box(-1.0, -0.4, 0, -0.35, 0.4, 1.35, c, top=top)
    f += box(0.35, -0.4, 0, 1.0, 0.4, 1.35, c, top=top)
    f += box(-1.0, -0.4, 1.35, 1.0, 0.4, 1.7, c, top=top)
    f += box(-0.42, -0.34, 1.7, 0.42, 0.34, 2.75, "#9fbad0", top=top)
    f += box(-0.25, -0.22, 2.75, 0.25, 0.22, 2.95, top)
    f += prism(0, 0, 0.04, 2.95, 0.0, 3.4, 4, "#d9e1e6")
    return _fit_height(f)


def memorial():
    """中正紀念堂：三層白色臺基、白牆、寶藍色八角屋頂。"""
    blue = "#2f5fa8"
    f = box(-1.1, -1.1, 0, 1.1, 1.1, 0.18, WHITE, top="#e9e6dd")
    f += box(-0.9, -0.9, 0.18, 0.9, 0.9, 0.36, WHITE, top="#e9e6dd")
    f += box(-0.6, -0.6, 0.36, 0.6, 0.6, 1.05, WHITE)
    f += prism(0, 0, 0.92, 1.05, 0.55, 1.3, 8, blue, phase=math.pi / 8)
    f += prism(0, 0, 0.55, 1.3, 0.55, 1.45, 8, WHITE, phase=math.pi / 8)
    f += prism(0, 0, 0.72, 1.45, 0.0, 1.95, 8, blue, phase=math.pi / 8)
    f += box(-0.5, -1.35, 0, 0.5, -1.1, 0.06, "#e9e6dd")          # 正面大階梯
    return f


def bridge():
    """跨海大橋：海面上一長段橋面、橋墩與一道道拱。"""
    f = flat([(-1.5, -0.45), (1.5, -0.45), (1.5, 0.45), (-1.5, 0.45)], 0.01, WATER)
    f += box(-1.5, -0.12, 0.42, 1.5, 0.12, 0.5, "#d7d9dc", top="#9aa0a7")
    for x in (-1.1, -0.37, 0.37, 1.1):
        f += box(x - 0.06, -0.1, 0.01, x + 0.06, 0.1, 0.42, "#c9cdd2")
    for x in (-0.73, 0.0, 0.73):
        f += _arc_xz(x, -0.13, 0.34, 0.08, 0.0, math.pi, 12, 0.05, 0.035, WHITE, depth=0.05)
        f += _arc_xz(x, 0.13, 0.34, 0.08, 0.0, math.pi, 12, 0.05, 0.035, WHITE, depth=0.05)
    return f


def trussbridge():
    """西螺大橋：紅色鋼桁架長橋。"""
    red = "#c8352c"
    f = flat([(-1.5, -0.4), (1.5, -0.4), (1.5, 0.4), (-1.5, 0.4)], 0.01, "#9cb7a0")
    f += box(-1.5, -0.2, 0.2, 1.5, 0.2, 0.26, "#8b9097")
    for y in (-0.2, 0.2):
        f += box(-1.5, y - 0.03, 0.62, 1.5, y + 0.03, 0.68, red)
        for k in range(7):
            x = -1.5 + k * 0.5
            f += box(x - 0.03, y - 0.03, 0.26, x + 0.03, y + 0.03, 0.62, red)
            if k < 6:          # 斜桿：用一串小方塊拼成
                for t in range(4):
                    xx, zz = x + 0.07 + t * 0.12, 0.3 + t * 0.1
                    f += box(xx - 0.04, y - 0.025, zz, xx + 0.04, y + 0.025, zz + 0.07, red)
    for x in (-1.0, 0.0, 1.0):
        f += box(x - 0.08, -0.18, 0.01, x + 0.08, 0.18, 0.2, "#c9cdd2")
    return f


def archgate():
    """牌樓：兩根柱子撐起的門楣與屋頂（太魯閣口的牌樓），後面是山。"""
    f = prism(-0.2, 0.55, 0.8, 0, 0.0, 1.35, 6, "#5f8f5a")
    f += prism(0.7, 0.75, 0.6, 0, 0.0, 1.0, 6, "#6c9c64")
    for x in (-0.75, 0.75):
        f += box(x - 0.1, -0.1, 0, x + 0.1, 0.1, 0.95, "#c8473a")
    f += box(-0.95, -0.12, 0.95, 0.95, 0.12, 1.15, "#c8473a")
    f += roof(-1.15, -0.32, 1.15, 0.32, 1.15, -0.7, 0.0, 0.7, 0.0, 1.45, TILE_YELLOW)
    return f


def buddha():
    """大佛：蓮花座上的坐佛。"""
    gold, base = "#c9a24a", "#b6ad9d"
    f = box(-1.0, -1.0, 0, 1.0, 1.0, 0.18, base, top="#cfc7b8")
    f += prism(0, 0, 0.85, 0.18, 0.95, 0.42, 12, "#d98aa8")                 # 蓮花座
    f += prism(0, 0, 0.82, 0.42, 0.55, 0.85, 10, gold, squash=0.8)          # 盤坐的腿
    f += prism(0, 0.05, 0.52, 0.85, 0.46, 1.45, 10, gold, squash=0.75)      # 身體
    f += prism(0, 0.05, 0.46, 1.45, 0.14, 1.6, 10, gold, squash=0.75)       # 肩
    f += prism(0, 0.05, 0.14, 1.6, 0.25, 1.78, 10, gold)                    # 頭
    f += prism(0, 0.05, 0.25, 1.78, 0.17, 1.98, 10, gold)
    f += prism(0, 0.05, 0.12, 1.98, 0.0, 2.15, 10, "#a8853a")               # 肉髻
    return f


def _pagoda(cx, cy, levels, color, roof_color):
    f = []
    z, r = 0.05, 0.3
    for i in range(levels):
        f += prism(cx, cy, r * 0.75, z, r * 0.72, z + 0.18, 8, color, phase=math.pi / 8)
        f += prism(cx, cy, r * 1.05, z + 0.18, r * 0.7, z + 0.26, 8, roof_color, phase=math.pi / 8)
        z += 0.26
        r *= 0.92
    f += prism(cx, cy, 0.08, z, 0.0, z + 0.25, 8, "#c9a24a")
    return f


def twinpagoda():
    """蓮池潭龍虎塔：湖上兩座七層塔與九曲橋。"""
    f = disc(0, 0, 1.2, 0.02, 12, WATER, squash=0.7)
    f += _pagoda(-0.42, 0.1, 7, "#f2d45c", "#c8473a")
    f += _pagoda(0.42, 0.1, 7, "#f2d45c", "#c8473a")
    for k in range(5):
        x0 = -0.6 + k * 0.24
        y0 = -0.75 if k % 2 == 0 else -0.6
        f += box(x0, y0, 0.02, x0 + 0.24, y0 + 0.12, 0.08, "#e4c56a")
    return f


def opera():
    """台中國家歌劇院：白色方正量體上一個個像洞穴的弧形開口。"""
    f = box(-1.0, -0.65, 0, 1.0, 0.65, 1.05, "#f3f3ef", top="#e6e6e0")
    for x in (-0.6, 0.0, 0.6):
        f += prism(x, -0.66, 0.24, 0.12, 0.24, 0.85, 10, "#5b6b7a", squash=0.08)
    for x in (-0.3, 0.3):
        f += prism(x, -0.66, 0.18, 0.55, 0.18, 0.98, 10, "#7f8d99", squash=0.08)
    for y, z0, z1 in ((-0.35, 0.12, 0.8), (0.3, 0.12, 0.8), (0.0, 0.55, 0.98)):   # 側面也有開口
        f += box(1.0, y - 0.18, z0, 1.02, y + 0.18, z1, "#5b6b7a")
        f += box(-1.02, y - 0.18, z0, -1.0, y + 0.18, z1, "#5b6b7a")
    return f


def mtntrain():
    """阿里山森林鐵路：山坡上的紅色小火車與月台。"""
    f = prism(0.1, 0.45, 0.9, 0, 0.0, 1.2, 7, "#3f8048")
    f += prism(-0.75, 0.75, 0.55, 0, 0.0, 0.8, 7, "#4f9a5c")
    f += flat([(-1.3, -0.5), (1.3, -0.5), (1.3, -0.32), (-1.3, -0.32)], 0.02, "#6d6a66")
    for k in range(3):
        x0 = -1.0 + k * 0.62
        f += box(x0, -0.52, 0.04, x0 + 0.55, -0.3, 0.32, "#b8322a", top="#e8e2d4")
    f += box(0.95, -0.25, 0, 1.3, 0.05, 0.4, "#c9a27a", top="#8a5a36")
    return f


def tulou():
    """客家圓樓：圓形的環狀樓房圍出中庭。"""
    f = []
    n = 16
    for k in range(n):
        a = 2 * math.pi * k / n
        x, y = 0.82 * math.cos(a), 0.82 * math.sin(a)
        f += box(x - 0.2, y - 0.2, 0, x + 0.2, y + 0.2, 0.55, "#d8c3a0", top="#7d5a3c")
    f += disc(0, 0, 0.6, 0.02, 12, "#b9a98c")
    f += box(-0.15, -0.15, 0.02, 0.15, 0.15, 0.3, "#c8473a")
    return f


def chapel():
    """路思義教堂：兩片像帳篷一樣彎曲的黃色琉璃瓦屋面，頂上留一道天窗。"""
    yel = "#e0b23c"
    f = box(-0.7, -0.9, 0, 0.7, 0.9, 0.06, "#c9c3b5")
    f += roof(-0.75, -0.9, -0.05, 0.9, 0.06, -0.12, -0.55, -0.05, 0.55, 1.8, yel)
    f += roof(0.05, -0.9, 0.75, 0.9, 0.06, 0.05, -0.55, 0.12, 0.55, 1.8, "#d4a530")
    return f


def roundhouse():
    """彰化扇形車庫：扇形排開的車庫與中央轉車台。"""
    f = disc(0, -0.55, 0.42, 0.02, 12, "#8b9097")
    for k in range(7):
        a = math.pi * (0.12 + 0.76 * k / 6)
        x, y = 0.95 * math.cos(a), -0.55 + 0.95 * math.sin(a)
        f += prism(x, y, 0.2, 0, 0.2, 0.42, 4, "#d9c9a5", top="#6f757b", phase=a + math.pi / 4)
    f += box(-0.32, -0.6, 0.02, 0.32, -0.5, 0.1, "#2b2f33")
    return f


def heartweir():
    """七美雙心石滬：海邊兩顆疊在一起的愛心形石牆。"""
    f = flat([(-1.4, -1.0), (1.4, -1.0), (1.4, 1.0), (-1.4, 1.0)], 0.01, WATER)
    stone = "#9b9284"
    for cx, sc in ((-0.25, 1.0), (0.6, 0.6)):
        for k in range(32):
            t = 2 * math.pi * k / 32
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            px, py = cx + x * 0.05 * sc, 0.1 + y * 0.05 * sc
            f += box(px - 0.04, py - 0.04, 0.01, px + 0.04, py + 0.04, 0.14, stone, top="#b8ae9e")
    return f


def stonevillage():
    """馬祖芹壁：山坡上的閩東石頭屋聚落。"""
    f = prism(0.0, 0.4, 1.0, 0, 0.0, 0.9, 7, "#6c9c64")
    for x, y, z in ((-0.7, -0.4, 0), (-0.15, -0.5, 0), (0.45, -0.35, 0), (-0.4, 0.1, 0.25), (0.2, 0.15, 0.3)):
        f += box(x - 0.2, y - 0.16, z, x + 0.2, y + 0.16, z + 0.32, "#a59a88", top="#7c7468")
        f += roof(x - 0.22, y - 0.18, x + 0.22, y + 0.18, z + 0.32, x - 0.22, y, x + 0.22, y, z + 0.45, "#7c6f63")
    return f


def airport():
    """國際機場：長形航廈、塔台與停在旁邊的飛機。"""
    f = box(-1.2, -0.3, 0, 0.6, 0.3, 0.38, GLASS, top="#9fb0bd")
    f += roof(-1.25, -0.35, 0.65, 0.35, 0.38, -1.25, -0.1, 0.65, -0.1, 0.5, "#b9c6d0")
    f += prism(0.95, 0.35, 0.08, 0, 0.08, 1.1, 6, "#d9dde1")
    f += prism(0.95, 0.35, 0.2, 1.1, 0.2, 1.3, 8, "#4f7f98")
    f += box(-0.4, -1.0, 0.1, 0.6, -0.88, 0.22, WHITE)                    # 機身
    f += box(0.0, -1.35, 0.15, 0.2, -0.53, 0.19, WHITE)                    # 機翼
    f += box(-0.4, -0.97, 0.22, -0.3, -0.91, 0.42, "#c8473a")             # 尾翼
    return f


def lakepagoda():
    """日月潭：山間湖面、湖中小島，岸邊山頭上的寶塔。"""
    f = disc(0, -0.1, 1.15, 0.02, 12, "#3f8fc8", squash=0.7)
    f += disc(0.15, -0.15, 0.16, 0.05, 8, GREEN)
    f += prism(-0.75, 0.75, 0.55, 0, 0.0, 0.85, 7, "#3f8048")
    f += prism(0.8, 0.7, 0.5, 0, 0.0, 0.7, 7, "#4f9a5c")
    z = 0.6
    for i in range(5):                  # 山頂的慈恩塔
        f += prism(-0.75, 0.62, 0.1 - i * 0.012, z, 0.09 - i * 0.012, z + 0.12, 8, "#f2e6c9")
        f += prism(-0.75, 0.62, 0.15 - i * 0.015, z + 0.12, 0.08 - i * 0.012, z + 0.17, 8, "#c8473a")
        z += 0.17
    return f


def palace():
    """宮殿式建築（故宮、莒光樓）：白色臺基、長形主殿與黃綠色屋頂。"""
    f = box(-1.2, -0.75, 0, 1.2, 0.75, 0.2, WHITE, top="#e9e6dd")
    f += box(-0.95, -0.45, 0.2, 0.95, 0.45, 0.75, "#efe9dc")
    f += roof(-1.12, -0.6, 1.12, 0.6, 0.75, -0.7, 0.0, 0.7, 0.0, 1.15, "#d9b23c")
    f += box(-0.35, -0.3, 0.75, 0.35, 0.3, 1.1, "#efe9dc")
    f += roof(-0.5, -0.42, 0.5, 0.42, 1.1, -0.2, 0.0, 0.2, 0.0, 1.45, "#3f8f6a")
    f += box(-0.4, -1.1, 0, 0.4, -0.75, 0.08, "#e9e6dd")
    return f


def citygate():
    """古城門：磚石城臺、拱門洞與上面的城樓。"""
    f = box(-1.0, -0.5, 0, 1.0, 0.5, 0.7, "#a8a091", top="#8f877a")
    f += box(-0.22, -0.52, 0, 0.22, -0.49, 0.45, "#3b3a37")
    f += box(-0.6, -0.3, 0.7, 0.6, 0.3, 1.05, "#c8473a")
    f += roof(-0.8, -0.48, 0.8, 0.48, 1.05, -0.45, 0.0, 0.45, 0.0, 1.4, TILE_GRAY)
    return f


def themepark():
    """主題樂園：摩天輪與城堡尖塔。"""
    f = disc(0, 0, 1.1, 0.02, 10, "#8cc276", squash=0.75)
    f += box(-0.95, -0.08, 0, -0.85, 0.08, 0.95, "#c9cdd2")
    f += box(-0.15, -0.08, 0, -0.05, 0.08, 0.95, "#c9cdd2")
    f += _arc_xz(-0.5, 0.0, 0.7, 1.0, 0.0, 2 * math.pi, 16, 0.05, 0.05, "#e05a8a")
    for k in range(8):
        a = 2 * math.pi * k / 8
        x, z = -0.5 + 0.7 * math.cos(a), 1.0 + 0.7 * math.sin(a)
        f += box(x - 0.08, -0.08, z - 0.12, x + 0.08, 0.08, z, "#f2c14e")
    f += prism(0.65, 0.1, 0.22, 0, 0.22, 0.75, 8, "#e9e1f2")
    f += prism(0.65, 0.1, 0.28, 0.75, 0.0, 1.25, 8, "#5b6fc4")
    return f


def forest():
    """森林遊樂區：高聳的柳杉林與空中步道。"""
    f = disc(0, 0, 1.1, 0.02, 10, "#6f9a5a", squash=0.8)
    for x, y, h in ((-0.7, 0.3, 1.5), (-0.25, 0.55, 1.75), (0.3, 0.4, 1.6), (0.75, 0.1, 1.4), (-0.5, -0.35, 1.3), (0.25, -0.3, 1.55)):
        f += prism(x, y, 0.05, 0.02, 0.05, 0.4, 5, "#6a4a30")
        f += prism(x, y, 0.24, 0.4, 0.0, h, 7, DARK_GREEN)
    f += box(-1.0, -0.06, 0.75, 1.0, 0.06, 0.8, "#a07a52")
    return f


def ricefield():
    """稻田大道：一望無際的稻田、筆直的小路與一棵大樹。"""
    f = flat([(-1.3, -0.9), (1.3, -0.9), (1.3, 0.9), (-1.3, 0.9)], 0.02, "#b9cf5a")
    for k in range(5):
        y0 = -0.85 + k * 0.36
        f += flat([(-1.25, y0), (-0.12, y0), (-0.12, y0 + 0.3), (-1.25, y0 + 0.3)], 0.03, "#a3c24a" if k % 2 else "#c7d96a")
    f += flat([(-0.08, -0.9), (0.08, -0.9), (0.08, 0.9), (-0.08, 0.9)], 0.035, "#d9cfb0")
    f += prism(0.55, 0.2, 0.05, 0.03, 0.05, 0.55, 5, "#6a4a30")
    f += prism(0.55, 0.2, 0.45, 0.45, 0.2, 0.95, 8, GREEN, top="#74b06a")
    return f


def woodhouses():
    """日式木造宿舍群（檜意森活村、勝利星村）：深色木屋與黑瓦。"""
    f = disc(0, 0, 1.1, 0.02, 10, "#8cc276", squash=0.75)
    for x, y in ((-0.55, -0.3), (0.35, -0.35), (-0.25, 0.4), (0.6, 0.35)):
        f += box(x - 0.28, y - 0.2, 0.02, x + 0.28, y + 0.2, 0.32, "#8a6a4a")
        f += roof(x - 0.34, y - 0.26, x + 0.34, y + 0.26, 0.32, x - 0.15, y, x + 0.15, y, 0.55, "#3b3f45")
    return f


def waveroof():
    """衛武營：起伏如浪的大屋頂（仿榕樹林）覆蓋整片場館。"""
    f = box(-1.1, -0.7, 0, 1.1, 0.7, 0.35, "#e8e6e0", top="#d5d2ca")
    for k in range(6):
        x0 = -1.1 + k * 0.3667
        h = 0.65 + 0.25 * math.sin(k * 1.3)
        f += roof(x0, -0.8, x0 + 0.3667, 0.8, 0.35, x0 + 0.08, -0.6, x0 + 0.29, 0.6, 0.35 + h, "#c9cdd2", top="#e2e4e6")
    return f


def grandhotel():
    """圓山大飯店：白色臺基上的紅柱大樓，頂上金黃琉璃瓦的重簷宮殿屋頂。"""
    red, gold = "#b8322a", "#e0a62c"
    f = box(-1.2, -0.6, 0, 1.2, 0.6, 0.15, WHITE, top="#e9e6dd")
    f += box(-1.0, -0.42, 0.15, 1.0, 0.42, 1.25, red, top="#8f2a22")
    for z in (0.42, 0.7, 0.98):                                  # 每層樓的白色欄杆
        f += box(-1.02, -0.44, z, 1.02, 0.44, z + 0.04, "#f1e3c8")
    f += roof(-1.18, -0.6, 1.18, 0.6, 1.25, -0.85, -0.3, 0.85, 0.3, 1.45, gold)
    f += box(-0.8, -0.28, 1.45, 0.8, 0.28, 1.6, red)
    f += roof(-1.02, -0.46, 1.02, 0.46, 1.6, -0.5, 0.0, 0.5, 0.0, 1.98, gold)
    f += box(-0.25, -0.75, 0.15, 0.25, -0.42, 0.62, red)          # 正門
    f += roof(-0.36, -0.86, 0.36, -0.36, 0.62, -0.2, -0.61, 0.2, -0.61, 0.8, gold)
    return f


def arena():
    """臺北小巨蛋：長方形玻璃量體上一片緩拱的銀色屋頂。"""
    f = box(-1.15, -0.75, 0, 1.15, 0.75, 0.42, GLASS, top="#b9c6d0")
    f += box(-1.17, -0.77, 0.12, 1.17, 0.77, 0.16, "#8fa6b2")
    steps = 6
    for k in range(steps):                                       # 拱形屋頂：沿 y 方向一條條往中間升高
        y0 = -0.8 + 1.6 * k / steps
        y1 = -0.8 + 1.6 * (k + 1) / steps
        z0 = 0.42 + 0.32 * math.sin(math.pi * k / steps)
        z1 = 0.42 + 0.32 * math.sin(math.pi * (k + 1) / steps)
        f.append(([(-1.22, y0, z0), (1.22, y0, z0), (1.22, y1, z1), (-1.22, y1, z1)], "#c9d1d8" if k % 2 else "#d8dee3"))
    f += box(-1.3, -1.05, 0, 1.3, -0.78, 0.03, "#b9b2a6")         # 前廣場
    return f


def rainbowvillage():
    """彩虹眷村：一排排漆滿彩色圖案的平房。"""
    colors = ["#e0457b", "#f2b632", "#3fa0d8", "#5cb85c", "#9b59b6", "#ef7d32"]
    f = disc(0, 0, 1.15, 0.02, 10, "#cfc6b4", squash=0.8)
    k = 0
    for y in (-0.5, 0.15):
        for x in (-0.85, -0.25, 0.35):
            c = colors[k % len(colors)]
            f += box(x, y, 0.02, x + 0.52, y + 0.42, 0.34, c, top="#6f757b")
            f += box(x + 0.05, y - 0.005, 0.08, x + 0.2, y + 0.005, 0.26, colors[(k + 2) % len(colors)])   # 牆上的彩繪
            f += box(x + 0.3, y - 0.005, 0.12, x + 0.46, y + 0.005, 0.22, colors[(k + 4) % len(colors)])
            k += 1
    return f


def ballpark():
    """棒球場：扇形看台圍著綠色球場與紅土內野，四角有照明塔。"""
    f = []
    n = 9
    for k in range(n):                                          # 外野那一圈扇形看台
        a0 = math.pi * (0.25 + 0.5 * k / n)
        a1 = math.pi * (0.25 + 0.5 * (k + 1) / n)
        r0, r1 = 1.05, 1.35
        p = [(r0 * math.cos(a0), -0.9 + r0 * math.sin(a0)), (r1 * math.cos(a0), -0.9 + r1 * math.sin(a0)),
             (r1 * math.cos(a1), -0.9 + r1 * math.sin(a1)), (r0 * math.cos(a1), -0.9 + r0 * math.sin(a1))]
        f.append(([(p[0][0], p[0][1], 0.02), (p[3][0], p[3][1], 0.02), (p[2][0], p[2][1], 0.35), (p[1][0], p[1][1], 0.35)], "#c9cdd2"))
    fan = [(0, -0.9)] + [(1.05 * math.cos(math.pi * (0.25 + 0.5 * k / 8)), -0.9 + 1.05 * math.sin(math.pi * (0.25 + 0.5 * k / 8)))
                         for k in range(9)]
    f += flat(fan, 0.02, "#5fae55")
    f += flat([(0, -0.9), (0.32, -0.58), (0, -0.26), (-0.32, -0.58)], 0.03, "#c8865a")   # 內野紅土
    f += flat([(0, -0.84), (0.27, -0.58), (0, -0.32), (-0.27, -0.58)], 0.035, "#6cbf62")
    for x, y in ((-0.95, -0.3), (0.95, -0.3), (-0.6, 0.35), (0.6, 0.35)):
        f += box(x - 0.03, y - 0.03, 0, x + 0.03, y + 0.03, 1.05, "#9aa1a8")
        f += box(x - 0.12, y - 0.04, 1.05, x + 0.12, y + 0.04, 1.2, "#f4f1ea")
    return f


def windmills():
    """高美濕地：潮間帶濕地、木棧道與一排白色風車。"""
    f = flat([(-1.4, -1.0), (1.4, -1.0), (1.4, 1.0), (-1.4, 1.0)], 0.01, "#7fb3c9")
    f += flat([(-1.4, -1.0), (1.4, -1.0), (1.4, -0.35), (-1.4, -0.35)], 0.015, "#a9b98a")
    f += box(-0.08, -1.0, 0.015, 0.08, 0.2, 0.06, "#a07a52")          # 木棧道
    for x, y in ((-0.9, 0.55), (-0.2, 0.65), (0.45, 0.55), (0.9, 0.4)):
        f += prism(x, y, 0.04, 0.0, 0.025, 1.55, 6, "#f4f6f8")
        f += box(x - 0.05, y - 0.07, 1.5, x + 0.05, y + 0.05, 1.6, "#e6eaee")
        for a in (math.pi / 2, math.pi / 2 + 2 * math.pi / 3, math.pi / 2 + 4 * math.pi / 3):   # 三片葉片（在 xz 平面）
            ca, sa = math.cos(a), math.sin(a)
            nx, nz = -sa * 0.04, ca * 0.04                                # 葉片寬度方向
            tip, root = 0.62, 0.06
            p = [(x + root * ca - nx, 1.55 + root * sa - nz), (x + root * ca + nx, 1.55 + root * sa + nz),
                 (x + tip * ca + nx * 0.4, 1.55 + tip * sa + nz * 0.4), (x + tip * ca - nx * 0.4, 1.55 + tip * sa - nz * 0.4)]
            yb = y - 0.08
            front = [(px, yb, pz) for px, pz in p]
            f.append((front if _normal(front)[1] < 0 else front[::-1], "#ffffff"))      # 朝南的一面
            f.append((front[::-1] if _normal(front)[1] < 0 else front, "#f2f4f6"))     # 朝北的一面
    return f


# ------------------------------------------------------------------ 重大建設（開發案）的示意圖案
def tower():
    """商辦／旅館大樓：玻璃塔樓加裙樓。"""
    f = box(-0.75, -0.6, 0, 0.75, 0.6, 0.42, "#cfd3d8", top="#b6bcc3")
    f += box(-0.42, -0.38, 0.42, 0.42, 0.38, 2.05, "#9fbcd2", top="#7f9db3")
    for z in (0.85, 1.3, 1.75):
        f += box(-0.44, -0.4, z, 0.44, 0.4, z + 0.05, "#e8eef3")
    return f


def dome():
    """體育館、會展中心：圓頂大跨距建築。"""
    f = prism(0, 0, 1.0, 0, 0.95, 0.3, 16, "#d9dcdf", squash=0.75)
    f += prism(0, 0, 0.95, 0.3, 0.6, 0.62, 16, "#b8c6d0", squash=0.75)
    f += prism(0, 0, 0.6, 0.62, 0.0, 0.8, 16, "#a6b6c2", squash=0.75)
    return f


def blocks():
    """重劃區、區段徵收：劃好的街廓（草地與道路）上蓋起幾棟新大樓。"""
    f = flat([(-1.05, -0.8), (1.05, -0.8), (1.05, 0.8), (-1.05, 0.8)], 0.0, "#c9d6b0")
    for x0, y0 in ((-0.95, -0.7), (0.08, -0.7), (-0.95, 0.08), (0.08, 0.08)):
        f += flat([(x0, y0), (x0 + 0.87, y0), (x0 + 0.87, y0 + 0.62), (x0, y0 + 0.62)], 0.01, "#a9c08e")
    f += box(-0.8, -0.55, 0.01, -0.35, -0.15, 1.15, "#e2d6c2", top="#c8b9a0")
    f += box(0.25, -0.5, 0.01, 0.65, -0.12, 0.8, "#d9cbb4", top="#bfae94")
    f += box(-0.7, 0.25, 0.01, -0.3, 0.6, 0.6, "#e7ddcc", top="#cdbfa8")
    f += box(0.3, 0.3, 0.01, 0.75, 0.62, 1.45, "#dfd2bd", top="#c5b59b")
    return f


def sheds():
    """產業園區、工業區：幾排鋸齒屋頂的廠房。"""
    f = []
    for y0 in (-0.7, -0.05):
        f += box(-1.0, y0, 0, 1.0, y0 + 0.55, 0.32, "#d4d8dc", top="#b9c0c6")
        for k in range(4):
            x0 = -1.0 + k * 0.5
            f += roof(x0, y0, x0 + 0.5, y0 + 0.55, 0.32, x0 + 0.5, y0, x0 + 0.5, y0 + 0.55, 0.52, "#8fa3b3")
    f += prism(0.75, 0.62, 0.07, 0, 0.07, 0.95, 6, "#c4c9ce")
    return f


def interchange():
    """道路、交流道：交叉的路面加上一段高架匝道與橋墩。"""
    road = "#8b9097"
    f = flat([(-1.1, -0.14), (1.1, -0.14), (1.1, 0.14), (-1.1, 0.14)], 0.0, road)
    f += flat([(-0.14, -0.9), (0.14, -0.9), (0.14, 0.9), (-0.14, 0.9)], 0.005, road)
    f += box(-1.0, 0.32, 0.38, 1.0, 0.56, 0.46, "#b3b8be", top="#9aa0a7")
    for x in (-0.8, -0.27, 0.27, 0.8):
        f += box(x - 0.05, 0.4, 0, x + 0.05, 0.48, 0.38, "#c9cdd2")
    f += flat([(-1.1, 0.23), (1.1, 0.23), (1.1, 0.25), (-1.1, 0.25)], 0.006, "#f2f2f2")
    return f


def rail():
    """鐵路地下化：月台雨棚、軌道進入地下的隧道口，地面闢為綠園道。"""
    f = flat([(-1.1, -0.3), (1.1, -0.3), (1.1, 0.3), (-1.1, 0.3)], 0.0, "#8fb878")
    f += flat([(-1.1, -0.12), (0.2, -0.12), (0.2, 0.12), (-1.1, 0.12)], 0.005, "#6d6a66")
    f += box(0.2, -0.32, 0, 0.42, 0.32, 0.42, "#b7b2aa", top="#9d978d")
    f += box(-0.95, -0.55, 0, 0.0, -0.32, 0.5, "#e9e4da", top="#d3cbbd")
    f += roof(-1.0, -0.6, 0.05, -0.27, 0.5, -1.0, -0.43, 0.05, -0.43, 0.62, "#c0623a")
    return f


def metro():
    """捷運（高架單軌）：橋墩上的軌道梁、車站與列車。"""
    f = []
    for x in (-0.9, -0.3, 0.3, 0.9):
        f += box(x - 0.06, -0.06, 0, x + 0.06, 0.06, 0.62, "#c9cdd2")
    f += box(-1.1, -0.08, 0.62, 1.1, 0.08, 0.72, "#a9afb6", top="#9097a0")
    f += box(-0.45, -0.5, 0.45, 0.45, 0.5, 0.62, "#e4e7ea")
    f += roof(-0.5, -0.55, 0.5, 0.55, 0.98, -0.5, 0.0, 0.5, 0.0, 1.15, "#2a78d6")
    f += box(-0.45, -0.5, 0.62, -0.38, 0.5, 0.98, "#d4d8dc")
    f += box(0.38, -0.5, 0.62, 0.45, 0.5, 0.98, "#d4d8dc")
    f += box(-0.95, -0.1, 0.72, -0.2, 0.1, 0.92, "#2a78d6", top="#5b9be3")
    return f


def housing():
    """社會住宅、住宅開發：幾棟中高樓層住宅。"""
    f = box(-0.95, -0.5, 0, -0.35, 0.05, 1.25, "#efe6d6", top="#d9ccb5")
    f += box(-0.2, -0.6, 0, 0.4, -0.05, 1.6, "#e9dfcc", top="#d2c3aa")
    f += box(0.5, -0.2, 0, 1.0, 0.45, 1.0, "#f1e9db", top="#dacfbb")
    f += box(-0.6, 0.25, 0, 0.1, 0.7, 0.75, "#ece3d2", top="#d5c9b2")
    return f


def crane():
    """施工中：一座黃色塔吊。"""
    yellow = "#f2b632"
    f = box(-0.05, -0.05, 0, 0.05, 0.05, 2.3, yellow)
    f += box(-0.35, -0.04, 2.3, 1.05, 0.04, 2.38, yellow)
    f += box(-0.35, -0.08, 2.18, -0.15, 0.08, 2.3, "#6b7178")
    f += box(0.95, -0.02, 1.95, 0.97, 0.02, 2.3, "#6b7178")
    return f


STATES = ("完工", "施工中", "規劃中")


def _mix(hexcolor, other, t):
    a = [int(hexcolor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def project_faces(model, state, **kw):
    """重大建設的圖案：完工照原色；施工中旁邊加一座塔吊；規劃中整個淡化（只是「預定地」）。"""
    key = ("project", model, state, tuple(sorted(kw.items())))
    if key not in _CACHE:
        base = faces_of(model, **kw)
        if state == "規劃中":
            out = [(pts, _mix(color, "#ffffff", 0.58), n) for pts, color, n in base]
        elif state == "施工中":
            out = [(pts, _mix(color, "#ffffff", 0.18), n) for pts, color, n in base]
            for pts, color in crane():
                moved = [(x + 0.85, y + 0.55, z * 0.82) for x, y, z in pts]
                nrm = _normal(moved)
                if nrm is not None:
                    out.append((moved, color, nrm))
        else:
            out = list(base)
        _CACHE[key] = out
    return _CACHE[key]


def faces_for(item):
    """地圖上一個圖案（地標或重大建設）的面清單。"""
    params = item.get("params") or {}
    if item.get("state"):
        return project_faces(item["model"], item["state"], **params)
    return faces_of(item["model"], **params)


def build_state(build, year):
    """重大建設在某一年的狀態：完工／施工中／規劃中。build 是 intel.json 裡的 build 欄位。"""
    done, start, now = build.get("done"), build.get("start"), build.get("phase")
    if done and done <= year:
        return "完工"
    if now == "完工":
        return "完工"
    if start and start <= year:
        return "施工中"
    if now == "施工中":
        return "施工中"
    return "規劃中"


MODELS = {
    "pavilion": pavilion, "temple": temple, "fort": fort, "bastion": bastion, "museum": museum, "station": station,
    "hsr": hsr, "campus": campus, "artmuseum": artmuseum, "store": store, "saltmountain": saltmountain,
    "lighthouse": lighthouse, "reservoir": reservoir, "lake": lake, "hotspring": hotspring, "mangrove": mangrove,
    "cityhall": cityhall, "fab": fab, "saltfield": saltfield, "farm": farm, "lotus": lotus, "badlands": badlands,
    "tower": tower, "dome": dome, "blocks": blocks, "sheds": sheds, "interchange": interchange, "rail": rail,
    "metro": metro, "housing": housing, "crane": crane,
    # 全台各縣市的招牌地標
    "taipei101": taipei101, "tower85": tower85, "memorial": memorial, "bridge": bridge, "trussbridge": trussbridge,
    "archgate": archgate, "buddha": buddha, "twinpagoda": twinpagoda, "opera": opera, "mtntrain": mtntrain,
    "tulou": tulou, "chapel": chapel, "roundhouse": roundhouse, "heartweir": heartweir, "stonevillage": stonevillage,
    "airport": airport, "lakepagoda": lakepagoda, "palace": palace, "citygate": citygate, "themepark": themepark,
    "forest": forest, "ricefield": ricefield, "woodhouses": woodhouses, "waveroof": waveroof,
    "grandhotel": grandhotel, "arena": arena, "rainbowvillage": rainbowvillage, "ballpark": ballpark, "windmills": windmills,
}
_CACHE = {}


def faces_of(model, **kw):
    """回傳模型的面清單 [(頂點, 顏色, 法向量)]；沒有這個模型就用最簡單的方塊代替。"""
    key = (model, tuple(sorted(kw.items())))
    if key not in _CACHE:
        fn = MODELS.get(model)
        raw = fn(**kw) if fn else box(-0.5, -0.5, 0, 0.5, 0.5, 1.0, "#9aa5ae")
        out = []
        for pts, color in raw:
            n = _normal(pts)
            if n is not None:
                out.append((pts, color, n))
        _CACHE[key] = out
    return _CACHE[key]


def _normal(pts):
    """Newell 法求多邊形法向量（單位向量）；面積為零回傳 None。"""
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % len(pts)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-9:
        return None
    return nx / ln, ny / ln, nz / ln


def brightness(normal):
    """依面的朝向決定明暗：頂面最亮；側面以西北方來光計算（和地形陰影同一個方向）。"""
    nx, ny, nz = normal
    side = max(0.0, -nx * 0.7071 + ny * 0.7071)
    return max(0.7, min(1.0, 0.80 + 0.2 * max(0.0, nz) + 0.14 * side))


def load(county="D"):
    """讀取 data/landmarks.json，回傳地標清單。county=None 回傳全台；預設只回傳臺南市。"""
    items = load_json("landmarks.json")["items"]
    for i, it in enumerate(items):
        it.setdefault("id", "lm%d" % i)
        it.setdefault("county", "D")
    return [it for it in items if county is None or it["county"] == county]
