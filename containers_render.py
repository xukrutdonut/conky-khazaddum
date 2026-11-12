#!/usr/bin/env python3
"""Render para Conky: estado de los motores de inferencia locales
(contenedor OpenVINO de Intel Arc + contenedor ninfer-serve en V100)."""
import os
import re

DAT_FILE = '/tmp/conky_containers.dat'
HELPER_DIR = os.path.expanduser('~/.config/conky/state')


def helper(name):
    """Ruta persistente del helper (sobrevive reboots; /tmp no)."""
    return os.path.join(HELPER_DIR, name)


def write_helper(name, key):
    """Crea un script helper que extrae un valor del .dat para execgraph/execbar.

    Se reescribe SOLO si cambia el contenido y de forma atómica: Conky ejecuta
    estos scripts cada ciclo y reescribirlos siempre provocaba carreras
    ("Text file busy", "s.dat: not found" en el log de conky).
    """
    os.makedirs(HELPER_DIR, exist_ok=True)
    path = helper(name)
    content = (
        "#!/bin/sh\n"
        f"awk -F: '$1==\"{key}\" {{print $2; exit}}' {DAT_FILE}\n"
    )
    try:
        with open(path) as f:
            if f.read() == content:
                return path
    except OSError:
        pass
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(content)
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)
    return path


def bar(path, h=6):
    """Barra instantánea del valor que devuelve el helper."""
    return f"${{execbar {h},344 {path}}}"


def gpu_panel(data, key, label, extra=''):
    """Par de gráficas idéntico en los tres motores: barra instantánea + histórico.

    La barra (8 px) es el valor de este ciclo; el histórico son 2 filas de bloques
    (17 niveles, 46 columnas = 15 min) que mantiene el daemon en
    /tmp/conky_gpu_hist.json, así que no se vacía al reiniciar Conky como el
    buffer interno de execgraph.
    """
    path = write_helper(f'conky_{key.lower()}.sh', key)
    val = data.get(key, '0')
    lines = [f"${{color1}}{label} ${{color2}}{val}%${{color}}{extra}"]
    lines.append(f"${{color2}}{bar(path, 8)}${{color}}")
    top = data.get(key + '_SPARK_TOP', '')
    bot = data.get(key + '_SPARK_BOT', '')
    if top or bot:
        lines.append(top)
        lines.append(bot)
    else:
        lines.append('${color}sin histórico')
    return lines


