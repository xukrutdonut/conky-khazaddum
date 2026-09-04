#!/usr/bin/env bash
set -euo pipefail

# Unified Conky startup script for all instances
# Manages: rpi1-4, copilot, khazaddum, ollama, lmstudio, etc.
# Includes lockfile, dynamic display detection, watchdog and dependency checks

LOCKFILE="/tmp/start_all_conky.lock"
exec 200>"$LOCKFILE"
flock -n 200 || { echo "[$(date '+%H:%M:%S')] Another start_all_conky script is already running. Exiting."; exit 0; }

CONKY_DIR="$HOME/.config/conky"
LOG_DIR="$HOME/.local/share/conky"
TMPDIR_RPi="/tmp/conky_rpi"

# Ensure log directory exists
mkdir -p "$LOG_DIR" "$TMPDIR_RPi"

# ==============================================================================
# DISPLAY & XAUTHORITY DETECTION
# ==============================================================================

if [ -z "${XAUTHORITY:-}" ]; then
    MUTTER_AUTH=$(ls -t /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
    if [ -n "$MUTTER_AUTH" ]; then
        export XAUTHORITY="$MUTTER_AUTH"
    fi
fi

DETECTED_DISPLAY=""
for d in "${DISPLAY:-}" :0 :1 :2; do
    if [ -n "$d" ] && DISPLAY="$d" xset q >/dev/null 2>&1; then
        DETECTED_DISPLAY="$d"
        break
    fi
done

if [ -z "$DETECTED_DISPLAY" ]; then
    echo "[$(date '+%H:%M:%S')] ERROR: Could not find active X11/Xwayland display. Exiting." | tee -a "$LOG_DIR/conky.log"
    exit 1
fi

export DISPLAY="$DETECTED_DISPLAY"
echo "[$(date '+%H:%M:%S')] Using DISPLAY=$DISPLAY, XAUTHORITY=${XAUTHORITY:-default}" | tee -a "$LOG_DIR/conky.log"

# ==============================================================================
# PRE-CREATE DAEMON DATA
# ==============================================================================

touch /tmp/conky_arc.dat /tmp/conky_npu.dat /tmp/conky_diskio.dat 2>/dev/null || true

# Start Hailo stats daemon (feeds get_hailo_val.sh cache)
pkill -f 'fetch_hailo_stats.sh' 2>/dev/null || true
if [ -x "$CONKY_DIR/fetch_hailo_stats.sh" ]; then
    setsid "$CONKY_DIR/fetch_hailo_stats.sh" >> "$LOG_DIR/conky_hailo_daemon.log" 2>&1 &
    echo "[$(date '+%H:%M:%S')] Started Hailo stats daemon"
fi

# Start LM Studio stats daemon (feeds lmstudio_render.py cache)
pkill -f 'fetch_lmstudio_stats.py' 2>/dev/null || true
if [ -x "$CONKY_DIR/fetch_lmstudio_stats.py" ]; then
    setsid "$CONKY_DIR/fetch_lmstudio_stats.py" >> "$LOG_DIR/conky_lmstudio_daemon.log" 2>&1 &
    echo "[$(date '+%H:%M:%S')] Started LM Studio stats daemon"
fi

# ==============================================================================
# DEPENDENCIES CHECK
# ==============================================================================

if ! mountpoint -q /media/arkantu/Storage1TB 2>/dev/null; then
    mount /media/arkantu/Storage1TB 2>/dev/null || true
fi

# ==============================================================================
# CLEANUP OLD INSTANCES
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Cleaning up old Conky instances..."
for pid in $(pgrep -x conky || true); do
    kill -9 "$pid" 2>/dev/null || true
done
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
    [lmstudio]="$CONKY_DIR/conky_lmstudio.conf"
)

# ==============================================================================
# LAUNCH INSTANCES
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Launching Conky instances..."

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
# WATCHDOG LOOP (with safety limit)
# ==============================================================================

echo "[$(date '+%H:%M:%S')] Watchdog started."

(
    declare -A FAIL_COUNTS
    while true; do
        sleep 30

        # Verify display is still reachable
        if ! DISPLAY="$DISPLAY" xset q >/dev/null 2>&1; then
            echo "[$(date '+%H:%M:%S')] Display unreachable. Stopping watchdog." | tee -a "$LOG_DIR/conky.log"
            break
        fi

        # Ensure helper daemons are running
        if [ -x "$CONKY_DIR/fetch_hailo_stats.sh" ] && ! pgrep -f "fetch_hailo_stats.sh" > /dev/null 2>&1; then
            setsid "$CONKY_DIR/fetch_hailo_stats.sh" >> "$LOG_DIR/conky_hailo_daemon.log" 2>&1 &
        fi
        if [ -x "$CONKY_DIR/fetch_lmstudio_stats.py" ] && ! pgrep -f "fetch_lmstudio_stats.py" > /dev/null 2>&1; then
            setsid "$CONKY_DIR/fetch_lmstudio_stats.py" >> "$LOG_DIR/conky_lmstudio_daemon.log" 2>&1 &
        fi

        for name in "${!CONKY_INSTANCES[@]}"; do
            conf="${CONKY_INSTANCES[$name]}"
            log="$LOG_DIR/conky_${name}.log"
            
            if ! pgrep -f "$conf" > /dev/null 2>&1; then
                cnt=${FAIL_COUNTS[$name]:-0}
                if [ "$cnt" -lt 5 ]; then
                    FAIL_COUNTS[$name]=$((cnt + 1))
                    echo "[$(date '+%H:%M:%S')] conky_${name} died (attempt $((cnt+1))/5), restarting..." | tee -a "$log"
                    setsid conky -c "$conf" >> "$log" 2>&1 &
                else
                    echo "[$(date '+%H:%M:%S')] ERROR: conky_${name} failed 5 times, giving up." | tee -a "$log"
                fi
            else
                FAIL_COUNTS[$name]=0
            fi
        done
    done
) &

echo "[$(date '+%H:%M:%S')] All Conky instances initialized."
