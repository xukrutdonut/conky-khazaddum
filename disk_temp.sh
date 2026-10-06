#!/usr/bin/env bash
# Temperatura del disco de sistema (SATA) via hwmon del módulo drivetemp.
# Detección dinámica: tras la actualización de Ubuntu ya no hay hwmon fijo
# (antes hwmon1) y la enumeración cambia entre arranques.
for h in /sys/class/hwmon/hwmon*; do
    if [ "$(cat "$h/name" 2>/dev/null)" = "drivetemp" ]; then
        t=$(cat "$h/temp1_input" 2>/dev/null) && { echo "$((t / 1000))°C"; exit 0; }
    fi
done
echo N/A
