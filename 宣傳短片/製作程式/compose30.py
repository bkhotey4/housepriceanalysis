"""把錄好的畫面合成 60 秒短片：python compose.py phone|wide"""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))            # 宣傳短片/製作程式
ROOT = _os.path.dirname(_os.path.dirname(HERE))                # 專案根目錄
import json, subprocess, sys, bisect
from PIL import Image, ImageDraw, ImageFont, ImageFilter

MODE = sys.argv[1]
FPS = 30
SRC = f"{HERE}/frames30/{MODE}"
OUT = f"{_os.path.dirname(HERE)}/台南購屋_介紹30秒_{'直式' if MODE == 'phone' else '橫式'}.mp4"
T = json.load(open(f"{SRC}/times.json"))
FR, MARKS = T["frames"], T["marks"]
def _first(*paths):
    return next((p for p in paths if _os.path.exists(p)), paths[0])


# 中文字型：Linux 用 Noto Sans CJK，Windows 用微軟正黑體
FONT = _first("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/msjhbd.ttc")
FONT_R = _first("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msjh.ttc")
TC = 2  # ttc index for TC? find below
TEAL, TEAL_D, PINK = (11, 93, 87), (7, 60, 56), (216, 27, 96)

def font(size, bold=True):
    path = FONT if bold else FONT_R
    for i in range(10):
        f = ImageFont.truetype(path, size, index=i)
        if "TC" in f.getname()[0]:
            return f
    return ImageFont.truetype(path, size)

CAPS = [
    ("3D 房價地圖", "台南買房\n一張 3D 地圖全看懂"),
    ("地址搜尋", "輸入地址\n直接看那段路的成交"),
    ("換區查詢", "輸入「安平」\n每條路的單價，顏色一看就懂"),
    ("地標搜尋", "輸入「赤崁樓」\n飛到 3D 地標，看周邊行情"),
    ("重大建設", "拉動年份\n看見十年後的台南"),
    ("風險圖層", "土壤液化、活動斷層\n買之前先看清楚"),
]
URL = "bkhotey4.github.io/tainan-house"
TOTAL = 30.0
OUTRO = min(MARKS[-1], 26.5)


def src_frame(t):
    i = max(0, bisect.bisect_right(FR, t) - 1)
    return i


def rounded(im, r):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], r, fill=255)
    out = Image.new("RGBA", im.size); out.paste(im, (0, 0), m); return out


def scene_at(t):
    k = 0
    for i, m in enumerate(MARKS[:-1]):
        if t >= m:
            k = i
    return k


def text_center(d, cx, y, s, f, fill, spacing=14):
    w = d.multiline_textbbox((0, 0), s, font=f, spacing=spacing, align="center")[2]
    d.multiline_text((cx - w / 2, y), s, font=f, fill=fill, spacing=spacing, align="center")


