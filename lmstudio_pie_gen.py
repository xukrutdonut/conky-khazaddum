#!/usr/bin/env python3
import math
import subprocess
import json
import os
import re
import sys
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

W, H       = 350, 120
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
OUTPUT    = '/tmp/lmstudio_pie.png'

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

def draw_donut(img, cx, cy, R, pct, text_val, label, sublabel, clr):
    LW   = int(R * 0.28)
    DEG0 = -90

    arc_rgba(img, cx, cy, R - LW // 2, LW, 0, 360, TRACK_RGBA)

    capped = max(0.0, min(pct if pct is not None else 0.0, 100.0))
    if capped > 0.5:
        sweep = capped / 100.0 * 360.0
        arc_rgba(img, cx, cy, R - LW // 2, LW, DEG0, DEG0 + sweep, clr)

    draw = ImageDraw.Draw(img)

    fs  = max(10, int(R * 0.32))
    try:
        fnt = ImageFont.truetype(FONT_BOLD, fs)
    except Exception:
        fnt = ImageFont.load_default()
    text_centered(draw, text_val, cx, cy, fnt, WHITE)

    try:
        fnt2 = ImageFont.truetype(FONT_BOLD, 10)
    except Exception:
        fnt2 = ImageFont.load_default()
    text_centered(draw, label, cx, cy + R + 10, fnt2, clr)

    try:
        fnt3 = ImageFont.truetype(FONT_REG, 8)
    except Exception:
        fnt3 = ImageFont.load_default()
    text_centered(draw, sublabel, cx, cy + R + 21, fnt3, GREY)

# 1. Obtener datos de LM Studio
speed_val = 0.0
speed_str = "0 t/s"
speed_pct = 0.0
ctx_pct   = 0.0
ctx_str   = "0k"
ctx_sub   = "sin modelo"
status_clr = GREY_C
is_online = False

try:
    r = subprocess.run(
        ['/home/arkantu/.lmstudio/bin/lms', 'ps', '--json'],
        capture_output=True, text=True, timeout=2
    )
    if r.returncode == 0:
        is_online = True
        models = json.loads(r.stdout.strip()) if r.stdout.strip() else []
        if models:
            m = models[0]
            c_len = m.get('contextLength', 0)
            max_c = m.get('maxContextLength', 32768)
            if max_c > 0 and c_len > 0:
                ctx_pct = min(100.0, (c_len / max_c) * 100.0)
                ctx_str = f"{c_len // 1024}k" if c_len >= 1024 else str(c_len)
                ctx_sub = f"max {max_c // 1024}k"
            
            st = m.get('status', 'idle')
            if st in ['generating', 'generatingTokens']: status_clr = GREEN
            elif st in ['processingPrompt', 'eval']: status_clr = GOLD
            elif st in ['loading', 'loadingModel']: status_clr = BLUE
            else: status_clr = GREEN
except Exception:
    pass

# Buscar velocidad en logs
try:
    state_file = os.path.expanduser('~/.lmstudio/.internal/server-logs-state.json')
    log_path = None
    if os.path.exists(state_file):
        state = json.load(open(state_file))
        base = state.get('lastWrittenFile', {}).get('filePathBase', '')
        idx = state.get('lastWrittenFile', {}).get('index', 1)
        if base:
            log_path = os.path.expanduser(f'~/.lmstudio/server-logs/{base}{idx}.log')
    
    if log_path and os.path.exists(log_path):
        with open(log_path, 'r', errors='ignore') as f:
            lines = f.readlines()[-100:]
        for line in reversed(lines):
            m_speed = re.search(r'tg\s*=\s*([\d\.]+)\s*t/s', line)
            if m_speed:
                speed_val = float(m_speed.group(1))
                speed_str = f"{speed_val:.1f} t/s"
                # Escala 0-30 tok/s = 0-100%
                speed_pct = min(100.0, (speed_val / 30.0) * 100.0)
                break
except Exception:
    pass

img  = Image.new('RGBA', (W, H), BG)
draw = ImageDraw.Draw(img)

R  = 40
cy = 46
cx1, cx2 = W // 4, W * 3 // 4

draw.line([(W // 2, 4), (W // 2, cy + R + 24)], fill=DIVIDER, width=1)

draw_donut(img, cx1, cy, R, speed_pct, speed_str if speed_val > 0 else '—', 'VELOCIDAD', 'rendimiento', BLUE if speed_val > 0 else GREY_C)
draw_donut(img, cx2, cy, R, ctx_pct, ctx_str if is_online else 'OFF', 'CONTEXTO', ctx_sub, GREEN if ctx_pct > 0 else GREY_C)

tmp = OUTPUT + '.tmp'
img.save(tmp, format='PNG')
os.replace(tmp, OUTPUT)
