#!/usr/bin/env bash
CACHE="/tmp/antigravity_quota_cache.json"

if [ ! -f "$CACHE" ] || [ $(($(date +%s) - $(stat -c %Y "$CACHE" 2>/dev/null || echo 0))) -gt 300 ]; then
    ~/.nvm/versions/node/v22.22.2/bin/antigravity-usage quota --json > "$CACHE.tmp" 2>/dev/null && mv "$CACHE.tmp" "$CACHE" || true
fi

python3 -c "
import json
try:
    data = json.load(open('$CACHE'))
    models = data.get('models', [])
    seen = set()
    for m in models:
        mid = m.get('modelId', '')
        pct = int(m.get('remainingPercentage', 0) * 100)
        reset = m.get('timeUntilResetMs', 0) // 1000
        hrs = reset // 3600
        mins = (reset % 3600) // 60
        
        if 'claude' in mid and 'claude' not in seen:
            seen.add('claude')
            print(f'\${color1}Claude 4.6:\${color} \${color2}{pct}%\${color} (Reset: {hrs}h {mins}m)')
        elif 'gemini' in mid and 'gemini' not in seen:
            seen.add('gemini')
            print(f'\${color1}Gemini 3.6:\${color} \${color2}{pct}%\${color} (Reset: {hrs}h {mins}m)')
        elif 'gpt' in mid and 'gpt' not in seen:
            seen.add('gpt')
            print(f'\${color1}GPT-OSS:\${color}    \${color2}{pct}%\${color} (Reset: {hrs}h {mins}m)')
except Exception:
    print('\${color3}Cuotas no disponibles\${color}')
" 2>/dev/null
