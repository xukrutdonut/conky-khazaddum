#!/usr/bin/env python3
"""Daemon que recolecta stats de los servicios IA locales:
  - Intel OpenVINO Model Server (contenedor ia-gpu-intel-openvino, :8006)
  - LM Studio (:1234, Vulkan sobre la iGPU Arc) modelo, ctx y tokens/s
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
    Sin amdgpu la imagen Vulkan cae a llvmpipe y el panel debe decirlo.
    Se resuelve por direccion PCI estable (vendor 0x1002 + driver amdgpu):
    /dev/dri/cardN cambia de indice entre reinicios."""
    now = time.time()
    if _rpi5_gpu_cache['val'] is not None and now - _rpi5_gpu_cache['t'] < 60:
        return _rpi5_gpu_cache['val']
    val = {'driver': '', 'busy': 0, 'temp': 0, 'vram_pct': 0,
           'vram_used_mb': 0, 'vram_total_mb': 0, 'freq_mhz': 0,
           'power_w': 0, 'pci': 'none'}
    cmd = (
        'for p in /sys/bus/pci/devices/*/; do '
        'v=$(cat ${p}vendor 2>/dev/null); '
        'drv=$(readlink ${p}driver 2>/dev/null); drv=${drv##*/}; '
        '[ "$v" = "0x1002" ] && [ "$drv" = "amdgpu" ] || continue; '
        'hw=$(ls ${p}hwmon 2>/dev/null | head -1); '
        'busy=$(cat ${p}gpu_busy_percent 2>/dev/null); '
        'tmp=$(cat ${p}hwmon/$hw/temp1_input 2>/dev/null); '
        'vu=$(cat ${p}mem_info_vram_used 2>/dev/null); '
        'vt=$(cat ${p}mem_info_vram_total 2>/dev/null); '
        'fr=$(cat ${p}hwmon/$hw/freq1_input 2>/dev/null); '
        'pw=$(cat ${p}hwmon/$hw/power1_input 2>/dev/null); '
        'echo "amdgpu|${busy:-0}|${tmp:-0}|${vu:-0}|${vt:-0}|${fr:-0}|${pw:-0}|$(basename $p)"; '
        'exit 0; done; echo "none|0|0|0|0|0|0|none"'
    )
    try:
        r = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
             'arkantu@' + RPI5_HOST, cmd],
            capture_output=True, text=True, timeout=10
        )
        out = (r.stdout or '').strip().splitlines()
        if out:
            p = (out[-1].split('|') + [''] * 8)[:8]
            val['driver'] = p[0]
            val['busy'] = int(float(p[1] or 0))
            temp = int(float(p[2] or 0))
            val['temp'] = round(temp / 1000.0) if temp > 1000 else temp
            vu, vt = int(float(p[3] or 0)), int(float(p[4] or 0))
            val['vram_used_mb'] = vu // 1048576
            val['vram_total_mb'] = vt // 1048576
            if val['vram_total_mb']:
                val['vram_pct'] = val['vram_used_mb'] * 100 // val['vram_total_mb']
            val['freq_mhz'] = int(float(p[5] or 0)) // 1000000
            val['power_w'] = int(float(p[6] or 0)) // 1000000
            val['pci'] = p[7] or 'none'
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


# ------------------------------------------------- LM Studio (:1234) --
# LM Studio no publica metricas Prometheus. Fuentes reales que si existen:
#   * GET /api/v0/models  -> modelos, state (loaded/not-loaded), quant, ctx
#   * `lms ps --json`     -> status (idle/generating), queued, parallel, peso
#   * ~/.lmstudio/server-logs/AAAA-MM/AAAA-MM-DD.N.log  (verbose=true)
#       "[ts][DEBUG] ... print_timing: id 3 | task 346237 | n_gen = 4153,
#        tg = 72.30 t/s, tg_3s = 90.42 t/s"
#       "... | prompt eval time = 480.1 ms / 25 tokens (... 52.1 tokens per second)"
#     El log es la unica fuente de tokens/s. Se lee de forma incremental
#     (offset) para no releer 5 MB cada 5 s; al arrancar se lee entero una vez
#     para tener los totales del dia.
LM_PORT = 1234
LM_HOST = '127.0.0.1'
LM_LOG_DIR = os.path.expanduser('~/.lmstudio/server-logs')
LM_LIVE_WINDOW = 15      # s sin lineas de timing => generacion terminada
_lm_log = {'path': None, 'offset': 0, 'tail': '', 'tasks': {}, 'gens': 0, 'tok': 0}
_lm_ps = {'t': 0.0, 'val': {}}
_lm_last = {'pps': 0.0}
LM_TS_RE = re.compile(r'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]')
LM_GEN_RE = re.compile(
    r'print_timing: id\s+(\d+)\s*\|\s*task\s+(\d+)\s*\|\s*n_gen\s*=\s*(\d+),'
    r'\s*tg\s*=\s*([\d.]+) t/s,\s*tg_\d+s\s*=\s*([\d.]+) t/s'
)
LM_PROMPT_RE = re.compile(
    r'(?:prompt eval time =|prompt processing, n_tokens\s*=\s*\d+,)'
    r'.*?([\d.]+) tokens per second'
)
LM_TASK_RE = re.compile(r'print_timing: id\s+(\d+)\s*\|\s*task\s+(\d+)\s*\|')


