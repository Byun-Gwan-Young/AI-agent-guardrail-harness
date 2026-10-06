"""C-19-2 part 1: independent recompute of class, first STOP, credits and if-stopped ratio for chosen sessions, from
the raw run files (summary.json, steps.json llm_turns, session.json turns usage and observations criteria) instead of
the record/ files the aggregate reads. Only numbers and decision fields are read; no model text."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
agg = json.loads((ROOT / 'reports/c19/aggregate-main.json').read_text())
rows = {r['session_id']: r for r in agg['session_rows']}
PRICE = {'prompt': 150, 'cached': 30, 'completion': 500}  # tools/gateway_prices.py glm-5.3-flash


def klass(reason):
    return {'success': 'success', 'escalated': 'escalated', 'max_steps': 'stalled', 'guardrail_stop': 'stalled'}.get(reason, 'other')


out = []
for prefix in sys.argv[1:]:
    sid = next(k for k in rows if k.split('-v1-')[1].startswith(prefix))
    folder = ROOT / 'runs/demo' / sid
    summ = json.loads((folder / 'summary.json').read_text())
    steps = json.loads((folder / 'steps.json').read_text())
    sess = json.loads((folder / 'session.json').read_text())
    turn_by_no = {t['turn']: t for t in sess['turns']}
    first_stop = next((o['step_id'] for o in sess['observations']
                       if (o.get('criteria') or {}).get('decision') in ('deadlock', 'termination_failure')), None)
    tmpl = None
    tok_step, cred_step = {}, {}
    for st in steps:
        tk = cr = 0
        for n in st['llm_turns']:
            t = turn_by_no.get(n)
            if not t or t.get('tokens') is None:
                continue
            u = (t.get('response_body') or {}).get('usage') or {}
            cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
            p, c = t.get('prompt_tokens') or 0, t.get('completion_tokens') or 0
            tk += p + c
            cr += ((p - cached) * PRICE['prompt'] + cached * PRICE['cached'] + c * PRICE['completion']) / 1e6
        tok_step[st['step_id']], cred_step[st['step_id']] = tk, cr
    total_t, total_c = sum(tok_step.values()), sum(cred_step.values())
    after_t = sum(v for k, v in tok_step.items() if first_stop and k > first_stop)
    unlinked = len(sess['turns']) - sum(len(st['llm_turns']) for st in steps)
    r = rows[sid]
    mine = {'class': klass(summ['termination_reason']), 'steps': summ['steps'], 'first_stop': first_stop,
            'credits_estimated': round(total_c, 5), 'tokens': total_t,
            'if_stopped_ratio': round(after_t / total_t, 4) if first_stop else None}
    theirs = {'class': r['class'], 'steps': r['steps'], 'first_stop': r['first_stop_step'],
              'credits_estimated': r['credits_estimated'], 'tokens': r['tokens'],
              'if_stopped_ratio': (r['if_stopped'] or {}).get('token_ratio')}
    out.append({'session': sid, 'type': r['task_type'], 'mode': r['mode'], 'recomputed': mine, 'aggregate': theirs,
                'credits_measured_aggregate': r['credits_measured'], 'turns_not_in_a_step': unlinked,
                'match': {k: (abs(mine[k] - theirs[k]) < 1e-3 if isinstance(mine[k], float) and theirs[k] is not None
                              else mine[k] == theirs[k]) for k in mine}})
print(json.dumps(out, ensure_ascii=False, indent=1))
