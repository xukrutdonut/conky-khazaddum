#!/usr/bin/env python3
"""
Genera /tmp/antigravity_pie.png compacto (H=210):
  - Donuts para modelos con cuota medida (Claude, GPT-OSS)
  - ÚNICAMENTE el tiempo de reinicio global (sin lista de modelos uno a uno)
"""

import math
import subprocess
import json
import os
import sys
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# ── Configuración visual ──────────────────────────────────────────
W, H       = 350, 210
BG         = (0, 0, 0, 0)           # transparente
TRACK_RGBA = (255, 255, 255, 35)    # anillo de fondo
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
CACHE_TTL  = 300  # segundos

# ── Obtener quota con caché ───────────────────────────────────────
def fetch_quota():
    if os.path.exists(CACHE_FILE):
        age = (datetime.now(timezone.utc).timestamp() -
               os.path.getmtime(CACHE_FILE))
        if age < CACHE_TTL:
            try:
                with open(CACHE_FILE) as f:
                    return json.load(f)
            except Exception:
                pass

    try:
        r = subprocess.run(
            [os.path.expanduser('~/.nvm/versions/node/v22.22.2/bin/antigravity-usage'), 'quota', '--json'],
            capture_output=True, text=True, timeout=20
        )
        data = json.loads(r.stdout)
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
        return data
    except Exception:
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return None

def quota_color(p):
    if p is None: return GREY_C
    if p < 20:    return RED
    if p < 40:    return ORANGE
    return GREEN

# ── Helpers PIL ──────────────────────────────────────────────────
def arc_rgba(img, cx, cy, r, lw, start_deg, end_deg, color):
    """Dibuja un arco antialiased perfectamente circular."""
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

def format_time_ms(ms):
    try:
        total_s = int(ms) // 1000
        if total_s <= 0:
            return 'ya'
        h = total_s // 3600
        m = (total_s % 3600) // 60
        if h > 0:
            return f'{h}h {m:02d}m'
        return f'{m}m'
    except Exception:
        return '—'

def format_reset(reset_iso):
    try:
        dt = datetime.fromisoformat(reset_iso.replace('Z', '+00:00'))
        local = dt.astimezone()
        return local.strftime('%H:%M')
    except Exception:
        return '—'

# ── Obtener datos ────────────────────────────────────────────────
data = fetch_quota()
models = data.get('models', []) if data else []

metered  = [m for m in models
            if m.get('remainingPercentage') is not None
            and not m.get('isAutocompleteOnly', False)
            and not 'gemini' in m.get('label', '').lower()]

if not metered:
    metered = [m for m in models if not m.get('isAutocompleteOnly', False)][:2]

# ── Composición Compacta ─────────────────────────────────────────
img  = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

# Donuts compactos (R=48, cy=58)
R = 48
cy_donut = 58

n_donuts = min(len(metered), 3)

if n_donuts == 0:
    try: fnt_lbl = ImageFont.truetype(FONT_BOLD, 11)
    except Exception: fnt_lbl = ImageFont.load_default()
    text_centered(draw, 'Sin datos de quota', W // 2, cy_donut, fnt_lbl, GREY)
elif n_donuts == 1:
    m = metered[0]
    pct   = (m['remainingPercentage'] * 100)
    clr   = quota_color(pct)
    label = m['label'][:12]
    draw_donut(img, W // 2, cy_donut, R, pct, label, 'restante', clr)
elif n_donuts == 2:
    positions = [W // 4, W * 3 // 4]
    draw.line([(W // 2, 6), (W // 2, cy_donut + R + 28)], fill=DIVIDER, width=1)
    for i, m in enumerate(metered[:2]):
        pct   = m['remainingPercentage'] * 100
        clr   = quota_color(pct)
        label = m['label'][:12]
        draw_donut(img, positions[i], cy_donut, R, pct, label, 'restante', clr)
else:
    R_sm = 40
    positions = [W // 6 + 5, W // 2, W * 5 // 6 - 5]
    for i, m in enumerate(metered[:3]):
        pct   = m['remainingPercentage'] * 100
        clr   = quota_color(pct)
        label = m['label'][:9]
        draw_donut(img, positions[i], cy_donut, R_sm, pct, label, 'restante', clr)

# ── Separador horizontal ──────────────────────────────────────────
sep_y = cy_donut + R + 34
draw.line([(4, sep_y), (W - 4, sep_y)], fill=DIVIDER, width=1)

# ── Sección 2: SOLO Tiempo de Reinicio Global ────────────────────
try:
    fnt_reset = ImageFont.truetype(FONT_BOLD, 12)
    fnt_title = ImageFont.truetype(FONT_BOLD, 11)
except Exception:
    fnt_reset = ImageFont.load_default()
    fnt_title = ImageFont.load_default()

model_ref = next((m for m in models if 'gemini' in m.get('label', '').lower() or 'gemini' in m.get('modelId', '').lower()), models[0] if models else None)
reset_ms  = model_ref.get('timeUntilResetMs') if model_ref else None
reset_at  = format_reset(model_ref.get('resetTime', '')) if model_ref else '—'

y = sep_y + 16
if reset_ms is not None:
    countdown = format_time_ms(reset_ms)
    reset_info = f"↺ Tiempo restante: {countdown} ({reset_at})"
else:
    reset_info = f"↺ Reinicio a las : {reset_at}"

draw.text((12, y), reset_info, font=fnt_reset, fill=BLUE)

# ── Guardar ──────────────────────────────────────────────────────
tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
