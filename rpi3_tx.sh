#!/usr/bin/env bash
NAME=$(basename "$0" .sh)
case "${NAME%%_*}" in
    rpi1) IP=192.168.0.105 ;;
    rpi2) IP=192.168.0.193 ;;
    rpi3) IP=192.168.0.113 ;;
    rpi4) IP=192.168.0.80  ;;
    *) echo 0; exit 1 ;;
esac
METRIC="${NAME#*_}"
case "$METRIC" in
    cpu) KEY=CPU ;;
    ram) KEY=RAMPCT ;;
    rx)  KEY=RXBPS ;;
    tx)  KEY=TXBPS ;;
    gpu) KEY=GPUPCT ;;
    diskioread)  KEY=DISKIO_READ ;;
    diskiowrite) KEY=DISKIO_WRITE ;;
    *)   KEY="${METRIC^^}" ;;
esac

VAL=$(/home/arkantu/.config/conky/get_rpi_val.sh "$IP" "$KEY")

# rx/tx: % de capacidad Gigabit (0-100, entero)
if [[ "$METRIC" == "rx" || "$METRIC" == "tx" ]]; then
    LC_ALL=C awk -v v="$VAL" 'BEGIN{
        pct = int(v / 1250000 + 0.5)
        if (pct > 100) pct = 100
        if (pct < 0) pct = 0
        print pct
    }'
# diskio: % de 100 MB/s (1 MB/s = 1%)
elif [[ "$METRIC" == "diskioread" || "$METRIC" == "diskiowrite" ]]; then
    LC_ALL=C awk -v v="$VAL" 'BEGIN{
        pct = int(v / 1000000 + 0.5)
        if (pct > 100) pct = 100
        if (pct < 0) pct = 0
        print pct
    }'
else
    echo "$VAL"
fi
