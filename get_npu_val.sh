#!/usr/bin/env bash
# get_npu_val.sh — Lee un valor de /tmp/conky_npu.dat
# Uso: get_npu_val.sh <KEY>
KEY="${1:-}"
val=$(grep "^${KEY}:" /tmp/conky_npu.dat 2>/dev/null | head -1 | cut -d: -f2)
printf "%.0f" "${val:-0}" 2>/dev/null || echo "0"
