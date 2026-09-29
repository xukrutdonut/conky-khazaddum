#!/usr/bin/env python3
"""
Daemon: monitoriza el estado real de Ollama Cloud.
Escribe /tmp/ollama_cloud_stats.json atomicamente cada 60s.

Chequeos reales:
  1. Servidor Ollama local responde? (/api/tags) + latencia
  2. Modelos cloud disponibles (remote_host presente)
  3. Modelos cargados en memoria (/api/ps)
  4. Latencia real del cloud: genera 1 token con el primer modelo cloud
  5. Score de salud 0-100 combinando todo
"""
import json, os, time, urllib.request, urllib.error, socket
from datetime import datetime

STATS_FILE   = '/tmp/ollama_cloud_stats.json'
OLLAMA_URL   = 'http://localhost:11434'
POLL_INTERVAL = 60
CLOUD_HOST   = 'ollama.com'
CLOUD_PORT   = 443


def timed_request(url, timeout=10, data=None):
    t0 = time.monotonic()
    try:
        if data is not None:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode(),
                headers={'Content-Type': 'application/json'},
            )
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        elapsed = (time.monotonic() - t0) * 1000
        body = json.loads(resp.read().decode())
        return True, int(elapsed), body
    except Exception:
        elapsed = (time.monotonic() - t0) * 1000
        return False, int(elapsed), None


def check_server():
    return timed_request(f'{OLLAMA_URL}/api/tags', timeout=5)


def get_cloud_models(tags_data):
    models = []
    for m in tags_data.get('models', []):
        if m.get('remote_host'):
            models.append({
                'name': m.get('name'),
                'remote_model': m.get('remote_model'),
                'remote_host': m.get('remote_host'),
                'context_length': m.get('details', {}).get('context_length', 0),
            })
    return models


def get_loaded_models():
    ok, _, data = timed_request(f'{OLLAMA_URL}/api/ps', timeout=5)
    if ok and data:
        return [
            {
                'name': m.get('name'),
                'size': m.get('size', 0),
                'expires': m.get('expires_at', ''),
            }
            for m in data.get('models', [])
        ]
    return []


def check_cloud_latency(model_name, timeout=20):
    """Genera 1 token minimo para medir latencia real del cloud."""
    data = {
        'model': model_name,
        'prompt': '1',
        'stream': False,
        'options': {'num_predict': 1, 'temperature': 0},
    }
    ok, lat, resp = timed_request(f'{OLLAMA_URL}/api/generate', timeout=timeout, data=data)
    if ok and resp:
        eval_count = resp.get('eval_count', 0)
        eval_duration = resp.get('eval_duration', 0)
        total_duration = resp.get('total_duration', 0)
        # tokens/s del cloud
        if eval_duration > 0 and eval_count > 0:
            tps = eval_count / (eval_duration / 1e9)
        else:
            tps = 0
        return ok, lat, {'tps': tps, 'total_ms': int(total_duration / 1e6) if total_duration else 0}
    return False, lat, None


def check_cloud_reachable():
    """TCP connect a ollama.com:443 para verificar reachability sin generar tokens."""
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((CLOUD_HOST, CLOUD_PORT), timeout=5)
        sock.close()
        return True, int((time.monotonic() - t0) * 1000)
    except Exception:
        return False, int((time.monotonic() - t0) * 1000)


def compute_health(server_up, server_lat, cloud_models, cloud_ok, cloud_lat, cloud_reachable):
    score = 0
    if server_up:
        score += 25
        if server_lat < 50:
            score += 10
        elif server_lat < 200:
            score += 5
    if cloud_models:
        score += 15
    if cloud_reachable:
        score += 15
    if cloud_ok:
        score += 25
        if cloud_lat < 3000:
            score += 10
        elif cloud_lat < 8000:
            score += 5
    return min(score, 100)


def collect():
    stats = {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'server_up': False,
        'server_latency_ms': 0,
        'cloud_models': [],
        'cloud_model_count': 0,
        'loaded_models': [],
        'loaded_count': 0,
        'cloud_ok': False,
        'cloud_latency_ms': 0,
        'cloud_tps': 0,
        'cloud_reachable': False,
        'cloud_tcp_ms': 0,
        'health': 0,
        'status': 'CAIDO',
        'active_model': '',
    }

    server_ok, server_lat, tags_data = check_server()
    stats['server_up'] = server_ok
    stats['server_latency_ms'] = server_lat

    if server_ok and tags_data:
        cloud_models = get_cloud_models(tags_data)
        stats['cloud_models'] = [m['name'] for m in cloud_models]
        stats['cloud_model_count'] = len(cloud_models)

        loaded = get_loaded_models()
        stats['loaded_models'] = [m['name'] for m in loaded]
        stats['loaded_count'] = len(loaded)

        # TCP reachability al cloud (sin consumir tokens)
        reachable, tcp_ms = check_cloud_reachable()
        stats['cloud_reachable'] = reachable
        stats['cloud_tcp_ms'] = tcp_ms

        # Latencia real: generar 1 token con el primer modelo cloud
        if cloud_models:
            model_name = cloud_models[0]['name']
            stats['active_model'] = model_name
            cloud_ok, cloud_lat, cloud_info = check_cloud_latency(model_name, timeout=20)
            stats['cloud_ok'] = cloud_ok
            stats['cloud_latency_ms'] = cloud_lat
            if cloud_info:
                stats['cloud_tps'] = round(cloud_info.get('tps', 0), 1)

    health = compute_health(
        stats['server_up'], stats['server_latency_ms'],
        stats['cloud_models'], stats['cloud_ok'],
        stats['cloud_latency_ms'], stats['cloud_reachable'],
    )
    stats['health'] = health
    if health >= 80:
        stats['status'] = 'OK'
    elif health >= 40:
        stats['status'] = 'DEGRADADO'
    else:
        stats['status'] = 'CAIDO'

    return stats


def main():
    while True:
        try:
            stats = collect()
            tmp = STATS_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(stats, f, indent=2)
            os.replace(tmp, STATS_FILE)
        except Exception as e:
            # No morir nunca, el watchdog depende de esto
            pass
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()