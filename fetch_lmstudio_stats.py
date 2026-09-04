#!/usr/bin/env python3
import json
import os
import subprocess
import re
import time
import glob

DAT_FILE = '/tmp/conky_lmstudio.dat'
SPEED_TRACKER = '/tmp/conky_lmstudio_speed_tracker.json'
INTERVAL = 1.0

def load_speed_tracker():
    if os.path.exists(SPEED_TRACKER):
        try:
            with open(SPEED_TRACKER, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_speed_tracker(tracker):
    try:
        with open(SPEED_TRACKER + '.tmp', 'w') as f:
            json.dump(tracker, f)
        os.replace(SPEED_TRACKER + '.tmp', SPEED_TRACKER)
    except Exception:
        pass

def detect_hardware(m):
    text = f"{m.get('displayName', '')} {m.get('path', '')} {m.get('publisher', '')} {m.get('modelKey', '')}".lower()
    if 'rx480' in text or 'radeon' in text or 'amd-rx480' in text:
        return 'AMD Radeon RX 480'
    elif 'arc' in text or 'intel-arc' in text:
        return 'Intel Arc GPU'
    elif 'openvino' in text or 'ov-' in text or '[ov' in text or ' ov ' in text:
        return 'Intel OpenVINO'
    elif 'hailo' in text:
        return 'Hailo-8L NPU'
    elif 'npu' in text or 'ai boost' in text:
        return 'Intel AI Boost NPU'
    elif 'cuda' in text or 'nvidia' in text or 'rtx' in text:
        return 'NVIDIA CUDA GPU'
    elif 'vulkan' in text:
        return 'Vulkan GPU'
    elif 'rocm' in text:
        return 'AMD ROCm GPU'
    else:
        return 'CPU Host'

def tail_lines(filepath, n=3000):
    try:
        with open(filepath, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            buffer_size = min(size, 2 * 1024 * 1024)
            f.seek(size - buffer_size)
            data = f.read().decode('utf-8', errors='ignore')
            lines = data.splitlines()
            return lines[-n:]
    except Exception:
        return []

last_known_models = []
last_online_time = 0.0

def collect():
    global last_known_models, last_online_time
    speed_tracker = load_speed_tracker()
    dat_lines = []

    online = False
    models = []

    try:
        r = subprocess.run(
            ['/home/arkantu/.lmstudio/bin/lms', 'ps', '--json'],
            capture_output=True, text=True, timeout=15.0
        )
        if r.returncode == 0:
            online = True
            last_online_time = time.time()
            models_raw = json.loads(r.stdout.strip()) if r.stdout.strip() else []
            
            for idx, m in enumerate(models_raw):
                model_id = m.get('identifier') or m.get('modelKey') or str(idx)
                full_name = m.get('displayName') or model_id or 'Modelo'
                short_title = full_name.split('[')[0].strip() if '[' in full_name else full_name[:24]
                
                disp = full_name
                if len(disp) > 34:
                    disp = disp[:31] + '...'
                
                hw = detect_hardware(m)
                params = m.get('paramsString', '—')
                quant = m.get('quantization', {}).get('name', '—')
                arch = m.get('architecture', '—')
                c_len = m.get('contextLength', 0)
                max_c = m.get('maxContextLength', 32768)
                ctx_pct = int(min(100, (c_len / max_c) * 100)) if max_c > 0 else 0
                
                st = m.get('status', 'idle')
                if st in ['generating', 'generatingTokens', 'streaming']:
                    act_txt = 'Generando'
                elif st in ['processingPrompt', 'prompt_eval', 'eval']:
                    act_txt = 'Prompt Eval'
                elif st in ['loading', 'loadingModel']:
                    act_txt = 'Cargando'
                elif st in ['unloading']:
                    act_txt = 'Descargando'
                else:
                    act_txt = 'Listo'

                last_spd = float(speed_tracker.get(model_id, 0.0))

                models.append({
                    'idx': idx,
                    'model_id': model_id,
                    'hw': hw,
                    'short_title': short_title,
                    'name': disp,
                    'raw_status': st,
                    'params': params,
                    'quant': quant,
                    'arch': arch,
                    'c_len': c_len,
                    'max_c': max_c,
                    'ctx_pct': ctx_pct,
                    'act_txt': act_txt,
                    'spd_val': last_spd,
                    'spd_txt': f"{last_spd:.2f} tok/s" if last_spd > 0 else "0.00 tok/s",
                    'spd_pct': int(min(100, (last_spd / 30.0) * 100)) if last_spd > 0 else 0
                })
            last_known_models = models
    except Exception:
        pass

    # Si falló la llamada pero estaba online recientemente, mantener estado previo
    if not online and (time.time() - last_online_time) < 30.0 and last_known_models:
        online = True
        models = last_known_models

    n = len(models)
    state_str = f"ONLINE ({n} {'modelo' if n==1 else 'modelos'})" if online else "OFFLINE"

    # Leer logs de servidor para capturar velocidad REAL en tiempo real y 10 logs de developer
    logs_formatted = []
    try:
        log_files = sorted(glob.glob(os.path.expanduser('~/.lmstudio/server-logs/*/*.log')), key=os.path.getmtime, reverse=True)
        lines = []
        for lp in log_files[:3]:
            lines.extend(tail_lines(lp, 2500))

        if lines:
            for line in reversed(lines):
                m_speed = re.search(r'tg\s*=\s*([\d\.]+)\s*t/s', line)
                if m_speed:
                    val = float(m_speed.group(1))
                    if models:
                        active_id = models[0]['model_id']
                        speed_tracker[active_id] = val
                        models[0]['spd_val'] = val
                        models[0]['spd_txt'] = f"{val:.2f} tok/s"
                        models[0]['spd_pct'] = int(min(100, (val / 30.0) * 100))
                    break
                m_eval = re.search(r'([\d\.]+)\s*tokens per second', line)
                if m_eval:
                    val = float(m_eval.group(1))
                    if models:
                        active_id = models[0]['model_id']
                        speed_tracker[active_id] = val
                        models[0]['spd_val'] = val
                        models[0]['spd_txt'] = f"{val:.2f} tok/s"
                        models[0]['spd_pct'] = int(min(100, (val / 50.0) * 100))
                    break

            meaningful = []
            skip = ['Client created.', 'Client disconnected.', 'getInstanceProcessingState', 'getLoadConfig']
            last_line = ''
            for line in reversed(lines):
                clean = line.strip()
                if not clean or clean.startswith('{') or clean.startswith('}') or clean.startswith('"') or clean.endswith('}'):
                    continue
                if any(k in clean for k in skip):
                    continue
                if not clean.startswith('[') and not any(k in clean for k in ['INFO', 'DEBUG', 'ERROR', 'WARN', 'slot', 'load_model', 'POST', 'GET', 'HTTP']):
                    continue
                
                clean = re.sub(r'\[\d{4}-\d{2}-\d{2}\s+', '[', clean)
                clean = re.sub(r'\[LMSAuthenticator\](?:\[Client=[^\]]+\])?', '', clean)
                clean = re.sub(r'\[Endpoint=([^\]]+)\]', r'[\1]', clean)
                clean = re.sub(r'\s{2,}', ' ', clean)
                clean = re.sub(r'[^\x20-\x7E]', '', clean)
                
                if clean == last_line:
                    continue
                last_line = clean
                
                if len(clean) > 46:
                    clean = clean[:43] + '...'
                
                if '[ERROR]' in clean:
                    formatted = f"${{color3}}{clean}${{color}}"
                elif '[WARN]' in clean:
                    formatted = f"${{color5}}{clean}${{color}}"
                elif '[INFO]' in clean:
                    formatted = f"${{color2}}{clean}${{color}}"
                elif '[DEBUG]' in clean:
                    formatted = f"${{color1}}{clean}${{color}}"
                else:
                    formatted = f"${{color}}{clean}${{color}}"
                
                meaningful.append(formatted)
                if len(meaningful) >= 10:
                    break
            logs_formatted = list(reversed(meaningful))
    except Exception:
        pass

    save_speed_tracker(speed_tracker)

    # Construir DAT file
    dat_lines.append(f"STATE:{state_str}")
    dat_lines.append(f"ONLINE:{1 if online else 0}")
    dat_lines.append(f"NUM_MODELS:{len(models)}")

    for i, m in enumerate(models):
        dat_lines.append(f"M{i}_TITLE:{m['short_title']}")
        dat_lines.append(f"M{i}_NAME:{m['name']}")
        dat_lines.append(f"M{i}_HW:{m['hw']}")
        dat_lines.append(f"M{i}_CFG:{m['params']} {m['quant']}")
        dat_lines.append(f"M{i}_ARCH:{m['arch']}")
        dat_lines.append(f"M{i}_ACT:{m['act_txt']}")
        dat_lines.append(f"M{i}_SPD_TXT:{m['spd_txt']}")
        dat_lines.append(f"M{i}_SPD_VAL:{int(m['spd_val'])}")
        dat_lines.append(f"M{i}_SPD_PCT:{m['spd_pct']}")
        dat_lines.append(f"M{i}_CTX_USED:{m['c_len']:,}")
        dat_lines.append(f"M{i}_CTX_MAX:{m['max_c']:,}")
        dat_lines.append(f"M{i}_CTX_PCT:{m['ctx_pct']}")

    if logs_formatted:
        dat_lines.append(f"LOGS:{'@@@'.join(logs_formatted)}")
    else:
        dat_lines.append(f"LOGS:${{color6}}(Sin logs recientes)${{color}}")

    try:
        with open(DAT_FILE + '.tmp', 'w') as f:
            f.write("\n".join(dat_lines) + "\n")
        os.replace(DAT_FILE + '.tmp', DAT_FILE)
    except Exception:
        pass

def main():
    while True:
        try:
            collect()
        except Exception:
            pass
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
