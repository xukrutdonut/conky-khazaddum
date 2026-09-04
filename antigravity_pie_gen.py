#!/usr/bin/env python3
import math
import subprocess
import json
import os
import sys
import time
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

W, H       = 350, 210
BG         = (0, 0, 0, 0)
TRACK_RGBA = (255, 255, 255, 35)
WHITE      = (255, 255, 255, 235)
GREY       = (160, 160, 160, 180)
DIVIDER    = (130, 200, 255, 40)

GREEN  = (90,  247, 142, 230)
ORANGE = (255, 179,  71, 230)
RED    = (255, 110, 110, 230)
GREY_C = (136, 136, 136, 200)
BLUE   = (94, 184, 255, 235)
GOLD   = (255, 215,   0, 220)

FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
FONT_REG  = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
OUTPUT    = '/tmp/antigravity_pie.png'
CACHE_FILE = '/tmp/antigravity_quota_cache.json'
CACHE_TTL  = 120

def fetch_quota():
    if os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_TTL:
            try:
                with open(CACHE_FILE) as f:
                    return json.load(f)
            except Exception:
                pass

    try:
        r = subprocess.run(
            [os.path.expanduser('~/.nvm/versions/node/v22.22.2/bin/antigravity-usage'), 'quota', '--json'],
            capture_output=True, text=True, timeout=15
        )
        if r.stdout and r.returncode == 0:
            data = json.loads(r.stdout)
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
            return data
    except Exception:
        pass

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def quota_color(p):
    if p is None: return GREY_C
    if p < 20:    return RED
    if p < 40:    return ORANGE
    return GREEN

def arc_rgba(img, cx, cy, r, lw, start_deg, end_deg, color):
    S = 4
    ow, oh = img.size
    big = Image.new('RGBA', (ow * S, oh * S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(big)
    bx, by = cx * S, cy * S
    br = r * S
    blw = max(1, lw * S)
    bbox = [bx - br, by - br, bx + br, by + br]
    d.arc(bbox, start=start_deg, end=end_deg, fill=color, width=int(blw))
    small = big.resize((ow, oh), Image.LANCZOS)
    img.alpha_composite(small)

def text_centered(draw, text, cx, cy, font, color):
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    draw.text((cx - tw // 2, cy - th // 2), text, font=font, fill=color)

def draw_donut(img, cx, cy, R, pct, label, sublabel, clr):
    LW   = int(R * 0.28)
    DEG0 = -90

    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK_RGBA)

    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        sweep = capped / 100.0 * 360.0
        arc_rgba(img, cx, cy, R - LW // 2, LW, DEG0, DEG0 + sweep, clr)

    draw = ImageDraw.Draw(img)

    txt = f'{capped:.0f}%' if pct is not None else 'N/A'
    fs  = max(11, int(R * 0.35))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        fnt = ImageFont.load_default()
    text_centered(draw, txt, cx, cy, fnt, WHITE)

    try:
        fnt2 = ImageFont.truetype(FONT_BOLD, 10)
    except Exception:
        fnt2 = ImageFont.load_default()
    text_centered(draw, label, cx, cy + R + 11, fnt2, clr)

    try:
        fnt3 = ImageFont.truetype(FONT_REG, 8)
    except Exception:
        fnt3 = ImageFont.load_default()
    text_centered(draw, sublabel, cx, cy + R + 22, fnt3, GREY)

def format_time_ms(ms):
    try:
        total_s = int(ms) // 1000
        if total_s <= 0: return 'ya'
        h = total_s // 3600
        m = (total_s % 3600) // 60
        return f'{h}h {m:02d}m' if h > 0 else f'{m}m'
    except Exception:
        return '—'

data = fetch_quota()
models = data.get('models', []) if data else []

c_m, g_m, o_m = None, None, None
for m in models:
    mid = m.get('modelId', '').lower()
    if 'claude' in mid and not c_m:
        c_m = m
    elif 'gemini' in mid and not m.get('isAutocompleteOnly', False) and not g_m:
        g_m = m
    elif 'gpt' in mid and not o_m:
        o_m = m

items = []
if c_m: items.append(('CLAUDE', int(c_m.get('remainingPercentage', 0) * 100), c_m.get('timeUntilResetMs')))
if g_m: items.append(('GEMINI', int(g_m.get('remainingPercentage', 0) * 100), g_m.get('timeUntilResetMs')))
if o_m: items.append(('GPT-OSS', int(o_m.get('remainingPercentage', 0) * 100), o_m.get('timeUntilResetMs')))

if not items:
    items = [('CLAUDE', 100, 18000000), ('GEMINI', 100, 18000000), ('GPT-OSS', 100, 18000000)]

img  = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

R_sm = 38
cy_donut = 48
positions = [W // 6, W // 2, W * 5 // 6]

draw.line([(W // 3 + 6, 6), (W // 3 + 6, cy_donut + R_sm + 24)], fill=DIVIDER, width=1)
draw.line([(W * 2 // 3 - 6, 6), (W * 2 // 3 - 6, cy_donut + R_sm + 24)], fill=DIVIDER, width=1)

for i, (label, pct, reset_ms) in enumerate(items[:3]):
    clr = quota_color(pct)
    draw_donut(img, positions[i], cy_donut, R_sm, pct, label, 'restante', clr)

sep_y = cy_donut + R_sm + 28
draw.line([(4, sep_y), (W - 4, sep_y)], fill=DIVIDER, width=1)

try:
    fnt_reset = ImageFont.truetype(FONT_BOLD, 10)
    fnt_reg = ImageFont.truetype(FONT_REG, 10)
except Exception:
    fnt_reset = ImageFont.load_default()
    fnt_reg = ImageFont.load_default()

y = sep_y + 8
for label, pct, reset_ms in items[:3]:
    cd = format_time_ms(reset_ms) if reset_ms else '—'
    draw.text((16, y), f"↺ {label:<8}:", font=fnt_reset, fill=BLUE)
    draw.text((130, y), f"{pct:>3}% (Reset en {cd})", font=fnt_reg, fill=WHITE)
    y += 18

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
