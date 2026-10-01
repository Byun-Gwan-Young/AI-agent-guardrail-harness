"""C-17-1 part 3: re-judge existing sessions with deadlock-v0.3 / progress-v3 and explain-v1, offline.

Inputs are the proxy logs only (observation input fields; stored progress/criteria are compared, never reused).
No external call, no model text in the output (no narrative, reasoning, reasons or evidence). Also recomputes
deadlock-v0.2 / progress-v2 and checks it reproduces the stored records byte-for-byte.

Output: reports/c17-1/v03-recompute.json. The C-16 prediction is read from docs/design/demo-v03-inputs.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from criteria_policy import evaluate_criteria, pin_criteria  # noqa: E402
from experiment_config import load_config  # noqa: E402
from explain_v1 import STOP_DECISIONS, explain  # noqa: E402
from progress_schema import Observation  # noqa: E402
from progress_signal import calculate_progress  # noqa: E402
from progress_signal_v3 import calculate_progress as calculate_v3  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402

SESSIONS = {'G0-8': 'A-1-v2-b51f67df2fb9402ba15fccb35c3db53e',
            'A-1-v3': 'A-1-v3-4a0087756b2641f4b8f9b025c0419f73',
            'A-1-v4': 'A-1-v4-e174aafe805b4f59bb62d7c95716b8b7'}
CONFIG = ROOT / 'guardrail-deadlock-v0.3-kmu.yaml'
PREDICTION = ROOT / 'docs/design/demo-v03-inputs.json'
INPUT_FIELDS = set(Observation.model_fields)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def replay_v02(inputs, pin):
    history = []
    for raw in inputs:
        record = {**raw, 'progress': calculate_progress(history, raw, version=pin['criteria_parameters']['progress_version'])}
        history.append({**record, 'criteria': evaluate_criteria(history + [record], pin)})
    return history


def replay_v03(inputs, pin):
    history, timings = [], []
    for raw in inputs:
        started = time.perf_counter_ns()
        record = {**raw, 'progress': calculate_v3(history, raw, pin['criteria_parameters'])}
        record['criteria'] = evaluate_criteria(history + [record], pin)
        timings.append(time.perf_counter_ns() - started)
        history.append(record)
    return history, timings


def first_stop(rows):
    return next((r['step_id'] for r in rows if r['criteria']['decision'] in STOP_DECISIONS), None)


def session_report(label, session_id, pin, predictions):
    log_path = ROOT / 'logs' / f'{session_id}.json'
    log = json.loads(log_path.read_text(encoding='utf-8'))
    stored = log['observations']
    inputs = [{k: v for k, v in o.items() if k in INPUT_FIELDS} for o in stored]
    v02 = replay_v02(inputs, log['meta'])
    v03, timings = replay_v03(inputs, pin)
    scenario = load_scenario(ROOT / 'runs' / session_id / 'scenario.yaml')
    labels = {a.id: a.role for a in scenario.agents}
    rows, stops = [], []
    for old, again, new in zip(stored, v02, v03):
        t3 = new['progress'].get('t3') or {}
        rows.append({'step': old['step_id'], 'agent': old.get('agent_id'),
                     'v02_state': old['progress'].get('state'), 'v02_decision': old['criteria'].get('decision'),
                     'v03_state': new['progress'].get('state'), 'v03_decision': new['criteria'].get('decision'),
                     't3_applied': t3.get('applied'), 'global_revert': t3.get('global_revert'),
                     'test_plateau': t3.get('test_plateau'), 'steps_since_test_max': t3.get('steps_since_test_max'),
                     'only_file_change_progress': t3.get('only_file_change_progress')})
        explanation = new['criteria'].get('explanation')
        if explanation is not None:
            stops.append({'step': old['step_id'], 'decision': new['criteria']['decision'],
                          'template_id': explanation['template_id'], 'text': explanation['text'],
                          'values': explanation['values'], 'missing_values': explanation['missing_values'],
                          # PM decision 3 (role display) is open; the proxy writes role IDs.
                          'text_with_scenario_role_labels': explain(explanation['signals'], labels)['text']})
    v02_identical = all(dumps(a['progress']) == dumps(o['progress']) and dumps(a['criteria']) == dumps(o['criteria'])
                        for a, o in zip(v02, stored))
    predicted = predictions[label]['prediction']['first_step_reaching_consecutive']
    return {'session_id': session_id, 'log_sha256': sha256(log_path), 'steps': len(stored),
            'stored_criteria_version': log['meta'].get('criteria_version'),
            'v02_stored_first_stop': first_stop(stored), 'v02_recomputed_first_stop': first_stop(v02),
            'v02_recomputed_byte_identical': v02_identical,
            'v03_first_stop': first_stop(v03), 'c16_predicted_first_stop': predicted,
            'v03_matches_prediction': first_stop(v03) == predicted,
            'v03_stop_steps': [r['step'] for r in rows if r['v03_decision'] in STOP_DECISIONS],
            'steps_where_v02_v03_state_differs': [r['step'] for r in rows if r['v02_state'] != r['v03_state']],
            'steps_where_v02_v03_decision_differs': [r['step'] for r in rows if r['v02_decision'] != r['v03_decision']],
            't3_applied_steps': [r['step'] for r in rows if r['t3_applied']],
            'role_labels_from_scenario': labels,
            'first_stop_explanation': stops[0] if stops else None,
            'stop_explanations': stops,
            'offline_replay_ns': {'note': 'progress-v3 + deadlock-v0.3 per step, offline on this machine; '
                                          'not the proxy judgement_ns', 'n': len(timings),
                                  'p50_ms': statistics.median(timings) / 1e6, 'max_ms': max(timings) / 1e6},
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/c17-1/v03-recompute.json')
    args = parser.parse_args()
    config = load_config(CONFIG)
    pin = pin_criteria(config['criteria_version'], config['criteria_parameters'])
    predictions = json.loads(PREDICTION.read_text(encoding='utf-8'))['sessions']
    report = {'script': 'tools/recompute_v03.py', 'config': CONFIG.name, 'config_sha256': sha256(CONFIG),
              'criteria_version': pin['criteria_version'], 'criteria_sha256': pin['criteria_sha256'],
              'criteria_parameters': pin['criteria_parameters'], 'prediction_source': str(PREDICTION.relative_to(ROOT)),
              'sessions': {label: session_report(label, session_id, pin, predictions)
                           for label, session_id in SESSIONS.items()}}
    report['normal_session_A-1-v3_new_stop'] = bool(report['sessions']['A-1-v3']['v03_stop_steps'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    summary = {label: {k: v for k, v in s.items() if k not in ('rows', 'stop_explanations', 'role_labels_from_scenario')}
               for label, s in report['sessions'].items()}
    print(json.dumps({'criteria_sha256': pin['criteria_sha256'],
                      'normal_session_A-1-v3_new_stop': report['normal_session_A-1-v3_new_stop'],
                      'sessions': summary}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
