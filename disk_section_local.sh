#!/usr/bin/env bash
# disk_section_local.sh — discos locales de Khazad-dum via lsblk + df
export LC_ALL=C LANG=C

bar() {
    local pct=${1:-0} w=34
    local f=$(( pct * w / 100 )) e b=""
    (( f > w )) && f=$w
    e=$(( w - f ))
    for (( i=0; i<f; i++ )); do b+="▓"; done
    for (( i=0; i<e; i++ )); do b+="░"; done
    echo "$b"
}

human() {
    local mb=$1
    awk "BEGIN{if($mb>1048576)printf \"%.1fT\",$mb/1048576;else if($mb>1024)printf \"%.1fG\",$mb/1024;else printf \"${mb}M\"}"
}

declare -A seen
while IFS= read -r line; do
    read -r dev fstype mount <<< "$line"
    [[ "${seen[$dev]}" == "1" ]] && continue
    [[ "$mount" == "[SWAP]" || "$mount" == "/boot/efi" || "$mount" == "/boot/firmware" ]] && continue
    [[ "$mount" == *"/snap/"* || "$mount" == *"/docker/"* || -z "$mount" ]] && continue

    seen[$dev]=1
    parent=$(lsblk -no PKNAME "$dev" 2>/dev/null | tr -d ' \n')
    [[ -n "$parent" ]] && diskname="$parent" || diskname=$(basename "$dev")

    read -r used_mb total_mb <<< $(df -m "$mount" | awk 'NR==2{print $3,$2}')
    [[ -z "$total_mb" || "$total_mb" -eq 0 ]] && continue
    (( total_mb < 500 )) && continue
    pct=$(( used_mb * 100 / total_mb ))

    printf "%-14s %s / %s (%d%%)\n" "${diskname}:" "$(human $used_mb)" "$(human $total_mb)" "$pct"
    echo "$(bar $pct)"
done < <(lsblk -o NAME,FSTYPE,MOUNTPOINT -nrp | awk '$2~/ext4|xfs|btrfs|vfat/ && $3!=""')
