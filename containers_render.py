#!/usr/bin/env python3
"""Render para Conky: estado de los motores de inferencia locales
(contenedor OpenVINO de Intel + llama.cpp Vulkan del Pi5 .80)."""
import os

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
    write_helper('conky_lm_gpu.sh', 'LM_GPU')
    write_helper('conky_rpi_gpu_busy.sh', 'RPI_GPU_BUSY')

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

    # ══════════ LM Studio — Vulkan sobre la iGPU Arc ══════════
    print()
    print("${color4}── LM Studio — CUDA · V100 :1234 ──${color}")
    if data.get('LM_RUNNING', '0') != '1':
        print("${color1}Estado: ${color3}sin respuesta${color}")
        print("${color1}Servidor: ${color3}LM Studio cerrado${color}")
    else:
        n_load = int(data.get('LM_MODELS_LOADED', '0'))
        n_tot = int(data.get('LM_MODELS_TOTAL', '0'))
        gen = data.get('LM_GENERATING', '0') == '1'
        st_col = 'color2' if gen else 'color1'
        st_txt = 'generando' if gen else 'idle'
        print(f"${{color1}}Estado: ${{{st_col}}}{st_txt}${{color}}  "
              f"${{color1}}Modelos: ${{color2}}{n_load}/{n_tot}${{color}}")
        if n_load == 0:
            print("${color5}(Ningún modelo cargado)${color}")
        for i in range(min(n_load, 2)):
            name = data.get(f'LM_M{i}_NAME', '?')
            short = name if len(name) <= 30 else name[:27] + '...'
            quant = data.get(f'LM_M{i}_QUANT', '?')
            ctx = int(float(data.get(f'LM_M{i}_CTX', '0')))
            print(f"${{color2}}▶ {short}${{color}} ${{color1}}({quant}, "
                  f"ctx {ctx//1024}k)${{color}}")
            if i == 0:
                if gen:
                    pps = float(data.get('LM_PPS', '0'))
                    extra = f" · prompt {pps:.0f} t/s" if pps > 0 else ''
                    print(f"${{color1}}Gen: ${{color2}}{data.get('LM_TG', '0')} t/s"
                          f"${{color}}{extra}${{color1}} · "
                          f"${{color2}}{fmt_tok(data.get('LM_TOK', '0'))}${{color1}} tok${{color}}")
                else:
                    age = int(float(data.get('LM_LAST_AGE', '-1')))
                    if age >= 0:
                        print(f"${{color1}}Última: hace ${{color2}}{fmt_age(age)}${{color}}"
                              f"${{color1}} · ${{color2}}{data.get('LM_LAST_TG', '0')} t/s${{color}}"
                              f"${{color1}} · ${{color2}}{fmt_tok(data.get('LM_LAST_TOK', '0'))} tok${{color}}")
                    else:
                        print("${color5}(Sin generaciones registradas)${color}")
        if n_load:
            slots = data.get('LM_M0_SLOTS', '0')
            queue = data.get('LM_M0_QUEUE', '0')
            peso = float(data.get('LM_M0_SIZE', '0'))
            print(f"${{color1}}Peso: ${{color2}}{peso:.1f} GB${{color}}  "
                  f"${{color1}}Slots: ${{color2}}{slots}${{color}}  "
                  f"${{color1}}Cola: ${{color2}}{queue}${{color}}")
        print(f"${{color1}}Hoy: ${{color2}}{data.get('LM_TODAY_GENS', '0')}${{color}}"
              f"${{color1}} gen · ${{color2}}"
              f"{fmt_tok(data.get('LM_TODAY_TOK', '0'))}${{color}}"
              f"${{color1}} tok${{color}}")
        vram_u = float(data.get('LM_VRAM_USED', '0') or 0)
        vram_t = float(data.get('LM_VRAM_TOTAL', '0') or 0)
        extra = (f" · {data.get('LM_PWR', '0')} W" if vram_t else '')
        if vram_t:
            print(f"${{color1}}VRAM: ${{color2}}{vram_u:.0f}/{vram_t:.0f} GB${{color}}")
        for line in gpu_panel(data, 'LM_GPU', 'Uso GPU V100:', extra):
            print(line)

    # ══════════ Pi5 .80 — llama.cpp Vulkan ══════════
    print()
    print("${color4}── Pi5 .80 — llama.cpp Vulkan ──${color}")
    running = data.get('RPI_RUNNING', '0') == '1'
    state = data.get('RPI_STATE', '?')
    sc = 'color2' if running else 'color3'
    print(f"${{color1}}Estado: ${{{sc}}}{state}${{color}}  ${{color1}}:1235${{color}}")
    gpu_on = data.get('RPI_GPU_DRIVER', '') == 'amdgpu'
    write_helper('conky_rpi5_bar.sh', 'RPI_GPU_BUSY' if gpu_on else 'RPI_KV')
    write_helper('conky_rpi5_vram.sh', 'RPI_GPU_VRAMPCT')
    if not running:
        http = data.get('RPI_HTTP', '000')
        detail = 'proceso caído' if http == '000' else f'HTTP {http}'
        print(f"${{color1}}Nodo: ${{color5}}192.168.0.80${{color}}  ${{color3}}{detail}${{color}}")
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
    # La GPU se muestra siempre: sirve igual con llama.cpp parado
    if gpu_on:
        print(f"${{color1}}GPU RX 480: ${{color2}}{data.get('RPI_GPU_BUSY', '0')}%${{color}}  "
              f"${{color1}}Temp: ${{color2}}{data.get('RPI_GPU_TEMP', '0')}°C${{color}}  "
              f"${{color1}}VRAM: ${{color2}}{data.get('RPI_GPU_VRAMPCT', '0')}%${{color}}")
        print(f"${{color1}}Frec: ${{color2}}{data.get('RPI_GPU_FREQ', '0')} MHz${{color}}  "
              f"${{color1}}Pwr: ${{color2}}{data.get('RPI_GPU_PWR', '0')} W${{color}}  "
              f"${{color5}}{data.get('RPI_GPU_PCI', 'none')}${{color}}")
        for line in gpu_panel(data, 'RPI_GPU_BUSY', 'Uso GPU RX 480:', ''):
            print(line)
    else:
        print("${color5}GPU: amdgpu ausente (llvmpipe)${color}")
        for line in gpu_panel(data, 'RPI_GPU_BUSY', 'Uso GPU RX 480:', ''):
            print(line)

if __name__ == '__main__':
    render()
