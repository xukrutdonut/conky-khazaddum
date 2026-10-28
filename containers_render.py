#!/usr/bin/env python3
"""Render para Conky: estado de los motores de inferencia locales
(contenedor OpenVINO de Intel + llama.cpp Vulkan del Pi5 .80)."""
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

    # ══════════ Pi5 .80 — llama.cpp Vulkan ══════════
    print()
    print("${color4}── Pi5 .80 — llama.cpp Vulkan ──${color}")
    running = data.get('RPI_RUNNING', '0') == '1'
    state = data.get('RPI_STATE', '?')
    sc = 'color2' if running else 'color3'
    print(f"${{color1}}Estado: ${{{sc}}}{state}${{color}}  ${{color1}}:1235${{color}}")
    gpu_on = data.get('RPI_GPU_DRIVER', '') == 'amdgpu'
    write_helper('/tmp/conky_rpi5_bar.sh', 'RPI_GPU_BUSY' if gpu_on else 'RPI_KV')
    if not running:
        http = data.get('RPI_HTTP', '000')
        detail = 'proceso caído' if http == '000' else f'HTTP {http}'
        print(f"${{color1}}Nodo: ${{color5}}192.168.0.80${{color}}  ${{color3}}{detail}${{color}}")
        if not gpu_on:
            print("${color5}GPU: sin amdgpu (llvmpipe/V3D)${color}")
    else:
        model = data.get('RPI_MODEL', '?')
        quant = data.get('RPI_QUANT', '-')
        ctx = data.get('RPI_CTX', '0')
        short = model if len(model) <= 30 else model[:27] + '...'
        print(f"${{color2}}▶ {short}${{color}} ${{color1}}({quant}, ctx {ctx})${{color}}")
        print(f"${{color1}}Slots: ${{color2}}{data.get('RPI_SLOTS', '0/0')}${{color}}  "
              f"${{color1}}KV: ${{color2}}{data.get('RPI_KV', '0')}%${{color}}")
        if data.get('RPI_METRICS', '0') == '1':
            print(f"${{color1}}Gen: ${{color2}}{data.get('RPI_TPS', '0')} t/s${{color}}  "
                  f"${{color1}}Prompt: ${{color2}}{data.get('RPI_PPS', '0')} t/s${{color}}")
            print(f"${{color1}}Peticiones: ${{color2}}{data.get('RPI_PROC', '0')}${{color}} ${{color1}}en curso, "
                  f"${{color}}{data.get('RPI_DEFER', '0')}${{color}} ${{color1}}en cola${{color}}")
        if gpu_on:
            print(f"${{color1}}GPU RX 480: ${{color2}}{data.get('RPI_GPU_BUSY', '0')}%${{color}}  "
                  f"${{color1}}Temp: ${{color2}}{data.get('RPI_GPU_TEMP', '0')}°C${{color}}")
            print(bar('/tmp/conky_rpi5_bar.sh'))
        else:
            print("${color5}GPU: amdgpu ausente (llvmpipe)${color}")
            print(bar('/tmp/conky_rpi5_bar.sh'))

if __name__ == '__main__':
    render()
