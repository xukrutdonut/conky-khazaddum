#!/usr/bin/env python3
"""Daemon de consumo Nous Portal para Conky.

Lee el access_token de OAuth de ~/.hermes/shared/nous_auth.json (que Hermes
renueva en cada llamada API) y consulta el saldo/crédito oficial:

    GET {portal}/api/oauth/account   Authorization: Bearer <token>

La cuenta aquí es un plan de ventana (p.ej. "Hermes Plus") cuyos gauges de uso
vienen en basis points (10000 = 100%) por día/semana/mes.

NUNCA refresca el token por su cuenta: el refresh_token de Nous es de un solo
uso y rotatorio; usarlo desde fuera de Hermes dispararía un "refresh token
reuse" y revocaría toda la sesión. Si la llamada da 401 (o el access_token
está caducado), escribe {"ok": false, "need_relogin": true} y conserva el
último dato válido (stale) para que el widget muestre algo en vez de hueco.

Salida: /tmp/nous_stats.json (escritura atómica).

Requiere: Pillow NO (render aparte); urllib + json + time (stdlib).
Autolimita a una consulta cada POLL_INTERVAL s (default 300).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

OUT = '/tmp/nous_stats.json'
AUTH = os.path.expanduser('~/.hermes/shared/nous_auth.json')
POLL_INTERVAL = int(os.environ.get('NOUS_POLL_INTERVAL', '300'))  # 5 min
BP = 10000.0  # basis points -> %

STATE_KEYS = None  # (access_token, portal_base_url, internal_id) leídos del archivo corriente


def log(msg):
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f'{ts} {msg}', file=sys.stderr, flush=True)


def read_token():
    """Devuelve (access_token, portal_base_url) o (None, None)."""
    try:
        with open(AUTH) as f:
            st = json.load(f)
    except (OSError, ValueError) as e:
        log(f'auth: no readable {AUTH}: {e}')
        return None, None
    if not isinstance(st, dict):
        return None, None
    tok = st.get('access_token')
    base = (st.get('portal_base_url') or 'https://portal.nousresearch.com').rstrip('/')
    return tok, base


def fetch_account(tok, base):
    headers = {'Authorization': f'Bearer {tok}', 'Accept': 'application/json'}
    req = urllib.request.Request(f'{base}/api/oauth/account', headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode()


def token_expired(st):
    """True si el access_token tiene expires_at en el pasado."""
    exp = st.get('expires_at')
    if not exp:
        return False
    try:
        expires = datetime.fromisoformat(str(exp).replace('Z', '+00:00'))
    except ValueError:
        return False
    return expires <= datetime.now(timezone.utc)


def extract(payload):
    """Normaliza /api/oauth/account al contrato de /tmp/nous_stats.json."""
    sub = payload.get('subscription') or {}
    psa = payload.get('paid_service_access') or {}
    uw = payload.get('usage_window') or {}
    gauges = {g.get('id'): g for g in (uw.get('gauges') or []) if isinstance(g, dict)}
    out = {
        'ok': True,
        'ts': int(time.time()),
        'plan': sub.get('plan'),
        'tier': sub.get('tier'),
        'monthly_charge': sub.get('monthly_charge'),
        'current_period_end': sub.get('current_period_end'),
        'credits_remaining': sub.get('credits_remaining'),
        'rollover_credits': sub.get('rollover_credits'),
        'paused_reason': uw.get('paused_reason'),
        'keep_going_on_credits': UW_BOOL(uw.get('keep_going_on_credits')),
        'auto_top_up': UW_BOOL(uw.get('auto_top_up_enabled')),
        'paid_access': psa.get('allowed'),
        'paid_reason': psa.get('reason'),
        'member_spend_usd': psa.get('member_spend_usd'),
        'member_spend_cap_usd': psa.get('member_spend_cap_usd'),
        'user_email': (payload.get('user') or {}).get('email'),
        'gauges': {},
    }
    for gid, label in (('day', 'hoy'), ('week', 'semana'), ('month', 'mes')):
        g = gauges.get(gid)
        if g:
            out['gauges'][gid] = {
                'label': label,
                'pct': float(g.get('used_bp', 0)) / BP * 100.0,
                'resets_at_ms': g.get('resets_at_ms'),
            }
    return out


def UW_BOOL(v):
    return bool(v) if isinstance(v, bool) else None


def write(payload):
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, OUT)


def load_last():
    try:
        with open(OUT) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main():
    while True:
        auth_file = dict()
        try:
            with open(AUTH) as f:
                auth_file = json.load(f)
        except (OSError, ValueError):
            pass
        tok, base = read_token()
        if not tok:
            write({'ok': False, 'need_relogin': True, 'ts': int(time.time()),
                   'error': 'no access_token en nous_auth.json'})
            log('sin token; esperando Hermes')
            time.sleep(POLL_INTERVAL)
            continue

        expired = token_expired(auth_file)
        try:
            status, body = fetch_account(tok, base)
        except urllib.error.HTTPError as e:
            status, body = e.code, ''
        except Exception as e:
            log(f'fetch falló: {e}')
            last = load_last()
            if last:
                last['ts'] = int(time.time())
                last['stale'] = True
                write(last)
            time.sleep(POLL_INTERVAL)
            continue

        if status == 200:
            try:
                payload = json.loads(body)
            except ValueError:
                log('payload ilegible')
                time.sleep(POLL_INTERVAL)
                continue
            data = extract(payload)
            data['stale'] = False
            write(data)
            g = data['gauges']
            log(f"plan {data['plan']} · día {g.get('day', {}).get('pct', 0):.0f}% · "
                f"semana {g.get('week', {}).get('pct', 0):.0f}% · mes {g.get('month', {}).get('pct', 0):.0f}%")
        elif status in (401, 403) or expired:
            log(f'HTTP {status} / token caducado -> stale (auth la renueva Hermes)')
            last = load_last()
            if last:
                last['ts'] = int(time.time())
                last['stale'] = True
                last['need_relogin'] = status in (401, 403)
                write(last)
        else:
            log(f'HTTP {status} inesperado')
            last = load_last()
            if last:
                last['ts'] = int(time.time())
                last['stale'] = True
                write(last)
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
