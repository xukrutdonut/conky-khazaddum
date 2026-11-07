#!/usr/bin/env bash
# get_v100_val.sh — Lee un valor de /tmp/conky_v100.dat (lo escribe v100_stats.sh)
KEY="${1:-}"
val=$(awk -F: -v k="$KEY" '$1==k {print $2; exit}' /tmp/conky_v100.dat 2>/dev/null)
case "$KEY" in
    THROTTLE|PSTATE|STATE|NAME)
        # texto: no filtrar bytes
        printf '%s\n' "${val:-0}"
        ;;
    POWER)
        # Pwr lleva decimales opcionales, ya redondeado por el daemon
        printf '%s\n' "$(echo "$val" | tr -dc '0-9')" | sed 's/^$/0/'
        ;;
    *)
        val_clean=$(echo "$val" | tr -dc '0-9')
        echo "${val_clean:-0}"
        ;;
esac