def lm_log_path():
    """Log del servidor mas reciente (rota a medianoche)."""
    try:
        files = glob.glob(os.path.join(LM_LOG_DIR, '*', '*.log'))
        return max(files, key=os.path.getmtime) if files else None
    except Exception:
        return None


def lm_parse_lines(lines, st, now):
    for line in lines:
        ts = now
        tsm = LM_TS_RE.match(line)
        if tsm:
            try:
                ts = time.mktime(time.strptime(tsm.group(1), '%Y-%m-%d %H:%M:%S'))
            except Exception:
                ts = now
        m = LM_GEN_RE.search(line)
        if m:
            task = int(m.group(2))
            n_gen = int(m.group(3))
            t = st['tasks'].get(task)
            if t is None:
                t = {'task': task, 'n_gen': 0}
                st['tasks'][task] = t
            if not t.get('counted'):
                t['counted'] = True
                st['gens'] += 1
            if n_gen > t['n_gen']:
                st['tok'] += n_gen - t['n_gen']
            t.update({'n_gen': max(n_gen, t['n_gen']), 'ts': ts,
                      'tg': float(m.group(4)), 'tg3': float(m.group(5)),
                      'slot': int(m.group(1))})
            continue
        m = LM_PROMPT_RE.search(line)
        if m:
            tm = LM_TASK_RE.search(line)
            if not tm:
                continue
            task = int(tm.group(2))
            t = st['tasks'].setdefault(task, {'task': task, 'n_gen': 0})
            t['pps'] = float(m.group(1))
            _lm_last['pps'] = t['pps']
            t.setdefault('ts', ts)


def lm_read_log(st, now):
    """Lectura incremental del log: reconstruye el dia al arrancar/rotar."""
    path = lm_log_path()
    if not path:
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if path != st['path'] or size < st['offset']:
        st.update({'path': path, 'offset': 0, 'tail': '', 'tasks': {},
                   'gens': 0, 'tok': 0})
    if size <= st['offset']:
        return
    try:
        with open(path, 'r', errors='replace') as f:
            f.seek(st['offset'])
            chunk = f.read()
    except OSError:
        return
    st['offset'] = size
    lines = (st['tail'] + chunk).split('\n')
    st['tail'] = lines.pop() if lines else ''
    lm_parse_lines(lines, st, now)
    if len(st['tasks']) > 400:       # poda: solo las 100 tareas recientes
        keep = sorted(st['tasks'].values(), key=lambda t: t.get('ts', 0))[-100:]
        st['tasks'] = {t['task']: t for t in keep}


def lm_ps_info():
    """`lms ps --json` cacheado 60 s (status, cola, slots, tamano del modelo)."""
    now = time.time()
    if _lm_ps['val'] and now - _lm_ps['t'] < 60:
        return _lm_ps['val']
    val = {}
    lms = '/usr/local/bin/lms' if os.path.exists('/usr/local/bin/lms') else 'lms'
    try:
        r = subprocess.run([lms, 'ps', '--json'], capture_output=True,
                           text=True, timeout=8)
        if r.returncode == 0 and r.stdout.strip():
            for m in json.loads(r.stdout.strip()):
                key = m.get('modelKey') or m.get('identifier') or '?'
                val[key] = {
                    'status': m.get('status', ''),
                    'queued': int(m.get('queued', 0) or 0),
                    'parallel': int(m.get('parallel', 0) or 0),
                    'ctx': int(m.get('contextLength', 0) or 0),
                    'size_gb': round((m.get('sizeBytes') or 0) / 1073741824.0, 1),
                    'display': m.get('displayName') or key,
                }
    except Exception:
        val = {}
    _lm_ps.update({'t': now, 'val': val})
    return val