# ---------------------------------------------------------------- 片尾卡
def outro(W, H, a):
    im = Image.new("RGB", (W, H), TEAL_D)
    d = ImageDraw.Draw(im)
    icon = Image.open(_os.path.join(ROOT, "web", "img", "icon-512.png")).convert("RGBA")
    big = H > W
    s = 260 if big else 200
    icon = rounded(icon.resize((s, s)), s // 5)
    y = int(H * (0.25 if big else 0.17))
    im.paste(icon, ((W - s) // 2, y), icon)
    y += s + (60 if big else 36)
    text_center(d, W / 2, y, "台南購屋深度分析", font(96 if big else 80), "white"); y += 150 if big else 115
    lines = ["實價登錄每 10 天自動更新", "免安裝・免註冊・手機打開就能用", "所有計算都在你的裝置上完成"]
    for ln in lines:
        text_center(d, W / 2, y, ln, font(50 if big else 40, False), (220, 238, 235)); y += 82 if big else 60
    note = "房價：內政部實價登錄開放資料｜統計為中位數，僅供參考，不構成投資建議"
    fn = font(28 if big else 22, False)
    w = d.textbbox((0, 0), note, font=fn)[2]
    d.text(((W - w) / 2, H - (110 if big else 60)), note, font=fn, fill=(160, 200, 195))
    return im


# ---------------------------------------------------------------- 字幕
def caption_layer(W, H, k, a, big):
    tag, txt = CAPS[k]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if big:      # 直式：上方標題區
        ft, fc = font(38), font(62)
        tw = d.textbbox((0, 0), f"{k+1}/6  {tag}", font=ft)[2]
        d.rounded_rectangle([(W - tw) / 2 - 22, 34, (W + tw) / 2 + 22, 92], 29, fill=PINK + (int(255 * a),))
        d.text(((W - tw) / 2, 38), f"{k+1}/6  {tag}", font=ft, fill=(255, 255, 255, int(255 * a)))
        text_center(d, W / 2, 112, txt, fc, (255, 255, 255, int(255 * a)), spacing=12)
    else:        # 橫式：地圖左下
        ft, fc = font(30), font(50)
        x0, y1 = 40, H - 46
        bb = d.multiline_textbbox((0, 0), txt, font=fc, spacing=10)
        bw, bh = bb[2] + 60, bb[3] + 100
        d.rounded_rectangle([x0, y1 - bh, x0 + bw, y1], 22, fill=(10, 20, 22, int(205 * a)))
        d.rounded_rectangle([x0 + 30, y1 - bh + 22, x0 + 30 + d.textbbox((0, 0), f"{k+1}/6  {tag}", font=ft)[2] + 32, y1 - bh + 68], 23,
                            fill=PINK + (int(255 * a),))
        d.text((x0 + 46, y1 - bh + 24), f"{k+1}/6  {tag}", font=ft, fill=(255, 255, 255, int(255 * a)))
        d.multiline_text((x0 + 30, y1 - bh + 82), txt, font=fc, fill=(255, 255, 255, int(255 * a)), spacing=10)
    return lay


def main():
    big = MODE == "phone"
    W, H = (1080, 1920) if big else (1920, 1080)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", _os.path.join(HERE, "music.wav"), "-shortest",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", OUT]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    if big:
        bg = Image.new("RGB", (W, H), TEAL_D)
        # 手機外框陰影
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([150 - 6, 300 - 2, 150 + 780 + 6, 300 + 1560 + 14], 44, fill=(0, 0, 0, 120))
        bg.paste(sh.filter(ImageFilter.GaussianBlur(16)), (0, 0), sh.filter(ImageFilter.GaussianBlur(16)))
        fu = font(30, False)
        dd = ImageDraw.Draw(bg)
    last_i, last_shot = None, None
    out_img = outro(W, H, 1)
    caps = {}
    n = int(TOTAL * FPS)
    for fi in range(n):
        t = fi / FPS
        if t >= OUTRO:
            a = min(1, (t - OUTRO) / 0.4)
            frame = out_img if a >= 1 else Image.blend(prev, out_img, a)
            ff.stdin.write(frame.tobytes()); continue
        i = src_frame(t)
        if i != last_i:
            shot = Image.open(f"{SRC}/{i:05d}.jpg").convert("RGB")
            if big:
                shot = rounded(shot.resize((780, 1560)), 36)
            else:
                shot = shot.resize((W, H))
            last_i, last_shot = i, shot
        k = scene_at(t)
        a = min(1, (t - MARKS[k]) / 0.35)
        key = (k, round(a, 2))
        if key not in caps:
            caps = {key: caption_layer(W, H, k, a, big)} | ({kk: v for kk, v in caps.items() if kk[1] == 1} )
        if big:
            frame = bg.copy()
            frame.paste(last_shot, (150, 300), last_shot)
        else:
            frame = last_shot.copy()
        frame.paste(caps[key], (0, 0), caps[key])
        prev = frame
        ff.stdin.write(frame.tobytes())
    ff.stdin.close(); ff.wait()
    print("ok", OUT)


main()
