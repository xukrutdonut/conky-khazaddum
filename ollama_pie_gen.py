#!/usr/bin/env python3
"""
Genera /tmp/ollama_pie.png - dashboard real de Ollama Cloud.
Lee /tmp/ollama_cloud_stats.json (escrito por fetch_ollama_cloud_stats.py).

Muestra:
  - Donut principal: score de salud general (0-100)
  - 4 metricas clave: servidor, cloud, latencia, modelos
  - Estado textual: OK / DEGRADADO / CAIDO
  - Modelo activo + TPS
"""
import json, os, time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

W, H = 350, 230
BG = (0, 0, 0, 0)
TRACK_RGBA = (255, 255, 255, 35)
WHITE = (255, 255, 255, 235)
GREY = (160, 160, 160, 180)
DIVIDER = (130, 200, 255, 40)

GREEN = (90, 247, 142, 230)
ORANGE = (255, 179, 71, 230)
RED = (255, 110, 110, 230)
GREY_C = (136, 136, 136, 200)
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


def health_color(p):
    if p is None: return GREY_C
    if p < 40: return RED
    if p < 70: return ORANGE
    return GREEN


def status_text(status):
    if status == 'OK': return 'OPERATIVO', GREEN
    if status == 'DEGRADADO': return 'DEGRADADO', ORANGE
    return 'CAIDO', RED


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


def text_left(draw, text, x, y, font, color):
    draw.text((x, y), text, font=font, fill=color)


def draw_donut(img, cx, cy, R, pct, label, sublabel, clr):
    LW = int(R * 0.28)
    DEG0 = -90
    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK_RGBA)
    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        sweep = capped / 100.0 * 360.0
        arc_rgba(img, cx, cy, R - LW // 2, LW, DEG0, DEG0 + sweep, clr)
    draw = ImageDraw.Draw(img)
    txt = f'{capped:.0f}' if pct is not None else 'N/A'
    fs = max(14, int(R * 0.42))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        fnt = ImageFont.load_default()
    text_centered(draw, txt, cx, cy - 4, fnt, WHITE)
    try:
        fnt_pct = ImageFont.truetype(FONT_REG, 9)
    except Exception:
        fnt_pct = ImageFont.load_default()
    text_centered(draw, '/100', cx, cy + fs // 2 + 2, fnt_pct, GREY)
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


def draw_check(draw, x, y, ok, font, label):
    icon = '\u2713' if ok else '\u2717'
    clr = GREEN if ok else RED
    text_left(draw, f'{icon} ', x, y, font, clr)
    text_left(draw, label, x + 16, y, font, WHITE if ok else GREY)


def fmt_ms(ms):
    if ms is None or ms == 0: return '\u2014'
    if ms >= 1000: return f'{ms/1000:.1f}s'
    return f'{ms}ms'


# ─── Main ──────────────────────────────────────────────────────────

stats = load_stats()

img = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

try:
    fnt_bold_11 = ImageFont.truetype(FONT_BOLD, 11)
    fnt_bold_10 = ImageFont.truetype(FONT_BOLD, 10)
    fnt_reg_10 = ImageFont.truetype(FONT_REG, 10)
    fnt_reg_9 = ImageFont.truetype(FONT_REG, 9)
    fnt_reg_8 = ImageFont.truetype(FONT_REG, 8)
except Exception:
    fnt_bold_11 = fnt_bold_10 = fnt_reg_10 = fnt_reg_9 = fnt_reg_8 = ImageFont.load_default()

if stats is None:
    # Sin datos - el daemon no ha corrido
    text_centered(draw, 'SIN DATOS', W // 2, 80, fnt_bold_11, RED)
    text_centered(draw, 'Daemon no inicializado', W // 2, 100, fnt_reg_9, GREY)
    tmp = OUTPUT + '.tmp'
    img.save(tmp, format='PNG')
    os.replace(tmp, OUTPUT)
    raise SystemExit(0)

health = stats.get('health', 0)
status = stats.get('status', 'CAIDO')
status_lbl, status_clr = status_text(status)

# Donut de salud a la izquierda
R = 42
cx_donut = 60
cy_donut = 55
draw_donut(img, cx_donut, cy_donut, R, health, 'SALUD', 'score', health_color(health))

# Panel derecho con detalles
px = 125
py = 18

# Estado general
text_left(draw, 'Estado:', px, py, fnt_reg_10, BLUE)
text_left(draw, status_lbl, px + 48, py, fnt_bold_11, status_clr)
py += 18

# Checks individuales
draw_check(draw, px, py, stats.get('server_up', False), fnt_reg_10, f"Ollama ({fmt_ms(stats.get('server_latency_ms', 0))})")
py += 15

draw_check(draw, px, py, stats.get('cloud_reachable', False), fnt_reg_10, f"Cloud TCP ({fmt_ms(stats.get('cloud_tcp_ms', 0))})")
py += 15

draw_check(draw, px, py, stats.get('cloud_ok', False), fnt_reg_10, f"Inference ({fmt_ms(stats.get('cloud_latency_ms', 0))})")
py += 15

# Modelos cloud
n_models = stats.get('cloud_model_count', 0)
text_left(draw, f'Modelos cloud: {n_models}', px, py, fnt_reg_10, WHITE if n_models else GREY)
py += 15

# Cargados en memoria
n_loaded = stats.get('loaded_count', 0)
clr_loaded = ORANGE if n_loaded > 0 else GREY
text_left(draw, f'En memoria: {n_loaded}', px, py, fnt_reg_10, clr_loaded)
py += 15

# TPS si hay inference ok
tps = stats.get('cloud_tps', 0)
if tps > 0:
    text_left(draw, f'Cloud TPS: {tps}', px, py, fnt_reg_10, GREEN)
    py += 15

# Separador
sep_y = cy_donut + R + 16
draw.line([(8, sep_y), (W - 8, sep_y)], fill=DIVIDER, width=1)

# Modelo activo abajo
py = sep_y + 8
active = stats.get('active_model', '')
if active:
    # Truncar nombre si es muy largo
    short = active if len(active) <= 28 else active[:25] + '...'
    text_left(draw, 'Modelo:', 12, py, fnt_reg_9, BLUE)
    text_left(draw, short, 56, py, fnt_reg_9, WHITE)
    py += 14

# Modelos cloud listados
models = stats.get('cloud_models', [])
for mname in models[:3]:
    short = mname if len(mname) <= 32 else mname[:29] + '...'
    text_left(draw, f'  {short}', 12, py, fnt_reg_8, GREY)
    py += 12

# Timestamp + age
age = stats.get('_age_s', 0)
age_str = f'hace {age}s' if age < 60 else f'hace {age//60}m'
ts = stats.get('timestamp', '')
text_left(draw, f'{ts} ({age_str})', W - 110, H - 14, fnt_reg_8, GREY)

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)