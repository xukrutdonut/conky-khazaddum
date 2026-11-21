#!/usr/bin/env python3
"""Daemon que recolecta stats de los contenedores IA (Intel OpenVINO + Ninfer V100).
Monitoriza el uso de GPU para Intel y el contenedor ninfer-serve para el V100.
Escribe /tmp/conky_containers.dat para que containers_render.py lo lea.
"""
import calendar
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
_hist = {}            # series 0-100 de uso GPU (para la sparkline)
_loads = {}           # id -> (duracion ultimo 'engine ready' en s, ts de fin)
_load_seen = {}       # id -> ts en que el panel vio 'loading' por primera vez


def hist_load():
    global _hist, _loads
    try:
        with open(HIST_FILE) as f:
            d = json.load(f)
        _loads = {k: (float(v[0]), float(v[1])) for k, v in (d.get('__loads__') or {}).items()}
        # se descartan las series SWAP:: antiguas (carriles de tiempo)
        _hist = {k: [float(x) for x in v][-HIST_MAX:]
                 for k, v in d.items()
                 if not k.startswith('__') and not k.startswith('SWAP::')}
    except Exception:
        _hist, _loads = {}, {}


def hist_save():
    try:
        out = {**_hist, '__loads__': {k: [v[0], v[1]] for k, v in _loads.items()}}
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


def parse_dur(txt):
    """'1m 24.1s' | '50.2s' | '710 ms' | '30m 23.8s' -> segundos."""
    total = 0.0
    for val, unit in re.findall(r'([\d.]+)\s*(ms|m|s)', txt):
        v = float(val)
        total += v / 1000.0 if unit == 'ms' else (v * 60.0 if unit == 'm' else v)
    return total


def log_ts(line):
    m = re.match(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)', line)
    if not m:
        return 0.0
    try:
        # serve.log del contenedor ninfer escribe en UTC (host en CET):
        return calendar.timegm(time.strptime(m.group(1), '%Y-%m-%d %H:%M:%S'))
    except Exception:
        return 0.0


def alpha_prefix(word):
    """Primera secuencia alfabetica en minuscula: 'qwen38-...'->'qwen', 'Gemma-4'->'gemma'."""
    return ''.join(re.findall(r'[a-z]+', word.lower())[:1])


def read_ninfer_log():
    """Ultimos 256 KB de serve.log del contenedor (una sola lectura por ciclo)."""
    try:
        r = subprocess.run(
            ['docker', 'exec', 'ninfer-serve', 'tail', '-c', '262144', '/tmp/serve.log'],
            capture_output=True, text=True, timeout=8)
        return r.stdout or ''
    except Exception:
        return ''


def parse_ninfer_log(text):
    """Cola de serve.log: (eventos engine-ready, episodio de carga abierto).

    Evento = (ts_fin, dur_s, nombre_artefacto) de
    "engine ready | NAME | total 1m 24.1s".
    Episodio = (ts_inicio, pct|None, ts_ultimo, eta_s|None) mientras haya lineas
    "loading weights" posteriores al ultimo evento. serve.log nombra el ARTEFACTO
    (qwen38-35b-a3b-distill), no el id del router (qwen3.8-35b-a3b): cada evento se
    atribuye al id cuyo prefijo alfabetico coincide, y si no coincide ninguno y el
    buffer solo tiene un candidato posible, al ultimo modelo cargado.
    """
    events = []
    ep_start = ep_last = 0.0
    ep_pct = ep_eta = None
    for line in text.splitlines():
        ts = log_ts(line)
        if not ts:
            continue
        if 'engine ready' in line and ' | ' in line:
            m = re.search(r'total (.+?)\s*(?:\||$)', line)
            nm = re.search(r'engine ready \| ([^|]+?)\s*\|', line)
            if m:
                events.append((ts, parse_dur(m.group(1)), nm.group(1).strip() if nm else ''))
            ep_start = ep_last = 0.0
            ep_pct = ep_eta = None
        elif re.search(r'INFO\s+loading weights \|', line):
            ep_start = ep_start or ts
            ep_last = ts
        elif re.search(r'INFO\s+loading weights \d', line):
            m = re.search(r'loading weights ([\d.]+)%.*ETA (.+?)\s*(?:\||$)', line)
            if m:
                ep_pct = float(m.group(1))
                ep_eta = parse_dur(m.group(2))
            ep_start = ep_start or ts
            ep_last = ts
    ep = (ep_start, ep_pct, ep_last, ep_eta) if ep_start else None
    return events, ep


