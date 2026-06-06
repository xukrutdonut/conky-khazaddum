#!/bin/bash
# Extrae el % de uso del contexto de la sesión Copilot CLI más reciente

LOG_DIR="$HOME/.copilot/logs"

# Log más reciente con datos de contexto
LATEST_LOG=$(grep -rl "CompactionProcessor: Utilization" "$LOG_DIR" 2>/dev/null \
  | xargs ls -t 2>/dev/null | head -1)

if [ -z "$LATEST_LOG" ]; then
  echo "N/A"
  exit 0
fi

# Comprueba que el log sea de los últimos 60 minutos (sesión activa)
MTIME=$(stat -c %Y "$LATEST_LOG" 2>/dev/null)
NOW=$(date +%s)
AGE=$(( NOW - MTIME ))
if [ "$AGE" -gt 3600 ]; then
  echo "N/A"
  exit 0
fi

# Extrae el último valor de utilización del log
LINE=$(grep "CompactionProcessor: Utilization" "$LATEST_LOG" 2>/dev/null | tail -1)
if [ -z "$LINE" ]; then
  echo "N/A"
  exit 0
fi

# Ejemplo: "Utilization 42.2% (54061/128000 tokens)"
PCT=$(echo "$LINE" | grep -oP 'Utilization \K[0-9.]+')
USED=$(echo "$LINE" | grep -oP '\((\K[0-9]+)(?=/)' )
TOTAL=$(echo "$LINE" | grep -oP '/\K[0-9]+(?= tokens)')

if [ -n "$PCT" ]; then
  LC_NUMERIC=C printf "%.1f" "$PCT"
else
  echo "N/A"
fi
