#!/usr/bin/env bash
set -euo pipefail

# Unified Conky startup script for all instances
# Manages: khazaddum, rpi1, rpi2, rpi4, rpi3b, copilot, ollama
# Includes lockfile, watchdog and dependency checks

LOCKFILE="/tmp/start_all_conky.lock"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "[$(date '+%H:%M:%S')] Another start_all_conky script is already running. Exiting."; exit 0; }

CONKY_DIR="$HOME/.config/conky"
LOG_DIR="$HOME/.local/share/conky"
TMPDIR_RPi="/tmp/conky_rpi"

# Ensure log directory exists
mkdir -p "$LOG_DIR" "$TMPDIR_RPi"

# ==============================================================================
# DEPENDENCIES CHECK
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Mounting Storage1TB if needed..."
if ! mountpoint -q /media/arkantu/Storage1TB 2>/dev/null; then
    for i in $(seq 1 10); do
        mount /media/arkantu/Storage1TB 2>/dev/null && break
        sleep 3
    done
fi

echo "[$(date '+%H:%M:%S')] Waiting for daemon data files..."
for i in $(seq 1 9); do
    if ls /tmp/conky_rpi/rpi_*.dat 2>/dev/null | head -1 | grep -q . && \
       [ -f /tmp/conky_arc.dat ] && [ -f /tmp/conky_npu.dat ] && [ -f /tmp/conky_diskio.dat ] 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] All daemon data available."
        break
    fi
    sleep 5
done
sleep 2

# ==============================================================================
# CLEANUP OLD INSTANCES
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Cleaning up old Conky instances..."
pkill -9 conky || true
sleep 1

# ==============================================================================
# CONFIGURATION FOR ALL INSTANCES
# ==============================================================================

declare -A CONKY_INSTANCES=(
    [khazaddum]="$CONKY_DIR/conky_khazaddum.conf"
    [rpi1]="$CONKY_DIR/conky_rpi1.conf"
    [rpi2]="$CONKY_DIR/conky_rpi2.conf"
    [rpi4]="$CONKY_DIR/conky_rpi4.conf"
    [rpi3b]="$CONKY_DIR/conky_rpi3b.conf"
    [copilot]="$CONKY_DIR/conky_copilot.conf"
    [ollama]="$CONKY_DIR/conky_ollama.conf"
)

# ==============================================================================
# LAUNCH INSTANCES
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Launching Conky instances..."
export DISPLAY=:0

for name in "${!CONKY_INSTANCES[@]}"; do
    conf="${CONKY_INSTANCES[$name]}"
    log="$LOG_DIR/conky_${name}.log"
    if [ -f "$conf" ]; then
        setsid conky -c "$conf" >> "$log" 2>&1 &
        echo "[$(date '+%H:%M:%S')] Started conky_${name}"
        sleep 0.5
    else
        echo "[$(date '+%H:%M:%S')] WARNING: Config not found: $conf" | tee -a "$LOG_DIR/conky.log"
    fi
done

# ==============================================================================
# WATCHDOG LOOP (restart fallen instances every 30s)
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Watchdog started."

(
    while true; do
        sleep 30
        for name in "${!CONKY_INSTANCES[@]}"; do
            conf="${CONKY_INSTANCES[$name]}"
            log="$LOG_DIR/conky_${name}.log"
            
            if ! pgrep -f "conky.*${conf##*/}" > /dev/null 2>&1; then
                echo "[$(date '+%H:%M:%S')] conky_${name} died, restarting..." | tee -a "$log"
                setsid conky -c "$conf" >> "$log" 2>&1 &
            fi
        done
    done
) &

echo "[$(date '+%H:%M:%S')] All Conky instances initialized."
