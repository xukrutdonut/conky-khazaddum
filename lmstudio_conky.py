#!/usr/bin/env python3
import json
import os
import subprocess
import re
import time

def make_bar(pct, length=38, color_fill='${color2}', color_empty='${color6}'):
    pct = max(0, min(100, int(pct)))
    filled_len = int(round(length * pct / 100))
    empty_len = length - filled_len
    if pct > 85:
        color_fill = '${color3}'
    elif pct > 60:
        color_fill = '${color5}'
    
    return f"{color_fill}{'█' * filled_len}{color_empty}{'░' * empty_len}${{color}}"

def get_lmstudio_data():
    data = {
        'online': False,
        'models_count': 0,
        'models': [],
        'speed_tps': 0.0,
        'speed_str': '0.00 tok/s',
        'speed_pct': 0,
        'logs': []
    }

    try:
        r = subprocess.run(
            ['/home/arkantu/.lmstudio/bin/lms', 'ps', '--json'],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            data['online'] = True
            models = json.loads(r.stdout.strip()) if r.stdout.strip() else []
            data['models_count'] = len(models)
            data['models'] = models
    except Exception:
        data['online'] = False

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
                lines = f.readlines()[-3000:]

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

            meaningful_logs = []
            skip_keywords = [
                'listLoaded', 'Client disconnected', 'Client created',
                'getInstanceProcessingState', 'getModelInfo', 'getLoadConfig',
                'listDownloadedModels', 'lmstudio-greeting', '    at '
            ]
            for line in reversed(lines):
                clean = line.strip()
                if not clean or clean.startswith('{') or clean.startswith('}') or clean.startswith('"') or clean.endswith('}'):
                    continue
                if any(x in clean for x in skip_keywords):
                    continue
                if not clean.startswith('[') and not any(k in clean for k in ['INFO', 'DEBUG', 'ERROR', 'WARN', 'slot', 'load_model']):
                    continue
                
                clean = re.sub(r'\[\d{4}-\d{2}-\d{2}\s+', '[', clean)
                if len(clean) > 46:
                    clean = clean[:43] + '...'
                meaningful_logs.append(clean)
                if len(meaningful_logs) >= 6:
                    break
            
            data['logs'] = list(reversed(meaningful_logs))
    except Exception:
        pass

    return data

def render():
    d = get_lmstudio_data()

    if not d['online']:
        print("${color1}Servidor:${color} ${color3}OFFLINE${color}")
        print("${color6}(LM Studio server no responde en puerto 1234)${color}")
        return

    print(f"${{color1}}Servidor:${{color}} ${{color2}}ONLINE (1234)${{color}}   ${{color1}}Modelos cargados:${{color}} ${{color4}}{d['models_count']}${{color}}")
    
    if not d['models']:
        print("${color1}Actividad:${{color}} ${color6}Sin modelo en memoria${color}")
        print("${hr 1}")
    else:
        for idx, m in enumerate(d['models'][:2]):
            disp = m.get('displayName') or m.get('identifier') or m.get('modelKey') or 'Modelo'
            if len(disp) > 34:
                disp = disp[:31] + '...'
            
            params = m.get('paramsString', '—')
            quant = m.get('quantization', {}).get('name', '—')
            arch = m.get('architecture', '—')
            c_len = m.get('contextLength', 0)
            max_c = m.get('maxContextLength', 32768)
            ctx_pct = int((c_len / max_c * 100)) if max_c > 0 else 0
            
            status_raw = m.get('status', 'idle')
            if status_raw in ['generating', 'generatingTokens', 'streaming']:
                st_disp = 'Generando Respuestas'
                st_clr = '${color5}'
            elif status_raw in ['processingPrompt', 'prompt_eval', 'eval']:
                st_disp = 'Evaluando Prompt (Prompt Eval)'
                st_clr = '${color4}'
            elif status_raw in ['loading', 'loadingModel']:
                st_disp = 'Cargando Modelo...'
                st_clr = '${color1}'
            elif status_raw in ['unloading']:
                st_disp = 'Descargando...'
                st_clr = '${color3}'
            else:
                st_disp = 'Listo / Inactivo'
                st_clr = '${color2}'

            print("${color4}── MODELO " + (f"#{idx+1} " if d['models_count'] > 1 else "") + "────────────────────────────────${color}")
            print(f"${{color4}}{disp}${{color}}")
            print(f"${{color1}}Config:${{color}}    ${{color2}}{params} {quant}${{color}} ({arch})")
            print(f"${{color1}}Actividad:${{color}} {st_clr}{st_disp}${{color}}")
            
            # Barra de Velocidad
            spd_pct = d['speed_pct'] if d['speed_tps'] > 0 else 0
            spd_txt = d['speed_str']
            print(f"${{color1}}Velocidad:${{color}} ${{color2}}{spd_txt}${{color}}  ${{color5}}({spd_pct}%)${{color}}")
            print(make_bar(spd_pct, length=38, color_fill='${color2}'))
            
            # Barra de Contexto
            print(f"${{color1}}Contexto:${{color}}  ${{color2}}{c_len:,} / {max_c:,}${{color}} tokens ${{color5}}({ctx_pct}%)${{color}}")
            print(make_bar(ctx_pct, length=38, color_fill='${color1}'))

    # Sección de Logs
    print("${color4}── LOGS DE DESARROLLADOR ────────────────────────${color}")
    if d['logs']:
        for log in d['logs']:
            if '[ERROR]' in log:
                print(f"${{color3}}{log}${{color}}")
            elif '[WARN]' in log:
                print(f"${{color5}}{log}${{color}}")
            elif '[INFO]' in log:
                print(f"${{color2}}{log}${{color}}")
            elif '[DEBUG]' in log:
                print(f"${{color1}}{log}${{color}}")
            else:
                print(f"${{color6}}{log}${{color}}")
    else:
        print("${color6}(Sin eventos recientes en logs)${color}")

if __name__ == '__main__':
    render()
