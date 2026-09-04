#!/usr/bin/env bash
# arc_gpu_daemon.sh — Monitoriza GPU Intel usando intel_gpu_top
OUTFILE="/tmp/conky_arc.dat"

cleanup() {
    rm -f "$OUTFILE"
    pkill -P $$ 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT EXIT

# Inicializar
cat > "$OUTFILE" << 'INIT'
FREQ_REQ:0
FREQ_ACT:0
RC6:0
POWER:0
RNDR:0
VIDEO:0
COMPUTE:0
COPY:0
INIT

python3 -u - << 'EOF'
import subprocess, json, os

OUTFILE = '/tmp/conky_arc.dat'

proc = subprocess.Popen(
    ['intel_gpu_top', '-J', '-s', '2000'],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
    bufsize=1
)

buf = ""
for line in proc.stdout:
    buf += line
    if line.strip().startswith('}') and buf.count('{') == buf.count('}'):
        # Encontramos un objeto JSON completo en la raíz
        try:
            # Eliminar caracteres iniciales extra como '[' o comas
            s = buf.strip()
            if s.startswith('['):
                s = s[1:].strip()
            s = s.rstrip(',')
            
            data = json.loads(s)
            freq_act = data.get('frequency', {}).get('actual', 0)
            power_gpu = data.get('power', {}).get('GPU', 0)
            rc6 = data.get('rc6', {}).get('value', 0)
            
            engines = data.get('engines', {})
            rndr = 0
            for name, eng in engines.items():
                if 'Render' in name or '3D' in name:
                    rndr = max(rndr, eng.get('busy', 0))
            
            video = 0
            for name, eng in engines.items():
                if 'Video' in name:
                    video = max(video, eng.get('busy', 0))

            compute = 0
            for name, eng in engines.items():
                if 'Compute' in name:
                    compute = max(compute, eng.get('busy', 0))

            copy = 0
            for name, eng in engines.items():
                if 'Blitter' in name or 'Copy' in name:
                    copy = max(copy, eng.get('busy', 0))

            out = f"""FREQ_REQ:0
FREQ_ACT:{freq_act:.0f}
RC6:{rc6:.0f}
POWER:{power_gpu:.1f}
RNDR:{rndr:.0f}
VIDEO:{video:.0f}
COMPUTE:{compute:.0f}
COPY:{copy:.0f}
"""
            with open(OUTFILE + '.tmp', 'w') as f:
                f.write(out)
            os.rename(OUTFILE + '.tmp', OUTFILE)
        except Exception as e:
            pass
        buf = ""
EOF
