"""錄製產品介紹短片的畫面（CDP screencast），輸出 frames/<name>/*.jpg 與 times.json。
用法：python record.py phone|wide
"""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))            # 宣傳短片/製作程式
ROOT = _os.path.dirname(_os.path.dirname(HERE))                # 專案根目錄
import asyncio, base64, json, os, sys, time
from playwright.async_api import async_playwright

MODE = sys.argv[1]
URL = "http://localhost:8765/index.html"
OUT = f"{HERE}/frames3/{MODE}"
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    os.remove(os.path.join(OUT, f))

if MODE == "phone":
    VIEW, DPR = {"width": 390, "height": 780}, 2
else:
    VIEW, DPR = {"width": 1280, "height": 720}, 1.5

# 每一段的長度（秒），跟字幕／旁白對齊
SCENES = [6, 8, 10, 8, 10, 7, 6]   # 最後 5 秒片尾卡另外做

TAP_CSS = """
.tapdot{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
 background:rgba(216,27,96,.35);border:3px solid rgba(216,27,96,.9);pointer-events:none;z-index:9999;
 animation:tapd .6s ease-out forwards}
@keyframes tapd{0%{transform:scale(.4);opacity:1}100%{transform:scale(1.4);opacity:0}}
"""


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        ctx = await b.new_context(viewport=VIEW, device_scale_factor=DPR, has_touch=(MODE == "phone"),
                                  is_mobile=(MODE == "phone"), locale="zh-TW", timezone_id="Asia/Taipei")
        page = await ctx.new_page()
        await page.goto(URL)
        await page.wait_for_function("window.__app && window.__app.D.txs")
        await page.add_style_tag(content=TAP_CSS)
        await page.wait_for_timeout(1500)

        cdp = await ctx.new_cdp_session(page)
        frames = []

        def on_frame(ev):
            idx = len(frames)
            with open(f"{OUT}/{idx:05d}.jpg", "wb") as f:
                f.write(base64.b64decode(ev["data"]))
            frames.append(ev["metadata"]["timestamp"])
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        W, H = int(VIEW["width"] * DPR), int(VIEW["height"] * DPR)

        ev = page.evaluate

        async def tap(sel=None, xy=None):
            if sel:
                box = await page.locator(sel).first.bounding_box()
                xy = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await ev("([x,y])=>{const d=document.createElement('div');d.className='tapdot';d.style.left=x+'px';d.style.top=y+'px';document.body.appendChild(d);setTimeout(()=>d.remove(),700)}", list(xy))
            await page.wait_for_timeout(180)
            await page.mouse.click(*xy)

        async def spin(deg, secs, pitch=0):
            steps = int(secs * 20)
            for _ in range(steps):
                await ev(f"window.__app.view.rotate({deg/steps},{pitch/steps})")
                await page.wait_for_timeout(50)

        t0 = time.time()
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})
        wall0 = None
        marks = []

        async def until(sec):
            left = sec - (time.time() - t0)
            if left > 0:
                await page.wait_for_timeout(int(left * 1000))

        edge = 0
        async def setq(text, d=55):
            await ev("document.querySelector('#q').value=''")
            await tap("#q")
            await page.locator("#q").type(text, delay=d)
            await tap("#search button")
        async def half():
            await ev("(()=>{const e=document.querySelector('#sheet');if(innerWidth<900){e.className='half';}})()")
        # 1. 全市 3D（3 秒）
        marks.append(time.time() - t0)
        await spin(40, 2.7, pitch=-5)
        edge += 3; await until(edge)
        # 2. 善化地址（3.5 秒）
        marks.append(time.time() - t0)
        await setq("善化區成功路169巷10號", 40)
        await page.wait_for_timeout(1800)
        edge += 3.5; await until(edge)
        # 3. 安平（4 秒）
        marks.append(time.time() - t0)
        await ev("(()=>{const a=window.__app;a.S.addr=null;a.S.pin=null;})()")
        await setq("安平", 100)
        await page.wait_for_timeout(700)
        await tap("#tabs button[data-tab='roads']")
        await ev("window.__app.view.flyTo(22.995,120.163,52,700)")
        await page.wait_for_timeout(800)
        await spin(20, 1.0, pitch=4)
        edge += 4; await until(edge)
        # 4. 赤崁樓（4 秒）
        marks.append(time.time() - t0)
        await setq("赤崁樓", 100)
        await page.wait_for_timeout(900)
        await ev("window.__app.view.zoomAt(2.6)")
        await page.wait_for_timeout(400)
        await spin(50, 1.6, pitch=6)
        edge += 4; await until(edge)
        # 5. 通勤 A→B（6 秒）
        marks.append(time.time() - t0)
        await ev("document.querySelector('#q').value=''")
        await ev("window.__app.selectDistrict('台南市', false)")
        await tap("#tabs button[data-tab='commute']")
        await page.wait_for_timeout(300)
        await tap("#tab-body select[data-set='work']")
        await page.select_option("#tab-body select[data-set='work']", "南科台南園區")
        await half()
        await ev("window.__app.view.flyTo(23.06,120.26,13,800)")
        await page.wait_for_timeout(900)
        for m in (15, 20, 25, 30):
            await ev(f"(()=>{{const i=document.querySelector('#commute-min');i.value={m};i.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
            await page.wait_for_timeout(650)
        await spin(15, 0.8)
        edge += 6; await until(edge)
        # 6. 建設年份（3.5 秒）
        marks.append(time.time() - t0)
        await ev("(()=>{const e=document.querySelector(\"#tab-body select[data-set='work']\");e.value='';e.dispatchEvent(new Event('change',{bubbles:true}))})()")
        await tap("#tabs button[data-tab='projects']")
        await ev("window.__app.view.flyTo(23.095,120.27,26,600)")
        await page.wait_for_timeout(600)
        y0 = await ev("window.__app.S.year")
        for y in range(y0, y0 + 10):
            await ev(f"(()=>{{const i=document.querySelector('#year');i.value={y};i.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
            await page.wait_for_timeout(210)
        edge += 3.5; await until(edge)
        # 7. 風險圖層（3 秒）
        marks.append(time.time() - t0)
        await ev("(()=>{const a=window.__app;a.S.settings.liq=true;a.S.settings.fault=true;a.view.layerOn={town:true,liq:true,fault:true};a.view.request();})()")
        await ev("window.__app.view.flyTo(23.0,120.22,22,700)")
        await page.wait_for_timeout(800)
        await spin(-15, 1.4)
        edge += 3; await until(edge)
        marks.append(time.time() - t0)

        await cdp.send("Page.stopScreencast")
        await page.wait_for_timeout(300)
        base = t0
        json.dump({"frames": [t - base for t in frames], "marks": marks, "lag": 0, "size": [W, H]},
                  open(f"{OUT}/times.json", "w"))
        print(MODE, len(frames), "frames", marks)
        await b.close()


async def _center(loc):
    box = await loc.bounding_box()
    return (box["x"] + min(box["width"] / 2, 160), box["y"] + box["height"] / 2)

asyncio.run(main())