def collect_lmstudio():
    """Estado del servidor LM Studio local (:1234) + ritmo de generacion."""
    now = time.time()
    lm_read_log(_lm_log, now)
    models = http_get_json(f'http://{LM_HOST}:{LM_PORT}/api/v0/models')
    running = isinstance(models, dict) and isinstance(models.get('data'), list)
    ps = lm_ps_info() if running else {}

    loaded = []
    total = 0
    if running:
        for m in models.get('data', []):
            total += 1
            if m.get('state') == 'loaded':
                mid = m.get('id', '?')
                p = ps.get(mid, {})
                loaded.append({
                    'id': mid,
                    'quant': m.get('quantization') or '?',
                    'ctx': int(m.get('loaded_context_length')
                               or m.get('max_context_length') or 0),
                    'parallel': p.get('parallel', 0),
                    'queued': p.get('queued', 0),
                    'size_gb': p.get('size_gb', 0),
                })

    tasks = [t for t in _lm_log['tasks'].values() if 'tg' in t and t.get('ts')]
    live = [t for t in tasks if t.get('ts') and now - t['ts'] <= LM_LIVE_WINDOW]
    live.sort(key=lambda t: t['ts'])
    gen = live[-1] if live else None
    older = [t for t in tasks if t.get('ts') and now - t['ts'] > LM_LIVE_WINDOW]
    last = max(older, key=lambda t: t['ts']) if older else None
    if not live:
        last = max((t for t in tasks if t.get('ts')), key=lambda t: t['ts'],
                   default=None)

    return {
        'running': running,
        'models_total': total,
        'models_loaded': loaded,
        'generating': gen is not None,
        'g_tg': gen['tg'] if gen else 0.0,
        'g_tg3': gen['tg3'] if gen else 0.0,
        'g_tok': gen['n_gen'] if gen else 0,
        'g_pps': (gen.get('pps') if gen else 0.0) or _lm_last['pps'],
        'last_tg': last['tg'] if last else 0.0,
        'last_tok': last['n_gen'] if last else 0,
        'last_age': int(now - last['ts']) if last else -1,
        'today_gens': _lm_log['gens'],
        'today_tok': int(_lm_log['tok']),
    }


def build_dat(intel, lm, rpi5):
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

    # ---- LM Studio (:1234, misma iGPU Arc por Vulkan)
    lines.append(f"LM_RUNNING:{1 if lm['running'] else 0}")
    lines.append(f"LM_STATE:{'listo' if lm['running'] else 'sin respuesta'}")
    lines.append(f"LM_MODELS_TOTAL:{lm['models_total']}")
    lines.append(f"LM_MODELS_LOADED:{len(lm['models_loaded'])}")
    for i, m in enumerate(lm['models_loaded'][:3]):
        lines.append(f"LM_M{i}_NAME:{m['id']}")
        lines.append(f"LM_M{i}_QUANT:{m['quant']}")
        lines.append(f"LM_M{i}_CTX:{m['ctx']}")
        lines.append(f"LM_M{i}_SLOTS:{m['parallel']}")
        lines.append(f"LM_M{i}_QUEUE:{m['queued']}")
        lines.append(f"LM_M{i}_SIZE:{m['size_gb']}")
    lines.append(f"LM_GENERATING:{1 if lm['generating'] else 0}")
    lines.append(f"LM_TG:{lm['g_tg']:.1f}")
    lines.append(f"LM_TG3:{lm['g_tg3']:.1f}")
    lines.append(f"LM_TOK:{lm['g_tok']}")
    lines.append(f"LM_PPS:{lm['g_pps']:.0f}")
    lines.append(f"LM_LAST_TG:{lm['last_tg']:.1f}")
    lines.append(f"LM_LAST_TOK:{lm['last_tok']}")
    lines.append(f"LM_LAST_AGE:{lm['last_age']}")
    lines.append(f"LM_TODAY_GENS:{lm['today_gens']}")
    lines.append(f"LM_TODAY_TOK:{lm['today_tok']}")

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
    lines.append(f"RPI_GPU_VRAMPCT:{int(gpu['vram_pct'])}")
    lines.append(f"RPI_GPU_VRAMUSED:{int(gpu['vram_used_mb'])}")
    lines.append(f"RPI_GPU_VRAMTOTAL:{int(gpu['vram_total_mb'])}")
    lines.append(f"RPI_GPU_FREQ:{int(gpu['freq_mhz'])}")
    lines.append(f"RPI_GPU_PWR:{int(gpu['power_w'])}")
    lines.append(f"RPI_GPU_PCI:{gpu['pci']}")

    write_dat(lines)


def main():
    while True:
        try:
            gpu = read_intel_gpu_stats()
            intel = collect_intel(gpu)
            lm = collect_lmstudio()
            rpi5 = collect_rpi5()
            build_dat(intel, lm, rpi5)
        except Exception:
            pass
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
