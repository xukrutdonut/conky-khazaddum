#!/usr/bin/env bash
# Daemon: muestrea I/O del disco del sistema (global) y del disco 2TB (/mnt/data)
# Resuelve el device del 2TB por mountpoint una sola vez (robusto a reboot/renombrado).
OUTFILE=/tmp/conky_diskio.dat

# device base del disco que monta /mnt/data (ej: /dev/sdb2 -> sdb); 'none' si no monta
# findmnt devuelve 2 lineas (la del / es systemd-1); quedarse con la que es /dev/
DATA_DEV=$(findmnt -no SOURCE /mnt/data 2>/dev/null | grep '^/dev/' | sed 's#^/dev/##; s/[0-9]*$//' | head -1)
[ -z "$DATA_DEV" ] && DATA_DEV=none

while true; do
    snap() {
        awk -v dd="$DATA_DEV" '
            $3 ~ /^(sd[a-z]|nvme[0-9]+n[0-9]+)$/ {
                tot_r += $6; tot_w += $10
                if ($3 == dd) { d_r += $6; d_w += $10 }
            }
            END { printf "%d %d %d %d", tot_r+0, tot_w+0, d_r+0, d_w+0 }
        ' /proc/diskstats
    }

    read -r R1 W1 DR1 DW1 < <(snap)
    sleep 1
    read -r R2 W2 DR2 DW2 < <(snap)

    bnd(){ [ $(( $2 - $1 )) -gt 0 ] && echo $(( ($2 - $1) * 512 )) || echo 0; }

    printf "DISKIO_READ:%d\nDISKIO_WRITE:%d\nDATA_READ:%d\nDATA_WRITE:%d\n" \
        "$(bnd $R1 $R2)" "$(bnd $W1 $W2)" "$(bnd $DR1 $DR2)" "$(bnd $DW1 $DW2)" > "$OUTFILE"
done