def fmt_tokrate(x):
    """'809.3' | '1070' | '1.07k' -> cadena compacta de tok/s (soporta sufijo k)."""
    try:
        s = str(x).strip().lower()
        mult = 1000.0 if s.endswith('k') else 1.0
        if s.endswith('k'):
            s = s[:-1]
        v = float(s) * mult
    except (TypeError, ValueError):
        return '?'
    if v >= 1000:
        return f'{v/1000:.1f}k'
    return f'{v:.0f}'


def abbrev_req(line):
    """Linea de actividad legible: estado + peticion + tokens + tiempo + velocidad."""
    ts = ''
    m = re.match(r'\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})', line)
    if m:
        ts = m.group(1)[3:]  # mm:ss
    if ' done | openai' in line:
        pr = re.search(r'prompt (\d+)', line)
        op = re.search(r'output (\d+)', line)
        tot = re.search(r'total ([0-9.]+) ?(ms|s)', line)
        dec = re.search(r'decode ([\d.]+k?) tok/s', line)
        msgs = re.search(r'(\d+) messages', line)
        ident = f'#{m_req(line)}'
        if msgs:
            ident += f' · {msgs.group(1)} msgs'
        tok = f'{pr.group(1) if pr else "?"}→{op.group(1) if op else "?"} tok'
        total = ''
        if tot:
            total = f'{tot.group(1)}{"ms" if tot.group(2)=="ms" else "s"}'
        rate = f'{fmt_tokrate(dec.group(1))} tok/s' if dec else ''
        bits = ' · '.join(x for x in (tok, total, rate) if x)
        st = ' [stream]' if 'stream' in line else ''
        return f'✓ {ident}  {bits}{st}'
    if ' started |' in line:
        msgs = re.search(r'(\d+) messages', line)
        mx = re.search(r'max output ([\d,]+)', line)
        ident = f'#{m_req(line)}'
        if mx:
            ident += f' · máx {mx.group(1)}'
        return f'▶ {ident} …'
    if 'throughput |' in line:
        pre = re.search(r'prefill ([\d.]+k?) tok/s', line)
        dec = re.search(r'decode ([\d.]+k?) tok/s', line)
        run = re.search(r'running (\d+)', line)
        bits = []
        if pre: bits.append(f'prefill {fmt_tokrate(pre.group(1))}')
        if dec: bits.append(f'decode {fmt_tokrate(dec.group(1))}')
        if run: bits.append(f'{run.group(1)} activas')
        prefix = f'{ts} ' if ts else ''
        return prefix + ' · '.join(bits) + ' · resumen 5s'
    if 'engine ready' in line or 'loading weights' in line:
        return line[10:58]
    return ''


def m_req(line):
    m = re.search(r'req#(\d+)', line)
    return m.group(1) if m else '?'


def console_done(text, minn=5, maxx=10):
    """Lineas de actividad legibles, en orden cronologico.

    Prioriza lineas informativas — completadas (✓), resumen de throughput y
    eventos de carga — y solo usa 'en proceso' (▶) de relleno, para que con
    muchas peticiones concurrentes no se llene la consola de 'en proceso…'.
    Devuelve entre minn y maxx lineas (amplia la ventana hacia atras si falta)."""
    prim, sec = [], []
    for raw in reversed(text.splitlines()):
        if ' throughput ' in raw or 'engine ready' in raw or 'loading weights' in raw:
            ab = abbrev_req(raw)
            if ab:
                prim.append((raw, ab))
        elif ' done |' in raw:
            ab = abbrev_req(raw)
            if ab:
                prim.append((raw, ab))
        elif ' started |' in raw:
            ab = abbrev_req(raw)
            if ab:
                sec.append((raw, ab))
        if len(prim) >= maxx:
            break
    # Rellenar solo con 'en proceso' si las primarias no llegan a maxx.
    entries = (prim + sec[: maxx - len(prim)])[:maxx]
    entries.reverse()
    # Si faltan hasta minn, ampliar la ventana hacia atras en el log.
    if len(entries) < minn:
        extra = []
        seen = {raw for raw, _ in entries}
        for raw in reversed(text.splitlines()):
            if ' throughput ' in raw or 'engine ready' in raw or 'loading weights' in raw or ' done |' in raw or ' started |' in raw:
                if raw in seen:
                    continue
                ab = abbrev_req(raw)
                if ab:
                    extra.append((raw, ab))
                if len(entries) + len(extra) >= minn:
                    break
        extra.reverse()
        entries = (extra + entries)[:maxx]
    return entries


