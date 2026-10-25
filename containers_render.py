#!/usr/bin/env python3
"""Render para Conky: estado de los motores de inferencia locales
(contenedor OpenVINO de Intel + servidor Intel de LM Studio)."""
import os

DAT_FILE = '/tmp/conky_containers.dat'


def write_helper(path, key):
    """Crea un script helper en /tmp que extrae un valor del .dat para execbar."""
    content = (
        "#!/bin/sh\n"
        f"awk -F: '$1==\"{key}\" {{print $2; exit}}' {DAT_FILE}\n"
    )
    with open(path, 'w') as f:
        f.write(content)
    os.chmod(path, 0o755)


def bar(path):
    return f"${{execbar 4,344 {path}}}"


def render():
    write_helper('/tmp/conky_intel_gpu.sh', 'INTEL_GPU_BUSY')
    write_helper('/tmp/conky_lm_gpu.sh', 'LM_GPU_BUSY')

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
        gu = data.get('INTEL_GPU_BUSY', '0')
        gp = data.get('INTEL_GPU_PWR', '0')
        print(f"${{color1}}Uso GPU: ${{color2}}{gu}%${{color}}  ${{color1}}Pwr: ${{color2}}{gp}W${{color}}")
        print(bar('/tmp/conky_intel_gpu.sh'))
        if n_avail:
            names = []
            for i in range(min(n_avail, 4)):
                a = data.get(f'INTEL_A{i}_NAME', '')
                if a:
                    names.append(a if len(a) <= 20 else a[:17] + '...')
            if names:
                print(f"${{color1}}Disponibles: ${{color}}{', '.join(names)}${{color}}")

    # ══════════ LM Studio ══════════
    print()
    print("${color4}── LM Studio — Vulkan GGML ──${color}")
    if data.get('LM_RUNNING', '0') != '1':
        print("${color3}Estado: APAGADO${color}")
        print("${color1}:1234${color}  ${color3}servidor parado${color}")
        print("${color5}arráncalo con: lms server start${color}")
    else:
        srv = data.get('LM_SERVER', '0') == '1'
        app = data.get('LM_APP', '0') == '1'
        state = 'ready' if srv else ('app abierta, servidor off' if app else '?')
        sc = 'color2' if srv else 'color5'
        print(f"${{color1}}Estado: ${{{sc}}}{state}${{color}}  ${{color1}}:1234${{color}}")
        n_total = int(data.get('LM_NUM_TOTAL', '0'))
        n_load = int(data.get('LM_NUM_LOADED', '0'))
        disk = data.get('LM_DISK', '0')
        print(f"${{color1}}Modelos: ${{color2}}{n_load}/{n_total}${{color}}  ${{color1}}Disco: ${{color2}}{disk} GB${{color}}")
        if n_load:
            for i in range(min(n_load, 3)):
                name = data.get(f'LM_M{i}_NAME', '?')
                ctx = data.get(f'LM_M{i}_CTX', '0')
                quant = data.get(f'LM_M{i}_QUANT', '-')
                size = int(float(data.get(f'LM_M{i}_SIZE', '0')))
                short = name if len(name) <= 28 else name[:25] + '...'
                print(f"${{color2}}▶ {short}${{color}} ${{color1}}({size} MB)${{color}}")
                print(f"${{color1}}  Ctx: ${{color2}}{ctx}${{color}}  ${{color1}}Quant: ${{color2}}{quant}${{color}}")
        else:
            print("${color5}(Sin modelos cargados)${color}")
        gu = data.get('LM_GPU_BUSY', '0')
        gp = data.get('LM_GPU_PWR', '0')
        print(f"${{color1}}Uso GPU: ${{color2}}{gu}%${{color}}  ${{color1}}Pwr: ${{color2}}{gp}W${{color}}")
        print(bar('/tmp/conky_lm_gpu.sh'))
        n_idle = int(data.get('LM_NUM_IDLE', '0'))
        if n_idle:
            print(f"${{color1}}En disco sin cargar: ${{color}}{n_idle}${{color}}")


if __name__ == '__main__':
    render()
