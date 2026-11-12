#!/usr/bin/env python3
"""
Genera /tmp/nous_pie.png - dashboard de consumo Nous Portal.
Lee /tmp/nous_stats.json (escrito por fetch_nous_stats.py).

Layout: 3 donuts (DÍA / SEMANA / MES) con el % usado del plan de ventana,
pie con plan, cobro y reset del mes. Si el dato está stale o no hay auth,
se pone un aviso en vez de números falsos.
"""
import json
import os
import time
from datetime import datetime, timezone

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
OUTPUT = '/tmp/nous_pie.png'
STATS_FILE = '/tmp/nous_stats.json'

MAX_STALE = 20 * 60  # 20 min sin refresco del daemon == sospechoso


def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def usage_color(pct):
    if pct < 50:
        return GREEN
    if pct < 75:
        return YELLOW
    if pct < 90:
        return ORANGE
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
    fs = max(11, int(R * 0.36))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
        fnt2 = ImageFont.truetype(FONT_BOLD, 9)
        fnt3 = ImageFont.truetype(FONT_REG, 7)
    except Exception:
        fnt = fnt2 = fnt3 = ImageFont.load_default()
    text_centered(draw, center_txt, cx, cy, fnt, WHITE)
    text_centered(draw, label, cx, cy + R + 8, fnt2, clr)
    text_centered(draw, sublabel, cx, cy + R + 19, fnt3, GREY)


# ─── Main ──────────────────────────────────────────────────────────
stats = load_stats()
img = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)
try:
    f_lbl = ImageFont.truetype(FONT_BOLD, 11)
    f_sm = ImageFont.truetype(FONT_REG, 9)
    f_xs = ImageFont.truetype(FONT_REG, 8)
except Exception:
    f_lbl = f_sm = f_xs = ImageFont.load_default()


def finish(placeholder_text, why):
    """Silueta mínima con el motivo, sin falsos datos."""
    if placeholder_text:
        text_centered(draw, placeholder_text, W // 2, H // 2 - 10, f_lbl, RED)
    text_centered(draw, why, W // 2, H // 2 + 10, f_xs, GREY)
    tmp = OUTPUT + '.tmp'
    img.save(tmp, format='PNG')
    os.replace(tmp, OUTPUT)
    raise SystemExit(0)


if not stats or not stats.get('ok'):
    finish('SIN DATOS', 'Nous Portal inaccesible')
if stats.get('need_relogin'):
    finish('SESIÓN', 'hay que reloguear en Hermes')
now = time.time()
age = now - stats.get('ts', now)
if stats.get('stale'):
    finish('STALE', f'datos de hace {int(age // 60)} min')

gauges = stats.get('gauges') or {}

# Donuts DÍA / SEMANA / MES  (centros fijos como en openrouter)
gx = [92, 175, 258]
order = [('day', 'DÍA'), ('week', 'SEMANA'), ('month', 'MES')]
for (gid, label), cx in zip(order, gx):
    g = gauges.get(gid) or {}
    pct = float(g.get('pct', 0) or 0)
    draw_donut(img, cx, 72, 40, pct,
               f'{pct:.0f}%', label, 'USADO', usage_color(pct))

# Sep
draw.line([(20, 138), (W - 20, 138)], fill=(255, 255, 255, 45), width=1)

# Pie: plan + cobro + reset del mes / créditos
plan = stats.get('plan') or 'Nous'
charge = stats.get('monthly_charge')
cred = stats.get('credits_remaining')
line1 = plan
if charge:
    line1 += f' · €{charge}/mo'
if cred is not None and cred > 0:
    line1 += f' · {cred} cr'
text_centered(draw, line1, W // 2, 158, f_lbl, BLUE)

for k, lbl in (('current_period_end', 'RESET MES'),):
    v = stats.get(k)
    if v:
        try:
            dt = datetime.fromisoformat(str(v).replace('Z', '+00:00')).astimezone()
            s = f'{lbl}: {dt.strftime("%d %b")}'
        except ValueError:
            s = f'{lbl}: {v}'
        break
else:
    s = ''
text_centered(draw, s, W // 2, 180, f_sm, GREY)

ms = stats.get('member_spend_usd')
cap = stats.get('member_spend_cap_usd')
if ms is not None:
    foot = f'gasto miembro ${ms}'
    if cap:
        foot += f' / ${cap}'
    text_centered(draw, foot, W // 2, 202, f_xs, GREY)

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
