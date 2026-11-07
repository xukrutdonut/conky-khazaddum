#!/usr/bin/env bash
# get_rx480_val.sh — Lee un valor de /tmp/conky_rx480.dat (lo escribe rx480_stats.sh)
KEY="${1:-}"
val=$(awk -F: -v k="$KEY" '$1==k {print $2; exit}' /tmp/conky_rx480.dat 2>/dev/null)
case "$KEY" in
    STATE|DRIVER|PCI|LINK)
        printf '%s\n' "${val:-no-detectada}"
        ;;
    *)
        val_clean=$(echo "$val" | tr -dc '0-9')
        echo "${val_clean:-0}"
        ;;
esac
