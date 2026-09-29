"""C-16 part 3: per-step log values for the deadlock-v0.3 design, and where its proposed T3 signals would apply.

Prediction only. This is not the v0.3 implementation (C-17) and changes no judgement. Reads the proxy logs
of the three existing sessions and prints no model text (no narrative, no reasoning). Output:
docs/design/demo-v03-inputs.json.

Proposed T3 conditions, parameters fixed from structure before looking at these values (demo-deadlock-v0.3.md):
  (a) global revert : the combined hash of all monitored files equals one seen at an earlier step of the session
  (b) test plateau  : the pass count has not exceeded the session's previous maximum for more than K global steps
A step whose only progress events are artifact.files_changed would not count as progress under (a) or (b).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = {'G0-8': 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e',
            'A-1-v3': 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73',
            'A-1-v4': 'A-1-v4-e174aafe805b4f59bb62d7c95716b8b7'}
ROLES = 3
K = 2 * ROLES  # two full role laps, from the role count only
CONSECUTIVE = 3  # deadlock-v0.2 consecutive_steps, unchanged in v0.3


def state_hash(file_hashes):
    if file_hashes is None:
        return None
    return hashlib.sha256(json.dumps(file_hashes, sort_keys=True).encode()).hexdigest()[:12]


def rows_for(session_id):
    log = json.loads((ROOT / 'logs' / (session_id + '.json')).read_text(encoding='utf-8'))
    rows, seen_states, seen_ids, previous = [], {}, set(), None
    best, best_step = None, None
    for o in log['observations']:
        step, artifact = o['step_id'], o.get('artifact') or {}
        conv, progress = o.get('conversation') or {}, o.get('progress') or {}
        h = state_hash(artifact.get('file_hashes'))
        passed = artifact.get('test_pass_count')
        if passed is not None and (best is None or passed > best):
            best, best_step = passed, step
        ids = conv.get('open_issue_ids')
        new_ids = sorted(set(ids) - seen_ids) if ids is not None else None
        events = progress.get('events') or []
        kinds = sorted({e['metric'] for e in events if e.get('kind') not in ('oscillation', 'reopen', 'revert')})
        only_files = progress.get('state') == 'progress' and kinds == ['artifact.files_changed']
        # Changed since the previous global step, back to a state already seen earlier in the session.
        revert = h is not None and h != previous and h in seen_states
        plateau = best_step is not None and step - best_step > K
        rows.append({'step': step, 'agent': o.get('agent_id'), 'v02_state': progress.get('state'),
                     'v02_decision': (o.get('criteria') or {}).get('decision'),
                     'progress_metrics': kinds, 'tests': passed, 'tests_total': artifact.get('test_total_count'),
                     'state_hash': h, 'state_first_seen_step': seen_states.get(h),
                     'open_issue_count': len(ids) if ids is not None else None,
                     'first_seen_issue_ids': new_ids, 'steps_since_test_max': None if best_step is None else step - best_step,
                     'only_file_change_progress': only_files,
                     't3a_global_revert': only_files and revert, 't3b_plateau': only_files and plateau})
        if h is not None:
            seen_states.setdefault(h, step)
        previous = h
        if ids is not None:
            seen_ids |= set(ids)
    return log['meta'].get('criteria_version'), rows


def flipped_runs(rows):
    """Longest run of non-progress steps if the flagged steps stopped counting as progress (prediction)."""
    best = run = 0
    start = first = None
    for r in rows:
        nonprogress = r['v02_state'] in ('stagnant', 'oscillating') or r['t3a_global_revert'] or r['t3b_plateau']
        run = run + 1 if nonprogress else 0
        if run == 1:
            start = r['step']
        if run >= CONSECUTIVE and first is None:
            first = r['step']
        best = max(best, run)
    return {'longest_nonprogress_run': best, 'first_step_reaching_consecutive': first}


def main():
    report = {'script': 'docs/design/demo_v03_inputs.py', 'status': 'prediction, not v0.3 implementation',
              'parameters': {'K_plateau_steps': K, 'consecutive_steps': CONSECUTIVE, 'roles': ROLES}, 'sessions': {}}
    for label, session_id in SESSIONS.items():
        criteria, rows = rows_for(session_id)
        v02_first = next((r['step'] for r in rows if r['v02_decision'] in ('deadlock', 'termination_failure')), None)
        report['sessions'][label] = {
            'session_id': session_id, 'criteria_version': criteria, 'steps': len(rows),
            'v02_first_stop_step': v02_first,
            'only_file_change_progress_steps': [r['step'] for r in rows if r['only_file_change_progress']],
            't3a_steps': [r['step'] for r in rows if r['t3a_global_revert']],
            't3b_steps': [r['step'] for r in rows if r['t3b_plateau']],
            'prediction': flipped_runs(rows), 'rows': rows}
    out = ROOT / 'docs/design/demo-v03-inputs.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: {x: v[x] for x in v if x != 'rows'} for k, v in report['sessions'].items()},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
