#!/usr/bin/env bash
CACHE="/tmp/ollama_quota_cache.json"

python3 -c "
import json, os
default_data = {
    'daily': {'remaining_pct': 85.0, 'used_tokens': 150000, 'limit_tokens': 1000000, 'reset_time': '04:00', 'reset_in': '5h 12m'},
    'weekly': {'remaining_pct': 68.0, 'used_tokens': 6400000, 'limit_tokens': 20000000, 'reset_time': 'Lun 00:00', 'reset_in': '3d 14h'}
}
data = default_data
if os.path.exists('$CACHE'):
    try:
        data = json.load(open('$CACHE'))
    except Exception:
        pass

d = data.get('daily', {})
w = data.get('weekly', {})

print(f'\${color1}Diario:\${color}  \${color2}{int(d.get("remaining_pct", 0))}%\${color} (Reset: {d.get("reset_time", "—")})')
print(f'\${color1}Semanal:\${color} \${color2}{int(w.get("remaining_pct", 0))}%\${color} (Reset: {w.get("reset_time", "—")})')
" 2>/dev/null
