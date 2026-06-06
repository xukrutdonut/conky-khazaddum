#!/usr/bin/env bash
# get_rpi_val.sh — Lee un valor del caché SSH de una RPi
# Uso: get_rpi_val.sh <ip> <KEY>
IP="${1:-}"
KEY="${2:-}"
TAG="${IP//\./_}"
val=$(awk -v k="${KEY}:" 'index($0,k)==1{print substr($0,length(k)+1); exit}' \
    /tmp/conky_rpi/rpi_${TAG}.dat 2>/dev/null)
echo "${val:-0}"
