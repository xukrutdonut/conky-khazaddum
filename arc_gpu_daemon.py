#!/usr/bin/env python3
"""arc-gpu-daemon — métricas de GPU Intel Arc (driver xe) para Conky.

Sustituye al sondeo con `gputop -d 1 -n 1` cada 15 s, que abría el device
/dev/dri/renderD128 para leer contadores OA/perf y provocaba rachas de
"TLB invalidation fence timeout" en el driver xe, con bloqueos del
compositor de hasta 239 s y finalmente cuelgue total del escritorio.

Este daemon NO abre el device: sólo lee /proc/<pid>/fdinfo/* de los
clientes DRM (necesita root para ver fdinfo de otros UID, p.ej. contenedores).

Detalles del driver xe (comprobados en esta máquina):
  * un mismo cliente exporta varios fds (renderD128 + card0) y varios procesos
    pueden heredar el mismo fd -> hay que agrupar por drm-client-id, si no la
    memoria se cuenta 3-5 veces.
  * drm-cycles-<motor> es el tiempo activo y drm-total-cycles-* el reloj de
    referencia global: ocupación = 100 * delta(cycles) / delta(total).

Salida (formato que espera Conky):
  FREQ:<MHz>  GTT:<GiB>  RNDR:<%>  VIDEO:<%>  COMPUTE:<%>  COPY:<%
"""
import os
import sys
import time

OUTFILE = os.environ.get("ARC_OUTFILE", "/tmp/conky_arc.dat")
INTERVAL = float(os.environ.get("ARC_INTERVAL", "15"))
DRI = "/dev/dri/"
ENGINES = ("rcs", "vcs", "vecs", "bcs", "ccs")
FREQ_PATHS = (
    "/sys/class/drm/card0/device/tile0/gt0/freq0/act_freq",
    "/sys/class/drm/card0/device/tile0/gt0/freq0/cur_freq",
)


def read_freq():
    vals = {}
    for p in FREQ_PATHS:
        try:
            with open(p) as f:
                vals[os.path.basename(p)] = int(f.read().strip())
        except (OSError, ValueError):
            pass
    return vals.get("act_freq") or vals.get("cur_freq") or 0


def drm_clients():
    """{clave_cliente: {clave_drm: valor}} agrupado por drm-client-id."""
    out = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            fds = os.scandir(f"/proc/{entry.name}/fd")
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        with fds:
            for fd in fds:
                try:
                    target = os.readlink(fd.path)
                except OSError:
                    continue
                if not target.startswith(DRI):
                    continue
                vals = {}
                try:
                    with open(fd.path.replace("/fd/", "/fdinfo/")) as f:
                        for line in f:
                            key, _, raw = line.partition(":")
                            if not key.startswith("drm-"):
                                continue
                            try:
                                vals[key] = int(raw.strip().split()[0])
                            except (ValueError, IndexError):
                                continue
                except OSError:
                    continue
                if not vals:
                    continue
                cid = vals.get("drm-client-id")
                key = (cid, target) if cid is not None else (fd.path, target)
                prev = out.get(key)
                if prev is None or vals.get("drm-total-cycles-rcs", 0) > prev.get(
                    "drm-total-cycles-rcs", 0
                ):
                    out[key] = vals
    return out


def sample(prev):
    clients = drm_clients()
    gtt_kib = sum(v.get("drm-total-gtt", 0) for v in clients.values())

    busy = dict.fromkeys(ENGINES, 0.0)
    if prev:
        dtot = max(
            (
                v.get("drm-total-cycles-rcs", 0)
                - prev.get(k, {}).get("drm-total-cycles-rcs", 0)
                for k, v in clients.items()
                if k in prev
            ),
            default=0,
        )
        if dtot > 0:
            for eng in ENGINES:
                key = f"drm-cycles-{eng}"
                delta = sum(
                    max(v.get(key, 0) - prev.get(k, {}).get(key, 0), 0)
                    for k, v in clients.items()
                    if k in prev
                )
                busy[eng] = max(0.0, min(100.0, delta / dtot * 100.0))
    return clients, gtt_kib, busy


def write(freq, gtt_gib, busy):
    out = (
        f"FREQ:{freq:.0f}\n"
        f"GTT:{gtt_gib:.1f}\n"
        f"RNDR:{busy['rcs']:.0f}\n"
        f"VIDEO:{busy['vcs']:.0f}\n"
        f"COMPUTE:{busy['ccs']:.0f}\n"
        f"COPY:{busy['bcs']:.0f}\n"
    )
    tmp = f"{OUTFILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(out)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUTFILE)


def main():
    once = "--once" in sys.argv
    verbose = "--verbose" in sys.argv
    prev = None
    while True:
        try:
            clients, gtt_kib, busy = sample(prev)
            prev = clients
            write(read_freq(), gtt_kib / 1024.0 / 1024.0, busy)
            if verbose:
                print(
                    f"clientes={len(clients)} gtt={gtt_kib/1024/1024:.2f}GiB "
                    + " ".join(f"{e}={busy[e]:.1f}%" for e in ENGINES),
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:  # nunca morir: el panel se quedaría a cero
            print(f"arc-gpu-daemon: error: {exc}", file=sys.stderr, flush=True)
        if once:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
