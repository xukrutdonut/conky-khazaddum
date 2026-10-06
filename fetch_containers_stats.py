#!/usr/bin/env python3
"""Daemon que recolecta stats de los contenedores IA (Intel OpenVINO + AMD RX480).
Escribe /tmp/conky_containers.dat para que containers_render.py lo lea.

Monitoriza uso real de GPU sin lanzar benchmarks.
- Intel Arc: intel_gpu_top -J (RC6 idle, power, engines)
- AMD RX480: sysfs gpu_busy_percent + mem_info_vram
"""
import json
import os
import subprocess
import time
import socket

DAT_FILE = '/tmp/conky_containers.dat'
INTERVAL = 5          # poll cada 5s
INTEL_PORT = 8006
AMD_PORT = 1235

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
        import time as _t
        deadline = _t.time() + 5
        while _t.time() < deadline:
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

def find_amdgpu_card():
    """Localiza el sysfs device del driver amdgpu dinámicamente
    (la enumeración DRM no es estable entre arranques)."""
    import glob
    for link in sorted(glob.glob('/sys/class/drm/card*/device/driver')):
        if os.path.basename(os.readlink(link)) == 'amdgpu':
            return os.path.dirname(link)
    return '/sys/class/drm/card0/device'


def read_amd_gpu_stats():
    """Lee uso real de AMD RX480 via sysfs."""
    stats = {}
    card = find_amdgpu_card()
    try:
        with open(f'{card}/gpu_busy_percent') as f:
            stats['gpu_busy'] = int(f.read().strip())
    except Exception:
        stats['gpu_busy'] = -1
    try:
        with open(f'{card}/mem_info_vram_used') as f:
            stats['vram_used_mb'] = int(f.read().strip()) // (1024 * 1024)
    except Exception:
        stats['vram_used_mb'] = -1
    try:
        with open(f'{card}/mem_info_vram_total') as f:
            stats['vram_total_mb'] = int(f.read().strip()) // (1024 * 1024)
    except Exception:
        stats['vram_total_mb'] = -1
    return stats if stats.get('gpu_busy', -1) >= 0 else None

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

def collect_intel():
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

    # Uso real de GPU via intel_gpu_top
    gpu_usage = read_intel_gpu_stats()

    return {
        'running': True,
        'status': status,
        'health': 'ready' if ready else 'starting',
        'models': all_models,
        'loaded_models': loaded_models,
        'gpu': None,
        'gpu_usage': gpu_usage,
    }

def collect_amd():
    """Recolecta datos del contenedor AMD RX480 (:1235)."""
    running, status = docker_status('ia-gpu-amd-rx480')
    if not running:
        return {
            'running': False,
            'status': status,
            'models': [],
            'gpu_usage': None,
        }

    models = []
    if port_open(AMD_PORT):
        # LM Studio API nativa devuelve 'state': 'loaded'/'not-loaded'
        data = http_get_json(f'http://127.0.0.1:{AMD_PORT}/api/v0/models', timeout=3)
        if data and 'data' in data:
            for m in data['data']:
                models.append({
                    'name': m.get('id', '?'),
                    'loaded': m.get('state', '') == 'loaded',
                    'type': m.get('type', '?'),
                    'quant': m.get('quantization', '?'),
                    'ctx': m.get('loaded_context_length', 0),
                })

    gpu_usage = read_amd_gpu_stats()

    return {
        'running': True,
        'status': status,
        'models': models,
        'gpu_usage': gpu_usage,
    }

