#!/usr/bin/env bash
# fetch_rpi_stats.sh — Daemon SSH que recoge estadísticas de las RPis cada 30s
RPIS=("192.168.0.105" "192.168.0.193" "192.168.0.80" "192.168.0.101" "192.168.0.102" "192.168.0.103" "192.168.0.221")
INTERVAL=30
TMPDIR="/tmp/conky_rpi"
mkdir -p "$TMPDIR"

fetch_one() {
    local IP="$1"
    local TAG="${IP//\./_}"
    local OUTFILE="$TMPDIR/rpi_${TAG}.dat"
    local LOCKFILE="$TMPDIR/rpi_${TAG}.lock"

    [[ -f "$LOCKFILE" ]] && return
    touch "$LOCKFILE"
    trap "rm -f '$LOCKFILE'" EXIT SIGTERM SIGINT SIGHUP

    local DATA
    DATA=$(ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=no -o BatchMode=yes \
        arkantu@"$IP" 'bash -s' << 'REMOTE'
#!/usr/bin/env bash
# --- Muestreo inicial CPU/red ---
mapfile -t _c1 < <(awk '/^cpu[0-9]/{
    total=$2+$3+$4+$5+$6+$7+$8; idle=$5+$6; n=substr($1,4)+0
    printf "%d %d %d\n",n,total,idle
}' /proc/stat)
read -r _rx1 _tx1 < <(awk '$1~/^eth|^enp|^end|^wl/{print $2,$10;exit}' /proc/net/dev)
read -r _diskr1 _diskw1 < <(awk '$3~/^(sd[a-z]|hd[a-z]|mmcblk[0-9]+|nvme[0-9]+n[0-9]+|vd[a-z])$/{r+=$6;w+=$10}END{printf "%.0f %.0f\n",r+0,w+0}' /proc/diskstats)
sleep 1
mapfile -t _c2 < <(awk '/^cpu[0-9]/{
    total=$2+$3+$4+$5+$6+$7+$8; idle=$5+$6; n=substr($1,4)+0
    printf "%d %d %d\n",n,total,idle
}' /proc/stat)
read -r _rx2 _tx2 < <(awk '$1~/^eth|^enp|^end|^wl/{print $2,$10;exit}' /proc/net/dev)
read -r _diskr2 _diskw2 < <(awk '$3~/^(sd[a-z]|hd[a-z]|mmcblk[0-9]+|nvme[0-9]+n[0-9]+|vd[a-z])$/{r+=$6;w+=$10}END{printf "%.0f %.0f\n",r+0,w+0}' /proc/diskstats)

# --- CPU total % ---
read -r _ct1 _ci1 < <(awk '/^cpu /{total=$2+$3+$4+$5+$6+$7+$8;idle=$5+$6;print total,idle;exit}' /proc/stat)
read -r _ct2 _ci2 < <(awk '/^cpu /{total=$2+$3+$4+$5+$6+$7+$8;idle=$5+$6;print total,idle;exit}' /proc/stat)
_dt=$(( _ct2 - _ct1 )); _di=$(( _ci2 - _ci1 ))
if (( _dt > 0 )); then
    CPU_PCT=$(( (_dt - _di) * 100 / _dt ))
else
    # Fallback: promedio de los cores individuales
    CPU_PCT=0
    _n=0
    for _line in "${_c1[@]}"; do read -r _ni _t1 _idle1 <<< "$_line"; done
    for _i in "${!_c1[@]}"; do
        read -r _ni _t1 _idle1 <<< "${_c1[$_i]}"
        read -r _ni2 _t2 _idle2 <<< "${_c2[$_i]}"
        _dt2=$(( _t2 - _t1 )); _di2=$(( _idle2 - _idle1 ))
        (( _dt2 > 0 )) && CPU_PCT=$(( CPU_PCT + (_dt2 - _di2) * 100 / _dt2 ))
        (( _n++ ))
    done
    (( _n > 0 )) && CPU_PCT=$(( CPU_PCT / _n ))
fi

# --- Por core ---
declare -A _core_pcts
for _i in "${!_c1[@]}"; do
    read -r _ni _t1 _idle1 <<< "${_c1[$_i]}"
    read -r _ni2 _t2 _idle2 <<< "${_c2[$_i]}"
    _dt=$(( _t2 - _t1 )); _di=$(( _idle2 - _idle1 ))
    (( _dt > 0 )) && _core_pcts[$_ni]=$(( (_dt - _di) * 100 / _dt )) || _core_pcts[$_ni]=0
done

# --- Red ---
_rxdiff=$(( _rx2 - _rx1 ))
_txdiff=$(( _tx2 - _tx1 ))
(( _rxdiff < 0 )) && _rxdiff=0
(( _txdiff < 0 )) && _txdiff=0

_rx_human() {
    local b=$1
    if (( b > 1048576 )); then awk "BEGIN{printf \"%.1f MB/s\",$b/1048576}"
    elif (( b > 1024 )); then awk "BEGIN{printf \"%.1f KB/s\",$b/1024}"
    else echo "${b} B/s"; fi
}

# --- Temperatura CPU ---
TEMP=0
for _tf in /sys/class/thermal/thermal_zone*/temp; do
    _type=$(cat "${_tf%temp}type" 2>/dev/null)
    if [[ "$_type" == *cpu* ]] || [[ "$_type" == *CPU* ]] || [[ "$_type" == *SoC* ]] || [[ "$_type" == *soc* ]]; then
        TEMP=$(( $(cat "$_tf" 2>/dev/null || echo 0) / 1000 ))
        break
    fi
done
if [[ $TEMP -eq 0 ]]; then
    _tf=$(ls /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1)
    [[ -n "$_tf" ]] && TEMP=$(( $(cat "$_tf" 2>/dev/null || echo 0) / 1000 ))
fi

# --- RAM ---
eval $(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{
    u=t-a
    printf "RAM_TOT=%d RAM_USED=%d RAM_PCT=%d\n",t/1024,u/1024,(u*100/t)
}' /proc/meminfo)
RAM_TOT_H=$(awk "BEGIN{printf \"%.1fG\",${RAM_TOT}/1024}")
RAM_USED_H=$(awk "BEGIN{printf \"%.1fG\",${RAM_USED}/1024}")

# --- Discos: lsblk para descubrir particiones montadas ---
_human_mb() {
    local m=$1
    awk "BEGIN{if($m>1048576)printf \"%.1fT\",$m/1048576;else if($m>1024)printf \"%.1fG\",$m/1024;else printf \"${m}M\"}"
}
declare -A _seen_disk
_diskcnt=0
while IFS= read -r _line; do
    read -r _dev _fstype _mount <<< "$_line"
    [[ "${_seen_disk[$_dev]}" == "1" ]] && continue
    [[ "$_mount" == "[SWAP]" || "$_mount" == "/boot/firmware" || "$_mount" == "/boot/efi" ]] && continue
    [[ "$_mount" == *"/docker/"* || "$_mount" == *"/snap/"* || -z "$_mount" ]] && continue
    _seen_disk[$_dev]=1

    # Preferir mountpoints /mnt/raid-* sobre nombres legacy del mismo device
    _best=$(awk -v d="$_dev" '$1==d && $2~/\/mnt\/raid-/{print $2; exit}' /proc/mounts)
    [[ -n "$_best" ]] && _mount="$_best"
    # Usar el mountpoint como nombre del disco (más legible que el device name)
    [[ "$_mount" == "/" ]] && _dname="root" || _dname=$(basename "$_mount")

    read -r _dum _dtot <<< $(LC_ALL=C df -m "$_mount" 2>/dev/null | awk 'NR==2{print $3,$2}')
    [[ -z "$_dtot" || "$_dtot" -eq 0 ]] && continue
    (( _dtot < 500 )) && continue
    _dpct=$(( _dum * 100 / _dtot ))

    echo "DISK${_diskcnt}_NAME:$_dname"
    echo "DISK${_diskcnt}_PCT:$_dpct"
    echo "DISK${_diskcnt}_USED_H:$(_human_mb $_dum)"
    echo "DISK${_diskcnt}_TOTAL_H:$(_human_mb $_dtot)"
    (( _diskcnt++ ))
    (( _diskcnt >= 5 )) && break
done < <(LC_ALL=C lsblk -o NAME,FSTYPE,MOUNTPOINT -nrp 2>/dev/null | awk '$2~/ext4|xfs|btrfs/ && $3!=""')
echo "DISK_COUNT:$_diskcnt"

# --- Hostname, uptime, kernel, iface ---
HOST=$(hostname)
UPTIME=$(uptime -p | sed 's/up //')
KERNEL=$(uname -r)
IFACE=$(awk '$1~/^eth|^enp|^end|^wl/{print substr($1,1,length($1)-1);exit}' /proc/net/dev 2>/dev/null || ip route | awk '/default/{print $5;exit}')

# --- GPU AMD (solo si hay card con amdgpu) ---
GPU_PCT=0; GPU_TEMP=0; VRAM_PCT=0; VRAM_USED_MB=0; VRAM_TOTAL_MB=0; GPU_FREQ=0
for _card in /sys/class/drm/card*/device; do
    _drv=$(readlink "$_card/driver" 2>/dev/null | xargs basename 2>/dev/null)
    if [[ "$_drv" == "amdgpu" ]]; then
        GPU_PCT=$(cat "$_card/gpu_busy_percent" 2>/dev/null || echo 0)
        _hwmon=$(ls "$_card/hwmon/" 2>/dev/null | head -1)
        GPU_TEMP=$(( $(cat "$_card/hwmon/$_hwmon/temp1_input" 2>/dev/null || echo 0) / 1000 ))
        _vused=$(cat "$_card/mem_info_vram_used" 2>/dev/null || echo 0)
        _vtot=$(cat "$_card/mem_info_vram_total" 2>/dev/null || echo 0)
        VRAM_USED_MB=$(( _vused / 1048576 ))
        VRAM_TOTAL_MB=$(( _vtot / 1048576 ))
        (( VRAM_TOTAL_MB > 0 )) && VRAM_PCT=$(( VRAM_USED_MB * 100 / VRAM_TOTAL_MB ))
        GPU_FREQ=$(( $(cat "$_card/hwmon/$_hwmon/freq1_input" 2>/dev/null || echo 0) / 1000000 ))
        break
    fi
done

# --- Hailo PCIe ---
HAILO_STATE="N/A"
for _pf in /sys/bus/pci/devices/*/power_state; do
    _dev=$(dirname "$_pf")
    if ls "$_dev/" 2>/dev/null | grep -q hailo; then
        HAILO_STATE=$(cat "$_pf" 2>/dev/null || echo "N/A")
        break
    fi
done
if [[ "$HAILO_STATE" == "N/A" ]]; then
    _pf=$(find /sys/bus/pci/devices -name power_state 2>/dev/null | head -1)
    # Check if hailo device exists differently
    if [[ -e /dev/hailo0 ]]; then
        HAILO_STATE=$(cat /sys/bus/pci/devices/0001:01:00.0/power_state 2>/dev/null || echo "activo")
    fi
fi

# --- Salida ---
echo "HOST:$HOST"
echo "UPTIME:$UPTIME"
echo "KERNEL:$KERNEL"
echo "IFACE:${IFACE:-eth0}"
echo "CPU:$CPU_PCT"
for _k in "${!_core_pcts[@]}"; do echo "CPU${_k}:${_core_pcts[$_k]}"; done
echo "TEMP:$TEMP"
echo "RAMUSED:$RAM_USED"
echo "RAMTOTAL:$RAM_TOT"
echo "RAMPCT:$RAM_PCT"
echo "RAMUSED_H:$RAM_USED_H"
echo "RAMTOTAL_H:$RAM_TOT_H"
echo "RXBPS:$_rxdiff"
echo "TXBPS:$_txdiff"
echo "RXBPS_H:$(_rx_human $_rxdiff)"
echo "TXBPS_H:$(_rx_human $_txdiff)"
_diskr_bps=$(( (_diskr2 - _diskr1) * 512 ))
_diskw_bps=$(( (_diskw2 - _diskw1) * 512 ))
(( _diskr_bps < 0 )) && _diskr_bps=0
(( _diskw_bps < 0 )) && _diskw_bps=0
echo "DISKIO_READ:$_diskr_bps"
echo "DISKIO_WRITE:$_diskw_bps"
echo "DISKIO_READ_H:$(_rx_human $_diskr_bps)"
echo "DISKIO_WRITE_H:$(_rx_human $_diskw_bps)"
echo "GPUPCT:$GPU_PCT"
echo "GPUTEMP:$GPU_TEMP"
echo "VRAMPCT:$VRAM_PCT"
echo "VRAMUSEDMB:$VRAM_USED_MB"
echo "VRAMTOTALMB:$VRAM_TOTAL_MB"
echo "GPUFREQ:$GPU_FREQ"
echo "HAILOSTATE:$HAILO_STATE"
REMOTE
    )
    local EXIT=$?
    if [[ $EXIT -ne 0 ]] || [[ -z "$DATA" ]]; then
        echo "OFFLINE:1" > "$OUTFILE"
    else
        echo "$DATA" > "$OUTFILE"
        echo "OFFLINE:0" >> "$OUTFILE"
    fi
    rm -f "$LOCKFILE"
}

echo "fetch_rpi_stats.sh iniciado (PID $$)"
# Limpiar lock files residuales de ejecuciones anteriores
rm -f "$TMPDIR"/*.lock 2>/dev/null
while true; do
    for IP in "${RPIS[@]}"; do
        fetch_one "$IP" &
    done
    wait
    sleep $INTERVAL
done
