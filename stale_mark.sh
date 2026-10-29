#!/usr/bin/env bash
# stale_mark.sh — Marca visible cuando el .dat de un nodo lleva demasiado
# tiempo sin refrescarse. Sin esto un daemon atascado deja el panel mostrando
# el último valor para siempre (p.ej. la RX 480 clavada en "Uso: 100%").
# Uso: stale_mark.sh <ip>   (salida vacía si el dato está fresco)
IP="${1:-}"
TAG="${IP//./_}"
F="/tmp/conky_rpi/rpi_${TAG}.dat"
if [[ ! -f "$F" ]]; then
    echo "\${color3}⚠ sin datos\${color}"
    exit 0
fi
AGE=$(( $(date +%s) - $(stat -c %Y "$F") ))
if (( AGE > 180 )); then
    echo "\${color3}⚠ DATOS CONGELADOS (${AGE}s sin refrescar)\${color}"
fi
exit 0
