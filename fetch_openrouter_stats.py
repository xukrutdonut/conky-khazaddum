#!/usr/bin/env python3
"""
Daemon: monitoriza el consumo de OpenRouter (workspace default).
Escribe /tmp/openrouter_stats.json atomicamente cada POLL_INTERVAL segundos.

Fuentes (API de OpenRouter):
  GET  /api/v1/key              -> usage_daily/weekly/monthly (USD), limit (key normal)
  GET  /api/v1/credits          -> total_credits, total_usage (saldo de cuenta)
  POST /api/v1/analytics/query  -> nº peticiones + gasto por dia/modelo (MANAGEMENT KEY)

Claves en ~/.hermes/.env:
  OPENROUTER_MGMT_KEY  (management key: permite analytics -> nº de peticiones)
  OPENROUTER_API_KEY   (key normal: gasto en /key; fallback)
"""
import json, os, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

STATS_FILE    = '/tmp/openrouter_stats.json'
ENV_FILE      = '/home/arkantu/.hermes/.env'
POLL_INTERVAL = 60

KEY_API     = 'https://openrouter.ai/api/v1/key'
CREDITS_API = 'https://openrouter.ai/api/v1/credits'
QUERY_API   = 'https://openrouter.ai/api/v1/analytics/query'


def read_env(name):
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith(name + '='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get(name, '')


def get_keys():
    mgmt = read_env('OPENROUTER_MGMT_KEY')
    std = read_env('OPENROUTER_API_KEY') or mgmt
    return mgmt, std


def api(url, key, payload=None, timeout=15):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
               'User-Agent': 'conky-openrouter/1.0'}
    if data:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def num(v, cast=float):
    try:
        return cast(v)
    except Exception:
        return 0


def query_daily(key, days):
    """Peticiones + gasto por dia (y por modelo) en los ultimos <days> dias."""
    end = datetime.now(timezone.utc)
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    payload = {
        'dimensions': ['model'],
        'granularity': 'day',
        'metrics': ['request_count', 'total_usage', 'tokens_total'],
        'time_range': {'start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'end': end.strftime('%Y-%m-%dT%H:%M:%SZ')},
    }
    rows = api(QUERY_API, key, payload).get('data', {}).get('data', [])
    by_date = {}
    by_model = {}
    for r in rows:
        d = r.get('date__day') or ''
        req = num(r.get('request_count'), int)
        usd = num(r.get('total_usage'))
        tok = num(r.get('tokens_total'), int)
        agg = by_date.setdefault(d, {'requests': 0, 'usage': 0.0, 'tokens': 0})
        agg['requests'] += req
        agg['usage'] += usd
        agg['tokens'] += tok
        m = r.get('model') or '?'
        bm = by_model.setdefault(m, {'requests': 0, 'usage': 0.0})
        bm['requests'] += req
        bm['usage'] += usd
    return by_date, by_model


def collect():
    mgmt_key, key = get_keys()
    stats = {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'ok': False,
        'has_mgmt_key': bool(mgmt_key),
        'usage_daily': None, 'usage_weekly': None, 'usage_monthly': None,
        'limit': None, 'limit_remaining': None, 'limit_reset': None,
        'free_used': 0, 'free_limit': 0,
        'total_credits': None, 'total_usage': None, 'balance': None,
        'requests_today': None, 'requests_week': None, 'requests_month': None,
        'tokens_week': None, 'usage_week': None,
        'analytics_ok': False, 'by_model_week': [],
    }
    if not key:
        return stats

    # 1) key info (key normal del workspace)
    try:
        d = api(KEY_API, key).get('data', {})
        stats['ok'] = True
        stats['usage_daily'] = d.get('usage_daily')
        stats['usage_weekly'] = d.get('usage_weekly')
        stats['usage_monthly'] = d.get('usage_monthly')
        stats['limit'] = d.get('limit')
        stats['limit_remaining'] = d.get('limit_remaining')
        stats['limit_reset'] = d.get('limit_reset')
        fm = d.get('free_model_daily_requests') or {}
        stats['free_used'] = fm.get('used', 0)
        stats['free_limit'] = fm.get('limit', 0)
    except Exception as e:
        stats['error_key'] = str(e)

    # 2) saldo de la cuenta
    try:
        d = api(CREDITS_API, key).get('data', {})
        stats['total_credits'] = d.get('total_credits')
        stats['total_usage'] = d.get('total_usage')
        if stats['total_credits'] is not None and stats['total_usage'] is not None:
            stats['balance'] = round(stats['total_credits'] - stats['total_usage'], 4)
    except Exception as e:
        stats['error_credits'] = str(e)

    # 3) analytics: peticiones/gasto (management key)
    if mgmt_key:
        try:
            by_date, by_model = query_daily(mgmt_key, 7)
            today = datetime.now(timezone.utc).date().isoformat()
            stats['requests_today'] = by_date.get(today, {}).get('requests', 0)
            stats['requests_week'] = sum(v['requests'] for v in by_date.values())
            stats['usage_week'] = round(sum(v['usage'] for v in by_date.values()), 4)
            stats['tokens_week'] = sum(v['tokens'] for v in by_date.values())
            stats['analytics_ok'] = True
            stats['by_model_week'] = sorted(
                [{'model': k, **v} for k, v in by_model.items()],
                key=lambda x: -x['requests'])[:5]
            # mes
            bm_date, _ = query_daily(mgmt_key, 30)
            stats['requests_month'] = sum(v['requests'] for v in bm_date.values())
        except urllib.error.HTTPError as e:
            stats['error_analytics'] = f'HTTP {e.code}'
        except Exception as e:
            stats['error_analytics'] = str(e)

    return stats


def main():
    while True:
        try:
            stats = collect()
            tmp = STATS_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(stats, f, indent=2)
            os.replace(tmp, STATS_FILE)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
