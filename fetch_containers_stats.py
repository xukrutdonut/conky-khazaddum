#!/usr/bin/env python3
"""Daemon que recolecta stats de los contenedores IA (Intel OpenVINO + Ninfer V100).
Monitoriza el uso de GPU para Intel y el contenedor ninfer-serve para el V100.
Escribe /tmp/conky_containers.dat para que containers_render.py lo lea.
"""
import json
import os
import subprocess
import time
import socket
import re

DAT_FILE = '/tmp/conky_containers.dat'
INTERVAL = 5          # poll cada 5s
INTEL_PORT = 8006
NINFER_NAME = 'ninfer-serve'

# --- histórico persistido (revive del commit c61f97c; se perdió en a90bd83) ---
# 180 muestras x 5 s = 15 min; se agrega por máximos a SPARK_W columnas para que
# los picos no se pierdan. Persiste en disco para no vaciarse al reiniciar el
# daemon, y además guarda el registro de modelos (__reg__) para que los carriles
# de swap no cambien de orden/identidad si la API falla un ciclo.
HIST_FILE = '/tmp/conky_gpu_hist.json'
HIST_MAX = 180
SPARK_W = 46          # 46 x 5.42 px = 249 px + etiqueta <=14 = 325 px < 344 utiles
_SPARK_BLOCKS = '▁▂▃▄▅▆▇█'
_SWAP_MAX_ENG = 8     # carriles maximos por motor
_hist = {}
_swapreg = {}


def hist_load():
    global _hist, _swapreg
    try:
        with open(HIST_FILE) as f:
            d = json.load(f)
        _swapreg = {k: [str(x) for x in v] for k, v in (d.get('__reg__') or {}).items()}
        _hist = {k: [float(x) for x in v][-HIST_MAX:] for k, v in d.items() if k != '__reg__'}
    except Exception:
        _hist, _swapreg = {}, {}


def hist_save():
    try:
        out = {**_hist, '__reg__': {k: list(v) for k, v in _swapreg.items()}}
        tmp = HIST_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(out, f)
        os.replace(tmp, HIST_FILE)
    except Exception:
        pass


def hist_push(key, val):
    try:
        v = max(0.0, min(100.0, float(val)))
    except Exception:
        v = 0.0
    h = _hist.setdefault(key, [])
    h.append(v)
    del h[:-HIST_MAX]


def hist_cols(key):
    """Columnas del histórico: SPARK_W valores 0-100 (max de cada tramo)."""
    h = _hist.get(key) or [0.0]
    n = len(h)
    cols = []
    for i in range(SPARK_W):
        a = int(i * n / SPARK_W)
        b = max(a + 1, int((i + 1) * n / SPARK_W))
        cols.append(max(h[a:b] or [0.0]))
    # pad de ceros a la izquierda para que el ancho sea constante
    return [0.0] * (SPARK_W - len(cols)) + cols


def spark(key):
    """Histórico en UNA fila de 8 niveles, color fijo (sin umbrales rojo/amarillo)."""
    out = []
    for v in hist_cols(key):
        v = max(0.0, min(100.0, v))
        out.append(_SPARK_BLOCKS[int(round(v / 100.0 * 7))])
    return ''.join(out)


def swap_row(key):
    """Fila de 46 cols: █ donde el modelo estuvo residente, vacío si no.

    Se usa ESPACIO (no ▁) para 'descargado': ▁ pinta una rayita continua y el
    carril vacío se leía como relleno.
    """
    return ''.join('█' if c >= 0.5 else ' ' for c in hist_cols(key))


def swap_age_ev(key):
    """Segundos en el estado actual y nº de cargas (0->1) dentro de la ventana."""
    h = _hist.get(key) or []
    if not h:
        return 0, 0
    now = 1 if h[-1] >= 0.5 else 0
    age = 0
    for v in reversed(h):
        if (1 if v >= 0.5 else 0) == now:
            age += 1
        else:
            break
    ev = sum(1 for a, b in zip(h, h[1:]) if a < 0.5 <= b)
    return age * INTERVAL, ev


