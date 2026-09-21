"""Side-by-side offline comparison of two analysed sessions (C-11). Read-only.

Each column is computed from logs/<session>.json and runs/<session>/ through analyze_session.analyse.
Nothing is estimated. The comparison does not attribute differences to any cause: sessions may differ
in provider, runner protocol and max_tokens at the same time, and seed is unverified.

Definitions (mechanical):
- reread_in_context: a read_file call whose path already has a read_file result (tool message) in the
  request that issued the call. `identical` when the new result text equals the earlier one.
- budget_exhausted_without_edit: a step of a role with writable paths, gate not yet successful at step
  start, where every tool-capable call (max_llm_calls_per_step - 1) returned tool calls and none was an edit.
- credits: optional user-recorded monthly_allocated.used before/after; compared with
  prompt x $0.15 + completion x $0.60 per 1M tokens x 1000 (cached prompt tokens reported separately).
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from analyze_session import EDIT_TOOLS, analyse, load
from scenario_schema import load_scenario

PRICE_PER_M = {'prompt': 0.15, 'completion': 0.60}
LEGACY_COMPLETION_LIMIT = 1200


def read_results(messages):
    """path -> list of read_file result texts present in one request's messages."""
    paths, found = {}, {}
    for m in messages:
        for call in m.get('tool_calls') or []:
            if call['function']['name'] == 'read_file':
                try:
                    paths[call['id']] = json.loads(call['function']['arguments']).get('path')
                except ValueError:
                    pass
        if m.get('role') == 'tool' and m.get('tool_call_id') in paths:
            found.setdefault(paths[m['tool_call_id']], []).append(m.get('content'))
    return found


def result_text(messages, call_id):
    """Tool result for call_id: a tool message, or a FunctionExecutionResult inside a final call's records."""
    for m in messages:
        if m.get('role') == 'tool' and m.get('tool_call_id') == call_id:
            return m.get('content')
        if m.get('role') == 'user' and isinstance(m.get('content'), str) and call_id in m['content']:
            try:
                records = json.loads(m['content']).get('observed_records') or []
            except (ValueError, AttributeError):
                continue
            for record in records:
                for item in record.get('content') or [] if isinstance(record, dict) else []:
                    if isinstance(item, dict) and item.get('call_id') == call_id:
                        return item.get('content')
    return None


def rereads(steps, turns):
    rows = []
    for step in steps:
        for position, n in enumerate(step['llm_turns']):
            message = ((turns[n].get('response_body') or {}).get('choices') or [{}])[0].get('message') or {}
            earlier = read_results(turns[n]['request_body']['messages'])
            for call in message.get('tool_calls') or []:
                if call['function']['name'] != 'read_file':
                    continue
                try:
                    path = json.loads(call['function']['arguments']).get('path')
                except ValueError:
                    continue
                if path not in earlier:
                    continue
                later = step['llm_turns'][position + 1] if position + 1 < len(step['llm_turns']) else None
                new = result_text(turns[later]['request_body']['messages'], call['id']) if later else None
                rows.append({'step_id': step['step_id'], 'agent': step['agent'], 'turn': n, 'path': path,
                             'identical': None if new is None else new == earlier[path][-1]})
    return rows


