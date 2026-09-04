#!/usr/bin/env python3
import json
import os
import subprocess
import re
import sys
import time

CACHE_FILE = '/tmp/conky_lmstudio_cache.json'
CACHE_TTL = 1.5

def update_cache():
    if os.path.exists(CACHE_FILE):
        try:
            if (time.time() - os.path.getmtime(CACHE_FILE)) < CACHE_TTL:
                with open(CACHE_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass

    data = {
        'online': False,
        'models_count': 0,
        'model_name': 'Ninguno',
        'params': '—',
        'quant': '—',
        'arch': '—',
        'status_raw': 'idle',
        'status_display': 'Inactivo',
        'status_color': '5af78e',
        'c_len': 0,
        'max_c': 0,
        'ctx_pct': 0,
        'ctx_str': '0 / 0 tokens (0%)',
        'speed_tps': 0.0,
        'speed_str': '0.00 tok/s',
        'speed_pct': 0,
        'logs': []
    }

    try:
        r = subprocess.run(
            ['/home/arkantu/.lmstudio/bin/lms', 'ps', '--json'],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0:
            data['online'] = True
            models = json.loads(r.stdout.strip()) if r.stdout.strip() else []
            data['models_count'] = len(models)
            if models:
                m = models[0]
                disp = m.get('displayName') or m.get('identifier') or m.get('modelKey') or 'Modelo'
                data['model_name'] = disp[:34]
                data['params'] = m.get('paramsString', '—')
                data['quant'] = m.get('quantization', {}).get('name', '—')
                data['arch'] = m.get('architecture', '—')
                data['c_len'] = m.get('contextLength', 0)
                data['max_c'] = m.get('maxContextLength', 32768)
                if data['max_c'] > 0:
                    data['ctx_pct'] = int(min(100, (data['c_len'] / data['max_c']) * 100))
                    data['ctx_str'] = f"{data['c_len']:,} / {data['max_c']:,} tokens ({data['ctx_pct']}%)"
                
                st = m.get('status', 'idle')
                data['status_raw'] = st
                if st in ['generating', 'generatingTokens', 'streaming']:
                    data['status_display'] = 'Generando Respuestas'
                    data['status_color'] = 'ffb347'
                elif st in ['processingPrompt', 'prompt_eval', 'eval']:
                    data['status_display'] = 'Evaluando Prompt (Prompt Eval)'
                    data['status_color'] = 'ffd700'
                elif st in ['loading', 'loadingModel']:
                    data['status_display'] = 'Cargando Modelo...'
                    data['status_color'] = '5eb8ff'
                elif st in ['unloading']:
                    data['status_display'] = 'Descargando...'
                    data['status_color'] = 'ff6e6e'
                else:
                    data['status_display'] = 'Listo / Inactivo'
                    data['status_color'] = '5af78e'
            else:
                data['status_display'] = 'Sin modelo cargado'
                data['status_color'] = 'a0a0a0'
    except Exception:
        pass

    try:
        state_file = os.path.expanduser('~/.lmstudio/.internal/server-logs-state.json')
        log_path = None
        if os.path.exists(state_file):
            state = json.load(open(state_file))
            base = state.get('lastWrittenFile', {}).get('filePathBase', '')
            idx = state.get('lastWrittenFile', {}).get('index', 1)
            if base:
                log_path = os.path.expanduser(f'~/.lmstudio/server-logs/{base}{idx}.log')
        
        if not log_path or not os.path.exists(log_path):
            import glob
            logs = glob.glob(os.path.expanduser('~/.lmstudio/server-logs/*/*.log'))
            if logs:
                log_path = max(logs, key=os.path.getmtime)

        if log_path and os.path.exists(log_path):
            with open(log_path, 'r', errors='ignore') as f:
                lines = f.readlines()[-2000:]

            for line in reversed(lines):
                m_speed = re.search(r'tg\s*=\s*([\d\.]+)\s*t/s', line)
                if m_speed:
                    data['speed_tps'] = float(m_speed.group(1))
                    data['speed_str'] = f"{data['speed_tps']:.2f} tok/s"
                    data['speed_pct'] = int(min(100, (data['speed_tps'] / 30.0) * 100))
                    break
                m_speed2 = re.search(r'([\d\.]+)\s*(?:tokens/s|tok/s)', line)
                if m_speed2:
                    data['speed_tps'] = float(m_speed2.group(1))
                    data['speed_str'] = f"{data['speed_tps']:.2f} tok/s"
                    data['speed_pct'] = int(min(100, (data['speed_tps'] / 30.0) * 100))
                    break

            meaningful = []
            skip = ['listLoaded', 'Client disconnected', 'Client created', 'getInstanceProcessingState', 'getModelInfo', 'getLoadConfig', 'listDownloadedModels', 'lmstudio-greeting', '    at ']
            for line in reversed(lines):
                clean = line.strip()
                if not clean or clean.startswith('{') or clean.startswith('}') or clean.startswith('"') or clean.endswith('}'):
                    continue
                if any(k in clean for k in skip):
                    continue
                if not clean.startswith('[') and not any(k in clean for k in ['INFO', 'DEBUG', 'ERROR', 'WARN', 'slot', 'load_model']):
                    continue
                
                # Quitar caracteres no imprimibles
                clean = re.sub(r'[^\x20-\x7E]', '', clean)
                clean = re.sub(r'\[\d{4}-\d{2}-\d{2}\s+', '[', clean)
                if len(clean) > 46:
                    clean = clean[:43] + '...'
                meaningful.append(clean)
                if len(meaningful) >= 6:
                    break
            data['logs'] = list(reversed(meaningful))
    except Exception:
        pass

    try:
        with open(CACHE_FILE + '.tmp', 'w') as f:
            json.dump(data, f)
        os.replace(CACHE_FILE + '.tmp', CACHE_FILE)
    except Exception:
        pass

    return data

if __name__ == '__main__':
    data = update_cache()
    query = sys.argv[1] if len(sys.argv) > 1 else ''
    if query == 'speed_pct':
        print(data.get('speed_pct', 0))
    elif query == 'ctx_pct':
        print(data.get('ctx_pct', 0))
    elif query == 'speed_str':
        print(data.get('speed_str', '0.00 tok/s'))
    elif query == 'ctx_str':
        print(data.get('ctx_str', '0 / 0'))
    elif query == 'online':
        print(1 if data.get('online') else 0)
    else:
        print(0)
