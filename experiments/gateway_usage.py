"""Gateway usage around one demo session: credits_measured (DM-58 ③, C-18-1).

A scenario-v2 run reads the gateway's /credits/ twice with the key it already holds: once after the proxy session is
open and before the first model request, once after the session has ended. It reads the field the PM probe reads
(tools/probe_gateway.py CREDIT_USED_FIELDS; the probe is not imported here). The difference is the session's credits
only when nothing else used the same key between the two readings (another session in parallel, a probe, another
tool), so the record says so and keeps both reading times. A failed reading never stops or fails the session: the value
is unmeasured. The key is sent in the Authorization header only and never written anywhere.
"""
from datetime import datetime, timezone

import httpx

USAGE_VERSION = 'gateway-usage-v1'
CREDITS_PATH = '/credits/'
# The same fields, in the same order, as tools/probe_gateway.py CREDIT_USED_FIELDS (C-11; a test keeps them equal).
CREDIT_USED_FIELDS = (('monthly_allocated', 'used'), ('total', 'used'))
TIMEOUT_SECONDS = 30


def now():
    return datetime.now(timezone.utc).isoformat()


def used_value(body):
    """(value, 'parent.used') of the first CREDIT_USED_FIELDS entry present, else (None, None)."""
    for parent, field in CREDIT_USED_FIELDS:
        section = body.get(parent) if isinstance(body, dict) else None
        value = section.get(field) if isinstance(section, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, parent + '.' + field
    return None, None


async def reading(upstream, api_key):
    """One /credits/ reading: {read_at, http_status, used, field} or {read_at, error}. Never raises."""
    read_at = now()
    base_url = (upstream or {}).get('base_url')
    if not base_url:
        return {'read_at': read_at, 'error': 'no upstream base_url in the proxy session meta'}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(base_url + CREDITS_PATH, headers={'Authorization': 'Bearer ' + api_key})
        body = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        return {'read_at': read_at, 'error': type(exc).__name__}
    used, field = used_value(body)
    result = {'read_at': read_at, 'http_status': response.status_code, 'used': used, 'field': field}
    if used is None:
        result['error'] = ('HTTP ' + str(response.status_code) if response.status_code != 200 else
                           'none of ' + ', '.join(p + '.' + f for p, f in CREDIT_USED_FIELDS) + ' in the body')
    return result


def record(before, after):
    """credits_measured of one session from its two readings (either may be None when it was never taken)."""
    result = {'usage_version': USAGE_VERSION, 'before': before, 'after': after,
              'exact_only_if_alone': True,
              'note': 'after minus before; it includes any other use of the same key between the two read_at times '
                      '(parallel sessions, probes, other tools). Compare those times with other sessions.'}
    if before is None or after is None or before.get('used') is None or after.get('used') is None:
        return {**result, 'status': 'unmeasured', 'value': None,
                'reason': 'a reading is missing or failed' if before is not None else 'no reading was taken'}
    if before['field'] != after['field']:
        return {**result, 'status': 'unmeasured', 'value': None,
                'reason': 'the readings used different fields: ' + before['field'] + ', ' + after['field']}
    return {**result, 'status': 'measured', 'value': round(after['used'] - before['used'], 10),
            'field': before['field']}
