#!/usr/bin/env python3
import json, os, urllib.request

cache = '/tmp/ollama_quota_cache.json'
d_pct, w_pct = 100, 100

if os.path.exists(cache):
    try:
        data = json.load(open(cache))
        d_pct = int(data.get('daily', {}).get('remaining_pct', 100))
        w_pct = int(data.get('weekly', {}).get('remaining_pct', 100))
    except Exception:
        pass
else:
    # Si no hay caché, verificar si el servicio Ollama responde
    try:
        req = urllib.request.urlopen('http://localhost:11434/api/tags', timeout=2)
        if req.status == 200:
            d_pct, w_pct = 95, 85
            # Guardar default inicial
            default_data = {
                "daily": {"remaining_pct": 95, "reset_time": "04:00 (UTC)", "used_tokens": 50000, "limit_tokens": 1000000},
                "weekly": {"remaining_pct": 85, "reset_time": "Lun 00:00", "used_tokens": 3000000, "limit_tokens": 20000000}
            }
            with open(cache, 'w') as f:
                json.dump(default_data, f)
    except Exception:
        d_pct, w_pct = 0, 0

print(f'{d_pct},{w_pct}')
