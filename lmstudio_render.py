#!/usr/bin/env python3
import json
import os

CACHE_FILE = '/tmp/conky_lmstudio_cache.json'

def make_bar(pct, length=36, fill_clr='${color2}', empty_clr='${color6}'):
    pct = max(0, min(100, int(pct)))
    filled = int(round(length * pct / 100))
    empty = length - filled
    return f"${{color6}}[${{color}}{fill_clr}{'█' * filled}{empty_clr}{'─' * empty}${{color6}}]${{color}}"

def render():
    if not os.path.exists(CACHE_FILE):
        print("${color4}${alignc}LM STUDIO SERVER${color}")
        print("${color1}${alignc}localhost:1234 — ${color3}CARGANDO...${color}")
        print("${hr 1}")
        return

    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
    except Exception:
        print("${color4}${alignc}LM STUDIO SERVER${color}")
        print("${color1}${alignc}localhost:1234 — ${color3}OFFLINE${color}")
        print("${hr 1}")
        return

    if not data.get('online'):
        print("${color4}${alignc}LM STUDIO SERVER${color}")
        print("${color1}${alignc}localhost:1234 — ${color3}OFFLINE${color}")
        print("${hr 1}")
        print("${color6}${alignc}(Servidor no iniciado)${color}")
        return

    models = data.get('models', [])
    n_models = len(models)
    loading = data.get('loading_model')
    
    print("${color4}${alignc}LM STUDIO SERVER${color}")
    print(f"${{color1}}${{alignc}}localhost:1234 — ${{color2}}ONLINE${{color}} ({n_models} {'modelo' if n_models==1 else 'modelos'})")
    print("${hr 1}")

    if loading:
        print(f"${{color1}}Cargando nuevo modelo:${{color}} ${{color4}}{loading}${{color}}")
        print(f"${{color1}}Estado: ${{color1}}Inicializando motor...${{color}}")
        print(make_bar(50, length=36, fill_clr='${color1}'))

    if not models and not loading:
        print("${color6}${alignc}Sin modelos cargados en memoria${color}")
    else:
        for idx, m in enumerate(models):
            title = f"── MODELO #{idx+1} " + ("─" * 36)
            print(f"${{color4}}{title[:48]}${{color}}")
            print(f"${{color4}}{m['name']}${{color}}")
            print(f"${{color1}}Config:    ${{color2}}{m['params']} {m['quant']}${{color}} ({m['arch']})")
            print(f"${{color1}}Actividad: {m['status_clr']}{m['status_txt']}${{color}}")
            print(f"${{color1}}Velocidad: ${{color2}}{m['speed_txt']}${{color}}  ${{color5}}({m['speed_pct']}%)${{color}}")
            print(make_bar(m['speed_pct'], length=36, fill_clr='${color2}'))
            print(f"${{color1}}Contexto:  ${{color2}}{m['ctx_used']:,} / {m['ctx_max']:,}${{color}} tokens  (${{color5}}{m['ctx_pct']}%${{color}})")
            print(make_bar(m['ctx_pct'], length=36, fill_clr='${color1}'))

    print("${color4}── LOGS DE DESARROLLADOR ────────────────────────${color}")
    logs = data.get('logs', [])
    if logs:
        for log in logs:
            print(log)
    else:
        print("${color6}(Sin eventos recientes en logs)${color}")

if __name__ == '__main__':
    render()
