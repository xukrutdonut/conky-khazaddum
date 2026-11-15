#!/usr/bin/env bash
# get_v100_fan_val.sh — Lee un valor de /tmp/conky_v100_fan.dat
# (lo escribe v100_fan_daemon.sh). Por ahora solo DUTY.
KEY="${1:-DUTY}"
val=$(awk -F: -v k="$KEY" '$1==k {print $2; exit}' /tmp/conky_v100_fan.dat 2>/dev/null)
val_clean=$(echo "$val" | tr -dc '0-9')
echo "${val_clean:-0}"
