#!/usr/bin/env bash
# Daemon que recolecta métricas del Hailo-8L periodicamente
# y las escribe en /tmp/hailo_stats.txt para que conky lea rapido
# Formato: KEY=VALUE una por linea

STATS_FILE="/tmp/hailo_stats.txt"
INTERVAL=10  # segundos entre actualizaciones

# Funcion para detectar el dispositivo Hailo
detect_hailo() {
    for pf in /sys/bus/pci/devices/*/; do
        if [ -f "${pf}uevent" ] && grep -q "1E60" "${pf}uevent" 2>/dev/null; then
            HAILO_DEV="${pf}"
            return 0
        fi
    done
    HAILO_DEV=""
    return 1
}

# Recoger datos estaticos una vez (FW, SERIAL, ARCH, BOARD)
collect_static() {
    if [ -e /dev/hailo0 ] && command -v hailortcli &>/dev/null; then
        # fw-control identify da todo en una sola llamada
        local identify
        identify=$(hailortcli fw-control identify 2>/dev/null)
        echo "FW=$(echo "$identify" | grep -a 'Firmware Version' | sed 's/.*: //' | tr -d '\0')"
        echo "SERIAL=$(echo "$identify" | grep -a 'Serial Number' | sed 's/.*: //' | tr -d '\0')"
        echo "ARCH=$(echo "$identify" | grep -a 'Device Architecture' | sed 's/.*: //' | tr -d '\0')"
        echo "BOARD=$(echo "$identify" | grep -a 'Board Name' | sed 's/.*: //' | tr -d '\0' | tr -d ' ')"
        echo "PRODUCT=$(echo "$identify" | grep -a 'Product Name' | sed 's/.*: //' | tr -d '\0')"
    else
        echo "FW=N/A"
        echo "SERIAL=N/A"
        echo "ARCH=N/A"
        echo "BOARD=N/A"
        echo "PRODUCT=N/A"
    fi
}

# Recoger datos dinamicos cada tick
collect_dynamic() {
    detect_hailo
    if [ -n "$HAILO_DEV" ]; then
        if [ -e /dev/hailo0 ]; then
            echo "STATE=activo"
        elif [ -d "${HAILO_DEV}driver" ]; then
            echo "STATE=driver-cargado"
        else
            echo "STATE=sin-driver"
        fi
        echo "SLOT=$(basename "$HAILO_DEV")"
        echo "POWER=$(cat "${HAILO_DEV}power_state" 2>/dev/null || echo N/A)"
    else
        echo "STATE=no-detectado"
        echo "SLOT=N/A"
        echo "POWER=N/A"
    fi
    # Utilizacion: Hailo no expone % continuo via sysfs.
    # Si hay una app con HAILO_MONITOR=1, se podria leer, pero
    # sin inference activa el chip esta idle (0%).
    echo "UTIL=0"
}

# Main
mkdir -p "$(dirname "$STATS_FILE")"

# Recoger estaticos una vez al arrancar
STATIC_DATA=$(collect_static)

while true; do
    DYNAMIC_DATA=$(collect_dynamic)
    {
        echo "$STATIC_DATA"
        echo "$DYNAMIC_DATA"
    } > "$STATS_FILE.tmp"
    mv "$STATS_FILE.tmp" "$STATS_FILE"
    sleep "$INTERVAL"
done