def emit_swap(lines, intel, ninfer):
    """Carriles SWAP<i>_*: histérico 0/1 de 'modelo residente en VRAM' por modelo.

    OVMS: cargado == presente en /v1/config (eager, solo cambia con ovms-model).
    Ninfer: status.value loaded/ready/running de /v1/models (router models-max 1).
    Si la API del motor no responde el ciclo, todo su registro cuenta como 0: el
    carril no desaparece, se ve descargado.
    """
    idx = 0
    for eng, states in (('OVMS', intel.get('swap') or []), ('NINFER', ninfer.get('swap') or [])):
        reg = _swapreg.setdefault(eng, [])
        cur = dict(states)
        for name, _s in states:
            if name not in reg:
                reg.append(name)
        del reg[_SWAP_MAX_ENG:]
        for name in reg:
            hkey = f'SWAP::{eng}::{name}'
            hist_push(hkey, 1 if cur.get(name) else 0)
            age, ev = swap_age_ev(hkey)
            lines.append(f'SWAP{idx}_ENG:{eng}')
            lines.append(f'SWAP{idx}_NAME:{name}')
            lines.append(f'SWAP{idx}_ROW:{swap_row(hkey)}')
            lines.append(f'SWAP{idx}_NOW:{"1" if cur.get(name) else "0"}')
            lines.append(f'SWAP{idx}_AGE:{age}')
            lines.append(f'SWAP{idx}_EV:{ev}')
            idx += 1
    lines.append(f'SWAP_COUNT:{idx}')


def gpu_hist(lines, intel, ninfer):
    """Empuja el histórico de uso GPU y añade las filas SPARK que lee el render."""
    gu = intel.get('gpu_usage') or {}
    hist_push('INTEL_GPU_BUSY', float(gu.get('gpu_busy', 0) or 0))
    hist_push('NINFER_GPU_UTIL', float(ninfer.get('gpu_util', 0) or 0))
    for key in ('INTEL_GPU_BUSY', 'NINFER_GPU_UTIL'):
        lines.append(f'{key}_SPARK:{spark(key)}')
    hist_save()


def write_dat(lines):
    try:
        with open(DAT_FILE + '.tmp', 'w') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(DAT_FILE + '.tmp', DAT_FILE)
    except Exception:
        pass


