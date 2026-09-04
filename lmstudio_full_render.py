#!/usr/bin/env python3
import json
import os
import stat

DAT_FILE = '/tmp/conky_lmstudio.dat'

def ensure_helper(path, content):
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

def render():
    if not os.path.exists(DAT_FILE):
        print("${color4}${alignc}LM STUDIO SERVER${color}")
        print("${color1}${alignc}localhost:1234 — ${color3}OFFLINE${color}")
        print("${hr 1}")
        print("${color6}${alignc}(Servidor no iniciado)${color}")
        return

    data = {}
    logs_raw = ""
    with open(DAT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('LOGS:'):
                logs_raw = line[5:]
            elif ':' in line:
                k, v = line.split(':', 1)
                data[k] = v

    online = data.get('ONLINE', '0') == '1'
    state = data.get('STATE', 'OFFLINE')
    num_models = int(data.get('NUM_MODELS', '0'))

    print("${color4}${alignc}LM STUDIO SERVER${color}")
    if online:
        print(f"${{color1}}${{alignc}}localhost:1234 — ${{color2}}{state}${{color}}")
    else:
        print("${color1}${alignc}localhost:1234 — ${color3}OFFLINE${color}")
    print("${hr 1}")

    if not online:
        print("${color6}${alignc}(Servidor no iniciado)${color}")
    elif num_models == 0:
        print("${color6}${alignc}(Sin modelos cargados en memoria)${color}")
    else:
        for i in range(num_models):
            title = data.get(f'M{i}_TITLE', f'Modelo #{i+1}')
            hw = data.get(f'M{i}_HW', 'CPU Host')
            cfg = data.get(f'M{i}_CFG', '—')
            arch = data.get(f'M{i}_ARCH', '—')
            act = data.get(f'M{i}_ACT', 'Inactivo')
            spd_txt = data.get(f'M{i}_SPD_TXT', '0.00 tok/s')
            ctx_used = data.get(f'M{i}_CTX_USED', '0')
            ctx_max = data.get(f'M{i}_CTX_MAX', '0')
            ctx_pct = data.get(f'M{i}_CTX_PCT', '0')

            spd_script = f"/tmp/lms_m{i}_spd.sh"
            ctx_script = f"/tmp/lms_m{i}_ctx.sh"

            ensure_helper(spd_script, f"#!/bin/sh\nawk -F: '$1==\"M{i}_SPD_PCT\" {{print $2; exit}}' /tmp/conky_lmstudio.dat\n")
            ensure_helper(ctx_script, f"#!/bin/sh\nawk -F: '$1==\"M{i}_CTX_PCT\" {{print $2; exit}}' /tmp/conky_lmstudio.dat\n")

            header = f"── MODELO #{i+1} ─ {title} "
            header = header + ("─" * max(0, 48 - len(header)))
            print(f"${{color4}}{header[:48]}${{color}}")
            # 1. HARDWARE EN PRIMER LUGAR
            print(f"${{color1}}Hardware:  ${{color4}}{hw}${{color}}")
            print(f"${{color1}}Config:    ${{color2}}{cfg}${{color}}  ${{color1}}Arch: ${{color2}}{arch}${{color}}")
            print(f"${{color1}}Actividad: ${{color2}}{act}${{color}}")
            print(f"${{color1}}Velocidad: ${{color2}}{spd_txt}${{color}}")
            print(f"${{execbar 4,344 {spd_script}}}")
            print(f"${{color1}}Contexto:  ${{color2}}{ctx_used} / {ctx_max}${{color}}  (${{color5}}{ctx_pct}%${{color}})")
            print(f"${{execbar 4,344 {ctx_script}}}")

    print("${color4}── LOGS DE DESARROLLADOR ────────────────────────${color}")
    if logs_raw and logs_raw != "${color6}(Sin logs recientes)${color}":
        for l in logs_raw.split('@@@'):
            print(l)
    else:
        print("${color6}(Sin logs recientes)${color}")

if __name__ == '__main__':
    render()
