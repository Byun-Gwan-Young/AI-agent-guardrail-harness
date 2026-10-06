"""Independent re-derivation of the exclusion codes (DM-78, DM-79, DM-80, DM-81) from raw signals, written apart from
tools/demo_exclusions.py. Reads only: conditions.json, summary.json (termination, error first 120 chars), search
records status codes, and per failing proxy turn the status / upstream_ms / whether the body is empty. No model text."""
import json, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLANS = {'demo-main-v1', 'demo-main-v1-lr2', 'demo-main-v1-mr2'}
listed = json.loads((ROOT / 'reports/c18-8/exclusions.json').read_text())['sessions']
rows, mismatches = [], []
for folder in sorted((ROOT / 'runs/demo').iterdir()):
    cp = folder / 'conditions.json'
    if not cp.is_file():
        continue
    c = json.loads(cp.read_text())
    b = c.get('batch') or {}
    if b.get('plan_id') not in PLANS:
        continue
    s = json.loads((folder / 'summary.json').read_text())
    sid = folder.name
    end = s.get('termination_reason')
    srch = folder / 'search/records.jsonl'
    statuses = Counter()
    if srch.is_file():
        for line in srch.read_text().splitlines():
            if line.strip():
                statuses[json.loads(line).get('http_status')] += 1
    fail = None
    if end == 'runner_error':
        log = ROOT / 'logs/demo' / (sid + '.json')
        src = log if log.is_file() else folder / 'session.json'
        turns = json.loads(src.read_text()).get('turns') or []
        bad = [t for t in turns if t.get('status_code') not in (200, 403)]
        t = bad[-1] if bad else None
        fail = None if t is None else {'status': t.get('status_code'), 'wait_s': round((t.get('upstream_ms') or 0) / 1000),
                                       'empty_body': t.get('response_body') == {}, 'turn': t.get('turn'),
                                       'proxy_made': 'Upstream connection failed' in (s.get('error') or '')}
    # rules, first match, written from the guideline text
    if b['plan_id'] == 'demo-main-v1' and c['scenario']['scenario_id'].startswith('DEMO-LR-'):
        code = 'env_search_unavailable'
    elif statuses.get(401) or statuses.get(403):
        code = 'env_search_key_invalid'
    elif end == 'runner_error' and b.get('rerun_of'):
        code = 'incomplete_after_retry'
    elif end == 'runner_error' and fail and fail['status'] == 502 and fail['proxy_made'] and fail['wait_s'] >= 120:
        code = 'env_upstream_timeout'
    elif end == 'runner_error' and fail and fail['status'] == 502 and not fail['proxy_made']:
        code = 'env_upstream_502'
    elif end == 'user_interrupted':
        code = 'run_interrupted'
    elif end == 'runner_error':
        code = 'UNRESOLVED'
    else:
        code = None
    row = {'session': sid, 'plan': b['plan_id'], 'item': b.get('item'), 'end': end, 'steps': s.get('steps'),
           'rerun_of': (b.get('rerun_of') or '')[-32:][:8] or None, 'account': c.get('account_label'),
           'search_status': dict(statuses), 'fail': fail, 'code': code, 'listed': listed[sid]['excluded']}
    rows.append(row)
    if code != listed[sid]['excluded']:
        mismatches.append(row)
excluded = [r for r in rows if r['code']]
print(json.dumps({'sessions': len(rows), 'excluded': len(excluded), 'by_code': dict(Counter(r['code'] for r in excluded)),
                  'mismatches_vs_list': mismatches}, ensure_ascii=False, indent=1))
for r in excluded:
    print(r['code'], r['item'], r['session'][-32:][:8], r['end'], r['steps'], 'acct', r['account'],
          'rerun_of', r['rerun_of'], 'fail', r['fail'], 'search', r['search_status'] or '-')
Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
