#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# gpu_info.sh — Información de GPU Intel Arc desde sysfs
# Uso: gpu_info.sh [freq|freq_max|nvme_temp|cpu_temp]
# ─────────────────────────────────────────────────────────────────────────────

CARD="/sys/class/drm/card1"

case "${1:-freq}" in
    freq)
        # gt_cur_freq_mhz es más fiable que gt_act (que puede ser 0 en idle)
        f="${CARD}/gt_cur_freq_mhz"
        [ -f "$f" ] && awk '{printf "%d MHz", $1}' "$f" || echo "N/A"
        ;;
    freq_max)
        f="${CARD}/gt_max_freq_mhz"
        [ -f "$f" ] && awk '{printf "%d MHz", $1}' "$f" || echo "N/A"
        ;;
    nvme_temp)
        f="/sys/class/hwmon/hwmon1/temp1_input"
        [ -f "$f" ] && awk '{printf "%.0f°C", $1/1000}' "$f" || echo "N/A"
        ;;
    cpu_temp)
        # coretemp Package id 0 / thermal zone
        awk '{printf "%.0f°C", $1/1000; exit}' /sys/devices/platform/coretemp.0/hwmon/hwmon*/temp1_input /sys/class/thermal/thermal_zone1/temp 2>/dev/null || echo "N/A"
        ;;
esac
