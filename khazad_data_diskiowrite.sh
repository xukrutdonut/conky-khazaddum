#!/usr/bin/env bash
# Wrapper: lee /tmp/conky_diskio.dat y devuelve % de 500 MB/s para execgraph.
# I/O ESPECIFICO del disco 2TB (/mnt/data). El nombre del symlink define la métrica.
NAME=$(basename "$0" .sh)
case "$NAME" in
    *read)  KEY=DATA_READ ;;
    *write) KEY=DATA_WRITE ;;
    *) echo 0; exit 1 ;;
esac

VAL=$(awk -F: -v k="$KEY" '$1==k{print $2; exit}' /tmp/conky_diskio.dat 2>/dev/null)
# % de 200 MB/s (1 MB/s = 0.5%)
LC_ALL=C awk -v v="${VAL:-0}" 'BEGIN{
    pct = int(v / 2000000 + 0.5)
    if (pct > 100) pct = 100
    if (pct < 0) pct = 0
    print pct
}'
