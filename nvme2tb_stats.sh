#!/usr/bin/env bash
# nvme2tb_stats.sh — uso, tamaño, temperatura y tasa I/O del NVMe de 2 TB.
# Uso: nvme2tb_stats.sh USED|SIZE|PCT|TEMP|RATE_R|RATE_W|MOUNT
# Lee de /tmp/conky_nvme2tb_io.dat (lo mantiene nvme2tb_io_daemon.sh) para que
# conky no lance df/findmnt en cada refresco; si el fichero falta o está viejo,
# calcula en vivo. Funciona con el disco en /mnt/newroot y luego como /.
export LC_ALL=C LANG=C
DEV=/dev/nvme0n1p2
IOFILE=/tmp/conky_nvme2tb_io.dat

human() {
    awk -v b="$1" 'BEGIN{
        if (b >= 1099511627776) printf "%.2fT", b/1099511627776;
        else if (b >= 1073741824) printf "%.0fG", b/1073741824;
        else if (b >= 1048576) printf "%.0fM", b/1048576;
        else printf "%.0fK", b/1024;
    }'
}

human_rate() {
    awk -v v="${1:-0}" 'BEGIN{
        if (v >= 1073741824) printf "%.1fG/s", v/1073741824;
        else if (v >= 1048576) printf "%.0fM/s", v/1048576;
        else if (v >= 1024) printf "%.0fK/s", v/1024;
        else printf "%dB/s", v;
    }'
}

mountpoint_of() {
    findmnt -nr -S "$DEV" -o TARGET 2>/dev/null | head -1
}

field() { # KEY del fichero de caché
    awk -F: -v k="$1" '$1==k{print $2; exit}' "$IOFILE" 2>/dev/null
}

fresh() { # fichero actualizado en los últimos 30 s
    [ -f "$IOFILE" ] && [ -n "$(find "$IOFILE" -newermt '-30 seconds' 2>/dev/null)" ]
}

key=$(printf '%s' "${1:-}" | tr '[:lower:]' '[:upper:]')
case "$key" in
    RATE_R) v=$(field NVME2TB_READ); human_rate "${v:-0}"; exit 0 ;;
    RATE_W) v=$(field NVME2TB_WRITE); human_rate "${v:-0}"; exit 0 ;;
    TEMP|MOUNT|USED|SIZE|PCT) ;;
    *) echo "uso: $0 USED|SIZE|PCT|TEMP|RATE_R|RATE_W|MOUNT" >&2; exit 1 ;;
esac

# Camino rápido: caché del daemon
if fresh; then
    case "$key" in
        TEMP)  v=$(field TEMP) ;;
        MOUNT) v=$(field MOUNT) ;;
        USED)  v=$(field USED) ;;
        SIZE)  v=$(field SIZE) ;;
        PCT)   v=$(field PCT) ;;
    esac
    if [ -n "$v" ]; then echo "$v"; exit 0; fi
fi

# Fallback en vivo
case "$key" in
    TEMP)
        t=$(cat /sys/class/nvme/nvme0/hwmon*/temp1_input 2>/dev/null | head -1)
        if [ -n "$t" ]; then echo "$((t / 1000))°C"; else echo "N/A"; fi
        ;;
    MOUNT)
        m=$(mountpoint_of); [ -n "$m" ] && echo "$m" || echo "sin montar"
        ;;
    USED|SIZE|PCT)
        m=$(mountpoint_of)
        if [ -z "$m" ]; then echo "N/A"; exit 0; fi
        read -r u t <<< "$(df -B1 --output=used,size "$m" 2>/dev/null | awk 'NR==2{print $1, $2}')"
        if [ -z "${t:-}" ] || [ "${t:-0}" -eq 0 ]; then echo "N/A"; exit 0; fi
        case "$key" in
            USED) human "$u" ;;
            SIZE) human "$t" ;;
            PCT)  echo $(( u * 100 / t )) ;;
        esac
        ;;
esac
