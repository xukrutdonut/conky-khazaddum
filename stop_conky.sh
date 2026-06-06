#!/usr/bin/env bash
for pid in $(pgrep -f "conky -c.*conky_"); do kill "$pid" 2>/dev/null; done
# Los daemons arc_gpu_daemon, npu_daemon y fetch_rpi_stats son gestionados por systemd.
# Para pararlos: systemctl --user stop arc-gpu-daemon npu-daemon fetch-rpi-stats
echo "Conky detenido."
