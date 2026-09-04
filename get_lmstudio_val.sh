#!/usr/bin/env bash
# get_lmstudio_val.sh — Lee un valor de /tmp/conky_lmstudio.dat
KEY="${1:-}"
DAT="/tmp/conky_lmstudio.dat"

if [ "$KEY" = "LOGS" ]; then
    raw=$(awk -F: -v k="LOGS" '$1==k {print substr($0, 6); exit}' "$DAT" 2>/dev/null)
    echo -e "${raw//@@@/\\n}"
    exit 0
fi

val=$(awk -F: -v k="$KEY" '$1==k {print substr($0, length(k)+2); exit}' "$DAT" 2>/dev/null)

# Si es una clave numérica para execbar o execgraph, garantizar que devuelva un entero limpio
if [[ "$KEY" == *"_PCT"* || "$KEY" == *"_VAL"* ]]; then
    val_clean=$(echo "$val" | tr -dc '0-9')
    echo "${val_clean:-0}"
    exit 0
fi

echo "${val:-—}"
