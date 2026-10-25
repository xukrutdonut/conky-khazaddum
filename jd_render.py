#!/usr/bin/env python3
"""Renderiza la seccion JDownloader para conky a partir de /tmp/jdownloader_stats.json.
Emitido via ${execpi}: las variables conky (${color}) se parsean."""
import json
import sys
import time

STATS = '/tmp/jdownloader_stats.json'
STALE = 180  # sin datos frescos -> silencio

C_HDR, C_LBL, C_VAL, C_OK, C_ALT, C_WARN = 'color4', 'color1', 'color2', 'color5', 'color5', 'color3'


def fmt_size(b):
    b = float(b or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if b < 1024 or unit == 'GiB':
            return f'{b:.0f}{unit}' if unit in ('B', 'KiB') else f'{b:.1f}{unit}'
        b /= 1024
    return f'{b:.0f}B'


def fmt_speed(b):
    b = float(b or 0)
    if b <= 0:
        return ''
    return f'{b/1024:.0f} KiB/s' if b < 1024 * 1024 else f'{b/1048576:.1f} MiB/s'


def bar(pct, width=10):
    filled = int(round(pct / 100.0 * width))
    return '\u2588' * filled + '\u2591' * (width - filled)


def shorten(name, n=34):
    # los nombres de paquete son larguisimos: coge la parte util
    name = name.split(' -- ')[0] if ' -- ' in name else name
    return name if len(name) <= n else name[:n - 1] + '\u2026'


def main():
    try:
        d = json.load(open(STATS))
    except Exception:
        print('${' + C_LBL + '}JDownloader: sin datos${color}')
        return
    if 'error' in d or time.time() - d.get('ts', 0) > STALE:
        print('${' + C_LBL + '}JDownloader: ${' + C_WARN + '}sin conexion${color}')
        return

    spd = fmt_speed(d.get('speed'))
    out = [f'${{{C_HDR}}}\u2500\u2500 JDOWNLOADER \u2500 .105 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500${{{color}}}']
    head = ('${' + C_LBL + '}Estado: ${color}${' + C_VAL + '}' + d['state'] + '${color}   '
            '${' + C_LBL + '}Vel: ${color}${' + C_VAL + '}' + (spd or '0') + '${color}   '
            '${' + C_LBL + '}Pend: ${color}${' + C_ALT + '}' + str(d['active_count']) + '${color} '
            '${' + C_LBL + '}Hechos: ${color}${' + C_OK + '}' + str(d['finished_count']) + '/${color}${' + C_VAL + '}' + str(d['total_count']) + '${color}')
    out.append(head)

    for p in d.get('active', []):
        sp = fmt_speed(p['speed'])
        state = 'agotado' if 'limit' in (p['status'] or '').lower() else sp
        out.append(('${' + C_LBL + '}\u25b8 ' + shorten(p['name']) + '  ' + format(p['pct'], '.0f') + '%${color}')
                   + ('  ${' + C_VAL + '}' + state + '${color}' if state else ''))
        out.append('${' + C_VAL + '}' + bar(p['pct']) + '${color}  ' + fmt_size(p['loaded']) + '/' + fmt_size(p['total']))

    if not d.get('active'):
        out.append('${' + C_LBL + '}Sin descargas activas${color}')

    sys.stdout.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
