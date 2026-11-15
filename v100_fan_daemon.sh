#!/usr/bin/env bash
# v100_fan_daemon.sh — RPM del ventilador de la V100 para Conky.
#
# El ventilador ARCTIC lo controla fanctl-od.py en el RPi .101, que escribe
# /run/v100-fan/state.json (campo "rpm"). Este daemon copia ese valor a un
# fichero local /tmp/conky_v100_fan.dat para que conky no abra SSH por cada
# ${execi}/${execgraph}. Fallo de red = RPM 0.
OUTFILE="/tmp/conky_v100_fan.dat"
INTERVAL="${V100_FAN_INTERVAL:-3}"
RPI_HOST="${V100_FAN_HOST:-arkantu@192.168.0.101}"
STATE="/run/v100-fan/state.json"

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

while true; do
    rpm=""
    if json=$(timeout 4 ssh -o BatchMode=yes -o ConnectTimeout=3 "$RPI_HOST" "cat \"$STATE\"" 2>/dev/null); then
        rpm=$(echo "$json" | sed -n 's/.*"rpm": *\([0-9][0-9.]*\).*/\1/p')
    fi
    rpm="${rpm%%.*}"
    [[ "$rpm" =~ ^[0-9]+$ ]] || rpm=0
    printf 'RPM:%s\n' "$rpm" > "$OUTFILE.tmp"
    mv "$OUTFILE.tmp" "$OUTFILE" 2>/dev/null
    sleep "$INTERVAL"
done
