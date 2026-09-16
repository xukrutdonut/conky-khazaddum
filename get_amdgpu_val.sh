#!/usr/bin/env bash
# Script para extraer métricas de la GPU AMD Radeon (amdgpu / eGPU).
# Protección contra cuelgues del kernel (D-state) con COOLDOWN temporal:
# si una lectura a sysfs se bloquea en D-state, se entra en cooldown 60s
# durante el cual se devuelve 0 sin tocar el kernel. Pasado el cooldown
# se reintenta automáticamente. Nunca se mata conky_khazaddum permanentemente.

COOLDOWN_FILE="/tmp/conky_amdgpu_cooldown"
LOG_FILE="/tmp/conky_amdgpu_cooldown.log"
COOLDOWN_SECS=60

# 1. Si estamos en cooldown, verificar si ha expirado
if [ -f "$COOLDOWN_FILE" ]; then
    cooldown_time=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$((now - cooldown_time))
    if [ "$age" -lt "$COOLDOWN_SECS" ]; then
        # Aún en cooldown: salir sin tocar el kernel
        echo "0"
        exit 0
    else
        # Cooldown expirado: limpiar y continuar
        rm -f "$COOLDOWN_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Cooldown expirado (${age}s). Reintentando lecturas amdgpu." >> "$LOG_FILE"
    fi
fi

# 2. Pre-chequeo: procesos reales (no kworkers) en estado D relacionados con amdgpu
#    Solo kworkers con nombre explícito de amdgpu/ttm/card1 cuentan como bloqueo real
if ps -eo stat,args 2>/dev/null | grep -E '^[[:space:]]*D' | grep -v '\[kworker' | grep -iE '(card1|amdgpu|ttm)' >/dev/null 2>&1; then
    date +%s > "$COOLDOWN_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: Proceso no-kworker en D-state relacionado con amdgpu. Cooldown ${COOLDOWN_SECS}s." >> "$LOG_FILE"
    echo "0"
    exit 0
fi

# Función de lectura segura con timeout. Si la lectura se bloquea en D-state,
# entra cooldown temporal (no permanente). Nunca mata conky.
safe_read() {
    local target="$1"
    local default_val="${2:-0}"
    [ ! -e "$target" ] && { echo "$default_val"; return 0; }

    local tmp_file="/tmp/.amdgpu_val_${$}_${RANDOM}"
    timeout 1s cat "$target" > "$tmp_file" 2>/dev/null &
    local rpid=$!

    # Monitorear hasta ~250ms (5 ticks de 50ms)
    local waited=0
    while kill -0 "$rpid" 2>/dev/null; do
        if [ "$waited" -ge 5 ]; then
            local state
            state=$(awk '{print $3}' "/proc/$rpid/stat" 2>/dev/null || true)
            if [[ "$state" =~ D ]]; then
                # Lectura bloqueada en D-state: entrar en cooldown temporal
                date +%s > "$COOLDOWN_FILE"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: Lectura de $target bloqueada en D-state (PID $rpid). Cooldown ${COOLDOWN_SECS}s." >> "$LOG_FILE"
                kill -9 "$rpid" 2>/dev/null || true
                rm -f "$tmp_file" 2>/dev/null
                echo "$default_val"
                return 1
            fi
            # Si simplemente tardó más de la cuenta sin ser D, abortar el proceso hijo
            kill -9 "$rpid" 2>/dev/null || true
            break
        fi
        sleep 0.05
        waited=$((waited + 1))
    done

    local val="$default_val"
    if [ -s "$tmp_file" ]; then
        val=$(cat "$tmp_file")
    fi
    rm -f "$tmp_file" 2>/dev/null
    echo "$val"
    return 0
}

# Detección del nodo drm de amdgpu
CARD_DEV=""
for card in /sys/class/drm/card*/device; do
    if [ "$(basename "$(readlink "$card/driver" 2>/dev/null)" 2>/dev/null)" = "amdgpu" ]; then
        CARD_DEV="$card"
        break
    fi
done

# Fallback por dirección PCI si el enlace drm no está presente
if [ -z "$CARD_DEV" ] && [ -d "/sys/bus/pci/devices/0000:01:00.0" ]; then
    CARD_DEV="/sys/bus/pci/devices/0000:01:00.0"
fi

