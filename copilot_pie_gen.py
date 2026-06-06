#!/usr/bin/env python3
"""
Genera /tmp/copilot_pie.png con dos donuts:
  izquierda → % contexto usado en sesión activa
  derecha   → % cuota premium restante
"""

import math
import subprocess
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont

# ── Configuración visual ──────────────────────────────────────────
W, H       = 350, 290
BG         = (0, 0, 0, 0)          # transparente
TRACK_RGBA = (255, 255, 255, 35)   # anillo de fondo
WHITE      = (255, 255, 255, 235)
GREY       = (160, 160, 160, 180)

GREEN  = (90,  247, 142, 230)
ORANGE = (255, 179,  71, 230)
RED    = (255, 110, 110, 230)
GREY_C = (136, 136, 136, 200)

FONT_BOLD  = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
FONT_REG   = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
OUTPUT     = '/tmp/copilot_pie.png'

# ── Leer valores ─────────────────────────────────────────────────
def run(script):
    try:
        r = subprocess.run(script, shell=True, capture_output=True, text=True, timeout=10)
        v = r.stdout.strip()
        return float(v)
    except Exception:
        return None

ctx_pct   = run('~/.config/conky/copilot_context.sh')
quota_pct = run('~/.config/conky/copilot_quota.sh')

# Reset date desde caché
reset_date = '—'
try:
    with open('/tmp/copilot_quota_cache.json') as f:
        reset_date = json.load(f).get('quota_reset_date', '—')
except Exception:
    pass

# ── Color dinámico ───────────────────────────────────────────────
def ctx_color(p):
    if p is None: return GREY_C
    if p > 80:    return RED
    if p > 55:    return ORANGE
    return GREEN

def quota_color(p):
    if p is None: return GREY_C
    if p < 20:    return RED
    if p < 40:    return ORANGE
    return GREEN

# ── Helpers PIL ──────────────────────────────────────────────────
def arc_rgba(img, cx, cy, r, lw, start_deg, end_deg, color):
    """Dibuja un arco antialiased simulado con oversample x4."""
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
    LW    = int(R * 0.30)
    DEG0  = -90           # inicio en la parte superior

    # Track completo
    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK_RGBA)

    # Arco de valor
    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        sweep = capped / 100.0 * 360.0
        arc_rgba(img, cx, cy, R - LW // 2, LW, DEG0, DEG0 + sweep, clr)

    draw = ImageDraw.Draw(img)

    # Porcentaje central
    txt = f'{capped:.0f}%' if pct is not None else 'N/A'
    fs  = max(12, int(R * 0.32))
    try: fnt = ImageFont.truetype(FONT_BOLD, fs)
    except: fnt = ImageFont.load_default()
    text_centered(draw, txt, cx, cy, fnt, WHITE)

    # Etiqueta principal
    try: fnt2 = ImageFont.truetype(FONT_BOLD, 13)
    except: fnt2 = ImageFont.load_default()
    text_centered(draw, label, cx, cy + R + 14, fnt2, clr)

    # Subetiqueta
    try: fnt3 = ImageFont.truetype(FONT_REG, 10)
    except: fnt3 = ImageFont.load_default()
    text_centered(draw, sublabel, cx, cy + R + 30, fnt3, GREY)

# ── Composición ──────────────────────────────────────────────────
img = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

R  = 82
cy = 145
cx1, cx2 = W // 4, W * 3 // 4

# Divisor vertical
draw.line([(W // 2, 10), (W // 2, cy + R + 45)], fill=(255, 215, 0, 45), width=1)

# Donuts
draw_donut(img, cx1, cy, R, ctx_pct,   'CONTEXTO',
           'sin sesión' if ctx_pct is None else 'sesión activa', ctx_color(ctx_pct))
draw_donut(img, cx2, cy, R, quota_pct, 'CUOTA',
           'restante', quota_color(quota_pct))

# Línea de detalle inferior
try: fnt_d = ImageFont.truetype(FONT_REG, 9)
except: fnt_d = ImageFont.load_default()
line = f'Reset: {reset_date}'
bb = draw.textbbox((0, 0), line, font=fnt_d)
tw = bb[2] - bb[0]
draw.text(((W - tw) // 2, H - 16), line, font=fnt_d, fill=(94, 184, 255, 160))

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