def emit_console(lines, text):
    """CONSOLE*: linea de actividad abreviada + tipo de color (min 5, max 10).
    CONSOLE_RUN: procesos en curso (running N de la ultima linea throughput)."""
    act = console_done(text)
    lines.append(f'CONSOLE_COUNT:{len(act)}')
    for i, (raw, ab) in enumerate(act):
        kind = 'start' if ' started |' in raw else ('done' if ' done |' in raw else ('thr' if 'throughput' in raw else 'load'))
        lines.append(f'CONSOLE{i}_T:{kind}')
        lines.append(f'CONSOLE{i}_L:{ab}')
    # running N: la linea throughput mas reciente del buffer indica cuantos
    # procesos hay en curso (prefill + decode en el slot). Se usa de tope.
    run = 0
    for raw in reversed(text.splitlines()):
        if 'throughput |' in raw:
            m = re.search(r'running (\d+)', raw)
            if m:
                run = int(m.group(1))
            break
    lines.append(f'CONSOLE_RUN:{run}')



def emit_loads(lines, ninfer, text):
    """LOAD*: estado por modelo + duracion de su ultima carga + swap en curso.

    STATE: loaded (residente) | loading (la API reporta carga en marcha) |
    unloaded. DUR/AGO salen del evento 'engine ready' atribuido al id que se
    quedo cargado. Si ningun id dice 'loading' pero el episodio de serve.log
    sigue vivo, el render pinta una linea generica "swap en curso" con pct/ETA.
    """
    states = ninfer.get('swap') or []
    events, ep = parse_ninfer_log(text)
    now = time.time()
    # atribuir por prefijo alfabetico: el ultimo evento de cada prefijo es la
    # ultima carga de su id (no depende de que el modelo este cargado AHORA,
    # asi sobrevive reinicios del daemon y swaps entre ambos)
    by_pref = {}
    for name, _v in states:
        by_pref.setdefault(alpha_prefix(name), []).append(name)
    for ev_ts, ev_dur, ev_name in events:
        cand = by_pref.get(alpha_prefix(ev_name))
        if cand and len(cand) == 1:
            _loads[cand[0]] = (ev_dur, ev_ts)
            _load_seen.pop(cand[0], None)
    if ep and events and ep[0] < events[-1][0]:
        ep = None
    lines.append(f'LOAD_COUNT:{len(states)}')
    for i, (name, val) in enumerate(states):
        if val in ('loaded', 'ready', 'running'):
            st = 'loaded'
        elif val in ('loading', 'starting', 'pending', 'warming', 'sync'):
            st = 'loading'
        else:
            st = 'unloaded'
        dur = ago = elap = ''
        if st == 'loading':
            # serve.log escribe con buffer: durante la carga puede no haber
            # lineas nuevas aun, asi que el cronometro lo lleva el daemon.
            t = _load_seen.setdefault(name, now)
            elap = f'{max(0.0, now - t):.0f}'
        else:
            _load_seen.pop(name, None)
        if name in _loads:
            d, ts = _loads[name]
            dur, ago = f'{d:.1f}', f'{max(0.0, now - ts):.0f}'
        lines.append(f'LOAD{i}_NAME:{name}')
        lines.append(f'LOAD{i}_STATE:{st}')
        lines.append(f'LOAD{i}_DUR:{dur}')
        lines.append(f'LOAD{i}_AGO:{ago}')
        lines.append(f'LOAD{i}_ELAP:{elap}')
    if ep and (now - ep[2]) < 120:
        _start, pct, last, eta = ep
        lines.append(f'LOAD_EP:{last:.0f}|{"" if pct is None else pct}|{"" if eta is None else f"{eta:.0f}"}')
    hist_save()


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
                    swap_list.append((entry['id'], str((entry.get('status') or {}).get('value') or 'unloaded')))
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
    text = read_ninfer_log()
    emit_loads(lines, ninfer, text)
    emit_console(lines, text)

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
