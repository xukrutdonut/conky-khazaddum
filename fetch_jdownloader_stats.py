#!/usr/bin/env python3
"""
Daemon: monitoriza JDownloader (contenedor en .105 via API de My JDownloader).
Escribe /tmp/jdownloader_stats.json atomicamente cada POLL_INTERVAL segundos.

Fuente: api.jdownloader.org (My JDownloader), credenciales en
~/.config/conky/.jd_creds (MYJDOWNLOADER_EMAIL/PASSWORD/DEVICE_NAME).

Payload:
  ts, state ('RUNNING'|'PAUSED'|'STOPPED'|...), speed (B/s global),
  active [ {name, pct, loaded, total, speed, status} ]  (paquetes sin terminar,
  ordenados por velocidad descendente, sin nombre recortado -> recorta el render),
  finished_count, total_count
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser('~/.local/lib/python3.14/site-packages'))
try:
    import myjdapi
except ImportError:
    myjdapi = None

STATS_FILE = '/tmp/jdownloader_stats.json'
CRED_FILE = os.path.expanduser('~/.config/conky/.jd_creds')
POLL_INTERVAL = 30
MAX_ACTIVE = 6

FIELDS = [{'name': True, 'bytesLoaded': True, 'bytesTotal': True,
           'speed': True, 'finished': True, 'status': True}]


def read_creds():
    env = {}
    with open(CRED_FILE) as f:
        for line in f:
            k, _, v = line.strip().partition('=')
            env[k] = v
    return env


def collect():
    if myjdapi is None:
        raise RuntimeError('myjdapi no instalado')
    env = read_creds()
    jd = myjdapi.Myjdapi()
    jd.set_app_key('conky-khazaddum')
    jd.connect(env['MYJDOWNLOADER_EMAIL'], env['MYJDOWNLOADER_PASSWORD'])
    dev = jd.get_device(env['MYJDOWNLOADER_DEVICE_NAME'])

    state = dev.downloadcontroller.get_current_state()
    speed = dev.downloadcontroller.get_speed_in_bytes() or 0

    resp = dev.downloads.query_packages(FIELDS)
    pkgs = resp.get('data', []) if isinstance(resp, dict) else resp

    active, finished = [], 0
    for p in pkgs:
        total = p.get('bytesTotal') or 0
        if p.get('finished') or (total and (p.get('bytesLoaded') or 0) >= total):
            finished += 1
            continue
        pct = round(100.0 * (p.get('bytesLoaded') or 0) / total, 1) if total else 0.0
        active.append({
            'name': p.get('name') or '?',
            'pct': pct,
            'loaded': p.get('bytesLoaded') or 0,
            'total': total,
            'speed': p.get('speed') or 0,
            'status': p.get('status') or '',
        })
    active.sort(key=lambda x: (-x['speed'], -x['pct']))
    return {
        'ts': time.time(),
        'state': state,
        'speed': int(speed),
        'active': active[:MAX_ACTIVE],
        'active_count': len(active),
        'finished_count': finished,
        'total_count': len(pkgs),
    }


def write_atomic(data):
    tmp = STATS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, STATS_FILE)


def main():
    while True:
        try:
            write_atomic(collect())
        except Exception as e:
            try:
                write_atomic({'ts': time.time(), 'error': str(e)[:200]})
            except OSError:
                pass
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