def fmt_tok(n):
    """Tokens abreviados: 987 / 48.2k / 1.03M."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def fmt_age(sec):
    sec = int(sec)
    if sec < 0:
        return '-'
    if sec < 60:
        return f'{sec}s'
    if sec < 3600:
        return f'{sec//60}m'
    return f'{sec//3600}h{(sec%3600)//60:02d}'


def render():
    # Helpers siempre presentes: si faltan, Conky falla al evaluar execgraph
    write_helper('conky_intel_gpu_busy.sh', 'INTEL_GPU_BUSY')
    write_helper('conky_ninfer_cpu.sh', 'NINFER_CPU')
    write_helper('conky_ninfer_mem_used.sh', 'NINFER_MEM_USED')

    if not os.path.exists(DAT_FILE):
        print("${color4}${alignc}IA GPU${color}")
        print("${color1}${alignc}Esperando datos...${color}")
        return

    data = {}
    with open(DAT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or ':' not in line:
                continue
            k, v = line.split(':', 1)
            data[k] = v

    print("${color4}${alignc}IA GPU CONTAINERS${color}")
    print("${hr 1}")

    # ══════════ Intel — OpenVINO ══════════
    running = data.get('INTEL_RUNNING', '0') == '1'
    print("${color4}── Intel Arc — OpenVINO GenAI ──${color}")
    if not running:
        print(f"${{color3}}Estado: {data.get('INTEL_STATUS', 'unknown')}${{color}}")
        print("${color1}:8006${color}  ${color3}DETENIDO${color}")
    else:
        health = data.get('INTEL_HEALTH', '?')
        n_load = int(data.get('INTEL_NUM_LOADED', '0'))
        n_avail = int(data.get('INTEL_NUM_AVAIL', '0'))
        hc = 'color2' if health == 'ready' else 'color5'
        print(f"${{color1}}Estado: ${{{hc}}}{health}${{color}}  ${{color1}}:8006${{color}}")
        total_mb = sum(int(float(data.get(f'INTEL_M{i}_SIZE', '0'))) for i in range(n_load))
        print(f"${{color1}}Peso: ${{color2}}{total_mb/1024:.1f} GB${{color}}  ${{color1}}Modelos: ${{color2}}{n_load}${{color}}")
        if n_load:
            for i in range(n_load):
                name = data.get(f'INTEL_M{i}_NAME', '?')
                mtype = data.get(f'INTEL_M{i}_TYPE', '?')
                size = int(float(data.get(f'INTEL_M{i}_SIZE', '0')))
                short = name if len(name) <= 30 else name[:27] + '...'
                print(f"${{color2}}▶ {short}${{color}} ${{color1}}({mtype}, {size} MB)${{color}}")
        else:
            print("${color5}(Sin modelos cargados)${color}")
        pwr = float(data.get('INTEL_GPU_PWR', '0') or 0)
        for line in gpu_panel(data, 'INTEL_GPU_BUSY', 'Uso GPU OVMS:',
                              f" · Pwr {pwr:.0f} W" if pwr > 0 else ''):
            print(line)
        if n_avail:
            names = []
            for i in range(min(n_avail, 4)):
                a = data.get(f'INTEL_A{i}_NAME', '')
                if a:
                    names.append(a if len(a) <= 20 else a[:17] + '...')
            if names:
                print(f"${{color1}}Disponibles: ${{color}}{', '.join(names)}${{color}}")

    # ══════════ Ninfer — V100 :8090 ══════════
    print()
    print("${color4}── Ninfer — NVIDIA V100 ──${color}")
    running = data.get('NINFER_RUNNING', '0') == '1'
    if not running:
        print(f"${{color3}}Estado: {data.get('NINFER_STATUS', 'unknown')}${{color}}")
        print("${color1}:8090${color}  ${color3}DETENIDO${color}")
    else:
        cpu = float(data.get('NINFER_CPU', '0'))
        mem_u = float(data.get('NINFER_MEM_USED', '0'))
        mem_t = float(data.get('NINFER_MEM_TOTAL', '0'))
        n_workers = int(data.get('NINFER_WORKERS', '0'))
        kv_cache = float(data.get('NINFER_KV_CACHE_PCT', '0'))
        total_vram = float(data.get('NINFER_VRAM_TOTAL', '0'))
        used_vram = float(data.get('NINFER_VRAM_USED', '0'))
        
        # Estado general
        status_text = data.get('NINFER_HEALTH', 'ready')
        sc = 'color2' if status_text == 'ready' else 'color5'
        print(f"${{color1}}Estado: ${{{sc}}}{status_text}${{color}}  ${{color1}}:8090${{color}}")
        
        # Modelo cargado y cuantos workers
        model = data.get('NINFER_MODEL', '?')
        quant = data.get('NINFER_QUANT', '?')
        ctx = data.get('NINFER_CTX', '0')
        short = model if len(model) <= 30 else model[:27] + '...'
        print(f"${{color2}}▶ {short}${{color}} ${{color1}}({quant}, ctx {ctx})${{color}}")
        print(f"${{color1}}Workers: ${{color2}}{n_workers}${{color}}  "
              f"${{color1}}CPU: ${{color2}}{cpu}%${{color}}  "
              f"${{color1}}RAM: ${{color2}}{mem_u/1024:.1f}/{mem_t/1024:.1f} GB${{color}}")
        
        # VRAM (de v100_stats.sh si está disponible)
        if total_vram > 0:
            print(f"${{color1}}VRAM: ${{color2}}{used_vram:.0f}/{total_vram:.0f} GB ({kv_cache:.0f}% KV cache)${{color}}")
            for line in gpu_panel(data, 'LM_GPU', 'Uso GPU V100:', ''):
                print(line)
        else:
            for line in gpu_panel(data, 'LM_GPU', 'Uso GPU V100:', ''):
                print(line)

if __name__ == '__main__':
    render()
