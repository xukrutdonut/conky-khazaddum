#!/usr/bin/env bash
# v100_stats.sh — daemon de métricas de la Tesla V100 (nvidia-smi) para Conky.
# Escribe /tmp/conky_v100.dat cada 2 s. Una sola invocación de nvidia-smi por
# ciclo: el panel hace ~20 lecturas y nvidia-smi tarda ~400 ms, así que no se
# puede llamar desde cada ${execi}.
OUTFILE="/tmp/conky_v100.dat"
INTERVAL="${V100_INTERVAL:-2}"
QUERY="utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,enforced.power.limit,clocks.current.sm,clocks.max.sm,pstate,clocks_throttle_reasons.active"

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

# Mapa de bits de clocks_throttle_reasons.active (orden documentado por NVIDIA)
throttle_name() {
    local mask=$(( $1 ))
    local out=""
    (( mask & 0x04 )) && out+="PwrCap "
    (( mask & 0x08 )) && out+="HW-Slowdown "
    (( mask & 0x20 )) && out+="SW-Termico "
    (( mask & 0x40 )) && out+="HW-Termico "
    (( mask & 0x80 )) && out+="PwrBrake "
    echo "${out:-none}"
}

num() {  # "135" -> 135 ; "[N/A]" / "" -> 0
    local v="${1// /}"
    [[ "$v" =~ ^[0-9]+([.][0-9]+)?$ ]] && printf '%s\n' "$v" || echo 0
}

write_err() {
    cat > "$OUTFILE.tmp" << BLOCK
STATE:error
NAME:Tesla V100
UTIL:0
MEMUSED:0
MEMTOTAL:0
MEMPCT:0
TEMP:0
POWER:0
POWERLIM:0
FREQ:0
FREQMAX:0
PSTATE:--
THROTTLE:nvidia-smi falla
BLOCK
    mv "$OUTFILE.tmp" "$OUTFILE" 2>/dev/null
}

while true; do
    line=$(timeout 5 nvidia-smi --query-gpu="$QUERY" --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [[ -z "$line" ]]; then
        write_err
        sleep "$INTERVAL"
        continue
    fi
    IFS=',' read -r q_util q_memused q_memtot q_temp q_pwr q_plim q_freq q_fmax q_pstate q_thr <<< "$line"

    util=$(num "$q_util");   util=${util%%.*}
    memu=$(num "$q_memused"); memu=${memu%%.*}
    memt=$(num "$q_memtot");  memt=${memt%%.*}
    temp=$(num "$q_temp");    temp=${temp%%.*}
    pwr=$(num "$q_pwr")
    plim=$(num "$q_plim");    plim=${plim%%.*}
    freq=$(num "$q_freq");    freq=${freq%%.*}
    fmax=$(num "$q_fmax");    fmax=${fmax%%.*}
    pstate="${q_pstate// /}"; [[ -z "$pstate" ]] && pstate="--"
    thr=$(throttle_name "${q_thr// /}")

    mempct=0
    (( memt > 0 )) && mempct=$(( memu * 100 / memt ))
    pwr_fmt=$(printf '%.0f' "${pwr:-0}")

    cat > "$OUTFILE.tmp" << BLOCK
STATE:ok
NAME:Tesla V100
UTIL:${util}
MEMUSED:${memu}
MEMTOTAL:${memt}
MEMPCT:${mempct}
TEMP:${temp}
POWER:${pwr_fmt}
POWERLIM:${plim}
FREQ:${freq}
FREQMAX:${fmax}
PSTATE:${pstate}
THROTTLE:${thr}
BLOCK
    mv "$OUTFILE.tmp" "$OUTFILE"
    sleep "$INTERVAL"
done
