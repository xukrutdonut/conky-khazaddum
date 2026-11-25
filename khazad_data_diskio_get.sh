#!/usr/bin/env bash
# Getter: tasa instantanea de I/O del disco 2TB (/mnt/data) en formato legible.
# Uso: khazad_data_diskio_get.sh [read|write]
KEY=$([[ "$1" == "write" ]] && echo DATA_WRITE || echo DATA_READ)
VAL=$(awk -F: -v k="$KEY" '$1==k{print $2; exit}' /tmp/conky_diskio.dat 2>/dev/null)
# formatear bytes/s -> B/K/M/G
LC_ALL=C awk -v v="${VAL:-0}" 'BEGIN{
    if (v >= 1073741824) printf "%.1fG", v/1073741824
    else if (v >= 1048576) printf "%.1fM", v/1048576
    else if (v >= 1024) printf "%.0fK", v/1024
    else printf "%dB", v
}'
