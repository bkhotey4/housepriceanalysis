"""原創背景音樂（程式合成，無版權問題）：輕快明亮，C–G–Am–F，112 BPM，長度 18 秒。"""
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))            # 宣傳短片/製作程式
ROOT = _os.path.dirname(_os.path.dirname(HERE))                # 專案根目錄
import numpy as np, wave, sys

SR = 48000
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0
BPM = 112
BEAT = 60 / BPM
N = int(SR * DUR)
out = np.zeros((N, 2))
rng = np.random.default_rng(7)

def hz(m): return 440 * 2 ** ((m - 69) / 12)

def add(sig, t0, pan=0.0, gain=1.0):
    i = int(t0 * SR)
    if i >= N: return
    sig = sig[: N - i] * gain
    out[i:i + len(sig), 0] += sig * (1 - pan) ** 0.5
    out[i:i + len(sig), 1] += sig * (1 + pan) ** 0.5

def env(n, a=0.005, r=0.3):
    t = np.arange(n) / SR
    e = np.minimum(1, t / a) * np.exp(-t / r)
    return e

def pluck(m, dur, r=0.25):
    n = int(dur * SR); t = np.arange(n) / SR; f = hz(m)
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    return s * env(n, 0.003, r)

def pad(ms, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    s = np.zeros(n)
    for m in ms:
        for det in (-0.08, 0.08):
            f = hz(m + det)
            s += np.sin(2 * np.pi * f * t) + 0.2 * np.sin(4 * np.pi * f * t)
    a = np.minimum(1, t / 0.25) * np.minimum(1, (dur - t) / 0.3)
    return s * a / len(ms)

def kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t / 0.04)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.12)

def hat(len_=0.05):
    n = int(len_ * SR); s = rng.standard_normal(n)
    s = np.diff(np.concatenate([[0], s]))          # 高通
    return s * np.exp(-np.arange(n) / SR / 0.015)

def clap():
    n = int(0.18 * SR); s = rng.standard_normal(n)
    return s * np.exp(-np.arange(n) / SR / 0.05)

chords = [(60, [48, 60, 64, 67]), (55, [43, 59, 62, 67]), (57, [45, 60, 64, 69]), (53, [41, 60, 65, 69])]
bar = 4 * BEAT
nbars = int(np.ceil(DUR / bar))
end_t = DUR - 3.4      # 片尾卡開始：只留和弦延音
for b in range(nbars):
    t0 = b * bar
    root, notes = chords[b % 4]
    if t0 >= end_t:
        add(pad([48, 60, 64, 67, 72], DUR - t0 + 0.1), t0, gain=0.22)
        add(pluck(84, 2.0, 0.8), t0, 0.2, 0.18)
        add(kick(), t0, gain=0.7)
        break
    add(pad(notes[1:], bar + 0.05), t0, gain=0.16)
    add(pluck(notes[0], bar, 0.9), t0, gain=0.35)                   # 低音
    arp = [notes[1] + 12, notes[2] + 12, notes[3] + 12, notes[2] + 12]
    for k in range(8):                                             # 八分音符琶音
        tt = t0 + k * BEAT / 2
        if tt >= end_t: break
        add(pluck(arp[k % 4], 0.4, 0.18), tt, pan=0.3 if k % 2 else -0.3, gain=0.16)
    for k in range(4):
        tt = t0 + k * BEAT
        if tt >= end_t: break
        if b > 0 or k >= 2:
            add(kick(), tt, gain=0.55)
        add(hat(), tt + BEAT / 2, pan=0.4, gain=0.08)
        if k in (1, 3) and b > 0:
            add(clap(), tt, pan=-0.1, gain=0.1)

# 淡入淡出、正規化
t = np.arange(N) / SR
fade = np.minimum(1, t / 0.15) * np.minimum(1, (DUR - t) / 1.2)
out *= fade[:, None]
out /= np.max(np.abs(out)) / 0.85
with wave.open(_os.path.join(HERE, "music.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((out * 32767).astype("<i2").tobytes())
print("music ok", DUR)
