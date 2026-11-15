#!/usr/bin/env python3
"""
v100_therm_render.py — gráfica de líneas superpuestas (TEMP y RPM) de la V100.

Genera /tmp/conky_v100_therm.png (RGBA transparente) con DOS polilíneas sobre
el MISMÍSIMO panel, tal y como pide el usuario:
  - TEMP (°C): escala fija 0..100, verde (5af78e) <=78°C y rojo (ff6e6e) por arriba.
  - VENT (RPM): escala fija 0..8040 (máx S12038-8K), azul (5eb8ff) <=5000 RPM
    y naranja (ffb347) por encima.

La historia se mantiene en /tmp/conky_v100_therm.hist (ts temp rpm), ~15 min
(400 muestras a 3 s). Se invoca desde ${execi 3} en conky: cada llamada añade
la muestra actual, recorta la ventana y redibuja el PNG; conky lo muestra con
${image ... -n} en el ciclo siguiente.

Los valores vienen de:
  - /tmp/conky_v100.dat       (TEMP, escribo v100_stats.sh · nvidia-smi)
  - /tmp/conky_v100_fan.dat   (RPM,  escribe v100_fan_daemon.sh · RPi .101)
"""
import os
from PIL import Image, ImageDraw

W, H = 344, 48
OUTPUT = '/tmp/conky_v100_therm.png'
HIST = '/tmp/conky_v100_therm.hist'
MAX_SAMPLES = 400
KEEP_SECS = 900          # 15 min
BG = (0, 0, 0, 0)
GRID = (255, 255, 255, 40)

TEMP_MAX = 100.0
FAN_MAX = 8040.0
TEMP_HOT = 78
FAN_HOT = 5000

GREEN = (90, 247, 142, 235)
RED = (255, 110, 110, 235)
BLUE = (94, 184, 255, 235)
ORANGE = (255, 179, 71, 235)


def read_val(path, key):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + ':'):
                    return float(line.split(':', 1)[1].strip())
    except Exception:
        pass
    return None


def load_hist():
    out = []
    if os.path.exists(HIST):
        try:
            with open(HIST) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 3:
                        out.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except Exception:
            pass
    return out


def save_hist(h):
    tmp = HIST + '.tmp'
    with open(tmp, 'w') as f:
        for ts, t, r in h:
            f.write('%.0f %.0f %.0f\n' % (ts, t, r))
    os.replace(tmp, HIST)


def main():
    # -- 1. capturar muestra actual
    temp = read_val('/tmp/conky_v100.dat', 'TEMP')
    fan = read_val('/tmp/conky_v100_fan.dat', 'RPM')
    ts = os.time() if False else __import__('time').time()

    hist = load_hist()
    if temp is not None and fan is not None:
        if not hist or hist[-1][0] < ts - 1.0:
            hist.append((ts, temp, fan))
    # recortar ventana
    cut = ts - KEEP_SECS
    hist = [s for s in hist if s[0] >= cut][-MAX_SAMPLES:]

    img = Image.new('RGBA', (W, H), BG)
    draw = ImageDraw.Draw(img)

    # rejilla base
    draw.line([(0, H - 1), (W - 1, H - 1)], fill=GRID, width=1)
    for yf in (0.25, 0.5, 0.75, 1.0):
        draw.line([(0, int(H * yf)), (W - 1, int(H * yf))], fill=GRID, width=1)

    if len(hist) >= 2:
        # mapeo horizontal: la muestra más antigua a la izquierda
        def x_of(i):
            return int(W * i / (len(hist) - 1))

        def y_norm(v, vmax):
            return H - 1 - int((H - 3) * (min(v, vmax) / vmax))

        def trace(getter, vmax, c_low, c_high, thr):
            # dibujar segmento a segmento, color según el umbral de CADA extremo
            pts = [(x_of(i), y_norm(getter(s), vmax)) for i, s in enumerate(hist)]
            for a in range(len(pts) - 1):
                va = getter(hist[a])
                vb = getter(hist[a + 1])
                col = c_high if (va >= thr or vb >= thr) else c_low
                if (pts[a + 1][0] - pts[a][0]) > 0:
                    draw.line([pts[a], pts[a + 1]], fill=col, width=2)
            # último punto visible para densificar el extremo derecho
            draw.point(pts[-1], fill=c_high if getter(hist[-1]) >= thr else c_low)

        trace(lambda s: s[1], TEMP_MAX, GREEN, RED, TEMP_HOT)   # temp °C
        trace(lambda s: s[2], FAN_MAX, BLUE, ORANGE, FAN_HOT)   # vent RPM

    img.save(OUTPUT)
    # persistir historia recortada
    save_hist(hist)


if __name__ == '__main__':
    main()
