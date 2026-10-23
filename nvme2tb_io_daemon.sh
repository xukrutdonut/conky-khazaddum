#!/usr/bin/env bash
# Daemon: muestrea solo el NVMe de 2 TB (/dev/nvme0n1) cada segundo y refresca
# uso/tamaño/temperatura cada 5 s. Un único fichero para todo el widget,
# así conky no lanza df/awk por cada campo (evita parpadeos).
DEV=/dev/nvme0n1p2
OUTFILE=/tmp/conky_nvme2tb_io.dat
export LC_ALL=C LANG=C

samp() {
    awk '$3=="nvme0n1"{printf "%.0f %.0f\n", $6+0, $10+0}' /proc/diskstats
}

mountpoint_of() {
    findmnt -nr -S "$DEV" -o TARGET 2>/dev/null | head -1
}

human() {
    awk -v b="$1" 'BEGIN{
        if (b >= 1099511627776) printf "%.2fT", b/1099511627776;
        else if (b >= 1073741824) printf "%.0fG", b/1073741824;
        else if (b >= 1048576) printf "%.0fM", b/1048576;
        else printf "%.0fK", b/1024;
    }'
}

usage_fields() {
    local m u t
    m=$(mountpoint_of)
    if [ -z "$m" ]; then
        echo "USED:N/A"
        echo "SIZE:$(human "$(blockdev --getsize64 /dev/nvme0n1 2>/dev/null || echo 0)")"
        echo "PCT:0"
        echo "MOUNT:sin montar"
        return
    fi
    read -r u t <<< "$(df -B1 --output=used,size "$m" 2>/dev/null | awk 'NR==2{print $1, $2}')"
    if [ -z "${t:-}" ] || [ "${t:-0}" -eq 0 ]; then
        echo "USED:N/A"; echo "SIZE:N/A"; echo "PCT:0"; echo "MOUNT:$m"; return
    fi
    echo "USED:$(human "$u")"
    echo "SIZE:$(human "$t")"
    echo "PCT:$(( u * 100 / t ))"
    echo "MOUNT:$m"
}

temp_field() {
    local t
    t=$(cat /sys/class/nvme/nvme0/hwmon*/temp1_input 2>/dev/null | head -1)
    if [ -n "$t" ]; then echo "TEMP:$((t / 1000))°C"; else echo "TEMP:N/A"; fi
}

tick=0
while true; do
    read -r _r1 _w1 < <(samp)
    sleep 1
    read -r _r2 _w2 < <(samp)
    if [ -z "${_r2:-}" ]; then
        printf "NVME2TB_READ:0\nNVME2TB_WRITE:0\n" > "$OUTFILE"
        sleep 4
        continue
    fi
    _rbps=$(( (_r2 - ${_r1:-0}) * 512 ))
    _wbps=$(( (_w2 - ${_w1:-0}) * 512 ))
    (( _rbps < 0 )) && _rbps=0
    (( _wbps < 0 )) && _wbps=0

    {
        printf "NVME2TB_READ:%d\nNVME2TB_WRITE:%d\n" "$_rbps" "$_wbps"
        if (( tick % 5 == 0 )); then
            usage_fields
            temp_field
        else
            grep -E '^(USED|SIZE|PCT|MOUNT|TEMP):' "$OUTFILE" 2>/dev/null
        fi
    } > "$OUTFILE.tmp" && mv -f "$OUTFILE.tmp" "$OUTFILE"

    tick=$(( tick + 1 ))
done
