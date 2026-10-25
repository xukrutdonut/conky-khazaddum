#!/usr/bin/env python3
"""Daemon que recolecta stats de los servicios IA locales:
  - Intel OpenVINO Model Server (contenedor ia-gpu-intel-openvino, :8006)
  - LM Studio (app nativa, servidor REST :1234, backend Vulkan sobre la Arc)
Escribe /tmp/conky_containers.dat para que containers_render.py lo lea.

Monitoriza uso real de GPU sin lanzar benchmarks:
  - Intel Arc: intel_gpu_top -J (RC6 idle, power, engines) — una sola
    muestra por ciclo, compartida por ambas secciones (misma iGPU).
"""
import glob
import json
import os
import re
import socket
import subprocess
import time

DAT_FILE = '/tmp/conky_containers.dat'
INTERVAL = 5          # poll cada 5s
INTEL_PORT = 8006
LMSTUDIO_PORT = 1234


def write_dat(lines):
    try:
        with open(DAT_FILE + '.tmp', 'w') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(DAT_FILE + '.tmp', DAT_FILE)
    except Exception:
        pass


def docker_status(name):
    """Devuelve (running, status_str) de un contenedor docker."""
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
    """Lee uso real de Intel Arc via intel_gpu_top -J (streaming).
    Lee el primer objeto JSON completo y mata el proceso.
    Devuelve dict con gpu_busy%, gpu_power_w, pkg_power_w, render%, compute%."""
    p = None
    try:
        p = subprocess.Popen(
            ['intel_gpu_top', '-J', '-s', '1000'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
        assert p.stdout is not None
        buf = ''
        deadline = time.time() + 5
        while time.time() < deadline:
            line = p.stdout.readline()
            if not line:
                break
            buf += line
            idx = buf.find('{')
            if idx == -1:
                continue
            depth = 0
            end = -1
            for i, c in enumerate(buf[idx:], idx):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
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


def intel_peak_sample(prev=None):
    """intel_gpu_top da una foto instantanea y la inferencia es en rafagas:
    muestrea varias veces dentro de la ventana y devuelve el pico observado."""
    first = read_arc_sample()
    peak = dict(first) if first else None
    for _ in range(3):
        time.sleep(INTERVAL / 10)
        s = read_arc_gpu_stats()
        if s and (peak is None or s.get('gpu_busy', 0) > peak.get('gpu_busy', 0)):
            peak = s
    return peak


def read_arc_gpu_stats():
    """Muestra corta (1 s) para el muestreo de pico."""
    return read_intel_gpu_stats()


def read_arc_sample():
    return read_intel_gpu_stats()


def model_disk_size_mb(name, _cache={}):
    """Tamaño en disco (MB) de un modelo OVMS desde el volumen del host.
    Cacheado: los ficheros no cambian mientras el contenedor corre."""
    if name in _cache:
        return _cache[name]
    total = 0
    try:
        base = '/home/arkantu/produccion/openvino-models/.openvino-ir'
        mdir = os.path.join(base, name)
        if os.path.isdir(mdir):
            for root, _dirs, files in os.walk(mdir):
                for fn in files:
                    try:
                        total += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass
    except Exception:
        pass
    _cache[name] = total / (1024 * 1024)
    return _cache[name]


def collect_intel(gpu=None):
    """Recolecta datos del contenedor Intel OpenVINO (:8006)."""
    running, status = docker_status('ia-gpu-intel-openvino')
    if not running:
        return {
            'running': False,
            'status': status,
            'models': [],
            'gpu': None,
            'gpu_usage': None,
        }

    # OVMS no expone /health ni /v1/admin/*: los endpoints correctos son
    # /v1/models y /v1/config. Todos los modelos del config se cargan de
    # forma EAGER al arrancar el contenedor, asi que "cargado" == presente.
    ready = port_open(INTEL_PORT)
    config = http_get_json(f'http://127.0.0.1:{INTEL_PORT}/v1/config')

    loaded_models = []
    all_models = []
    if isinstance(config, dict):
        for name in config:
            entry = {
                'name': name,
                'type': 'embeddings' if ('embed' in name.lower() or 'minilm' in name.lower()) else 'llm',
                'loaded': True,
                'size_mb': model_disk_size_mb(name),
            }
            all_models.append(entry)
            loaded_models.append(entry)

    return {
        'running': True,
        'status': status,
        'health': 'ready' if ready else 'starting',
        'models': all_models,
        'loaded_models': loaded_models,
        'gpu': None,
        'gpu_usage': gpu,
    }


# ---------------------------------------------------------------- LM Studio --
def quant_from_display(display):
    """LM Studio no siempre rellena quantization.name; el nombre visible
    incluye la cuantizacion tipo 'Qwen3 0.6B Q4 K M Vulkan (...)'."""
    m = re.search(r'\b(I?Q\d[A-Z0-9]*(?:_[A-Z0-9]+)*)\b', display)
    if not m:
        return ''
    parts = display[m.start():].split(' ')
    tokens = []
    for tok in parts:
        if re.fullmatch(r'I?Q\d[A-Z0-9]*|K|_?[SML]|S|M|L', tok.strip()):
            tokens.append(tok.strip())
        else:
            break
    return '_'.join(tokens) if tokens else m.group(1)


def lmstudio_pids():
    """PIDs del servicio LM Studio (scan de /proc, sin llamar a la CLI `lms`,
    que arrancaria el servicio como efecto colateral)."""
    pids = []
    for entry in glob.glob('/proc/[0-9]*'):
        try:
            with open(os.path.join(entry, 'cmdline'), 'rb') as f:
                cmd = f.read().lower()
        except OSError:
            continue
        if b'lm-studio' in cmd or b'lmstudio' in cmd:
            pids.append(int(os.path.basename(entry)))
    return pids


def _rss_mb(pid):
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def collect_lmstudio(gpu=None):
    """Recolecta datos de LM Studio: app nativa + servidor REST :1234.
    Los modelos se cargan en el propio proceso (llama.cpp Vulkan sobre la Arc),
    asi que el RSS del proceso equivale a la memoria de modelo en GTT."""
    pids = lmstudio_pids()
    server_up = port_open(LMSTUDIO_PORT)
    data = http_get_json(f'http://127.0.0.1:{LMSTUDIO_PORT}/api/v1/models') if server_up else None
    if not data or 'models' not in data:
        # fallback API v0 (LM Studio < 0.3.6)
        data = http_get_json(f'http://127.0.0.1:{LMSTUDIO_PORT}/api/v0/models') if server_up else None
        if data and 'data' in data:
            data = {'models': [
                {
                    'key': m.get('id', '?'),
                    'type': m.get('type', 'llm'),
                    'size_bytes': 0,
                    'quantization': m.get('quantization'),
                    'loaded_instances': [{}] if m.get('state') == 'loaded' else [],
                } for m in data['data']
            ]}

    models = []
    if data:
        for m in data.get('models', []):
            inst = m.get('loaded_instances') or []
            cfg = (inst[0] or {}).get('config', {}) if inst else {}
            quant = ((m.get('quantization') or {}).get('name')
                     or quant_from_display(m.get('display_name') or ''))
            models.append({
                'name': m.get('key') or m.get('id') or '?',
                'display': m.get('display_name') or m.get('key', '?'),
                'type': m.get('type', 'llm'),
                'loaded': bool(inst),
                'size_mb': (m.get('size_bytes') or 0) / (1024 * 1024),
                'quant': quant or '?',
                'ctx': cfg.get('context_length') or 0,
                'arch': m.get('architecture') or '',
            })

    return {
        'running': bool(pids) or server_up,
        'app': bool(pids),
        'server': server_up,
        'models': models,
        'rss_mb': sum(_rss_mb(p) for p in pids),
        'gpu_usage': gpu,
    }


def build_dat(intel, lm):
    lines = []
    # ---- Intel OpenVINO
    lines.append(f"INTEL_RUNNING:{1 if intel['running'] else 0}")
    lines.append(f"INTEL_STATUS:{intel['status']}")
    if intel['running']:
        lines.append(f"INTEL_HEALTH:{intel.get('health', '?')}")
        lines.append("INTEL_GPU_NAME:Intel Arc")
        lines.append("INTEL_GPU_MEM:0")
        loaded = intel.get('loaded_models', [])
        lines.append(f"INTEL_NUM_LOADED:{len(loaded)}")
        for i, m in enumerate(loaded):
            lines.append(f"INTEL_M{i}_NAME:{m['name']}")
            lines.append(f"INTEL_M{i}_TYPE:{m['type']}")
            lines.append(f"INTEL_M{i}_SIZE:{m['size_mb']:.0f}")
        unloaded = [m for m in intel.get('models', []) if not m['loaded']]
        lines.append(f"INTEL_NUM_AVAIL:{len(unloaded)}")
        for i, m in enumerate(unloaded[:4]):
            lines.append(f"INTEL_A{i}_NAME:{m['name']}")
            lines.append(f"INTEL_A{i}_TYPE:{m['type']}")
        gu = intel.get('gpu_usage') or {}
        lines.append(f"INTEL_GPU_BUSY:{int(gu.get('gpu_busy', 0))}")
        lines.append(f"INTEL_GPU_PWR:{gu.get('gpu_power', 0)}")
        lines.append(f"INTEL_PKG_PWR:{gu.get('pkg_power', 0)}")
        lines.append(f"INTEL_RENDER:{int(gu.get('render', 0))}")
        lines.append(f"INTEL_COMPUTE:{int(gu.get('compute', 0))}")

    # ---- LM Studio
    lines.append(f"LM_RUNNING:{1 if lm['running'] else 0}")
    lines.append(f"LM_APP:{1 if lm.get('app') else 0}")
    lines.append(f"LM_SERVER:{1 if lm.get('server') else 0}")
    lines.append(f"LM_RSS:{lm.get('rss_mb', 0):.0f}")
    models = lm.get('models', [])
    loaded = [m for m in models if m['loaded']]
    lines.append(f"LM_NUM_TOTAL:{len(models)}")
    lines.append(f"LM_NUM_LOADED:{len(loaded)}")
    lines.append(f"LM_DISK:{sum(m['size_mb'] for m in models) / 1024:.1f}")
    for i, m in enumerate(loaded[:3]):
        lines.append(f"LM_M{i}_NAME:{m['name']}")
        lines.append(f"LM_M{i}_CTX:{m['ctx']}")
        lines.append(f"LM_M{i}_QUANT:{m['quant']}")
        lines.append(f"LM_M{i}_SIZE:{m['size_mb']:.0f}")
    idle = [m for m in models if not m['loaded']]
    lines.append(f"LM_NUM_IDLE:{len(idle)}")
    for i, m in enumerate(idle[:3]):
        lines.append(f"LM_I{i}_NAME:{m['name']}")
    gm = lm.get('gpu_usage') or {}
    lines.append(f"LM_GPU_BUSY:{int(gm.get('gpu_busy', 0))}")
    lines.append(f"LM_GPU_PWR:{gm.get('gpu_power', 0)}")

    write_dat(lines)


def main():
    while True:
        try:
            gpu = read_intel_gpu_stats()
            intel = collect_intel(gpu)
            lm = collect_lmstudio(gpu)
            build_dat(intel, lm)
        except Exception:
            pass
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
