#!/usr/bin/env python3
"""arc-gpu-daemon — métricas de GPU Intel Arc (driver xe) para Conky.

Sustituye al sondeo con `gputop -d 1 -n 1` cada 15 s, que abría el device
/dev/dri/renderD128 para leer contadores OA/perf y provocaba rachas de
"TLB invalidation fence timeout" en el driver xe, con bloqueos del
compositor de hasta 239 s y finalmente cuelgue total del escritorio.

Este daemon NO abre el device: sólo lee /proc/<pid>/fdinfo/* de los
clientes DRM (corre como root para ver fdinfo de otros UID, p.ej. contenedores).

Detalles del driver xe (comprobados en esta máquina):
  * un mismo cliente exporta varios fds (renderD128 + card0) y varios procesos
    pueden heredar el mismo fd -> hay que agrupar por drm-client-id, si no la
    memoria se cuenta 3-5 veces.
  * drm-cycles-<motor> es el tiempo activo y drm-total-cycles-* el reloj de
    referencia global: ocupación = 100 * delta(cycles) / delta(total).
  * atribución por proceso: `ovms` (contenedor OpenVINO, cid del proceso ovms)
    y el backend llama.cpp de LM Studio (`llama-server` bajo ~/.lmstudio).
    Sin esa atribución los dos motores comparten la misma iGPU y el panel
    enseñaría el mismo número en las dos secciones.

Salida (formato que espera Conky):
  FREQ:<MHz>  GTT:<GiB>  RNDR:<%>  VIDEO:<%>  COMPUTE:<%>  COPY:<%>
  OVMS:<%>  LMBUSY:<%>
"""
import os
import sys
import time

OUTFILE = os.environ.get("ARC_OUTFILE", "/tmp/conky_arc.dat")
INTERVAL = float(os.environ.get("ARC_INTERVAL", "5"))
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


def classify(comm, cmd):
    """Motor propietario del cliente DRM, o None si es ruido de escritorio."""
    s = f"{comm} {cmd}".lower()
    if "ovms" in s:
        return "ovms"
    if "llama-server" in s and "lmstudio" in s:
        return "lm"
    return None


def drm_clients():
    """{clave_cliente: {'v': {clave_drm: valor}, 'own': motor}} por drm-client-id."""
    out = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            comm = open(f"/proc/{entry.name}/comm").read().strip()
        except OSError:
            comm = "?"
        try:
            with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                cmd = f.read().decode("utf8", "replace").replace("\0", " ").strip()
        except OSError:
            cmd = ""
        own = classify(comm, cmd)
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
                if prev is None or vals.get("drm-total-cycles-rcs", 0) > prev["v"].get(
                    "drm-total-cycles-rcs", 0
                ):
                    out[key] = {"v": vals, "own": own}
    return out


def sample(prev):
    clients = drm_clients()
    gtt_kib = sum(c["v"].get("drm-total-gtt", 0) for c in clients.values())

    busy = dict.fromkeys(ENGINES, 0.0)
    own = {"ovms": 0.0, "lm": 0.0}
    if prev:
        dtot = max(
            (
                c["v"].get("drm-total-cycles-rcs", 0)
                - prev.get(k, {}).get("v", {}).get("drm-total-cycles-rcs", 0)
                for k, c in clients.items()
                if k in prev
            ),
            default=0,
        )
        if dtot > 0:
            for eng in ENGINES:
                key = f"drm-cycles-{eng}"
                delta = sum(
                    max(c["v"].get(key, 0) - prev.get(k, {}).get("v", {}).get(key, 0), 0)
                    for k, c in clients.items()
                    if k in prev
                )
                busy[eng] = max(0.0, min(100.0, delta / dtot * 100.0))
            # Por motor: el motor más cargado de cada cliente suyo (evita sumar
            # el mismo trabajo en rcs+ccs) y luego se reparte sobre el reloj global.
            per = {"ovms": 0, "lm": 0}
            for k, c in clients.items():
                if not c["own"] or k not in prev:
                    continue
                pv = prev[k]["v"]
                d = max(
                    max(c["v"].get(f"drm-cycles-{e}", 0) - pv.get(f"drm-cycles-{e}", 0), 0)
                    for e in ENGINES
                )
                per[c["own"]] += d
            for name, d in per.items():
                own[name] = max(0.0, min(100.0, d / dtot * 100.0))
    return clients, gtt_kib, busy, own


def write(freq, gtt_gib, busy, own):
    out = (
        f"FREQ:{freq:.0f}\n"
        f"GTT:{gtt_gib:.1f}\n"
        f"RNDR:{busy['rcs']:.0f}\n"
        f"VIDEO:{busy['vcs']:.0f}\n"
        f"COMPUTE:{busy['ccs']:.0f}\n"
        f"COPY:{busy['bcs']:.0f}\n"
        f"OVMS:{own['ovms']:.0f}\n"
        f"LMBUSY:{own['lm']:.0f}\n"
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
            clients, gtt_kib, busy, own = sample(prev)
            prev = clients
            write(read_freq(), gtt_kib / 1024.0 / 1024.0, busy, own)
            if verbose:
                print(
                    f"clientes={len(clients)} gtt={gtt_kib/1024/1024:.2f}GiB "
                    + " ".join(f"{e}={busy[e]:.1f}%" for e in ENGINES)
                    + f" ovms={own['ovms']:.0f}% lm={own['lm']:.0f}%",
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