def build_dat(intel, amd):
    lines = []
    # Intel
    lines.append(f"INTEL_RUNNING:{1 if intel['running'] else 0}")
    lines.append(f"INTEL_STATUS:{intel['status']}")
    if intel['running']:
        lines.append(f"INTEL_HEALTH:{intel.get('health', '?')}")
        gpu = intel.get('gpu', {})
        if gpu:
            lines.append(f"INTEL_GPU_NAME:{gpu.get('device', 'Intel Arc')}")
            lines.append(f"INTEL_GPU_MEM:{gpu.get('gpu_process_memory_mb', 0):.0f}")
        else:
            lines.append("INTEL_GPU_NAME:Intel Arc")
            lines.append("INTEL_GPU_MEM:0")
        loaded = intel.get('loaded_models', [])
        lines.append(f"INTEL_NUM_LOADED:{len(loaded)}")
        for i, m in enumerate(loaded):
            lines.append(f"INTEL_M{i}_NAME:{m['name']}")
            lines.append(f"INTEL_M{i}_TYPE:{m['type']}")
            lines.append(f"INTEL_M{i}_SIZE:{m['size_mb']:.0f}")
        # Modelos disponibles no cargados
        unloaded = [m for m in intel.get('models', []) if not m['loaded']]
        lines.append(f"INTEL_NUM_AVAIL:{len(unloaded)}")
        for i, m in enumerate(unloaded[:4]):
            lines.append(f"INTEL_A{i}_NAME:{m['name']}")
            lines.append(f"INTEL_A{i}_TYPE:{m['type']}")
        # Uso real de GPU (reemplaza tok/s)
        gu = intel.get('gpu_usage')
        if gu:
            lines.append(f"INTEL_GPU_BUSY:{gu['gpu_busy']}")
            lines.append(f"INTEL_GPU_PWR:{gu['gpu_power']}")
            lines.append(f"INTEL_PKG_PWR:{gu['pkg_power']}")
            lines.append(f"INTEL_RENDER:{gu['render']}")
            lines.append(f"INTEL_COMPUTE:{gu['compute']}")
        else:
            lines.append("INTEL_GPU_BUSY:0")
            lines.append("INTEL_GPU_PWR:0")
            lines.append("INTEL_PKG_PWR:0")
            lines.append("INTEL_RENDER:0")
            lines.append("INTEL_COMPUTE:0")

    # AMD
    lines.append(f"AMD_RUNNING:{1 if amd['running'] else 0}")
    lines.append(f"AMD_STATUS:{amd['status']}")
    if amd['running']:
        loaded = [m for m in amd['models'] if m['loaded']]
        lines.append(f"AMD_NUM_LOADED:{len(loaded)}")
        for i, m in enumerate(loaded):
            lines.append(f"AMD_M{i}_NAME:{m['name']}")
            lines.append(f"AMD_M{i}_TYPE:{m.get('type', '?')}")
            lines.append(f"AMD_M{i}_QUANT:{m.get('quant', '?')}")
            lines.append(f"AMD_M{i}_CTX:{m.get('ctx', 0)}")
        # Modelos disponibles no cargados
        unloaded = [m for m in amd['models'] if not m['loaded']]
        lines.append(f"AMD_NUM_AVAIL:{len(unloaded)}")
        for i, m in enumerate(unloaded[:4]):
            lines.append(f"AMD_A{i}_NAME:{m['name']}")
            lines.append(f"AMD_A{i}_TYPE:{m.get('type', '?')}")
        # Uso real de GPU
        gu = amd.get('gpu_usage')
        if gu:
            lines.append(f"AMD_GPU_BUSY:{gu.get('gpu_busy', 0)}")
            vram_used = gu.get('vram_used_mb', 0)
            vram_total = gu.get('vram_total_mb', 0)
            lines.append(f"AMD_VRAM_USED:{vram_used}")
            lines.append(f"AMD_VRAM_TOTAL:{vram_total}")
        else:
            lines.append("AMD_GPU_BUSY:0")
            lines.append("AMD_VRAM_USED:0")
            lines.append("AMD_VRAM_TOTAL:0")

    write_dat(lines)

def main():
    while True:
        try:
            intel = collect_intel()
            amd = collect_amd()
            # La inferencia en RX480 es en rafagas: muestrear gpu_busy varias
            # veces dentro de la ventana y guardar el PICO para la barra de
            # conky, si no la grafica casi siempre sale 0.
            peak = read_amd_gpu_stats()
            if peak:
                for _ in range(9):
                    time.sleep(INTERVAL / 10)
                    s = read_amd_gpu_stats()
                    if s and s.get('gpu_busy', 0) > peak.get('gpu_busy', 0):
                        peak['gpu_busy'] = s['gpu_busy']
                amd['gpu_usage']['gpu_busy'] = peak['gpu_busy']
            build_dat(intel, amd)
        except Exception:
            pass
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()