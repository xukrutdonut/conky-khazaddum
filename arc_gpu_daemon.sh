#!/usr/bin/env bash
# arc_gpu_daemon.sh — Monitoriza Intel Arc con intel_gpu_top, escribe /tmp/conky_arc.dat
OUTFILE="/tmp/conky_arc.dat"
cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

# Inicializar con ceros
cat > "$OUTFILE" << 'INIT'
FREQ_REQ:0
FREQ_ACT:0
RC6:0
POWER:0
RNDR:0
VIDEO:0
COMPUTE:0
COPY:0
INIT

header_skip=2
while IFS= read -r line; do
    # Saltar las dos líneas de cabecera
    if (( header_skip > 0 )); then
        (( header_skip-- ))
        continue
    fi
    # Formato: req_freq  act_freq  irq/s  RC6%  gpu_W  pkg_W  RCS%  ...  VCS%  ...  VECS%  ...  CCS%
    read -ra f <<< "$line"
    [[ ${#f[@]} -lt 10 ]] && { header_skip=2; continue; }
    # La línea vacía reinicia el bloque
    cat > "$OUTFILE" << BLOCK
FREQ_REQ:${f[0]:-0}
FREQ_ACT:${f[1]:-0}
RC6:${f[3]:-0}
POWER:${f[4]:-0}
RNDR:${f[6]:-0}
VIDEO:${f[12]:-0}
COMPUTE:${f[18]:-0}
COPY:${f[9]:-0}
BLOCK
done < <(intel_gpu_top -s 1000 2>/dev/null)
