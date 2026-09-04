#!/usr/bin/env bash
# Script para extraer métricas de la GPU AMD Radeon (amdgpu / eGPU)

CARD_DEV=""
for card in /sys/class/drm/card*/device; do
    if [ "$(basename "$(readlink "$card/driver" 2>/dev/null)" 2>/dev/null)" = "amdgpu" ]; then
        CARD_DEV="$card"
        break
    fi
done

# Fallback por dirección PCI si el enlace drm no está presente
if [ -z "$CARD_DEV" ] && [ -d "/sys/bus/pci/devices/0000:2e:00.0" ]; then
    CARD_DEV="/sys/bus/pci/devices/0000:2e:00.0"
fi

case "${1:-VRAM_PERC}" in
    GPU_BUSY)
        if [ -n "$CARD_DEV" ] && [ -f "$CARD_DEV/gpu_busy_percent" ]; then
            cat "$CARD_DEV/gpu_busy_percent" 2>/dev/null || echo "0"
        else
            echo "0"
        fi
        ;;
    GPU_TEMP)
        if [ -n "$CARD_DEV" ]; then
            hwmon=$(ls "$CARD_DEV/hwmon/" 2>/dev/null | head -1)
            if [ -n "$hwmon" ] && [ -f "$CARD_DEV/hwmon/$hwmon/temp1_input" ]; then
                t=$(cat "$CARD_DEV/hwmon/$hwmon/temp1_input" 2>/dev/null || echo 0)
                echo $((t / 1000))
            else
                echo "0"
            fi
        else
            echo "0"
        fi
        ;;
    GPU_FREQ)
        if [ -n "$CARD_DEV" ]; then
            hwmon=$(ls "$CARD_DEV/hwmon/" 2>/dev/null | head -1)
            if [ -n "$hwmon" ] && [ -f "$CARD_DEV/hwmon/$hwmon/freq1_input" ]; then
                f=$(cat "$CARD_DEV/hwmon/$hwmon/freq1_input" 2>/dev/null || echo 0)
                echo $((f / 1000000))
            else
                echo "0"
            fi
        else
            echo "0"
        fi
        ;;
    VRAM_PERC)
        if [ -n "$CARD_DEV" ] && [ -f "$CARD_DEV/mem_info_vram_used" ] && [ -f "$CARD_DEV/mem_info_vram_total" ]; then
            u=$(cat "$CARD_DEV/mem_info_vram_used" 2>/dev/null || echo 0)
            t=$(cat "$CARD_DEV/mem_info_vram_total" 2>/dev/null || echo 1)
            awk -v u="$u" -v t="$t" 'BEGIN { if (t>0) printf "%.0f\n", (u/t)*100; else print "0" }'
        else
            echo "0"
        fi
        ;;
    VRAM_USED_MB)
        if [ -n "$CARD_DEV" ] && [ -f "$CARD_DEV/mem_info_vram_used" ]; then
            u=$(cat "$CARD_DEV/mem_info_vram_used" 2>/dev/null || echo 0)
            awk -v u="$u" 'BEGIN { printf "%.0f\n", u/1048576 }'
        else
            echo "0"
        fi
        ;;
    VRAM_TOTAL_MB)
        if [ -n "$CARD_DEV" ] && [ -f "$CARD_DEV/mem_info_vram_total" ]; then
            t=$(cat "$CARD_DEV/mem_info_vram_total" 2>/dev/null || echo 0)
            awk -v t="$t" 'BEGIN { printf "%.0f\n", t/1048576 }'
        else
            echo "0"
        fi
        ;;
    GTT_PERC)
        if [ -n "$CARD_DEV" ] && [ -f "$CARD_DEV/mem_info_gtt_used" ] && [ -f "$CARD_DEV/mem_info_gtt_total" ]; then
            u=$(cat "$CARD_DEV/mem_info_gtt_used" 2>/dev/null || echo 0)
            t=$(cat "$CARD_DEV/mem_info_gtt_total" 2>/dev/null || echo 1)
            awk -v u="$u" -v t="$t" 'BEGIN { if (t>0) printf "%.0f\n", (u/t)*100; else print "0" }'
        else
            echo "0"
        fi
        ;;
    *)
        echo "0"
        ;;
esac
