#!/usr/bin/env bash
# disk_section.sh IP — genera sección de almacenamiento para RPi
# Lee del dat file del daemon SSH y muestra cada disco con barra unicode

IP="${1:-}"
TAG="${IP//\./_}"
DATFILE="/tmp/conky_rpi/rpi_${TAG}.dat"

bar() {
    local pct=${1:-0} w=34
    local f=$(( pct * w / 100 )) e
    (( f > w )) && f=$w
    e=$(( w - f ))
    local bar=""
    for (( i=0; i<f; i++ )); do bar+="▓"; done
    for (( i=0; i<e; i++ )); do bar+="░"; done
    echo "$bar"
}

count=$(grep "^DISK_COUNT:" "$DATFILE" 2>/dev/null | cut -d: -f2)
count=${count:-0}
(( count == 0 )) && { echo "(sin discos)"; exit 0; }

for i in $(seq 0 $(( count - 1 ))); do
    name=$(grep "^DISK${i}_NAME:" "$DATFILE" 2>/dev/null | cut -d: -f2)
    pct=$(grep "^DISK${i}_PCT:" "$DATFILE" 2>/dev/null | cut -d: -f2)
    used=$(grep "^DISK${i}_USED_H:" "$DATFILE" 2>/dev/null | cut -d: -f2)
    total=$(grep "^DISK${i}_TOTAL_H:" "$DATFILE" 2>/dev/null | cut -d: -f2)
    [[ -z "$name" || "$name" == "0" ]] && continue
    printf "%-14s %s / %s (%s%%)\n" "${name}:" "${used:-?}" "${total:-?}" "${pct:-0}"
    echo "$(bar ${pct:-0})"
done
