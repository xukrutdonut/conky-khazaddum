#!/usr/bin/env bash
# npu_daemon.sh — Monitoriza Intel NPU vía sysfs, escribe /tmp/conky_npu.dat
# Calcula % de uso midiendo delta de npu_busy_time_us en intervalos de 1s
NPU_PCI="0000:00:0b.0"
NPU_SYSFS="/sys/bus/pci/devices/${NPU_PCI}"
OUTFILE="/tmp/conky_npu.dat"
INTERVAL_US=1000000  # 1 segundo en microsegundos

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

# Inicializar con ceros
cat > "$OUTFILE" << 'INIT'
BUSY:0
FREQ:0
FREQ_MAX:0
MEM_MB:0
INIT

prev_busy=0

while true; do
    busy=$(cat "${NPU_SYSFS}/npu_busy_time_us" 2>/dev/null || echo 0)
    freq=$(cat "${NPU_SYSFS}/npu_current_frequency_mhz" 2>/dev/null || echo 0)
    freq_max=$(cat "${NPU_SYSFS}/npu_max_frequency_mhz" 2>/dev/null || echo 1600)
    mem_bytes=$(cat "${NPU_SYSFS}/npu_memory_utilization" 2>/dev/null || echo 0)

    if [[ $prev_busy -gt 0 ]]; then
        delta_busy=$(( busy - prev_busy ))
        # Usamos INTERVAL_US fijo porque hacemos sleep 1 exacto
        pct=$(( delta_busy * 100 / INTERVAL_US ))
        (( pct < 0 ))   && pct=0
        (( pct > 100 )) && pct=100
    else
        pct=0
    fi

    mem_mb=$(( mem_bytes / 1048576 ))

    cat > "$OUTFILE" << BLOCK
BUSY:${pct}
FREQ:${freq}
FREQ_MAX:${freq_max}
MEM_MB:${mem_mb}
BLOCK

    prev_busy=$busy
    sleep 1
done
