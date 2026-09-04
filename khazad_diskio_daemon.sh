#!/usr/bin/env bash
# Daemon: muestrea diskstats global (nvme + sda) cada segundo
OUTFILE=/tmp/conky_diskio.dat

while true; do
    read -r _r1 _w1 < <(awk '$3~/^(sd[a-z]|nvme[0-9]+n[0-9]+)$/{r+=$6;w+=$10}END{printf "%.0f %.0f\n",r+0,w+0}' /proc/diskstats)
    sleep 1
    read -r _r2 _w2 < <(awk '$3~/^(sd[a-z]|nvme[0-9]+n[0-9]+)$/{r+=$6;w+=$10}END{printf "%.0f %.0f\n",r+0,w+0}' /proc/diskstats)
    _rbps=$(( (_r2 - _r1) * 512 ))
    _wbps=$(( (_w2 - _w1) * 512 ))
    (( _rbps < 0 )) && _rbps=0
    (( _wbps < 0 )) && _wbps=0
    printf "DISKIO_READ:%d\nDISKIO_WRITE:%d\n" $_rbps $_wbps > "$OUTFILE"
done
