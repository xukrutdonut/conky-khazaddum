#!/usr/bin/env bash
# get_npu_val.sh — Lee un valor de /tmp/conky_npu.dat
KEY="${1:-}"
val=$(awk -F: -v k="$KEY" '$1==k {print $2; exit}' /tmp/conky_npu.dat 2>/dev/null)
val_clean=$(echo "$val" | tr -dc '0-9')
echo "${val_clean:-0}"

