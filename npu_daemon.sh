#!/usr/bin/env bash
# npu_daemon.sh — Monitoriza Intel NPU vía sysfs / /dev/accel/accel0, escribe /tmp/conky_npu.dat
NPU_PCI="0000:00:0b.0"
NPU_SYSFS="/sys/bus/pci/devices/${NPU_PCI}"
OUTFILE="/tmp/conky_npu.dat"
INTERVAL_US=2000000

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

cat > "$OUTFILE" << 'INIT'
BUSY:0
FREQ:0
FREQ_MAX:1600
MEM_MB:0
INIT

prev_busy=0

while true; do
    rstatus=$(cat "${NPU_SYSFS}/power/runtime_status" 2>/dev/null || echo "unknown")
    
    busy=$(cat "${NPU_SYSFS}/npu_busy_time_us" 2>/dev/null || echo 0)
    freq=$(cat "${NPU_SYSFS}/npu_current_frequency_mhz" 2>/dev/null || echo 0)
    freq_max=$(cat "${NPU_SYSFS}/npu_max_frequency_mhz" 2>/dev/null || echo 1600)
    mem_bytes=$(cat "${NPU_SYSFS}/npu_memory_utilization" 2>/dev/null || echo 0)

    if [[ $prev_busy -gt 0 && $busy -ge $prev_busy ]]; then
        delta_busy=$(( busy - prev_busy ))
        pct=$(( delta_busy * 100 / INTERVAL_US ))
        (( pct < 0 ))   && pct=0
        (( pct > 100 )) && pct=100
    else
        pct=0
    fi

    # Si la NPU está suspendida o idle, aseguramos reporte de memoria
    mem_mb=$(( mem_bytes / 1048576 ))

    cat > "$OUTFILE".tmp << BLOCK
BUSY:${pct}
FREQ:${freq}
FREQ_MAX:${freq_max}
MEM_MB:${mem_mb}
BLOCK
    mv "$OUTFILE".tmp "$OUTFILE"

    prev_busy=$busy
    sleep 2
done
