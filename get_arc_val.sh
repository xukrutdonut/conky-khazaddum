#!/usr/bin/env bash
# get_arc_val.sh — Lee un valor de /tmp/conky_arc.dat
KEY="${1:-}"
val=$(awk -F: -v k="$KEY" '$1==k {print $2; exit}' /tmp/conky_arc.dat 2>/dev/null)
if [ "$KEY" = "GTT" ]; then
    # GTT:50.2 — conservar el decimal (GB de memoria de GPU en uso)
    printf '%s\n' "$(echo "$val" | tr -dc '0-9.')" | sed 's/^$/0/'
    exit 0
fi
val_clean=$(echo "$val" | tr -dc '0-9')
echo "${val_clean:-0}"