case "${1:-VRAM_PERC}" in
    GPU_BUSY)
        if [ -n "$CARD_DEV" ]; then
            val=$(safe_read "$CARD_DEV/gpu_busy_percent" 0)
            echo "${val:-0}"
        else
            echo "0"
        fi
        ;;
    GPU_TEMP)
        if [ -n "$CARD_DEV" ]; then
            hwmon=$(ls "$CARD_DEV/hwmon/" 2>/dev/null | head -1)
            if [ -n "$hwmon" ]; then
                t=$(safe_read "$CARD_DEV/hwmon/$hwmon/temp1_input" 0)
                t_clean=$(echo "$t" | tr -dc '0-9')
                t_num=${t_clean:-0}
                if [ "$t_num" -gt 100000 ]; then
                    echo $((t_num / 10000))
                else
                    echo $((t_num / 1000))
                fi
            else
                echo "0"
            fi
        else
            echo "0"
        fi
        ;;
    GPU_FREQ)
        if [ -n "$CARD_DEV" ]; then
            if [ -f "$CARD_DEV/pp_dpm_sclk" ]; then
                sclk_content=$(safe_read "$CARD_DEV/pp_dpm_sclk" "")
                f=$(echo "$sclk_content" | grep '\*' 2>/dev/null | awk '{print $2}' | tr -d 'Mhz')
                if [ -n "$f" ]; then
                    echo "$f"
                else
                    echo "$sclk_content" | awk 'NR==1{print $2}' | tr -d 'Mhz' || echo "0"
                fi
            else
                hwmon=$(ls "$CARD_DEV/hwmon/" 2>/dev/null | head -1)
                if [ -n "$hwmon" ]; then
                    f=$(safe_read "$CARD_DEV/hwmon/$hwmon/freq1_input" 0)
                    f_clean=$(echo "$f" | tr -dc '0-9')
                    echo $(( ${f_clean:-0} / 1000000 ))
                else
                    echo "0"
                fi
            fi
        else
            echo "0"
        fi
        ;;
    GPU_POWER)
        if [ -n "$CARD_DEV" ]; then
            hwmon=$(ls "$CARD_DEV/hwmon/" 2>/dev/null | head -1)
            if [ -n "$hwmon" ]; then
                p1=$(safe_read "$CARD_DEV/hwmon/$hwmon/power1_average" 0)
                if [ "${p1:-0}" = "0" ]; then
                    p1=$(safe_read "$CARD_DEV/hwmon/$hwmon/power1_input" 0)
                fi
                p_clean=$(echo "$p1" | tr -dc '0-9')
                awk -v p="${p_clean:-0}" 'BEGIN { printf "%.1f\n", p/1000000 }'
            else
                echo "0"
            fi
        else
            echo "0"
        fi
        ;;
    VRAM_PERC)
        if [ -n "$CARD_DEV" ]; then
            u=$(safe_read "$CARD_DEV/mem_info_vram_used" 0)
            t=$(safe_read "$CARD_DEV/mem_info_vram_total" 1)
            u_clean=$(echo "$u" | tr -dc '0-9')
            t_clean=$(echo "$t" | tr -dc '0-9')
            awk -v u="${u_clean:-0}" -v t="${t_clean:-1}" 'BEGIN { if (t>0) printf "%.0f\n", (u/t)*100; else print "0" }'
        else
            echo "0"
        fi
        ;;
    VRAM_USED_MB)
        if [ -n "$CARD_DEV" ]; then
            u=$(safe_read "$CARD_DEV/mem_info_vram_used" 0)
            u_clean=$(echo "$u" | tr -dc '0-9')
            awk -v u="${u_clean:-0}" 'BEGIN { printf "%.0f\n", u/1048576 }'
        else
            echo "0"
        fi
        ;;
    VRAM_TOTAL_MB)
        if [ -n "$CARD_DEV" ]; then
            t=$(safe_read "$CARD_DEV/mem_info_vram_total" 0)
            t_clean=$(echo "$t" | tr -dc '0-9')
            awk -v t="${t_clean:-0}" 'BEGIN { printf "%.0f\n", t/1048576 }'
        else
            echo "0"
        fi
        ;;
    GTT_PERC)
        if [ -n "$CARD_DEV" ]; then
            u=$(safe_read "$CARD_DEV/mem_info_gtt_used" 0)
            t=$(safe_read "$CARD_DEV/mem_info_gtt_total" 1)
            u_clean=$(echo "$u" | tr -dc '0-9')
            t_clean=$(echo "$t" | tr -dc '0-9')
            awk -v u="${u_clean:-0}" -v t="${t_clean:-1}" 'BEGIN { if (t>0) printf "%.0f\n", (u/t)*100; else print "0" }'
        else
            echo "0"
        fi
        ;;
    *)
        echo "0"
        ;;
esac