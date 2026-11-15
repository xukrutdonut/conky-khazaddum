#!/usr/bin/env bash
# v100_fan_daemon.sh — duty del ventilador de la V100 para Conky.
#
# El ventilador ARCTIC lo controla fanctl-od.py en el RPi .101, que escribe
# /run/v100-fan/state.json. El campo "rpm" de ese fichero es CROSSTALK del
# PWM (lo documenta el propio fanctl: en este cableado el tacometro lee
# 10^5-10^6, max real 8040) y por eso fanctl controla EN LAZO ABIERTO por
# duty, sin PID de rpm. La senal fiable es "duty" (% de duty PWM aplicado).
#
# Este daemon copia ese duty a /tmp/conky_v100_fan.dat para que conky no abra
# SSH por cada ${execi}/${execgraph}. Fallo de red o duty invalido = 0.
OUTFILE="/tmp/conky_v100_fan.dat"
INTERVAL="${V100_FAN_INTERVAL:-3}"
RPI_HOST="${V100_FAN_HOST:-arkantu@192.168.0.101}"
STATE="/run/v100-fan/state.json"

cleanup() { rm -f "$OUTFILE"; exit 0; }
trap cleanup SIGTERM SIGINT

while true; do
    duty=0
    if json=$(timeout 4 ssh -o BatchMode=yes -o ConnectTimeout=3 "$RPI_HOST" "cat \"$STATE\"" 2>/dev/null); then
        duty=$(echo "$json" | sed -n 's/.*"duty": *\([0-9][0-9.]*\).*/\1/p')
    fi
    duty="${duty%%.*}"
    [[ "$duty" =~ ^[0-9]+$ ]] || duty=0
    # clamp 0..100
    (( duty > 100 )) && duty=100
    printf 'DUTY:%s\n' "$duty" > "$OUTFILE.tmp"
    mv "$OUTFILE.tmp" "$OUTFILE" 2>/dev/null
    sleep "$INTERVAL"
done
