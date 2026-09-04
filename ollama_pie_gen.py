#!/usr/bin/env python3
import math
import subprocess
import json
import os
import sys
import urllib.request
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

FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
FONT_REG  = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
OUTPUT    = '/tmp/ollama_pie.png'
CACHE_FILE = '/tmp/ollama_quota_cache.json'

DEFAULT_DATA = {
    "daily": {
        "remaining_pct": 95.0,
        "used_tokens": 50000,
        "limit_tokens": 1000000,
        "reset_time": "04:00",
        "reset_in": "5h 10m"
    },
    "weekly": {
        "remaining_pct": 85.0,
        "used_tokens": 3000000,
        "limit_tokens": 20000000,
        "reset_time": "Lun 00:00",
        "reset_in": "3d 14h"
    },
    "updated_at": datetime.now(timezone.utc).isoformat()
}

def fetch_data():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass

    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(DEFAULT_DATA, f, indent=2)
    except Exception:
        pass
    return DEFAULT_DATA

def quota_color(p):
    if p is None: return GREY_C
    if p < 20:    return RED
    if p < 40:    return ORANGE
    return GREEN

def format_tokens(num):
    if num is None: return '—'
    if num >= 1_000_000:
        return f'{num / 1_000_000:.1f}M'
    if num >= 1_000:
        return f'{num / 1_000:.0f}K'
    return str(num)

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
    fs  = max(12, int(R * 0.35))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        fnt = ImageFont.load_default()
    text_centered(draw, txt, cx, cy, fnt, WHITE)

    try:
        fnt2 = ImageFont.truetype(FONT_BOLD, 11)
    except Exception:
        fnt2 = ImageFont.load_default()
    text_centered(draw, label, cx, cy + R + 11, fnt2, clr)

    try:
        fnt3 = ImageFont.truetype(FONT_REG, 9)
    except Exception:
        fnt3 = ImageFont.load_default()
    text_centered(draw, sublabel, cx, cy + R + 23, fnt3, GREY)

data = fetch_data()

daily_data  = data.get("daily", {})
weekly_data = data.get("weekly", {})

daily_pct   = daily_data.get("remaining_pct", 100.0)
weekly_pct  = weekly_data.get("remaining_pct", 100.0)

daily_rem_tok  = daily_data.get("limit_tokens", 0) - daily_data.get("used_tokens", 0)
weekly_rem_tok = weekly_data.get("limit_tokens", 0) - weekly_data.get("used_tokens", 0)

daily_sub  = f"{format_tokens(max(0, daily_rem_tok))} rest."
weekly_sub = f"{format_tokens(max(0, weekly_rem_tok))} rest."

img  = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

R  = 46
cy = 54
cx1, cx2 = W // 4, W * 3 // 4

draw.line([(W // 2, 6), (W // 2, cy + R + 28)], fill=DIVIDER, width=1)

draw_donut(img, cx1, cy, R, daily_pct,  'DIARIO',  daily_sub,  quota_color(daily_pct))
draw_donut(img, cx2, cy, R, weekly_pct, 'SEMANAL', weekly_sub, quota_color(weekly_pct))

sep_y = cy + R + 32
draw.line([(4, sep_y), (W - 4, sep_y)], fill=DIVIDER, width=1)

try:
    fnt_reset = ImageFont.truetype(FONT_BOLD, 11)
except Exception:
    fnt_reset = ImageFont.load_default()

y = sep_y + 8
d_reset_time = daily_data.get("reset_time", "04:00 (UTC)")
d_reset_in   = daily_data.get("reset_in", "5h 10m")
w_reset_time = weekly_data.get("reset_time", "Lun 00:00")
w_reset_in   = weekly_data.get("reset_in", "3d 14h")

reset_line1 = f"↺ Reset Diario : {d_reset_time} ({d_reset_in})"
reset_line2 = f"↺ Reset Semanal: {w_reset_time} ({w_reset_in})"

draw.text((12, y), reset_line1, font=fnt_reset, fill=BLUE)
y += 20
draw.text((12, y), reset_line2, font=fnt_reset, fill=BLUE)

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
