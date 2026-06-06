#!/bin/bash
# Obtiene el % restante de cuota premium de GitHub Copilot
# Cachea el resultado 5 minutos para no saturar la API

CACHE_FILE="/tmp/copilot_quota_cache.json"
CACHE_TTL=300

read_cache() {
    python3 - "$1" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    qs = d.get('quota_snapshots', {}).get('premium_interactions', {})
    print('100' if qs.get('unlimited') else f"{qs.get('percent_remaining', 0):.1f}")
except:
    print('N/A')
PYEOF
}

# Usar caché si es reciente
if [ -f "$CACHE_FILE" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0) ))
    if [ "$AGE" -lt "$CACHE_TTL" ]; then
        read_cache "$CACHE_FILE"
        exit 0
    fi
fi

TOKEN=$(gh auth token 2>/dev/null)
[ -z "$TOKEN" ] && echo "N/A" && exit 0

curl -sf --max-time 10 --connect-timeout 5 \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/copilot_internal/user" \
    > "$CACHE_FILE" 2>/dev/null

[ ! -s "$CACHE_FILE" ] && echo "N/A" && exit 0
read_cache "$CACHE_FILE"
