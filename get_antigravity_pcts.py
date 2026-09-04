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

c_pct, g_pct, o_pct = 100, 100, 100
try:
    if os.path.exists(cache):
        data = json.load(open(cache))
        for m in data.get('models', []):
            mid = m.get('modelId', '').lower()
            pct = int(m.get('remainingPercentage', 0) * 100)
            if 'claude' in mid:
                c_pct = pct
            elif 'gemini' in mid and not m.get('isAutocompleteOnly', False):
                g_pct = pct
            elif 'gpt' in mid:
                o_pct = pct
except Exception:
    pass

print(f'{c_pct},{g_pct},{o_pct}')
