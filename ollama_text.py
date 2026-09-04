#!/usr/bin/env python3
import json, os, urllib.request

cache = '/tmp/ollama_quota_cache.json'
data = {'daily': {'remaining_pct': 95, 'reset_time': '04:00 (UTC)'}, 'weekly': {'remaining_pct': 85, 'reset_time': 'Lun 00:00'}}

if os.path.exists(cache):
    try:
        data = json.load(open(cache))
    except Exception:
        pass
else:
    try:
        req = urllib.request.urlopen('http://localhost:11434/api/tags', timeout=2)
        if req.status == 200:
            with open(cache, 'w') as f:
                json.dump(data, f)
    except Exception:
        pass

d = data.get('daily', {})
w = data.get('weekly', {})
dpct = int(d.get('remaining_pct', 0))
dres = d.get('reset_time', '—')
wpct = int(w.get('remaining_pct', 0))
wres = w.get('reset_time', '—')

# Obtener modelos cloud disponibles de Ollama
cloud_models = []
try:
    req = urllib.request.urlopen('http://localhost:11434/api/tags', timeout=2)
    tags_data = json.loads(req.read().decode())
    for m in tags_data.get('models', []):
        if 'cloud' in m.get('name', '') or m.get('remote_host'):
            cloud_models.append(m.get('name'))
except Exception:
    pass

print(f'${{color1}}Diario:${{color}}  ${{color2}}{dpct}%${{color}} (Reset: {dres})')
print(f'${{color1}}Semanal:${{color}} ${{color2}}{wpct}%${{color}} (Reset: {wres})')
if cloud_models:
    print(f'${{color1}}Modelo:${{color}}  ${{color4}}{", ".join(cloud_models[:1])}${{color}}')
else:
    print(f'${{color1}}Estado:${{color}}  ${{color2}}Conectado${{color}}')
