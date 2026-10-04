#!/usr/bin/env python3
"""
Genera /tmp/openrouter_pie.png - dashboard de consumo OpenRouter.
Lee /tmp/openrouter_stats.json (escrito por fetch_openrouter_stats.py).

Layout:
  - Donut izq : LIMITE MES  (% de uso mensual de la key vs su limite $)
  - Donut der : SALDO       (% de saldo restante sobre creditos comprados)
  - Centro-abajo: nº de peticiones ESTA SEMANA (grande)
  - Pie: peticiones hoy, gasto semana/mes
"""
import json, os
from PIL import Image, ImageDraw, ImageFont

W, H = 350, 230
BG = (0, 0, 0, 0)
TRACK = (255, 255, 255, 35)
WHITE = (255, 255, 255, 235)
GREY = (160, 160, 160, 180)

GREEN = (90, 247, 142, 230)
ORANGE = (255, 179, 71, 230)
RED = (255, 110, 110, 230)
YELLOW = (255, 215, 0, 230)
BLUE = (94, 184, 255, 235)

FONT_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
FONT_REG = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
OUTPUT = '/tmp/openrouter_pie.png'
STATS_FILE = '/tmp/openrouter_stats.json'


def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
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
    bx, by, br, blw = cx * S, cy * S, r * S, max(1, lw * S)
    d.arc([bx - br, by - br, bx + br, by + br], start=start_deg, end=end_deg,
          fill=color, width=int(blw))
    img.alpha_composite(big.resize((ow, oh), Image.LANCZOS))


def text_centered(draw, text, cx, cy, font, color):
    bb = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bb[2] - bb[0]) // 2, cy - (bb[3] - bb[1]) // 2 - bb[1] // 2),
              text, font=font, fill=color)


def draw_donut(img, cx, cy, R, pct, center_txt, label, sublabel, clr):
    LW = int(R * 0.28)
    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK)
    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        arc_rgba(img, cx, cy, R - LW // 2, LW, -90, -90 + capped / 100.0 * 360.0, clr)
    draw = ImageDraw.Draw(img)
    fs = max(12, int(R * 0.40))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
        fnt2 = ImageFont.truetype(FONT_BOLD, 9)
        fnt3 = ImageFont.truetype(FONT_REG, 8)
    except Exception:
        fnt = fnt2 = fnt3 = ImageFont.load_default()
    text_centered(draw, center_txt, cx, cy, fnt, WHITE)
    text_centered(draw, label, cx, cy + R + 9, fnt2, clr)
    text_centered(draw, sublabel, cx, cy + R + 21, fnt3, GREY)


# ─── Main ──────────────────────────────────────────────────────────
stats = load_stats()
img = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)
try:
    f_big = ImageFont.truetype(FONT_BOLD, 30)
    f_lbl = ImageFont.truetype(FONT_BOLD, 10)
    f_sm = ImageFont.truetype(FONT_REG, 9)
    f_xs = ImageFont.truetype(FONT_REG, 8)
except Exception:
    f_big = f_lbl = f_sm = f_xs = ImageFont.load_default()

if not stats or not stats.get('ok'):
    text_centered(draw, 'SIN DATOS', W // 2, H // 2 - 12, f_lbl, RED)
    text_centered(draw, 'OpenRouter inaccesible', W // 2, H // 2 + 8, f_xs, GREY)
    tmp = OUTPUT + '.tmp'; img.save(tmp, format='PNG'); os.replace(tmp, OUTPUT)
    raise SystemExit(0)

um = stats.get('usage_monthly')
lim = stats.get('limit')
pct_mes = (um / lim * 100.0) if (um is not None and lim) else 0.0
bal = stats.get('balance')
cred = stats.get('total_credits')
pct_saldo = (bal / cred * 100.0) if (bal is not None and cred) else 0.0

# Valores en EUR (convertidos en el daemon)
em  = stats.get('eur_month')
el  = stats.get('eur_limit')
eb  = stats.get('eur_balance')
ec  = stats.get('eur_credits')
ew  = stats.get('eur_week')
ed  = stats.get('eur_daily')

# Donuts
draw_donut(img, 92, 68, 40, pct_mes,
           f'€{em:.2f}' if em is not None else '—', 'CONSUMO MES',
           f'{pct_mes:.0f}% de €{el:.0f}' if el else '',
           usage_color(pct_mes) if pct_mes < 100 else RED)
draw_donut(img, 258, 68, 40, pct_saldo,
           f'€{eb:.2f}' if eb is not None else '—', 'SALDO',
           f'{pct_saldo:.0f}% de €{ec:.0f}' if ec else '',
           GREEN if pct_saldo > 50 else ORANGE if pct_saldo > 20 else RED)

# Sep
draw.line([(20, 138), (W - 20, 138)], fill=(255, 255, 255, 45), width=1)

# Peticiones esta semana (grande)
rw = stats.get('requests_week')
txt = f'{rw:,}'.replace(',', '.') if rw is not None else '—'
text_centered(draw, txt, W // 2, 170, f_big, BLUE)
text_centered(draw, 'PETICIONES ESTA SEMANA', W // 2, 195, f_lbl, WHITE)

# Pie: peticiones hoy + consumo hoy / 7d (EUR)
rt = stats.get('requests_today')
foot = (f'hoy {rt if rt is not None else "—"} req  ·  '
        f'€{ed or 0:.2f} hoy  ·  €{ew or 0:.2f} 7d')
text_centered(draw, foot, W // 2, 216, f_xs, GREY)

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
