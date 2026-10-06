#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# gpu_info.sh — Información de GPU Intel Arc desde sysfs
# Uso: gpu_info.sh [freq|freq_max|nvme_temp|cpu_temp]
#
# IMPORTANTE: rutas resueltas dinámicamente. La enumeración DRM (cardN) y la de
# hwmon NO son estables: cambian entre arranques y con actualizaciones de
# Ubuntu. Nunca fijar índices a mano.
# ─────────────────────────────────────────────────────────────────────────────

i915_card() {
    for c in /sys/class/drm/card[0-9]*; do
        [ "$(basename "$(readlink -f "$c/device/driver" 2>/dev/null)")" = "i915" ] && { echo "$c"; return; }
    done
}

hwmon_by_name() {
    for h in /sys/class/hwmon/hwmon*; do
        [ "$(cat "$h/name" 2>/dev/null)" = "$1" ] && { echo "$h"; return; }
    done
}

case "${1:-freq}" in
    freq)
        # gt_cur_freq_mhz es más fiable que gt_act (que puede ser 0 en idle)
        f="$(i915_card)/gt_cur_freq_mhz"
        [ -f "$f" ] && awk '{printf "%d MHz", $1}' "$f" || echo "N/A"
        ;;
    freq_max)
        f="$(i915_card)/gt_max_freq_mhz"
        [ -f "$f" ] && awk '{printf "%d MHz", $1}' "$f" || echo "N/A"
        ;;
    nvme_temp)
        # El disco de sistema es SATA: módulo drivetemp expone su temp por hwmon
        f="$(hwmon_by_name drivetemp)/temp1_input"
        [ -f "$f" ] && awk '{printf "%.0f°C", $1/1000}' "$f" || echo "N/A"
        ;;
    cpu_temp)
        # coretemp Package id 0 / thermal zone
        awk '{printf "%.0f°C", $1/1000; exit}' /sys/devices/platform/coretemp.0/hwmon/hwmon*/temp1_input /sys/class/thermal/thermal_zone1/temp 2>/dev/null || echo "N/A"
        ;;
esac
