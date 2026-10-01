"""Offline post-run analysis of one scenario session (guideline 7-3, C-8). Read-only.

Inputs: the proxy log logs/<session>.json and the runner folder runs/<session>/.
Every number is computed from those files; nothing is estimated. Values that cannot be
derived stay null with a reason. Writes one analysis JSON and one session manifest.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.step_execution import PROTOCOL_V8, PROTOCOL_V9, PROTOCOL_V10
from scenario_schema import load_scenario

STOP_DECISIONS = ('deadlock', 'termination_failure')
EDIT_TOOLS = ('write_file', 'replace_in_file')
SECRET_PATTERNS = {'groq_key': re.compile(r'gsk_[A-Za-z0-9]{8,}'),
                   'bearer_value': re.compile(r'Bearer\s+[A-Za-z0-9._\-]{8,}'),
                   'openai_style_key': re.compile(r'\bsk-[A-Za-z0-9]{16,}'),
                   'authorization_field': re.compile(r'"authorization"\s*:\s*"[^"]+', re.I)}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def log_file(session_id):
    """Proxy log: logs/<id>.json, or logs/demo/<id>.json for a demo proxy started with GUARDRAIL_LOG_DIR=logs/demo."""
    plain = ROOT / 'logs' / f'{session_id}.json'
    demo = ROOT / 'logs' / 'demo' / f'{session_id}.json'
    return demo if not plain.exists() and demo.exists() else plain


def run_dir(session_id):
    """Runner folder: runs/<id>, or runs/demo/<id> for a --phase demo run (DM-34)."""
    plain, demo = ROOT / 'runs' / session_id, ROOT / 'runs' / 'demo' / session_id
    return demo if not plain.exists() and demo.exists() else plain


def turn_calls(turn):
    """Tool calls returned by one 200 response: name, path argument, argument length."""
    body = turn.get('response_body') or {}
    calls = []
    for choice in body.get('choices') or []:
        for call in (choice.get('message') or {}).get('tool_calls') or []:
            try:
                path = json.loads(call['function']['arguments']).get('path')
            except (ValueError, AttributeError):
                path = None
            calls.append({'tool': call['function']['name'], 'path': path,
                          'argument_chars': len(call['function']['arguments'])})
    return calls


def http_errors(turn):
    if turn.get('status_code') == 200:
        return None
    error = (turn.get('response_body') or {}).get('error') or {}
    generated = error.get('failed_generation') if isinstance(error, dict) else None
    parse = None
    if isinstance(generated, str):
        try:
            json.loads(generated)
            parse = {'parses': True}
        except json.JSONDecodeError as exc:
            parse = {'parses': False, 'error': exc.msg, 'position': exc.pos, 'length': len(generated)}
    return {'turn': turn['turn'], 'status': turn.get('status_code'),
            'code': error.get('code') if isinstance(error, dict) else None,
            'message': error.get('message') if isinstance(error, dict) else None,
            'failed_generation_chars': len(generated) if isinstance(generated, str) else None,
            'failed_generation_tail': generated[-160:] if isinstance(generated, str) else None,
            'json_parse': parse}


def tokens(turns):
    known = [t for t in turns if t.get('tokens') is not None]
    missing = [t['turn'] for t in turns if t.get('tokens') is None]
    return {'known_prompt': sum(t.get('prompt_tokens') or 0 for t in known),
            'known_completion': sum(t.get('completion_tokens') or 0 for t in known),
            'known_total': sum(t['tokens'] for t in known),
            'usage_missing_turns': len(missing), 'usage_missing_turn_ids': missing,
            'total': sum(t['tokens'] for t in known) if not missing else None,
            'total_status': 'measured' if not missing else 'unmeasured'}


def distribution(values):
    values = [v for v in values if v is not None]
    if not values:
        return {'n': 0}
    return {'n': len(values), 'min': min(values), 'median': statistics.median(values), 'max': max(values)}


def step_rows(steps, turns_by_id, agents):
    rows, previous_hashes, previous_tests = [], None, None
    last_by_role = {}
    for step in steps:
        # A block-mode refused step has no acceptance run (DM-7).
        artifact = (step.get('acceptance') or {}).get('artifact') or {}
        hashes = artifact.get('file_hashes') or {}
        tests = artifact.get('test_pass_count')
        changed = sorted(p for p in hashes if previous_hashes is not None and previous_hashes.get(p) != hashes[p])
        observation = step.get('observation') or {}
        progress = observation.get('progress') or {}
        report = step.get('observed_final_report')
        own_ids = set(report['open_issue_ids']) if report and report['open_issue_ids'] is not None else None
        prior = last_by_role.get(step['agent'])
        calls = [c for n in step['llm_turns'] for c in turn_calls(turns_by_id[n])]
        errors = [e for e in (http_errors(turns_by_id[n]) for n in step['llm_turns']) if e]
        writable = set(agents[step['agent']].writable_paths)
        rows.append({
            'step_id': step['step_id'], 'agent': step['agent'], 'step_status': step['step_status'],
            'failure_reasons': step['failure_reasons'],
            'progress_state': progress.get('state'), 'comparison_step_id': progress.get('comparison_step_id'),
            'metrics': {k: v.get('value') for k, v in (progress.get('metrics') or {}).items()},
            'unmeasured_metrics': sorted(k for k, v in (progress.get('metrics') or {}).items()
                                         if v.get('status') == 'unmeasured'),
            'events': progress.get('events', []),
            'criteria_decision': (observation.get('criteria') or {}).get('decision'),
            'consecutive_steps': (observation.get('criteria') or {}).get('consecutive_steps'),
            'open_issue_ids': sorted(own_ids) if own_ids is not None else None,
            'open_issue_change_vs_same_role': None if own_ids is None or prior is None or prior['ids'] is None else
                {'added': sorted(own_ids - prior['ids']), 'removed': sorted(prior['ids'] - own_ids)},
            'tests_after_step': tests,
            'tests_change_in_step': None if previous_tests is None or tests is None else tests - previous_tests,
            'files_changed_in_step': changed,
            'tool_calls': calls,
            'edit_attempts': [c for c in calls if c['tool'] in EDIT_TOOLS],
            'edit_attempts_outside_writable_paths': [c for c in calls if c['tool'] in EDIT_TOOLS
                                                     and c['path'] not in writable],
            'tool_execution_errors': [e for e in step.get('tool_executions', []) if e['is_error']],
            'tool_errors': step.get('tool_errors', []),
            'http_errors': errors,
            'shared_narrative_source': step.get('shared_narrative_source'),
            'vocabulary_violation': step.get('vocabulary_violation'),
            'unlisted_issues': (observation.get('issue_report') or {}).get('unlisted_issues'),
            'info_items': (observation.get('conversation') or {}).get('info_items'),
            'completion_declared': report['completion_declared'] if report else None,
            'final_output_status': (step.get('collection') or {}).get('final_output_status'),
            'observation_has_conversation': (observation.get('conversation') or {}).get('open_issue_ids') is not None,
            'observation_has_artifact': observation.get('artifact') is not None,
            'llm_turns': step['llm_turns']})
        previous_hashes, previous_tests = hashes, tests
        last_by_role[step['agent']] = {'ids': own_ids, 'step': step['step_id']}
    return rows


def classify(rows):
    """Mechanical: did anything measurable change between the comparison step and this step?"""
    by_id = {r['step_id']: r for r in rows}
    result = []
    for r in rows:
        if r['progress_state'] not in ('stagnant', 'oscillating'):
            continue
        since = [by_id[s] for s in range(r['comparison_step_id'] + 1, r['step_id'] + 1)] if r['comparison_step_id'] else [r]
        files = sorted({p for s in since for p in s['files_changed_in_step']})
        tests = [s['step_id'] for s in since if s['tests_change_in_step']]
        issues = r['open_issue_change_vs_same_role']
        if r['unmeasured_metrics']:
            label, reason = 'undeterminable', 'selected metric unmeasured'
        elif files or tests or (issues and (issues['added'] or issues['removed'])):
            label, reason = 'progress_missed_by_metrics', {'files': files, 'test_change_steps': tests, 'issues': issues}
        else:
            label, reason = 'no_measurable_change', 'no file hash, test count or own open-issue change since comparison step'
        result.append({'step_id': r['step_id'], 'agent': r['agent'], 'state': r['progress_state'],
                       'classification': label, 'basis': reason,
                       'activity_outside_metrics': {
                           'read_calls': sum(c['tool'] == 'read_file' for c in r['tool_calls']),
                           'run_tests_calls': sum(c['tool'] == 'run_tests' for c in r['tool_calls']),
                           'edit_attempts': r['edit_attempts'], 'http_errors': [e['code'] for e in r['http_errors']],
                           'tool_execution_errors': [e['error_summary'] for e in r['tool_execution_errors']],
                           'no_tool_calls': not r['tool_calls']}})
    return result


def all_tests_passed(step):
    """Full suite passed at this step: pass count equals the suite total (not the largest count seen)."""
    artifact = (step.get('acceptance') or {}).get('artifact') or {}
    total = artifact.get('test_total_count')
    return total is not None and artifact.get('test_pass_count') == total


def counterfactual(rows, turns_by_id, stop_step, summary, steps):
    if stop_step is None:
        return {'first_stop_step': None}
    last_turn = max(turns_by_id[n]['turn'] for r in rows if r['step_id'] == stop_step for n in r['llm_turns'])
    after = [t for t in turns_by_id.values() if t['turn'] > last_turn]
    at_stop = next(r for r in rows if r['step_id'] == stop_step)
    return {'first_stop_step': stop_step, 'turns_after_stop': len(after),
            'known_tokens_after_stop': sum(t['tokens'] for t in after if t.get('tokens') is not None),
            'usage_missing_turns_after_stop': sum(t.get('tokens') is None for t in after),
            'tests_at_stop': at_stop['tests_after_step'], 'tests_at_end': summary.get('tests_passed_after'),
            # S-28: compare with the suite total; the old max-observed rule called 7/16 "all tests".
            'first_step_with_all_tests': next((s['step_id'] for s in steps if all_tests_passed(s)), None),
            'termination_reason_at_end': summary.get('termination_reason'),
            'reviewer_declaration_step': next((r['step_id'] for r in rows if r['agent'] == 'reviewer'
                                               and r['completion_declared']), None)}


def shared_artifact_progress(rows):
    """G0-12: one global file/test change counted as progress by more than one role."""
    counted = []
    for origin in (r for r in rows if r['files_changed_in_step'] or r['tests_change_in_step']):
        roles = [r for r in rows if r['step_id'] >= origin['step_id'] and r['progress_state'] == 'progress'
                 and any(e['metric'].startswith('artifact.') for e in r['events'])
                 and r['comparison_step_id'] is not None and r['comparison_step_id'] < origin['step_id']]
        counted.append({'origin_step': origin['step_id'], 'files': origin['files_changed_in_step'],
                        'counted_as_progress_by': [(r['step_id'], r['agent']) for r in roles],
                        'extra_counts': max(0, len(roles) - 1)})
    return counted


def secret_scan(paths, env_names=()):
    """Pattern hits plus the literal value of each named environment variable set right now (D-11)."""
    checked = {}
    patterns = dict(SECRET_PATTERNS)
    for name in sorted({n for n in env_names if n}):
        value = os.environ.get(name)
        checked[name] = 'set' if value else 'not set in this environment'
        if value and len(value) >= 8:
            patterns['env:' + name] = re.compile(re.escape(value))
    hits = {}
    for path in paths:
        for file in ([path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())):
            text = file.read_text(encoding='utf-8', errors='replace')
            for name, pattern in patterns.items():
                count = len(pattern.findall(text))
                if count:
                    hits.setdefault(file.relative_to(ROOT).as_posix(), {})[name] = count
    return {'files_scanned': sum(1 if p.is_file() else sum(1 for q in p.rglob('*') if q.is_file()) for p in paths),
            'patterns': sorted(patterns), 'environment_variables_checked': checked,
            'hits': hits, 'clean': not hits}


def analyse(session_id):
    log_path, run = log_file(session_id), run_dir(session_id)
    log, steps, summary = load(log_path), load(run / 'steps.json'), load(run / 'summary.json')
    conditions, session_copy = load(run / 'conditions.json'), load(run / 'session.json')
    scenario = load_scenario(run / 'scenario.yaml')
    agents = {a.id: a for a in scenario.agents}
    turns_by_id = {t['turn']: t for t in log['turns']}
    rows = step_rows(steps, turns_by_id, agents)
    linked = [n for s in steps for n in s['llm_turns']]
    stop = next((r['step_id'] for r in rows if r['criteria_decision'] in STOP_DECISIONS), None)
    ok = [t for t in log['turns'] if t.get('status_code') == 200]
    usage = [(t.get('response_body') or {}).get('usage') or {} for t in ok]
    finish = [((t.get('response_body') or {}).get('choices') or [{}])[0].get('finish_reason') for t in ok]
    system_prompts = {s['agent']: turns_by_id[s['llm_turns'][0]]['request_body']['messages'][0]['content']
                      for s in steps if s['llm_turns']}
    # A dialogue (T1) step has the scenario judge's gate instead of an acceptance run (C-17-4).
    gate_at_end = next((s['acceptance']['gate'] if s.get('acceptance') is not None else s['completion_gate']
                        for s in reversed(steps)
                        if s.get('acceptance') is not None or s.get('completion_gate') is not None), {})
    return {
        'session_id': session_id,
        'isolation': {
            'log_session_id_matches': log.get('session_id') == session_id,
            'runner_session_id_matches': conditions.get('session_id') == session_id,
            'runner_copy_equals_proxy_log': session_copy == log,
            'meta_scenario_id': log['meta'].get('scenario_id'), 'conditions_mixed': log['meta'].get('conditions_mixed'),
            'turns': len(log['turns']), 'turn_ids_consecutive': [t['turn'] for t in log['turns']] == list(range(1, len(log['turns']) + 1)),
            'turns_linked_to_steps': len(linked), 'every_turn_linked_once': sorted(linked) == [t['turn'] for t in log['turns']],
            'observation_step_ids': [o['step_id'] for o in log['observations']]},
        'scenario': {'id': scenario.scenario_id, 'sha256': hashlib.sha256((run / 'scenario.yaml').read_bytes()).hexdigest(),
                     'progress_metric': scenario.progress_metric.model_dump(), 'progress_source': scenario.progress_source,
                     'monitored_paths': scenario.monitored_paths,
                     'writable_paths': {a.id: a.writable_paths for a in scenario.agents}},
        'tokens': tokens(log['turns']),
        'termination': {'reason': summary['termination_reason'], 'steps_reached': summary['steps'],
                        'started_at': log['meta'].get('started_at'), 'ended_at': log['meta'].get('ended_at')},
        'judgement': {'tests_before': summary.get('tests_passed_before'), 'tests_after': summary.get('tests_passed_after'),
                      'machine_success_at_end': gate_at_end.get('machine_success'),
                      'gate_at_end': gate_at_end},
        'steps': rows,
        'first_stop_step': stop,
        'stagnant_classification': classify(rows),
        'counterfactual_stop': counterfactual(rows, turns_by_id, stop, summary, steps),
        'p0_checks': {
            'comparison_same_role': all(r['comparison_step_id'] is None or
                                        next(x for x in rows if x['step_id'] == r['comparison_step_id'])['agent'] == r['agent']
                                        for r in rows),
            'open_issue_events_by_step': {r['step_id']: [e for e in r['events'] if e['metric'] == 'conversation.open_issues_count']
                                          for r in rows if any(e['metric'] == 'conversation.open_issues_count' for e in r['events'])},
            'failed_steps_sources': [{k: r[k] for k in ('step_id', 'failure_reasons', 'final_output_status',
                                                         'observation_has_conversation', 'observation_has_artifact')}
                                     for r in rows if r['step_status'] == 'failed'],
            'vocabulary_violations_total': summary.get('vocabulary_violations_total'),
            'vocabulary_violation_steps': summary.get('vocabulary_violation_steps'),
            'unlisted_issues_by_step': {r['step_id']: r['unlisted_issues'] for r in rows},
            'judged_metrics': sorted({k for r in rows for k in r['metrics']}),
            'info_items_recorded': {r['step_id']: r['info_items'] for r in rows},
            'tool_execution_errors': [{'step_id': r['step_id'], 'agent': r['agent'], 'errors': r['tool_execution_errors'],
                                       'edit_attempts_outside_writable_paths': r['edit_attempts_outside_writable_paths']}
                                      for r in rows if r['tool_execution_errors']],
            'shared_narrative_source': {k: sum(r['shared_narrative_source'] == k for r in rows)
                                        for k in sorted({r['shared_narrative_source'] for r in rows}, key=str)},
            'unmeasured_due_to_missing_metric': [(r['step_id'], r['unmeasured_metrics']) for r in rows
                                                 if r['progress_state'] == 'unmeasured' and r['unmeasured_metrics']]},
        'g0_7': {'http_errors': [e for r in rows for e in r['http_errors']],
                 'finish_reason_counts': {k: finish.count(k) for k in sorted(set(finish), key=str)},
                 'completion_tokens': distribution([u.get('completion_tokens') for u in usage]),
                 'reasoning_tokens': distribution([(u.get('completion_tokens_details') or {}).get('reasoning_tokens') for u in usage]),
                 'max_tokens_requested': sorted({(t.get('request_body') or {}).get('max_tokens') for t in log['turns']}, key=str),
                 'edit_calls_200': [{'turn': t['turn'], **c, 'completion': u.get('completion_tokens'),
                                     'reasoning': (u.get('completion_tokens_details') or {}).get('reasoning_tokens')}
                                    for t, u in zip(ok, usage) for c in turn_calls(t) if c['tool'] in EDIT_TOOLS]},
        'g0_12_shared_artifact_progress': shared_artifact_progress(rows),
        'd_10': {'known_total': tokens(log['turns'])['known_total'],
                 'http_429_turns': [t['turn'] for t in log['turns'] if t.get('status_code') == 429]},
        'prompt_checks': {agent: {'writable_paths_listed': all(p in text for p in agents[agent].writable_paths)
                                  and 'writable' in text.lower(),
                                  'mentions_own_writable_files': [p for p in agents[agent].writable_paths if p in text],
                                  'states_call_budget': bool(re.search(r'max_llm_calls|call budget|calls per step|호출', text))}
                          for agent, text in system_prompts.items()},
        'conditions': {k: conditions.get(k) for k in ('temperature', 'run_index', 'context_buffer_messages', 'runner_protocol',
                                                      'collection_policy', 'output_contract_version', 'allowed_issues_sha256',
                                                      'recent_messages_policy', 'seed_support', 'requested_seed', 'versions')},
        'meta': {k: log['meta'].get(k) for k in ('model', 'max_tokens', 'criteria_version', 'criteria_sha256',
                                                  'temperature', 'seed_status', 'context_buffer_messages',
                                                  'framework_version', 'upstream')},
        'secret_scan': secret_scan([log_path, run],
                                   {(log['meta'].get('upstream') or {}).get('api_key_env'),
                                    'GROQ_API_KEY', 'KMU_API_KEY'})}


def base_manifest(a, phase, notes):
    scenario = load_scenario(run_dir(a['session_id']) / 'scenario.yaml')
    return {'manifest_version': 'session-manifest-v0.1', 'session_id': a['session_id'], 'rerun_of': None,
            'scenario': {'id': a['scenario']['id'], 'version': a['scenario']['id'], 'hash': a['scenario']['sha256']},
            'code': {'git_commit': None, 'criteria_version': a['meta']['criteria_version'],
                     'progress_version': (load(log_file(a['session_id']))['meta'].get('criteria_parameters')
                                          or {}).get('progress_version'),
                     'metrics_version': None},
            'condition': {'phase': phase, 'temperature': a['conditions']['temperature'],
                          'repeat_index': a['conditions']['run_index'],
                          'max_steps': scenario.termination.max_steps,
                          'max_llm_calls_per_step': scenario.termination.max_llm_calls_per_step,
                          'max_tokens': a['meta']['max_tokens'],
                          'context_buffer_messages': a['conditions']['context_buffer_messages'],
                          'guardrail_mode': 'observe' if scenario.termination.on_criteria_alert == 'observe_only' else None},
            # Provider comes from what the proxy recorded for this session; never assumed.
            'model': {'provider': (a['meta']['upstream'] or {}).get('base_url_host'),
                      'name': a['meta']['model'],
                      'upstream': a['meta']['upstream']},
            'seed': {'value': a['conditions']['requested_seed'], 'status': a['conditions']['seed_support']},
            'run': {'started_at': a['termination']['started_at'], 'ended_at': a['termination']['ended_at'],
                    'termination_reason': a['termination']['reason'], 'steps_reached': a['termination']['steps_reached']},
            'tokens': {k: a['tokens'][k] for k in ('known_prompt', 'known_completion', 'known_total',
                                                   'usage_missing_turns', 'total', 'total_status')},
            'judgement': {'before': {'tests_passed': a['judgement']['tests_before']},
                          'after': {'tests_passed': a['judgement']['tests_after'], 'gate': a['judgement']['gate_at_end']},
                          'normal_session': a['judgement']['machine_success_at_end']},
            'guardrail': {'virtual_decisions': [{'step_id': r['step_id'], 'progress': r['progress_state'],
                                                 'criteria': r['criteria_decision']} for r in a['steps']],
                          'first_stop_step': a['first_stop_step']},
            'validity': {'class': 'unclassified', 'reason': None, 'decided_by': None},
            'notes': notes + ['git_commit is null: the runner does not record the code commit']
                     + ([] if a['meta']['upstream'] else
                        ['model.provider is null: this session predates upstream recording in the proxy log'])}


def reasoning_effort(session_id):
    """Requested vs applied reasoning_effort (C-11). conditions.json first; older v8 sessions fall back to the
    values actually present in the request bodies. Applied is never inferred from the response."""
    recorded = load(run_dir(session_id) / 'conditions.json').get('reasoning_effort')
    if recorded:
        return {**recorded, 'source': 'conditions.json'}
    sent = sorted({t['request_body']['reasoning_effort'] for t in load(log_file(session_id))['turns']
                   if t['request_body'].get('reasoning_effort') is not None})
    return {'requested': sent[0] if len(sent) == 1 else sent or None, 'applied': 'unverified',
            'source': 'request bodies in the proxy log (conditions.json predates this field)'}


# USD per 1M tokens, per model. 1 credit = $0.001 on the gateway (C-11: exact match with the recorded usage).
PRICE_PER_M = {'accounts/fireworks/models/gpt-oss-120b': {'prompt': 0.15, 'completion': 0.60}}
METRICS_VERSION = 'metrics-v1'


def judgement_time(observations):
    """S-5 summary of per-step judgement_ns; p99 is the nearest-rank value, as in metrics-v1."""
    values = sorted(o['judgement_ns'] for o in observations if isinstance(o.get('judgement_ns'), int))
    if not values:
        return {'status': 'unmeasured', 'n': 0, 'p50_ms': None, 'p99_ms': None, 'max_ms': None,
                'reason': 'no judgement_ns in the observations'}
    return {'status': 'measured', 'n': len(values), 'steps_without_value': len(observations) - len(values),
            'p50_ms': statistics.median(values) / 1e6,
            'p99_ms': values[max(0, math.ceil(0.99 * len(values)) - 1)] / 1e6, 'max_ms': values[-1] / 1e6}


def session_credits(model, token_counts):
    price = PRICE_PER_M.get(model)
    if price is None:
        return {'status': 'unmeasured', 'value': None, 'reason': 'no price recorded for this model'}
    if token_counts['total_status'] != 'measured':
        return {'status': 'unmeasured', 'value': None, 'reason': 'usage missing on some turns',
                'known_value': round((token_counts['known_prompt'] * price['prompt'] + token_counts['known_completion']
                                      * price['completion']) / 1e6 * 1000, 5)}
    return {'status': 'measured', 'value': round((token_counts['known_prompt'] * price['prompt']
                                                  + token_counts['known_completion'] * price['completion'])
                                                 / 1e6 * 1000, 5),
            'basis': 'tokens x price per 1M x 1000 (S-12); not a /credits/ reading', 'price_per_1m_usd': price}


def validity_evidence(a):
    """Log facts behind a validity proposal (S-9). The class itself stays with the PM."""
    rows = a['steps']
    return {'isolation_ok': all(a['isolation'][k] for k in ('log_session_id_matches', 'runner_session_id_matches',
                                                            'every_turn_linked_once'))
                            and not a['isolation']['conditions_mixed'],
            'termination_reason': a['termination']['reason'],
            'http_error_codes': [e['code'] or e['status'] for e in a['g0_7']['http_errors']],
            'http_429_turns': a['d_10']['http_429_turns'],
            'finish_reason_length': a['g0_7']['finish_reason_counts'].get('length', 0),
            'tool_execution_errors': sum(len(r['tool_execution_errors']) for r in rows),
            'edit_attempts_outside_writable_paths': sum(len(r['edit_attempts_outside_writable_paths']) for r in rows),
            'unmeasured_steps': sum(r['criteria_decision'] == 'unmeasured' for r in rows)}


def v03_fields(result, a, conditions, observations):
    """session-manifest-v0.3 (S-8, S-1, S-23) for sessions whose runner recorded the Git state."""
    result['manifest_version'] = 'session-manifest-v0.3'
    result['scenario'].pop('version', None)
    result['code'].update(git_commit=conditions.get('git_commit'), git_dirty=conditions.get('git_dirty'),
                          git_state_status=conditions.get('git_state_status'), metrics_version=METRICS_VERSION)
    result['condition'].update(runner_protocol=conditions.get('runner_protocol'),
                               reasoning_effort={**(conditions.get('reasoning_effort') or {}),
                                                 'source': 'conditions.json'} if conditions.get('reasoning_effort')
                               else None,
                               dataset_run=conditions.get('dataset_run'))
    result['run']['parallel_group'] = conditions.get('parallel_group')
    result['judgement']['normal_session'] = a['termination']['reason'] == 'success'
    result['judgement']['normal_session_rule'] = 'S-1: all acceptance tests pass and completion declared'
    result['judgement_time'] = judgement_time(observations)
    result['credits'] = session_credits(a['meta']['model'], a['tokens'])
    result['replay'] = {'status': 'unmeasured', 'reason': 'multi-rule offline replay (S-6) is scheduled for C-16'}
    result['validity']['evidence'] = validity_evidence(a)
    result['notes'] = [n for n in result['notes'] if not n.startswith('git_commit is null')
                       or not conditions.get('git_commit')]
    return result


def v04_fields(result, observations):
    """session-manifest-v0.4 = v0.3 + the first STOP's DM-9 sentence and the values behind it (deadlock-v0.3).

    Copied from the proxy's criteria record, never rebuilt here: dashboard, block body and manifest share one string.
    """
    result['manifest_version'] = 'session-manifest-v0.4'
    result['guardrail']['first_stop_explanation'] = next(
        ({'step_id': o['step_id'], **o['criteria']['explanation']} for o in observations
         if (o.get('criteria') or {}).get('decision') in ('deadlock', 'termination_failure')
         and 'explanation' in o['criteria']), None)
    return result


def v05_fields(result, conditions, log):
    """session-manifest-v0.5 = v0.4 + run phase, the proxy's guardrail mode and, in block mode, what it refused.

    DM-23: a blocked session's saving is reported only as a difference from the same scenario's observe sessions,
    so this session alone leaves that field unmeasured. Its own tokens are the measured tokens section.
    """
    meta, block = log['meta'], log['meta'].get('guardrail_block')
    result['manifest_version'] = 'session-manifest-v0.5'
    # The proxy's record, not the scenario's on_criteria_alert, says whether requests could be refused.
    result['condition'].update(phase=conditions.get('phase'), guardrail_mode=meta.get('guardrail_mode'),
                               guardrail_mode_source='proxy session meta')
    result['guardrail']['mode'] = meta.get('guardrail_mode')
    first = result['guardrail'].get('first_stop_explanation') or {}
    explanation = (block or {}).get('explanation') or {}
    result['guardrail']['block'] = None if block is None else {
        'stop_step': block['stop_step'], 'blocked_at_step': block['blocked_at_step'],
        'first_blocked_turn': block['first_blocked_turn'], 'refused_requests': block['refused_requests'],
        'refused_turns': [t['turn'] for t in log['turns'] if t.get('blocked')],
        'forwarded_turns': sum(not t.get('blocked') for t in log['turns']),
        'explanation_text': explanation.get('text'),
        'same_text_as_first_stop_record': explanation.get('text') is not None and explanation.get('text') == first.get('text'),
        'tokens_used': {k: result['tokens'][k] for k in ('known_total', 'total', 'total_status')}}
    result['guardrail']['savings_vs_observe'] = None if meta.get('guardrail_mode') != 'block' else {
        'status': 'unmeasured', 'value': None, 'basis': 'DM-23: same-scenario observe sessions total tokens '
        '(median, range) minus this session total tokens', 'observe_session_ids': None,
        'observe_total_tokens': None, 'blocked_session_total_tokens': result['tokens']['total'],
        'reason': 'needs the same scenario observe sessions (demo aggregation, C-19); not computable from one session'}
    return result


def v06_fields(result, conditions, summary, log):
    """session-manifest-v0.6 = v0.5 + a scenario-v2 dialogue (T1) run (C-17-4): the session registration and its
    hash, the output contract, vocabulary violations, routing and how the run ended. Earlier sessions keep theirs."""
    registration = conditions.get('registration')
    observations = log['observations']
    result['manifest_version'] = 'session-manifest-v0.6'
    result['task'] = {k: conditions.get(k) for k in ('task_kind', 'turn_order', 'dialogue_flow', 'output_contract_version',
                                                     'contract_sha256', 'allowed_issues_sha256', 'closed_list_check',
                                                     'judge', 'inputs_dir', 'tools', 'tool_implementations')}
    result['registration'] = {
        'value': registration, 'sha256': conditions.get('registration_sha256'),
        'sha256_recomputed': hashlib.sha256(json.dumps(registration, ensure_ascii=False, sort_keys=True,
                                                       separators=(',', ':')).encode('utf-8')).hexdigest(),
        'proxy_stored_same': log['meta'].get('registration') == registration}
    result['vocabulary_violations'] = {'total': summary.get('vocabulary_violations_total'),
                                       'steps': summary.get('vocabulary_violation_steps'),
                                       'excluded_from_strict_failure_streak': True}
    result['run'].update(final_status=summary.get('final_status'), terminal_status=summary.get('terminal_status'))
    result['judgement'] = {'before': None, 'after': {'gate': summary.get('completion_gate'),
                                                     'final_status': summary.get('final_status')},
                           'normal_session': summary.get('termination_reason') == 'success',
                           'normal_session_rule': 'dialogue task: last ordered status, scenario judge resolved and '
                                                  'completion declared (demo-runner-extension.md 2)'}
    last = next((o for o in reversed(observations) if (o.get('progress') or {}).get('handoff') is not None), None)
    result['routing'] = {'turn_order': conditions.get('turn_order'), 'fallbacks': summary.get('route_fallbacks'),
                         'handoff_at_end': (last or {}).get('progress', {}).get('handoff'),
                         'handoff_note': 'recorded only; not a judgement input (DM-22)'}
    return result


def manifest(a, phase, notes):
    result = base_manifest(a, phase, notes)
    conditions = load(run_dir(a['session_id']) / 'conditions.json')
    if 'git_state_status' in conditions:
        # v0.3 only for sessions recorded by the Git-aware runner; earlier manifests are never rewritten.
        log = load(log_file(a['session_id']))
        observations = log['observations']
        result = v03_fields(result, a, conditions, observations)
        if a['meta']['criteria_version'] != 'deadlock-v0.3':
            return result
        result = v04_fields(result, observations)
        # v0.5 for sessions whose proxy recorded its guardrail mode (C-17-2 onward).
        if 'guardrail_mode' not in log['meta']:
            return result
        result = v05_fields(result, conditions, log)
        # v0.6 for scenario-v2 dialogue runs (C-17-4 onward).
        if conditions.get('task_kind') != 'dialogue':
            return result
        return v06_fields(result, conditions, load(run_dir(a['session_id']) / 'summary.json'), log)
    if a['conditions']['runner_protocol'] in (PROTOCOL_V8, PROTOCOL_V9, PROTOCOL_V10):
        # v0.2 adds condition.runner_protocol and condition.reasoning_effort; v7 sessions keep v0.1 unchanged.
        result['manifest_version'] = 'session-manifest-v0.2'
        result['condition'].update(runner_protocol=a['conditions']['runner_protocol'],
                                   reasoning_effort=reasoning_effort(a['session_id']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session_id')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--phase', choices=('verify', 'measure'), required=True)
    parser.add_argument('--note', action='append', default=[])
    args = parser.parse_args()
    analysis = analyse(args.session_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f'{args.session_id}-analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (args.output_dir / f'{args.session_id}-manifest.json').write_text(
        json.dumps(manifest(analysis, args.phase, args.note), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: analysis[k] for k in ('isolation', 'tokens', 'termination', 'judgement', 'first_stop_step',
                                               'counterfactual_stop', 'secret_scan')}, ensure_ascii=False, indent=1))
    return 0 if analysis['secret_scan']['clean'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
