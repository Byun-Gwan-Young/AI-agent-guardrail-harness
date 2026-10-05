"""C-18-6 part 0 evidence from the MR retest (batch plan demo-trial-c18-5, DM-74). Read-only: the runner's records,
the proxy log and the stored search responses only. No search, no model call. Model text (narrative, reasoning, cell
values) is not printed: fields are counted, states and gate reasons are shown, URLs are compared.

Per session: termination, steps, escalated_by, first STOP, credits, search calls, HTTP status codes; per step the role,
status, non-null deliverable cells, the v0.3 progress state and which T1 signal moved; every cited URL of the final
report against the stored results (url_key of scenario_judges/DEMO-MR-v1.py); the batch lane's key scan.
For the normal run's STOP (DM-74): the first completion declaration, every claim's judge result, the progress signals
of steps 1-6, and whether any model request followed the STOP observation (what block mode would have refused).

  venv/bin/python -B tools/c18_6_evidence.py --output reports/c18-6/mr-retest-evidence.json
"""
import argparse
import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments import search_tools  # noqa: E402
from tools.c18_4_evidence import mr_judge  # noqa: E402
from tools.rejudge_dialogue import rejudge  # noqa: E402

PLAN_ID = 'demo-trial-c18-5'
LANE_LOG = ROOT / 'runs/demo-batches' / PLAN_ID / 'lane-1-of-1.jsonl'
EXPECTED = ('DEMO-MR-normal-v1', 'DEMO-MR-stall-v1')
DIALOGUE_ENDINGS = {'success', 'escalated', 'max_steps'}
STOP_DECISIONS = {'deadlock', 'termination_failure'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def lane_sessions(lane_log=LANE_LOG):
    rows = [json.loads(line) for line in Path(lane_log).read_text(encoding='utf-8').splitlines() if line.strip()]
    return [r for r in rows if r.get('event') == 'session']


def cells(deliverable):
    return [cell for row in (deliverable or {}).get('rows') or [] for col, cell in row.items() if col != 'product']


def moved(progress):
    """Which T1 signals moved at this step, from the stored progress-v3 metrics (not recomputed)."""
    metrics = progress.get('metrics') or {}
    out = []
    status = (metrics.get('conversation.status_advance') or {}).get('value') or {}
    if status.get('index') is not None and status.get('previous_status') != status.get('status'):
        out.append(f"status {status.get('previous_status')}->{status.get('status')}")
    adopted = (metrics.get('conversation.adopted_items') or {}).get('value') or {}
    if adopted.get('first_seen'):
        out.append(f"adopted +{len(adopted['first_seen'])}")
    issues = (metrics.get('conversation.new_issue_ids') or {}).get('value') or {}
    if issues.get('first_seen'):
        out.append(f"new_issue +{len(issues['first_seen'])}")
    return out


def session_evidence(run_dir, lane_row):
    run_dir = Path(run_dir)
    judge = mr_judge()
    steps, summary, conditions = load(run_dir / 'steps.json'), load(run_dir / 'summary.json'), load(run_dir / 'conditions.json')
    log = load(run_dir / 'session.json')
    records = search_tools.replay_tool_records(run_dir)
    searches = [r for r in records if r['tool'] == 'web_search']
    shown = {judge.url_key(r['url']) for c in searches if not c['is_error']
             for r in c['search']['results'][:c['search']['results_sent']]}
    cap = ((conditions.get('tool_settings') or {}).get('web_search') or {}).get('max_calls_per_session')
    rows = []
    for step in steps:
        report = step.get('observed_final_report') or {}
        obs = step.get('observation') or {}
        progress = obs.get('progress') or {}
        criteria = obs.get('criteria') or {}
        rows.append({'step_id': step['step_id'], 'role': step['agent'], 'step_status': step['step_status'],
                     'status': report.get('status'), 'completion_declared': report.get('completion_declared'),
                     'handoff_to': report.get('handoff_to'), 'cells_non_null': sum(c is not None for c in cells(report.get('deliverable'))),
                     'cells_source_in_results': sum(c is not None and bool(c.get('source_url'))
                                                    and judge.url_key(c['source_url']) in shown
                                                    for c in cells(report.get('deliverable'))),
                     'adopted_items': len(report.get('adopted_items') or []),
                     'open_issue_ids': len(report.get('open_issue_ids') or []),
                     'progress_state': progress.get('state'), 'signals_moved': moved(progress),
                     'criteria_decision': criteria.get('decision'),
                     'search_calls': sum(c['step_id'] == step['step_id'] for c in searches),
                     'llm_turns': step.get('llm_turns'), 'call_error': step.get('call_error'),
                     'failure_reasons': step.get('failure_reasons'), 'vocabulary_violation': step.get('vocabulary_violation'),
                     'claim': ({k: step['completion_claim'][k] for k in ('accepted', 'reasons')}
                               if step.get('completion_claim') else None)})
    final = next((s['observed_final_report'] for s in reversed(steps) if s.get('observed_final_report')), {}) or {}
    cited = []
    for row in (final.get('deliverable') or {}).get('rows') or []:
        for column, cell in row.items():
            if column == 'product':
                continue
            url = None if cell is None else cell.get('source_url')
            cited.append({'cell': f"{row.get('product')}:{column}", 'null': cell is None, 'source_url': url,
                          'in_search_results': (judge.url_key(url) in shown) if url else None})
    stop = next(((o.get('step_id'), o['criteria']) for o in log['observations']
                 if (o.get('criteria') or {}).get('decision') in STOP_DECISIONS), (None, None))
    explanation = (stop[1] or {}).get('explanation') or {}
    turns = sorted(t['turn'] for t in log['turns'])
    status_codes = collections.Counter(t.get('status_code') for t in log['turns'])
    gate = summary.get('gateway_usage') or {}
    lane_summary = lane_row.get('summary') or {}
    return {'session_id': run_dir.name, 'scenario_id': run_dir.name.rsplit('-', 1)[0],
            'termination_reason': summary['termination_reason'],
            'dialogue_ending': summary['termination_reason'] in DIALOGUE_ENDINGS,
            'steps': len(steps), 'escalated_by': summary.get('escalated_by'), 'error': summary.get('error'),
            'first_stop': {'step': stop[0], 'decision': (stop[1] or {}).get('decision'),
                           'template': explanation.get('template_id'), 'text': explanation.get('text'),
                           'declared_step': (stop[1] or {}).get('declared_step')},
            'credits': {'measured': gate.get('value') if gate.get('status') == 'measured' else None,
                        'measured_status': gate.get('status'),
                        'estimated': lane_summary.get('credits_estimated')},
            'search': {'calls': len(searches), 'errors': sum(c['is_error'] for c in searches), 'cap': cap,
                       'cap_reached': cap is not None and len(searches) >= cap},
            'http': {'turns': len(turns), 'status_codes': {str(k): v for k, v in status_codes.items()},
                     'non_200': sum(v for k, v in status_codes.items() if k != 200)},
            'vocabulary_violation_steps': summary.get('vocabulary_violation_steps'),
            'failed_steps': summary.get('failed_steps'),
            'per_step': rows, 'final_report_cells': cited,
            'final_report_cells_in_results': sum(bool(c['in_search_results']) for c in cited),
            'key_scan': {'clean': lane_summary.get('key_scan_clean'),
                         'key_values_checked': lane_summary.get('key_values_checked'),
                         'source': str(LANE_LOG.relative_to(ROOT))},
            '_turns': turns, '_log': log, '_steps': steps}


def normal_stop(ev, run_dir):
    """DM-74: why the normal run's STOP came, and what block mode would have done with it."""
    steps, log = ev.pop('_steps'), ev.pop('_log')
    turns = ev.pop('_turns')
    stop_step = ev['first_stop']['step']
    judged = {r['step_id']: r for r in rejudge(run_dir)['steps']}
    claims = [{'step_id': s['step_id'], 'role': s['agent'], 'accepted': s['completion_claim']['accepted'],
               'reasons': s['completion_claim']['reasons'],
               'judge_missing': (judged[s['step_id']].get('recomputed_claim_gate') or {}).get('missing'),
               'judge_same_as_recorded': judged[s['step_id']].get('claim_gate_same')}
              for s in steps if s.get('completion_claim')]
    stop_turns = next(s['llm_turns'] for s in steps if s['step_id'] == stop_step)
    later = [t for t in turns if t > max(stop_turns)]
    return {'first_declaration_step': next((s['step_id'] for s in steps
                                            if (s.get('observed_final_report') or {}).get('completion_declared')), None),
            'claims': claims,
            'progress_by_step': [{k: r[k] for k in ('step_id', 'role', 'progress_state', 'signals_moved',
                                                     'cells_non_null', 'cells_source_in_results', 'adopted_items', 'status')}
                                 for r in ev['per_step']],
            'stop_step': stop_step, 'stop_step_llm_turns': stop_turns,
            'model_requests_after_stop_observation': len(later),
            'block_mode_reading': ('the STOP is judged from the step-%d observation, which the runner posts after that '
                                   "step's model calls and its completion claim (experiments/dialogue_runner.py); block "
                                   'mode refuses only the next model request (proxy.py blocking_stop). %d request(s) '
                                   'followed, so block mode would not have cut step %d.'
                                   % (stop_step, len(later), stop_step)) if not later else
                                  'model requests followed the STOP observation; block mode would have refused them'}


def evidence(lane_log=LANE_LOG, runs_root=ROOT / 'runs/demo'):
    sessions = lane_sessions(lane_log)
    found = {s['session_id'].rsplit('-', 1)[0]: s for s in sessions if s.get('session_id')}
    missing = [e for e in EXPECTED if e not in found]
    out = {'script': 'tools/c18_6_evidence.py', 'plan_id': PLAN_ID, 'lane_log': str(Path(lane_log).relative_to(ROOT)),
           'expected': list(EXPECTED), 'missing': missing, 'sessions': []}
    for scenario_id in EXPECTED:
        if scenario_id not in found:
            continue
        run_dir = Path(runs_root) / found[scenario_id]['session_id']
        ev = session_evidence(run_dir, found[scenario_id])
        if scenario_id == 'DEMO-MR-normal-v1' and ev['first_stop']['step'] is not None:
            ev['normal_stop'] = normal_stop(ev, run_dir)
        for k in ('_steps', '_log', '_turns'):
            ev.pop(k, None)
        out['sessions'].append(ev)
    out['stop_condition'] = {
        'both_present': not missing,
        'all_dialogue_endings': all(s['dialogue_ending'] for s in out['sessions']) and not missing,
        'any_http_error': any(s['http']['non_200'] for s in out['sessions']),
        'freeze_allowed': not missing and all(s['dialogue_ending'] for s in out['sessions'])}
    out['dm69_3_normal_success'] = any(s['scenario_id'] == 'DEMO-MR-normal-v1' and s['termination_reason'] == 'success'
                                       for s in out['sessions'])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/c18-6/mr-retest-evidence.json')
    args = parser.parse_args()
    result = evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