def column(session_id, credits):
    a = analyse(session_id)
    log = load(ROOT / 'logs' / f'{session_id}.json')
    run = ROOT / 'runs' / session_id
    steps = load(run / 'steps.json')
    scenario = load_scenario(run / 'scenario.yaml')
    limit = scenario.termination.max_llm_calls_per_step
    writable = {x.id: x.writable_paths for x in scenario.agents}
    turns = {t['turn']: t for t in log['turns']}
    rows = a['steps']
    usage = [(t.get('response_body') or {}).get('usage') or {} for t in log['turns'] if t.get('status_code') == 200]
    cached = [(u.get('prompt_tokens_details') or {}).get('cached_tokens') for u in usage]
    stagnant_runs, current = [], []
    for r in rows:
        if r['progress_state'] == 'stagnant':
            current.append(r['step_id'])
        elif current:
            stagnant_runs.append(current)
            current = []
    if current:
        stagnant_runs.append(current)
    success_before = {s['step_id']: prev['acceptance']['gate'].get('machine_success') if prev else False
                      for prev, s in zip([None] + steps[:-1], steps)}
    exhausted = [r['step_id'] for r, s in zip(rows, steps)
                 if writable[r['agent']] and not success_before[r['step_id']]
                 and sum(bool(((turns[n].get('response_body') or {}).get('choices') or [{}])[0]
                              .get('message', {}).get('tool_calls')) for n in s['llm_turns']) >= limit - 1
                 and not r['edit_attempts']]
    completions = [(t['turn'], t.get('completion_tokens')) for t in log['turns'] if t.get('completion_tokens') is not None]
    tok = a['tokens']
    credit = None
    if credits:
        used = round(credits[1] - credits[0], 10)
        by_price = (tok['known_prompt'] * PRICE_PER_M['prompt'] + tok['known_completion'] * PRICE_PER_M['completion']) / 1e6 * 1000
        credit = {'recorded_before': credits[0], 'recorded_after': credits[1], 'used': used,
                  'price_assumption_per_1M_usd': PRICE_PER_M, 'credits_by_price_x1000_all_prompt_full_price': round(by_price, 10),
                  'difference': round(used - by_price, 10) if tok['total_status'] == 'measured' else None,
                  'credits_per_1k_tokens': round(used / tok['known_total'] * 1000, 10) if tok['known_total'] else None,
                  'basis': 'user-recorded /credits/ monthly_allocated.used; no other use in between is a user confirmation item'}
    return {
        'session_id': session_id, 'scenario_id': a['scenario']['id'],
        'provider': (a['meta']['upstream'] or {}).get('base_url_host'), 'model': a['meta']['model'],
        'runner_protocol': a['conditions']['runner_protocol'], 'max_tokens': a['meta']['max_tokens'],
        'temperature': a['conditions']['temperature'], 'seed': a['conditions']['seed_support'],
        'termination_reason': a['termination']['reason'], 'steps_reached': a['termination']['steps_reached'],
        'tests_before': a['judgement']['tests_before'], 'tests_after': a['judgement']['tests_after'],
        'tokens': {k: tok[k] for k in ('known_prompt', 'known_completion', 'known_total', 'usage_missing_turns',
                                       'total', 'total_status')},
        'cached_prompt_tokens': None if all(c is None for c in cached) else sum(c or 0 for c in cached),
        'cached_prompt_tokens_status': 'not reported by provider' if all(c is None for c in cached) else 'reported',
        'llm_calls': len(log['turns']),
        'first_stop_step': a['first_stop_step'],
        'stagnant_runs': stagnant_runs,
        'first_test_change_step': next((r['step_id'] for r in rows if r['tests_change_in_step']), None),
        'rereads_in_context': rereads(steps, turns),
        'tool_calls_per_step': {r['step_id']: len(r['tool_calls']) for r in rows},
        'steps_without_tool_calls': [r['step_id'] for r in rows if not r['tool_calls']],
        'edit_attempts_outside_writable_paths': [{'step_id': r['step_id'], 'agent': r['agent'], **c}
                                                 for r in rows for c in r['edit_attempts_outside_writable_paths']],
        'budget_exhausted_without_edit_steps': exhausted,
        'http_errors': a['g0_7']['http_errors'],
        'tool_use_failed': sum(e['code'] == 'tool_use_failed' for e in a['g0_7']['http_errors']),
        'finish_reason_counts': a['g0_7']['finish_reason_counts'],
        'completion_over_1200': [{'turn': n, 'completion': c} for n, c in completions if c > LEGACY_COMPLETION_LIMIT],
        'edit_calls_200': a['g0_7']['edit_calls_200'],
        'reasoning_effort_requested': sorted({t['request_body'].get('reasoning_effort') for t in log['turns']}, key=str),
        'harness_facts_in_system_message': {agent: {'writable_files': 'Files this role can write:' in text,
                                                    'call_limit': 'model calls for this role' in text}
                                            for agent, text in {s['agent']: turns[s['llm_turns'][0]]['request_body']
                                                                ['messages'][0]['content'] for s in steps}.items()},
        'per_call_budget_fact_in_non_final_calls': [sum('call(s) remain after this one' in json.dumps(
            turns[n]['request_body']['messages'], ensure_ascii=False) for s in steps for n in s['llm_turns']
            if 'response_format' not in turns[n]['request_body']),
            sum('response_format' not in turns[n]['request_body'] for s in steps for n in s['llm_turns'])],
        'g0_12_extra_progress_counts': sum(x['extra_counts'] for x in a['g0_12_shared_artifact_progress']),
        'credits': credit}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('baseline')
    parser.add_argument('candidate')
    parser.add_argument('--candidate-credits', type=float, nargs=2, metavar=('BEFORE', 'AFTER'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'comparison_version': 'session-comparison-v0.1',
              'caveats': ['one session each; no causal attribution',
                          'provider, runner protocol and max_tokens may differ at once (see each column)',
                          'seed unverified: temperature 0.0 does not establish reproducibility'],
              'baseline': column(args.baseline, None),
              'candidate': column(args.candidate, args.candidate_credits)}
    report['changed_conditions'] = [k for k in ('provider', 'model', 'runner_protocol', 'max_tokens', 'temperature',
                                                'scenario_id') if report['baseline'][k] != report['candidate'][k]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
