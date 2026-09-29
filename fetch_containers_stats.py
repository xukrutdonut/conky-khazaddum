#!/usr/bin/env python3
"""Daemon que recolecta stats de los contenedores IA (Intel OpenVINO + AMD RX480).
Escribe /tmp/conky_containers.dat para que containers_render.py lo lea."""
import json
import os
import subprocess
import time
import socket

DAT_FILE = '/tmp/conky_containers.dat'
INTERVAL = 5          # poll cada 5s
BENCH_INTERVAL = 30   # benchmark tok/s cada 30s
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
            status = parts[0]  # running, exited, etc.
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

def http_post_json(url, payload, timeout=30):
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), '-X', 'POST',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps(payload), url],
            capture_output=True, text=True, timeout=timeout + 5
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

def collect_intel(last_bench_time, last_tps):
    """Recolecta datos del contenedor Intel OpenVINO (:8006)."""
    running, status = docker_status('ia-gpu-intel-openvino')
    if not running:
        return {
            'running': False,
            'status': status,
            'models': [],
            'gpu': None,
            'tps': 0.0,
            'tps_txt': '—',
            'tps_pct': 0,
            'last_bench': last_bench_time,
        }

    health = http_get_json(f'http://127.0.0.1:{INTEL_PORT}/health')
    gpu_info = http_get_json(f'http://127.0.0.1:{INTEL_PORT}/v1/admin/gpu/status')
    models_info = http_get_json(f'http://127.0.0.1:{INTEL_PORT}/v1/admin/models')

    loaded_models = []
    all_models = []
    if models_info and 'models' in models_info:
        for m in models_info['models']:
            entry = {
                'name': m.get('name', '?'),
                'type': m.get('type', '?'),
                'loaded': m.get('loaded', False),
                'size_mb': m.get('size_mb', 0),
            }
            all_models.append(entry)
            if entry['loaded']:
                loaded_models.append(entry)

    # Benchmark tok/s periódico
    now = time.time()
    tps = last_tps
    tps_txt = f"{last_tps:.1f} tok/s" if last_tps > 0 else "—"
    tps_pct = int(min(100, (last_tps / 50.0) * 100)) if last_tps > 0 else 0

    if loaded_models and (now - last_bench_time) >= BENCH_INTERVAL:
        model_name = loaded_models[0]['name']
        bench = http_post_json(
            f'http://127.0.0.1:{INTEL_PORT}/v1/admin/benchmark',
            {'model': model_name},
            timeout=45
        )
        if bench and 'tokens_per_second' in bench:
            tps = round(bench['tokens_per_second'], 1)
            tps_txt = f"{tps:.1f} tok/s"
            tps_pct = int(min(100, (tps / 50.0) * 100))
            last_bench_time = now

    return {
        'running': True,
        'status': status,
        'health': health.get('status', '?') if health else '?',
        'models': all_models,
        'loaded_models': loaded_models,
        'gpu': gpu_info,
        'tps': tps,
        'tps_txt': tps_txt,
        'tps_pct': tps_pct,
        'last_bench': last_bench_time,
    }

def collect_amd():
    """Recolecta datos del contenedor AMD RX480 (:1235)."""
    running, status = docker_status('ia-gpu-amd-rx480')
    if not running:
        return {
            'running': False,
            'status': status,
            'models': [],
            'tps_txt': '—',
            'tps_pct': 0,
        }

    # Si está corriendo, intentar API
    models = []
    if port_open(AMD_PORT):
        data = http_get_json(f'http://127.0.0.1:{AMD_PORT}/v1/models', timeout=3)
        if data and 'data' in data:
            for m in data['data']:
                models.append({
                    'name': m.get('id', '?'),
                    'loaded': m.get('loaded', False),
                })

    return {
        'running': True,
        'status': status,
        'models': models,
        'tps_txt': '—',  # AMD no tiene endpoint benchmark
        'tps_pct': 0,
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
        for i, m in enumerate(unloaded[:4]):  # max 4 para no saturar
            lines.append(f"INTEL_A{i}_NAME:{m['name']}")
            lines.append(f"INTEL_A{i}_TYPE:{m['type']}")
        lines.append(f"INTEL_TPS_TXT:{intel['tps_txt']}")
        lines.append(f"INTEL_TPS_PCT:{intel['tps_pct']}")

    # AMD
    lines.append(f"AMD_RUNNING:{1 if amd['running'] else 0}")
    lines.append(f"AMD_STATUS:{amd['status']}")
    if amd['running']:
        loaded = [m for m in amd['models'] if m['loaded']]
        lines.append(f"AMD_NUM_LOADED:{len(loaded)}")
        for i, m in enumerate(loaded):
            lines.append(f"AMD_M{i}_NAME:{m['name']}")
        lines.append(f"AMD_TPS_TXT:{amd['tps_txt']}")
        lines.append(f"AMD_TPS_PCT:{amd['tps_pct']}")

    write_dat(lines)

def main():
    last_bench_time = 0.0
    last_tps = 0.0
    while True:
        try:
            intel = collect_intel(last_bench_time, last_tps)
            last_bench_time = intel.get('last_bench', last_bench_time)
            last_tps = intel.get('tps', last_tps)
            amd = collect_amd()
            build_dat(intel, amd)
        except Exception:
            pass
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()