#!/usr/bin/env python3
"""Daemon que recolecta stats de los servicios IA locales:
  - Intel OpenVINO Model Server (contenedor ia-gpu-intel-openvino, :8006)
  - llama.cpp Vulkan del nodo Pi5 .80 (:1235, RX 480 por PCIe)
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
# Nodo Pi5 .80: llama.cpp Vulkan (RX 480 por PCIe) sirviendo en :1235
RPI5_HOST = '192.168.0.80'
RPI5_PORT = 1235
RPI5_BASE = f'http://{RPI5_HOST}:{RPI5_PORT}'
_rpi5_prev = {'t': 0.0, 'pred': 0.0, 'prompt': 0.0}
_rpi5_gpu_cache = {'t': 0.0, 'val': None}


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


# -------------------------------------------------- nodo Pi5 .80 (:1235) --
def http_status(url, timeout=3):
    """Codigo HTTP de un endpoint (000 = sin respuesta)."""
    try:
        r = subprocess.run(
            ['curl', '-s', '-o', '/dev/null', '-m', str(timeout), '-w', '%{http_code}', url],
            capture_output=True, text=True, timeout=timeout + 2
        )
        return r.stdout.strip() or '000'
    except Exception:
        return '000'


def http_get_text(url, timeout=3):
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 2
        )
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return ''


def parse_metrics(text):
    """Parser minimo de /metrics (formato Prometheus) -> {nombre: valor}."""
    vals = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.rsplit(' ', 1)
        if len(parts) != 2:
            continue
        try:
            vals[parts[0]] = float(parts[1])
        except ValueError:
            continue
    return vals


def rpi5_gpu():
    """GPU AMD del nodo .80 (amdgpu) leida por SSH y cacheada 60s.
    Sin amdgpu la imagen Vulkan cae a llvmpipe y el panel debe decirlo."""
    now = time.time()
    if _rpi5_gpu_cache['val'] is not None and now - _rpi5_gpu_cache['t'] < 60:
        return _rpi5_gpu_cache['val']
    val = {'driver': '', 'busy': 0, 'temp': 0}
    cmd = (
        'for d in /sys/class/drm/card*/device; do '
        'drv=$(grep -m1 "^DRIVER=" $d/uevent 2>/dev/null | cut -d= -f2); '
        'if [ "$drv" = "amdgpu" ]; then '
        'busy=$(cat $d/gpu_busy_percent 2>/dev/null); '
        'tmp=$(cat $d/hwmon/hwmon*/temp1_input 2>/dev/null | head -1); '
        'echo "$drv|${busy:-0}|${tmp:-0}"; exit 0; fi; done; echo "none|0|0"'
    )
    try:
        r = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
             'arkantu@' + RPI5_HOST, cmd],
            capture_output=True, text=True, timeout=10
        )
        out = (r.stdout or '').strip().splitlines()
        if out:
            parts = out[-1].split('|')
            val['driver'] = parts[0]
            val['busy'] = int(float(parts[1] or 0)) if len(parts) > 1 else 0
            temp = int(float(parts[2] or 0)) if len(parts) > 2 else 0
            val['temp'] = round(temp / 1000.0) if temp > 1000 else temp
    except Exception:
        pass
    _rpi5_gpu_cache.update({'t': now, 'val': val})
    return val


def collect_rpi5():
    """Estado del servidor llama.cpp del Pi5 .80 (Vulkan, RX 480) via HTTP."""
    code = http_status(RPI5_BASE + '/health')
    state = {'200': 'listo', '503': 'cargando', '000': 'sin respuesta'}.get(code, 'http ' + code)
    props = http_get_json(RPI5_BASE + '/props') if code == '200' else None
    slots = http_get_json(RPI5_BASE + '/slots') if code == '200' else None
    met = parse_metrics(http_get_text(RPI5_BASE + '/metrics')) if code == '200' else {}

    alias = (props or {}).get('model_alias') or ''
    if not alias:
        path = (props or {}).get('model_path') or ''
        alias = os.path.basename(path.rstrip('/')) if path else '?'
    params = ((props or {}).get('default_generation_settings') or {}).get('params') or {}
    n_ctx = params.get('n_ctx') or (props or {}).get('n_ctx') or 0

    total_slots = (props or {}).get('total_slots') or (len(slots) if isinstance(slots, list) else 0)
    busy_slots = sum(1 for s in (slots or []) if isinstance(s, dict) and s.get('is_processing'))

    now = time.time()
    pred = met.get('llamacpp:tokens_predicted_total', 0.0)
    prompt = met.get('llamacpp:prompt_tokens_total', 0.0)
    tps = pps = 0.0
    prev = _rpi5_prev
    if prev['t'] and now > prev['t'] and pred >= prev['pred']:
        dt = now - prev['t']
        tps = (pred - prev['pred']) / dt
        pps = (prompt - prev['prompt']) / dt
    if code == '200' and met:
        _rpi5_prev.update({'t': now, 'pred': pred, 'prompt': prompt})
    else:
        _rpi5_prev.update({'t': 0.0, 'pred': 0.0, 'prompt': 0.0})

    return {
        'state': state,
        'running': code == '200',
        'http': code,
        'model': alias,
        'quant': (props or {}).get('model_ftype') or '?',
        'ctx': n_ctx,
        'slots_total': total_slots,
        'slots_busy': busy_slots,
        'tps': tps,
        'pps': pps,
        'kv': met.get('llamacpp:kv_cache_usage_ratio', 0.0) * 100,
        'processing': int(met.get('llamacpp:requests_processing', 0)),
        'deferred': int(met.get('llamacpp:requests_deferred', 0)),
        'gpu': rpi5_gpu(),
        'metrics': bool(met),
    }


def build_dat(intel, rpi5):
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

    # ---- Pi5 .80: llama.cpp Vulkan (RX 480 por PCIe)
    lines.append(f"RPI_STATE:{rpi5['state']}")
    lines.append(f"RPI_RUNNING:{1 if rpi5['running'] else 0}")
    lines.append(f"RPI_HTTP:{rpi5['http']}")
    lines.append(f"RPI_MODEL:{rpi5['model']}")
    lines.append(f"RPI_QUANT:{rpi5['quant']}")
    lines.append(f"RPI_CTX:{rpi5['ctx']}")
    lines.append(f"RPI_SLOTS:{rpi5['slots_busy']}/{rpi5['slots_total']}")
    lines.append(f"RPI_TPS:{rpi5['tps']:.1f}")
    lines.append(f"RPI_PPS:{rpi5['pps']:.0f}")
    lines.append(f"RPI_KV:{rpi5['kv']:.0f}")
    lines.append(f"RPI_PROC:{rpi5['processing']}")
    lines.append(f"RPI_DEFER:{rpi5['deferred']}")
    lines.append(f"RPI_METRICS:{1 if rpi5['metrics'] else 0}")
    gpu = rpi5['gpu']
    lines.append(f"RPI_GPU_DRIVER:{gpu['driver']}")
    lines.append(f"RPI_GPU_BUSY:{int(gpu['busy'])}")
    lines.append(f"RPI_GPU_TEMP:{int(gpu['temp'])}")

    write_dat(lines)


def main():
    while True:
        try:
            gpu = read_intel_gpu_stats()
            intel = collect_intel(gpu)
            rpi5 = collect_rpi5()
            build_dat(intel, rpi5)
        except Exception:
            pass
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
