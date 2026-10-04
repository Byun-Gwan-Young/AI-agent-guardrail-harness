"""Recompute a dialogue (T1) run's judge results from what its run folder stored (C-17-6 part 2, DM-13).

Inputs: steps.json (the verified reports, also handed to a judge that reads them, C-18-4), tool-dispatch.json and the
stored search responses, read through experiments.search_tools.replay_tool_records (each response checked against its
sha256 and normalized again). No search, no model call, no proxy. Every step's completion gate and every completion claim is judged again with the
scenario's judge and compared with the recorded one. The judge file is compared with the hash the run recorded.

    venv/bin/python tools/rejudge_dialogue.py runs/demo/<session id> [--output <file>]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments import search_tools  # noqa: E402
from experiments.dialogue_runner import checked_gate, judge_call, load_judge  # noqa: E402
from experiments.run_scenario import safe_path  # noqa: E402
from scenario_schema import load_scenario  # noqa: E402

TOOL = 'tools/rejudge_dialogue.py'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rejudge(run_dir, scenario_root=ROOT):
    run_dir, scenario_root = Path(run_dir), Path(scenario_root)
    conditions, steps = load(run_dir / 'conditions.json'), load(run_dir / 'steps.json')
    scenario = load_scenario(run_dir / 'scenario.yaml')
    judge, judge_now = load_judge(scenario, scenario_root)
    inputs_dir = safe_path(scenario_root, scenario.inputs_dir)
    records = search_tools.replay_tool_records(run_dir)

    verified = [s['observed_final_report'] for s in steps if s.get('observed_final_report') is not None]

    def again(report, step_id):
        known = [r for r in records if r['step_id'] is not None and r['step_id'] <= step_id]
        reports = [r for r in verified if r['step_id'] <= step_id]
        return checked_gate(judge_call(judge, report, tool_records=known, inputs_dir=inputs_dir, reports=reports))
    latest, rows = None, []
    for step in steps:
        if step.get('completion_gate') is None:
            continue  # a step refused by block mode has no output and was not judged
        if step.get('observed_final_report') is not None:
            latest = step['observed_final_report']
        gate = again(latest, step['step_id'])
        row = {'step_id': step['step_id'], 'recorded_gate': step['completion_gate'], 'recomputed_gate': gate,
               'gate_same': gate == step['completion_gate']}
        claim = step.get('completion_claim')
        if claim is not None:
            claim_gate = again(step['observed_final_report'], step['step_id'])
            row.update(recorded_claim_gate=claim['gate'], recomputed_claim_gate=claim_gate,
                       claim_gate_same=claim_gate == claim['gate'])
        rows.append(row)
    recorded = conditions.get('judge') or {}
    search = [r for r in records if 'search' in r]
    return {'tool': TOOL, 'session_id': conditions.get('session_id'), 'run_dir': str(run_dir),
            'judge': {'path': judge_now['path'], 'sha256_recorded': recorded.get('sha256'),
                      'sha256_now': judge_now['sha256'], 'same_file': recorded.get('sha256') == judge_now['sha256']},
            'tool_calls': len(records), 'search_calls': len(search),
            'stored_responses_checked': len({r['search']['response_sha256'] for r in search
                                             if r['search']['response_sha256']}),
            'searched_again': False, 'steps': rows,
            'all_same': all(r['gate_same'] and r.get('claim_gate_same', True) for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--scenario-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = rejudge(args.run_dir, args.scenario_root)
    text = json.dumps(report, ensure_ascii=False, indent=1) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if report['all_same'] and report['judge']['same_file'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
