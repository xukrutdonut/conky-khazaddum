#!/usr/bin/env bash
# rx480_stats.sh — daemon de métricas de la RX 480 conectada por USB4 a Khazad-dum.
# Escribe /tmp/conky_rx480.dat cada 2 s.
#
# La tarjeta se localiza por vendor 0x1002 en /sys/bus/pci/devices (la dirección
# PCI cambia: aquí aparece como 0000:2e:00.0 tras el túnel USB4 / ASM2464PD).
# Si amdgpu no consigue inicializarla (probe con -110: "Timeout wait for RLC
# serdes" / fallo del ring gfx_v8_0), no hay hwmon ni gpu_busy_percent: el panel
# muestra el estado y el enlace en vez de ceros silenciosos, y se rellena solo
# en cuanto el driver enlace.
OUTFILE="/tmp/conky_rx480.dat"
INTERVAL="${RX480_INTERVAL:-2}"

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

write_out() {
    cat > "$OUTFILE.tmp" << BLOCK
STATE:$1
PCI:$2
DRIVER:$3
LINK:$4
UTIL:$5
TEMP:$6
POWER:$7
VRAMUSED:$8
VRAMTOTAL:$9
VRAMPCT:${10}
FREQ:${11}
FREQMAX:${12}
BLOCK
    mv "$OUTFILE.tmp" "$OUTFILE" 2>/dev/null
}

while true; do
    dev=""
    for p in /sys/bus/pci/devices/*/; do
        [[ "$(cat "${p}vendor" 2>/dev/null)" == "0x1002" ]] || continue
        dev="${p%/}"
        break
    done

    if [[ -z "$dev" ]]; then
        write_out "no-detectada" "none" "none" "none" 0 0 0 0 0 0 0 0
        sleep "$INTERVAL"
        continue
    fi

    pci=$(basename "$dev")
    drv="none"
    [[ -L "$dev/driver" ]] && drv=$(basename "$(readlink "$dev/driver")")
    spd=$(cat "$dev/current_link_speed" 2>/dev/null | awk '{print $1}')
    wid=$(cat "$dev/current_link_width" 2>/dev/null)
    link="${spd:-?}GT/s x${wid:-?}"

    if [[ "$drv" != "amdgpu" ]]; then
        # Enumerada pero sin driver enlazado: nada más que leer.
        write_out "sin-driver" "$pci" "$drv" "$link" 0 0 0 0 0 0 0 0
        sleep "$INTERVAL"
        continue
    fi

    hwmon=$(ls "$dev/hwmon/" 2>/dev/null | head -1)
    util=$(cat "$dev/gpu_busy_percent" 2>/dev/null || echo 0)
    temp=$(( $(cat "$dev/hwmon/$hwmon/temp1_input" 2>/dev/null || echo 0) / 1000 ))
    pw=$(cat "$dev/hwmon/$hwmon/power1_average" 2>/dev/null || cat "$dev/hwmon/$hwmon/power1_input" 2>/dev/null || echo 0)
    power=$(( pw / 1000000 ))
    vused=$(( $(cat "$dev/mem_info_vram_used" 2>/dev/null || echo 0) / 1048576 ))
    vtot=$(( $(cat "$dev/mem_info_vram_total" 2>/dev/null || echo 0) / 1048576 ))
    vpct=0
    (( vtot > 0 )) && vpct=$(( vused * 100 / vtot ))
    # pp_dpm_sclk marca con '*' el nivel activo; hwmon freq1_input = reloj de shader
    freq=$(( $(cat "$dev/hwmon/$hwmon/freq1_input" 2>/dev/null || echo 0) / 1000000 ))
    fmax=$(( $(awk '/^\s*\*\s*[0-9]+:/{print $2; exit}' "$dev/pp_dpm_sclk" 2>/dev/null || echo 0) / 1000000 ))
    [[ "$freq" == "0" ]] && freq=$fmax

    write_out "ok" "$pci" "$drv" "$link" "$util" "$temp" "$power" "$vused" "$vtot" "$vpct" "$freq" "$fmax"
    sleep "$INTERVAL"
done
