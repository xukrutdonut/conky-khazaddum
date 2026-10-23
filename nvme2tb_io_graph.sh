#!/usr/bin/env bash
# Wrapper: % de escala para execgraph de I/O del NVMe 2TB.
# El nombre del script determina la métrica: nvme2tb_read.sh / nvme2tb_write.sh
NAME=$(basename "$0" .sh)
case "$NAME" in
    *read)  KEY=NVME2TB_READ  ; MAX=2000000000 ;;   # 2 GB/s
    *write) KEY=NVME2TB_WRITE ; MAX=500000000  ;;   # 500 MB/s
    *) echo 0; exit 1 ;;
esac

VAL=$(awk -F: -v k="$KEY" '$1==k{print $2; exit}' /tmp/conky_nvme2tb_io.dat 2>/dev/null)
LC_ALL=C awk -v v="${VAL:-0}" -v m="$MAX" 'BEGIN{
    # escala raíz cuadrada: actividad pequeña visible (1% de MAX -> 10%)
    pct = int(100 * sqrt(v / m) + 0.5)
    if (pct > 100) pct = 100
    if (pct < 0) pct = 0
    print pct
}'
