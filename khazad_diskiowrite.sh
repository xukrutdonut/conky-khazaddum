#!/usr/bin/env bash
# Wrapper: lee /tmp/conky_diskio.dat y devuelve % de 500 MB/s para execgraph
# El nombre del symlink determina la métrica: khazad_diskioread.sh o khazad_diskiowrite.sh
NAME=$(basename "$0" .sh)
case "$NAME" in
    *read)  KEY=DISKIO_READ ;;
    *write) KEY=DISKIO_WRITE ;;
    *) echo 0; exit 1 ;;
esac

VAL=$(awk -F: -v k="$KEY" '$1==k{print $2; exit}' /tmp/conky_diskio.dat 2>/dev/null)
# % de 500 MB/s (1 MB/s = 0.2%)
LC_ALL=C awk -v v="${VAL:-0}" 'BEGIN{
    pct = int(v / 5000000 + 0.5)
    if (pct > 100) pct = 100
    if (pct < 0) pct = 0
    print pct
}'
