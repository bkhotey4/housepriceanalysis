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


def load():
    """讀取 data/landmarks.json，回傳地標清單。"""
    items = load_json("landmarks.json")["items"]
    for i, it in enumerate(items):
        it.setdefault("id", "lm%d" % i)
    return items
