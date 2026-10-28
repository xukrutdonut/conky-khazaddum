#!/usr/bin/env bash
# arc_gpu_daemon.sh — Monitoriza GPU Intel Arc (driver Xe) usando gputop
# Motivo: intel_gpu_top NO soporta dispositivos Xe ("Detected Xe device which is
# not supported by intel_gpu_top. Please use 'gputop' tool instead."), asi que el
# panel de conky se quedaba a cero. gputop si funciona, pero necesita root para
# leer el fdinfo de los procesos de contenedores (otros UID): regla sudoers
# NOPASSWD en /etc/sudoers.d/gputop-monitor.
OUTFILE="/tmp/conky_arc.dat"

cleanup() {
    rm -f "$OUTFILE"
    pkill -P $$ 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT EXIT

cat > "$OUTFILE" << 'INIT'
FREQ:0
GTT:0
RNDR:0
VIDEO:0
COMPUTE:0
COPY:0
INIT

exec python3 -u - << 'EOF'
import os
import re
import subprocess
import time

OUTFILE = '/tmp/conky_arc.dat'
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
PCT = re.compile(r'(\d+(?:\.\d+)?)%')
FREQ = re.compile(r'GT0-(\d+)/')
MEM = re.compile(r'^\s*\d+\s+([\d.]+)([MG])\s')

# Respaldo de frecuencia si gputop fallara.
FREQ_SYSFS = [
    '/sys/class/drm/card0/device/tile0/gt0/freq0/cur_freq',
    '/sys/class/drm/card0/gt_cur_freq_mhz',
]


def sysfs_freq():
    for p in FREQ_SYSFS:
        try:
            with open(p) as f:
                return int(f.read().strip())
        except OSError:
            continue
    return 0


def write(freq, gtt, rndr, video, compute, copy):
    out = (
        f"FREQ:{freq:.0f}\n"
        f"GTT:{gtt:.1f}\n"
        f"RNDR:{rndr:.0f}\n"
        f"VIDEO:{video:.0f}\n"
        f"COMPUTE:{compute:.0f}\n"
        f"COPY:{copy:.0f}\n"
    )
    tmp = OUTFILE + '.tmp'
    with open(tmp, 'w') as f:
        f.write(out)
    os.rename(tmp, OUTFILE)


def parse(text):
    freq = 0
    gtt = 0.0
    rcs = vcs = vecs = bcs = ccs = 0.0
    minor = None
    for raw in text.splitlines():
        line = ANSI.sub('', raw)
        if line.startswith('DRM minor'):
            minor = line
            m = FREQ.search(line)
            if m:
                freq = max(freq, int(m.group(1)))
            continue
        # Solo el render node (minor 128) para no duplicar; si no aparece, usa todo.
        if minor is not None and '128' not in minor:
            continue
        vals = [float(v) for v in PCT.findall(line)]
        if len(vals) >= 5:
            # columnas de gputop: rcs | vcs | vecs | bcs | ccs
            rcs += vals[0]
            vcs += vals[1]
            vecs += vals[2]
            bcs += vals[3]
            ccs += vals[4]
            mm = MEM.search(line)
            if mm:
                gtt += float(mm.group(1)) * (1.0 / 1024 if mm.group(2) == 'M' else 1.0)
    return (freq, gtt, min(rcs, 100.0), min(vcs, 100.0), min(vecs, 100.0),
            min(bcs, 100.0), min(ccs, 100.0))


while True:
    try:
        proc = subprocess.run(
            ['sudo', '-n', 'gputop', '-d', '1', '-n', '1'],
            capture_output=True, text=True, timeout=10,
        )
        f, gtt, rcs, vcs, vecs, bcs, ccs = parse(proc.stdout)
        write(f or sysfs_freq(), gtt, rcs, vcs, ccs, bcs)
    except Exception:
        write(sysfs_freq(), 0, 0, 0, 0, 0)
    # 2026-10-28: antes 1 s -> ~28 aperturas/min del device Xe con sudo (40k lineas
    # de sudo por arranque). Con 55 "TLB invalidation fence timeout" del driver xe
    # esa misma noche, era el principal candidato al cuelgue de las 02:00.
    # El panel de conky no necesita mas de una lectura cada 15 s.
    time.sleep(15)
EOF