def docker_status(name):
    try:
        r = subprocess.run(
            ['docker', 'inspect', name, '--format', '{{.State.Status}}|{{.State.Running}}'],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split('|')
            status = parts[0]
            running = parts[1].lower() == 'true' if len(parts) > 1 else False
            return running, status
    except Exception:
        pass
    return False, 'not-found'


def http_get_json(url, timeout=3):
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 2
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except Exception:
        pass
    return None


def port_open(port, timeout=1):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


def read_intel_gpu_stats():
    p = None
    try:
        p = subprocess.Popen(
            ['intel_gpu_top', '-J', '-s', '1000'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        if p.stdout is None: return None
        buf = ''
        import time as _t
        deadline = _t.time() + 5
        while _t.time() < deadline:
            line = p.stdout.readline()
            if not line: break
            buf += line
            idx = buf.find('{')
            if idx == -1: continue
            depth = 0
            end = -1
            for i, c in enumerate(buf[idx:], idx):
                if c == '{': depth += 1
                elif c == '}': depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            if end > 0:
                obj = json.loads(buf[idx:end])
                rc6 = obj.get('rc6', {}).get('value', 100)
                gpu_busy = max(0, 100 - rc6)
                power = obj.get('power', {})
                engines = obj.get('engines', {})
                render = engines.get('Render/3D', {}).get('busy', 0)
                compute = engines.get('Compute', {}).get('busy', 0)
                if compute == 0:
                    for k, v in engines.items():
                        if v.get('busy', 0) > 0 and k != 'Render/3D':
                            compute = max(compute, v['busy'])
                return {
                    'gpu_busy': round(gpu_busy, 1),
                    'gpu_power': round(power.get('GPU', 0), 2),
                    'pkg_power': round(power.get('Package', 0), 2),
                    'render': round(render, 1),
                    'compute': round(compute, 1),
                }
    except Exception:
        pass
    finally:
        if p:
            p.kill()
            p.wait()
    return None


def model_disk_size_mb(name, _cache={}):
    if name in _cache: return _cache[name]
    total = 0
    try:
        base = '/home/arkantu/produccion/openvino-models/.openvino-ir'
        mdir = os.path.join(base, name)
        if os.path.isdir(mdir):
            for root, _dirs, files in os.walk(mdir):
                for fn in files:
                    try: total += os.path.getsize(os.path.join(root, fn))
                    except OSError: pass
    except Exception: pass
    _cache[name] = total / (1024 * 1024)
    return _cache[name]


def parse_mem(s):
    m = re.search(r"([0-9.]+)\s*([KMGT]?B)", s)
    if not m: return 0.0
    v = float(m.group(1))
    u = m.group(2).upper()
    if u.startswith('K'): v /= 1024
    elif u.startswith('G'): v *= 1024
    elif u.startswith('T'): v *= 1024**2
    return v


def read_v100_gpu_stats():
    """Lee VRAM/GPU del fichero que escribe get_v100_val.sh / v100_stats.sh."""
    try:
        p = subprocess.run(
            ['bash', '-c', 'cat /tmp/conky_v100.dat 2>/dev/null || echo ""'],
            capture_output=True, text=True, timeout=5
        )
        if p.returncode != 0 or not p.stdout.strip():
            return {}
        stats = {}
        for line in p.stdout.strip().splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                stats[k.strip()] = v.strip()
        return stats
    except Exception:
        return {}


def read_arc_gpu_stats():
    """Lee la iGPU Arc (driver Xe) del arc_gpu_daemon.py.

    intel_gpu_top NO soporta el driver xe ("Detected Xe device ... please use
    'gputop'"); arc_gpu_daemon lee /proc/<pid>/fdinfo (sin abrir el device) y
    atribuye por proceso (OVMS vs llama), escribiendo /tmp/conky_arc.dat.
    """
    try:
        with open('/tmp/conky_arc.dat') as f:
            data = {}
            for line in f.read().splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    data[k.strip()] = v.strip()
        data['gpu_busy'] = data.get('RNDR', '0')
        data['render'] = data.get('RNDR', '0')
        data['compute'] = data.get('COMPUTE', '0')
        # arc.dat no trae potencia (solo fdinfo): se deja a 0 salvo que el daemon
        # lo amplíe con act_freq; mantener el contrato de build_dat.
        data.setdefault('gpu_power', '0')
        data.setdefault('pkg_power', '0')
        data.setdefault('gpu_process_memory_mb', '0')
        return data
    except Exception:
        return None


def collect_ninfer():
    running, status = docker_status(NINFER_NAME)
    if not running:
        return {'running': False, 'status': status, 'cpu': 0.0, 'mem_used': 0.0, 'mem_total': 0.0,
                'workers': 0, 'kv_cache_pct': 0.0, 'vram_used': 0.0, 'vram_total': 0.0,
                'gpu_util': 0.0, 'gpu_temp': 0.0,
                'model': '', 'quant': '', 'ctx': '', 'swap': []}
    # Fixed braces in f-string: use {{ to get a literal { in f-string
    cmd = f'docker stats {NINFER_NAME} --no-stream --format "{{{{.CPUPerc}}|{{{{.MemUsage}}}}}}" '
    r = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=5)
    cpu, mem_u, mem_t = 0.0, 0.0, 0.0
    if r.returncode == 0 and r.stdout.strip():
        parts = r.stdout.strip().split('|')
        if len(parts) >= 2:
            cpu = round(float(parts[0].replace('%', '')) if parts[0] else 0.0, 1)
            mem_u = parse_mem(parts[1])
            mem_t = mem_u

    # Leer VRAM y utilización de la V100 desde el daemon v100_stats.sh
    v100_stats = read_v100_gpu_stats()
    vram_used = float(v100_stats.get('MEMUSED', 0)) / 1024.0 if v100_stats else 0.0
    vram_total = float(v100_stats.get('MEMTOTAL', 32768)) / 1024.0 if v100_stats else 0.0
    kv_pct = float(v100_stats.get('KV_CACHE_PCT', 0)) if v100_stats else 0.0
    v100_util = float(v100_stats.get('UTIL', 0)) if v100_stats else 0.0
    v100_temp = float(v100_stats.get('TEMP', 0)) if v100_stats else 0.0

    # Leer workers/modelo del API de ninfer (formato OpenAI /v1/models)
    workers = 0
    model = ''
    quant = ''
    ctx = ''
    swap_list = []
    try:
        cfg = http_get_json('http://127.0.0.1:8090/v1/models')
        if isinstance(cfg, dict):
            data = cfg.get('data') or []
            # estado por modelo (orden del router) para los carriles de swap
            for entry in data:
                if isinstance(entry, dict) and entry.get('id'):
                    val = (entry.get('status') or {}).get('value')
                    swap_list.append((entry['id'], 1 if val in ('loaded', 'ready', 'running') else 0))
            chosen = None
            # 1) preferir el que esté realmente cargado (loaded/ready/running)
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                st = entry.get('status') or {}
                if st.get('value') in ('loaded', 'ready', 'running'):
                    chosen = entry
                    break
            # 2) si todos están unloaded (VRAM liberada en idle), usar el 1º
            #    del router para no dejar el panel en blanco.
            if chosen is None and data and isinstance(data[0], dict):
                chosen = data[0]
            if chosen is not None:
                st = chosen.get('status') or {}
                model = chosen.get('id', '')
                args = st.get('args') or []
                # --max-context N  y  --max-concurrency N  vienen en args
                try:
                    ai = args.index('--max-context')
                    ctx = args[ai + 1] if ai + 1 < len(args) else '0'
                except ValueError:
                    pass
                try:
                    ai = args.index('--max-concurrency')
                    workers = int(args[ai + 1]) if ai + 1 < len(args) else 0
                except ValueError:
                    pass
    except Exception:
        pass

    return {
        'running': True, 'status': status, 'cpu': cpu, 'mem_used': mem_u, 'mem_total': mem_t,
        'workers': workers, 'kv_cache_pct': kv_pct, 'vram_used': vram_used, 'vram_total': vram_total,
        'gpu_util': v100_util, 'gpu_temp': v100_temp,
        'model': model, 'quant': quant, 'ctx': ctx, 'swap': swap_list
    }


def collect_intel():
    running, status = docker_status('ia-gpu-intel-openvino')
    if not running:
        return {'running': False, 'status': status, 'models': [], 'gpu': {}, 'gpu_usage': None, 'swap': []}
    ready = port_open(INTEL_PORT)
    config = http_get_json(f'http://127.0.0.1:{INTEL_PORT}/v1/config')
    loaded_models = []
    all_models = []
    if isinstance(config, dict):
        for name in config:
            entry = {'name': name, 'type': 'embeddings' if ('embed' in name.lower() or 'minilm' in name.lower()) else 'llm', 'loaded': True, 'size_mb': model_disk_size_mb(name)}
            all_models.append(entry)
            loaded_models.append(entry)
    # La iGPU Arc usa el driver xe: intel_gpu_top NO lo soporta. arc_gpu_daemon
    # lee fdinfo (sin abrir el device) y atribuye por proceso.
    arc = read_arc_gpu_stats()
    gpu = {'device': 'Intel Arc'} if arc is not None else {}
    if arc is not None:
        gpu['gpu_process_memory_mb'] = float(arc.get('GTT', '0')) * 1024
    return {'running': True, 'status': status, 'health': 'ready' if ready else 'starting',
            'models': all_models, 'loaded_models': loaded_models,
            'gpu': gpu, 'gpu_usage': arc,
            'swap': [(m['name'], 1) for m in loaded_models]}


def build_dat(intel, ninfer):
    lines = []
    lines.append(f"INTEL_RUNNING:{1 if intel['running'] else 0}")
    lines.append(f"INTEL_STATUS:{intel['status']}")
    if intel['running']:
        lines.append(f"INTEL_HEALTH:{intel.get('health', '?')}")
        gpu = intel.get('gpu', {})
        lines.append(f"INTEL_GPU_NAME:{gpu.get('device', 'Intel Arc')}")
        lines.append(f"INTEL_GPU_MEM:{gpu.get('gpu_process_memory_mb', 0):.0f}")
        loaded = intel.get('loaded_models', [])
        lines.append(f"INTEL_NUM_LOADED:{len(loaded)}")
        for i, m in enumerate(loaded):
            lines.append(f"INTEL_M{i}_NAME:{m['name']}")
            lines.append(f"INTEL_M{i}_TYPE:{m['type']}")
            lines.append(f"INTEL_M{i}_SIZE:{m['size_mb']:.0f}")
        unloaded = [m for m in intel.get('models', []) if not m['loaded']]
        lines.append(f"INTEL_NUM_AVAIL:{len(unloaded)}")
        for i, a in enumerate(unloaded[:4]):
            lines.append(f"INTEL_A{i}_NAME:{a['name']}")
            lines.append(f"INTEL_A{i}_TYPE:{a['type']}")
        gu = intel.get('gpu_usage')
        if gu:
            lines.append(f"INTEL_GPU_BUSY:{gu['gpu_busy']}")
            lines.append(f"INTEL_GPU_PWR:{gu['gpu_power']}")
            lines.append(f"INTEL_PKG_PWR:{gu['pkg_power']}")
            lines.append(f"INTEL_RENDER:{gu['render']}")
            lines.append(f"INTEL_COMPUTE:{gu['compute']}")
        else:
            lines.extend(["INTEL_GPU_BUSY:0", "INTEL_GPU_PWR:0", "INTEL_PKG_PWR:0", "INTEL_RENDER:0", "INTEL_COMPUTE:0"])

    lines.append(f"NINFER_RUNNING:{1 if ninfer['running'] else 0}")
    lines.append(f"NINFER_STATUS:{ninfer['status']}")
    lines.append(f"NINFER_CPU:{ninfer['cpu']}")
    lines.append(f"NINFER_MEM_USED:{ninfer['mem_used']}")
    lines.append(f"NINFER_MEM_TOTAL:{ninfer['mem_total']}")
    lines.append(f"NINFER_WORKERS:{ninfer.get('workers', 0)}")
    lines.append(f"NINFER_KV_CACHE_PCT:{ninfer.get('kv_cache_pct', 0)}")
    lines.append(f"NINFER_VRAM_USED:{ninfer.get('vram_used', 0):.0f}")
    lines.append(f"NINFER_VRAM_TOTAL:{ninfer.get('vram_total', 0):.0f}")
    lines.append(f"NINFER_MODEL:{ninfer.get('model', '')}")
    lines.append(f"NINFER_QUANT:{ninfer.get('quant', '')}")
    lines.append(f"NINFER_CTX:{ninfer.get('ctx', '')}")
    lines.append(f"NINFER_GPU_UTIL:{ninfer.get('gpu_util', 0)}")
    lines.append(f"NINFER_GPU_TEMP:{ninfer.get('gpu_temp', 0)}")

    gpu_hist(lines, intel, ninfer)
    emit_swap(lines, intel, ninfer)

    write_dat(lines)


def main():
    hist_load()
    while True:
        try:
            intel = collect_intel()
            ninfer = collect_ninfer()
            build_dat(intel, ninfer)
        except Exception as e:
            print(f"Error in loop: {e}")
            time.sleep(1)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
