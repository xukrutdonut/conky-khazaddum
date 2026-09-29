#!/usr/bin/env python3
"""
Genera /tmp/ollama_pie.png - dashboard de Ollama Cloud usage.
Lee /tmp/ollama_cloud_stats.json (escrito por fetch_ollama_cloud_stats.py).

Muestra solo los donuts:
  - Session usage (% usado + requests)
  - Weekly usage (% usado + requests)
"""
import json, os, time
from PIL import Image, ImageDraw, ImageFont

W, H = 350, 230
BG = (0, 0, 0, 0)
TRACK_RGBA = (255, 255, 255, 35)
WHITE = (255, 255, 255, 235)
GREY = (160, 160, 160, 180)

GREEN = (90, 247, 142, 230)
ORANGE = (255, 179, 71, 230)
RED = (255, 110, 110, 230)
YELLOW = (255, 215, 0, 230)
BLUE = (94, 184, 255, 235)

FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
FONT_REG = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
OUTPUT = '/tmp/ollama_pie.png'
STATS_FILE = '/tmp/ollama_cloud_stats.json'


def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                data = json.load(f)
                age = time.time() - os.path.getmtime(STATS_FILE)
                data['_age_s'] = int(age)
                return data
        except Exception:
            pass
    return None


def usage_color(pct):
    if pct < 50: return GREEN
    if pct < 75: return YELLOW
    if pct < 90: return ORANGE
    return RED


def arc_rgba(img, cx, cy, r, lw, start_deg, end_deg, color):
    S = 4
    ow, oh = img.size
    big = Image.new('RGBA', (ow * S, oh * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
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
    LW = int(R * 0.28)
    DEG0 = -90
    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK_RGBA)
    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        sweep = capped / 100.0 * 360.0
        arc_rgba(img, cx, cy, R - LW // 2, LW, DEG0, DEG0 + sweep, clr)
    draw = ImageDraw.Draw(img)
    txt = f'{capped:.0f}%'
    fs = max(14, int(R * 0.42))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        fnt = ImageFont.load_default()
    text_centered(draw, txt, cx, cy - 4, fnt, WHITE)
    try:
        fnt2 = ImageFont.truetype(FONT_BOLD, 10)
    except Exception:
        fnt2 = ImageFont.load_default()
    text_centered(draw, label, cx, cy + R + 10, fnt2, clr)
    try:
        fnt3 = ImageFont.truetype(FONT_REG, 9)
    except Exception:
        fnt3 = ImageFont.load_default()
    text_centered(draw, sublabel, cx, cy + R + 22, fnt3, GREY)


# ─── Main ──────────────────────────────────────────────────────────

stats = load_stats()

img = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

try:
    fnt_bold_11 = ImageFont.truetype(FONT_BOLD, 11)
    fnt_reg_9 = ImageFont.truetype(FONT_REG, 9)
    fnt_reg_8 = ImageFont.truetype(FONT_REG, 8)
    fnt_reg_7 = ImageFont.truetype(FONT_REG, 7)
except Exception:
    fnt_bold_11 = fnt_reg_9 = fnt_reg_8 = fnt_reg_7 = ImageFont.load_default()

if stats is None:
    text_centered(draw, 'SIN DATOS', W // 2, 80, fnt_bold_11, RED)
    text_centered(draw, 'Daemon no inicializado', W // 2, 100, fnt_reg_9, GREY)
    tmp = OUTPUT + '.tmp'
    img.save(tmp, format='PNG')
    os.replace(tmp, OUTPUT)
    raise SystemExit(0)

# Dos donuts centrados: Session y Weekly
R = 48
cx_s = W // 4
cy_s = H // 2 - 10
cx_w = 3 * W // 4
cy_w = H // 2 - 10

session_pct = stats.get('session_usage_pct', 0.0)
weekly_pct = stats.get('weekly_usage_pct', 0.0)

draw_donut(img, cx_s, cy_s, R, session_pct, 'SESSION', f'{stats.get("session_requests",0)} req', usage_color(session_pct))
draw_donut(img, cx_w, cy_w, R, weekly_pct, 'WEEKLY', f'{stats.get("weekly_requests",0)} req', usage_color(weekly_pct))

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)