#!/usr/bin/env python3
import json, os, subprocess, time

cache = '/tmp/antigravity_quota_cache.json'
if not os.path.exists(cache) or (time.time() - os.path.getmtime(cache) > 120):
    try:
        r = subprocess.run([os.path.expanduser('~/.nvm/versions/node/v22.22.2/bin/antigravity-usage'), 'quota', '--json'], capture_output=True, text=True, timeout=10)
        if r.stdout and r.returncode == 0:
            with open(cache + '.tmp', 'w') as f:
                f.write(r.stdout)
            os.replace(cache + '.tmp', cache)
    except Exception:
        pass

try:
    if not os.path.exists(cache):
        print('${color3}Sin datos de cuota${color}')
        exit(0)

    data = json.load(open(cache))
    models = data.get('models', [])
    seen = set()
    for m in models:
        mid = m.get('modelId', '').lower()
        pct = int(m.get('remainingPercentage', 0) * 100)
        reset_ms = m.get('timeUntilResetMs', 0)
        reset = reset_ms // 1000 if reset_ms else 0
        hrs = reset // 3600
        mins = (reset % 3600) // 60
        
        if 'claude' in mid and 'claude' not in seen:
            seen.add('claude')
            print(f'${{color1}}Claude 4.6:${{color}} ${{color2}}{pct}%${{color}} (Reset: {hrs}h {mins}m)')
        elif 'gemini' in mid and not m.get('isAutocompleteOnly', False) and 'gemini' not in seen:
            seen.add('gemini')
            print(f'${{color1}}Gemini 3.7:${{color}} ${{color2}}{pct}%${{color}} (Reset: {hrs}h {mins}m)')
        elif 'gpt' in mid and 'gpt' not in seen:
            seen.add('gpt')
            print(f'${{color1}}GPT-OSS:${{color}}    ${{color2}}{pct}%${{color}} (Reset: {hrs}h {mins}m)')
except Exception:
    print('${color3}Cuotas no disponibles${color}')
