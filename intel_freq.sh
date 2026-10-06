#!/usr/bin/env bash
# Frecuencia actual del GPU Intel (i915) — detección dinámica del card,
# la enumeración DRM no es estable entre arranques/actualizaciones.
for c in /sys/class/drm/card[0-9]*; do
    if [ "$(basename "$(readlink -f "$c/device/driver" 2>/dev/null)")" = "i915" ]; then
        cat "$c/gt_cur_freq_mhz" 2>/dev/null && exit 0
    fi
done
echo 0
