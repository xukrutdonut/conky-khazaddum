#!/usr/bin/env python3
"""Cuota real de Ollama Cloud leída de https://ollama.com/settings.

Ollama no expone la cuota por API (issue #12532), así que se autentica con la
cookie de sesión de Chrome (`__Secure-session`) y se parsea el bloque
«Cloud usage»: porcentaje, modelos con peticiones y hora de reinicio.

Salida: /tmp/conky_ollama_cloud.json (escritura atómica)
    {"ts": 1762590000,
     "session": {"pct": 14.5, "requests": 616, "models": [["deepseek-v4.1-flash:1017", 616]],
                 "reset": "2026-11-08T10:00:00Z"},
     "weekly": {...}}

Requiere el venv ~/.venvs/conky-ollama (secretstorage + cryptography).
Se autolimita a una consulta cada MIN_INTERVAL segundos; --force lo salta.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

OUT = '/tmp/conky_ollama_cloud.json'
CHROME_COOKIES = os.path.expanduser('~/.config/google-chrome/Default/Cookies')
HOST = 'ollama.com'
COOKIE = '__Secure-session'
MIN_INTERVAL = 60
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/141.0.0.0 Safari/537.36')


def log(msg):
    print(f'{datetime.now().strftime("%H:%M:%S")} {msg}', file=sys.stderr)


def keyring_pwd():
    try:
        import secretstorage
    except ImportError:
        return None
    try:
        bus = secretstorage.dbus_init()
        for it in secretstorage.get_default_collection(bus).get_all_items():
            if it.get_label() == 'Chrome Safe Storage':
                return it.get_secret()
    except Exception as e:
        log(f'keyring: {e}')
    return None


def chrome_cookie():
    if not os.path.exists(CHROME_COOKIES):
        log('sin base de cookies de Chrome')
        return None
    tmp = os.path.join(tempfile.mkdtemp(), 'c.sqlite')
    shutil.copy2(CHROME_COOKIES, tmp)
    try:
        con = sqlite3.connect(tmp)
        row = con.execute('select encrypted_value, value from cookies where host_key=? and name=?',
                          (HOST, COOKIE)).fetchone()
        con.close()
    finally:
        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    if not row:
        log('sin cookie de ollama.com en Chrome')
        return None
    enc, plain = row
    if plain:
        return plain
    if not enc or enc[:3] not in (b'v10', b'v11'):
        log('formato de cookie no soportado')
        return None
    pwd = keyring_pwd()
    if not pwd:
        log('sin contraseña de keyring (¿sesión de escritorio bloqueada?)')
        return None
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = hashlib.pbkdf2_hmac('sha1', pwd, b'saltysalt', 1, 16)
    dec = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16)).decryptor()
    data = dec.update(enc[3:]) + dec.finalize()
    data = data[:-data[-1]]
    host_hash = hashlib.sha256(HOST.encode()).digest()
    if data.startswith(host_hash):
        data = data[32:]
    return data.decode('utf-8', 'replace')


def fetch(cookie):
    req = urllib.request.Request(f'https://{HOST}/settings',
                                 headers={'Cookie': f'{COOKIE}={cookie}', 'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=25) as f:
        return f.read().decode('utf-8', 'replace')


def parse_block(chunk):
    """Porcentaje, modelos con peticiones y reset de un bloque de uso."""
    m = re.search(r'([\d.]+)%\s*used', chunk)
    if not m:
        return None
    models = re.findall(r'data-model="([^"]+)"[^>]*?data-requests="(\d+)"', chunk, re.S)
    models = [[name, int(n)] for name, n in models]
    r = re.search(r'data-time="([^"]+)"', chunk)
    return {'pct': float(m.group(1)),
            'requests': sum(n for _, n in models),
            'models': models,
            'reset': r.group(1) if r else None}


def parse(html):
    if 'Session usage' not in html:
        raise ValueError('página sin bloque de uso (sesión caducada)')
    i = html.find('Session usage')
    j = html.find('Weekly usage')
    if j < 0:
        raise ValueError('sin bloque Weekly usage')
    out = {}
    for key, start, end in (('session', i, j), ('weekly', j, len(html))):
        blk = parse_block(html[start:end])
        if not blk:
            raise ValueError(f'bloque {key} ilegible')
        out[key] = blk
    return out


def fresh():
    try:
        st = os.stat(OUT)
        if time.time() - st.st_mtime < MIN_INTERVAL:
            return True
    except OSError:
        pass
    return False


def main():
    force = '--force' in sys.argv
    if not force and fresh():
        return 0
    cookie = chrome_cookie()
    if not cookie:
        return 3
    try:
        html = fetch(cookie)
        data = parse(html)
    except Exception as e:
        log(f'consulta fallida: {e}')
        return 4
    data['ts'] = int(time.time())
    data['host'] = HOST
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, OUT)
    log(f"session {data['session']['pct']}% · weekly {data['weekly']['pct']}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
