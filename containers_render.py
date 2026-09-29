#!/usr/bin/env python3
"""Render para conky: muestra estado de contenedores IA (Intel OpenVINO + AMD RX480)."""
import os
import stat

DAT_FILE = '/tmp/conky_containers.dat'

def ensure_helper(path, key):
    """Crea un script helper en /tmp que extrae un valor del .dat para execbar."""
    content = f"#!/bin/sh\nawk -F: '$1==\"{key}\" {{print $2; exit}}' {DAT_FILE}\n"
    needs_write = True
    if os.path.exists(path):
        with open(path) as f:
            needs_write = f.read() != content
    if needs_write:
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

def render():
    # Asegurar scripts helper para las barras
    ensure_helper('/tmp/conky_intel_tps.sh', 'INTEL_TPS_PCT')
    ensure_helper('/tmp/conky_amd_tps.sh', 'AMD_TPS_PCT')

    if not os.path.exists(DAT_FILE):
        print("${color4}${alignc}IA CONTAINERS${color}")
        print("${color1}${alignc}Esperando datos...${color}")
        return

    data = {}
    with open(DAT_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or ':' not in line:
                continue
            k, v = line.split(':', 1)
            data[k] = v

    # ── Cabecera ──
    print("${color4}${alignc}IA GPU CONTAINERS${color}")
    print("${hr 1}")

    # ══════════ INTEL OPENVINO ══════════
    intel_running = data.get('INTEL_RUNNING', '0') == '1'
    print("${color4}── Intel Arc — OpenVINO GenAI ──${color}")
    if not intel_running:
        status = data.get('INTEL_STATUS', 'unknown')
        print(f"${{color3}}Estado: {status}${{color}}")
        print("${color1}:8006${color}  ${color3}DETENIDO${color}")
    else:
        health = data.get('INTEL_HEALTH', '?')
        gpu_name = data.get('INTEL_GPU_NAME', 'Intel Arc')
        gpu_mem = data.get('INTEL_GPU_MEM', '0')
        tps_txt = data.get('INTEL_TPS_TXT', '—')
        tps_pct = data.get('INTEL_TPS_PCT', '0')
        num_loaded = int(data.get('INTEL_NUM_LOADED', '0'))
        num_avail = int(data.get('INTEL_NUM_AVAIL', '0'))

        health_color = 'color2' if health == 'ready' else 'color5'
        print(f"${{color1}}Estado: ${{{health_color}}}{health}${{color}}  ${{color1}}:8006${{color}}")
        print(f"${{color1}}GPU: ${{color4}}{gpu_name}${{color}}  ${{color1}}VRAM: ${{color2}}{gpu_mem} MB${{color}}")

        if num_loaded > 0:
            for i in range(num_loaded):
                name = data.get(f'INTEL_M{i}_NAME', '?')
                mtype = data.get(f'INTEL_M{i}_TYPE', '?')
                size = data.get(f'INTEL_M{i}_SIZE', '0')
                # Truncar nombre si es muy largo
                short = name if len(name) <= 30 else name[:27] + '...'
                print(f"${{color2}}▶ {short}${{color}}")
                print(f"${{color1}}  Tipo: ${{color}}{mtype}  ${{color1}}Size: ${{color2}}{size} MB${{color}}")
        else:
            print("${color5}(Sin modelos cargados)${color}")

        # tok/s con barra
        print(f"${{color1}}Velocidad: ${{color2}}{tps_txt}${{color}}")
        print(f"${{execbar 4,344 /tmp/conky_intel_tps.sh}}")

        # Modelos disponibles
        if num_avail > 0:
            avail_names = []
            for i in range(min(num_avail, 4)):
                aname = data.get(f'INTEL_A{i}_NAME', '')
                if aname:
                    short = aname if len(aname) <= 20 else aname[:17] + '...'
                    avail_names.append(short)
            if avail_names:
                print(f"${{color1}}Disponibles: ${{color}}{', '.join(avail_names)}${{color}}")

    # ══════════ AMD RX480 ══════════
    print()
    amd_running = data.get('AMD_RUNNING', '0') == '1'
    print("${color4}── AMD RX480 — Vulkan GGML ──${color}")
    if not amd_running:
        status = data.get('AMD_STATUS', 'unknown')
        print(f"${{color3}}Estado: {status}${{color}}")
        print("${color1}:1235${color}  ${color3}DETENIDO${color}")
    else:
        num_loaded = int(data.get('AMD_NUM_LOADED', '0'))
        tps_txt = data.get('AMD_TPS_TXT', '—')
        print(f"${{color1}}:1235${{color}}  ${{color2}}RUNNING${{color}}")
        if num_loaded > 0:
            for i in range(num_loaded):
                name = data.get(f'AMD_M{i}_NAME', '?')
                short = name if len(name) <= 30 else name[:27] + '...'
                print(f"${{color2}}▶ {short}${{color}}")
        else:
            print("${color5}(Sin modelos cargados)${color}")
        print(f"${{color1}}Velocidad: ${{color2}}{tps_txt}${{color}}")
        print(f"${{execbar 4,344 /tmp/conky_amd_tps.sh}}")

if __name__ == '__main__':
    render()