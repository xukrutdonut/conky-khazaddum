#!/usr/bin/env python3
"""Panel de cuota de Ollama Cloud para Conky (datos reales de ollama.com/settings).

Dibuja dos anillos (sesión / semanal) con el porcentaje consumido, las peticiones,
el reinicio de cada ventana, el modelo implicado y la antigüedad del dato. Los
datos los obtiene `ollama_cloud_usage.py` (cookie de sesión de Chrome); aquí solo
se refrescan cuando el JSON tiene más de MIN_INTERVAL segundos.

Salida: /tmp/ollama_quota.png (350x204, fondo transparente).
Uso en conky:  ${execi 20 python3 /home/arkantu/.config/conky/ollama_quota_gen.py}
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

W, H = 350, 204
OUTPUT = '/tmp/ollama_quota.png'
DATA = '/tmp/conky_ollama_cloud.json'
FETCH = '/home/arkantu/.config/conky/ollama_cloud_usage.py'
VENV_PY = os.path.expanduser('~/.venvs/conky-ollama/bin/python')
MIN_INTERVAL = 60

BG = (0, 0, 0, 0)
BLUE = (94, 184, 255)
GREEN = (90, 247, 142)
RED = (255, 110, 110)
YELLOW = (255, 215, 0)
GREY = (160, 160, 160)
DIM = (115, 115, 115)
GRID = (255, 255, 255, 38)
WHITE = (255, 255, 255, 238)

FD = '/usr/share/fonts/truetype/dejavu/'
f_pct = ImageFont.truetype(FD + 'DejaVuSansMono-Bold.ttf', 17)
f_lbl = ImageFont.truetype(FD + 'DejaVuSansMono-Bold.ttf', 9)
f_num = ImageFont.truetype(FD + 'DejaVuSansMono.ttf', 11)
f_model = ImageFont.truetype(FD + 'DejaVuSansMono-Bold.ttf', 11)
f_xs = ImageFont.truetype(FD + 'DejaVuSansMono.ttf', 9)


def txt_c(d, s, x, y, font, fill):
    d.text((x - d.textlength(s, font=font) / 2, y), s, font=font, fill=fill)


def txt_r(d, s, x, y, font, fill):
    d.text((x - d.textlength(s, font=font), y), s, font=font, fill=fill)


def band(pct):
    if pct >= 85:
        return RED
    if pct >= 60:
        return YELLOW
    return GREEN


def load_data():
    try:
        with open(DATA) as f:
            return json.load(f)
    except Exception:
        return None


def refresh(data):
    """Relanza la consulta a ollama.com solo si el dato tiene más de MIN_INTERVAL s."""
    ts = (data or {}).get('ts', 0)
    if time.time() - ts < MIN_INTERVAL:
        return
    if not os.path.exists(VENV_PY):
        return
    try:
        subprocess.run([VENV_PY, FETCH], capture_output=True, timeout=45)
    except Exception:
        pass


def fmt_n(n):
    return f'{n / 1000:.1f}k'.replace('.0k', 'k') if n >= 10000 else str(n)


def until(iso):
    """Tiempo que falta hasta el reinicio de la ventana."""
    if not iso:
        return ''
    try:
        ts = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except ValueError:
        return ''
    secs = (ts - datetime.now(timezone.utc)).total_seconds()
    if secs <= 0:
        return 'reiniciando'
    hh, mm = int(secs // 3600), int(secs % 3600 // 60)
    if hh >= 24:
        return f'{hh // 24}d {hh % 24}h'
    return f'{hh}h {mm:02d}m' if hh else f'{mm}m'


def clock(iso):
    """Hora local del reinicio."""
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone().strftime('%H:%M')
    except Exception:
        return ''


def ring(d, cx, cy, r, width, pct, color):
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, 0, 360, fill=GRID, width=width)
    if pct > 0:
        d.arc(box, -90, -90 + min(360.0, 360.0 * pct), fill=color, width=width)


def local_status():
    """Versión del daemon local y modelo cargado en memoria."""
    ver = model = ''
    try:
        out = subprocess.run(['curl', '-s', '-m', '2', 'http://127.0.0.1:11434/api/version'],
                             capture_output=True, text=True, timeout=4).stdout
        ver = json.loads(out).get('version', '')
    except Exception:
        pass
    try:
        out = subprocess.run(['curl', '-s', '-m', '2', 'http://127.0.0.1:11434/api/ps'],
                             capture_output=True, text=True, timeout=4).stdout
        ps = json.loads(out).get('models', [])
        if ps:
            model = f"{ps[0].get('name', '?').split(':')[0]} {ps[0].get('size_vram', 0) / 2**30:.0f}G"
    except Exception:
        pass
    return model, ver


def render(data):
    img = Image.new('RGBA', (W, H), BG)
    d = ImageDraw.Draw(img)
    if not data or 'session' not in data:
        txt_c(d, 'sin datos de ollama.com', W // 2, 66, f_num, RED)
        txt_c(d, 'no se pudo leer la sesión guardada en Chrome', W // 2, 86, f_xs, DIM)
        img.save(OUTPUT)
        return

    s, wk = data['session'], data['weekly']
    cy, r, wdt = 62, 44, 13
    for cx, blk, label in ((97, s, 'SESIÓN'), (253, wk, 'SEMANAL')):
        pct = blk['pct'] / 100.0
        col = band(blk['pct'])
        ring(d, cx, cy, r, wdt, pct, col)
        txt_c(d, f"{blk['pct']:.1f}%", cx, cy - 17, f_pct, col if pct >= 0.85 else WHITE)
        txt_c(d, label, cx, cy + 7, f_lbl, col)
        txt_c(d, f"{fmt_n(blk['requests'])} pet", cx, cy + r + 8, f_num, GREY)
        hh = clock(blk.get('reset') or '')
        txt_c(d, 'reset ' + until(blk.get('reset')) + (f' · {hh}' if hh else ''), cx, cy + r + 20, f_xs, DIM)

    d.line([(16, 142), (W - 16, 142)], fill=(255, 255, 255, 30), width=1)

    models = s.get('models') or []
    if models:
        main = max(models, key=lambda m: m[1])
        name = main[0]
        while d.textlength(name, font=f_model) > W - 30 and len(name) > 8:
            name = name[:-2]
        txt_c(d, name if name == main[0] else name + '…', W // 2, 148, f_model, BLUE)
        sub = f"{fmt_n(main[1])} pet sesión · {fmt_n(wk['requests'])} semanal"
        if len(models) > 1:
            sub += f" · +{len(models) - 1} mod"
        txt_c(d, sub, W // 2, 165, f_xs, GREY)
    else:
        txt_c(d, 'sin peticiones en la sesión', W // 2, 152, f_num, DIM)

    age = max(0, int(time.time() - data.get('ts', 0)))
    if age < 120:
        when, col = 'ahora', DIM
    elif age < 3600:
        when, col = f'hace {age // 60} min', DIM
    elif age < 86400:
        when, col = f'hace {age // 3600} h', YELLOW
    else:
        when, col = f'hace {age // 86400} d', RED
    txt_c(d, when, 58, 186, f_xs, col)

    model, ver = local_status()
    right = (model + (' · ' if model and ver else '') + (f'v{ver}' if ver else '')).strip()
    if right:
        txt_r(d, right, W - 16, 186, f_xs, DIM)
    img.save(OUTPUT)


def main():
    data = load_data()
    refresh(data)
    render(load_data())
    return 0


if __name__ == '__main__':
    sys.exit(main())
