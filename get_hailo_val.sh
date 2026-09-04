#!/usr/bin/env bash
# Script para extraer métricas del Hailo-8L AI Accelerator (PCIe) local
# Lee del cache /tmp/hailo_stats.txt actualizado por fetch_hailo_stats.sh

STATS_FILE="/tmp/hailo_stats.txt"

# Si no hay cache, devolver N/A
if [ ! -f "$STATS_FILE" ]; then
    echo "N/A"
    exit 0
fi

case "${1:-STATE}" in
    STATE)  grep -a '^STATE='  "$STATS_FILE" | cut -d= -f2- ;;
    POWER)  grep -a '^POWER='  "$STATS_FILE" | cut -d= -f2- ;;
    SLOT)   grep -a '^SLOT='   "$STATS_FILE" | cut -d= -f2- ;;
    FW)     grep -a '^FW='     "$STATS_FILE" | cut -d= -f2- ;;
    SERIAL) grep -a '^SERIAL=' "$STATS_FILE" | cut -d= -f2- ;;
    ARCH)   grep -a '^ARCH='   "$STATS_FILE" | cut -d= -f2- ;;
    BOARD)  grep -a '^BOARD='  "$STATS_FILE" | cut -d= -f2- ;;
    PRODUCT) grep -a '^PRODUCT=' "$STATS_FILE" | cut -d= -f2- ;;
    UTIL)   grep -a '^UTIL='   "$STATS_FILE" | cut -d= -f2- ;;
    *)      echo "N/A" ;;
esac