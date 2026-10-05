"""Credits and wall time the C-19 main run (batch_plans/demo-main-v1.yaml, 4 lanes) is expected to use. An estimate.

Per scenario the reference is its latest committed trial session (record/demo-summary.json: measured credits; minutes
between the two gateway usage reads). An observe item takes that session's values. A block item takes that session's
credits up to its first STOP step (tokens x price of the turns of steps 1..STOP, tools/gateway_prices.py; block mode
refuses the next request) and its minutes scaled by the same turn share; without a STOP in the reference, the whole
session (block mode never cuts it). The high value of an item is the most any
committed trial of the scenario measured. Reads committed records plus each reference session's local steps.json and
proxy log (usage fields only). No model call.

  venv/bin/python -B tools/c18_6_estimate.py --output reports/c18-6/estimate-main.json
"""
import argparse
import collections
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import gateway_prices, run_batch  # noqa: E402

PLAN = ROOT / 'batch_plans/demo-main-v1.yaml'
LANES = 4


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def trials(runs_root):
    by_scenario = collections.defaultdict(list)
    for path in sorted(Path(runs_root).glob('DEMO-*/record/demo-summary.json')):
        s = load(path)
        if s['credits_measured'].get('value') is None:
            continue
        start, end = (datetime.fromisoformat(t) for t in s['credits_measured']['read_at'])
        by_scenario[s['scenario_id']].append({'session_id': s['session_id'], 'started': start.isoformat(),
                                              'steps': s['steps'], 'termination_reason': s['termination_reason'],
                                              'first_stop_step': (s.get('first_stop') or {}).get('step_id'),
                                              'credits': s['credits_measured']['value'],
                                              'minutes': round((end - start).total_seconds() / 60, 2)})
    return {k: sorted(v, key=lambda r: r['started']) for k, v in by_scenario.items()}


def until_stop(runs_root, ref):
    """Credits and turn share of steps 1..first STOP of the reference session (what block mode lets through)."""
    folder = Path(runs_root) / ref['session_id']
    steps, log = load(folder / 'steps.json'), load(folder / 'session.json')
    keep = {t for s in steps if s['step_id'] <= ref['first_stop_step'] for t in s['llm_turns']}
    turns = [t for t in log['turns'] if t['turn'] in keep]
    value = gateway_prices.estimate(log['meta'].get('model'), turns)['value']
    return value, len(turns) / len(log['turns'])


def estimate(plan_path=PLAN, runs_root=ROOT / 'runs/demo', lanes=LANES):
    plan = run_batch.load_plan(plan_path)
    measured = trials(runs_root)
    per_item, refs = {}, {}
    for scenario_id, rows in measured.items():
        ref = rows[-1]
        refs[scenario_id] = {'reference': ref, 'high': max(r['credits'] for r in rows),
                             'high_minutes': max(r['minutes'] for r in rows), 'trials': len(rows)}
    lane_rows = []
    for lane in range(1, lanes + 1):
        items = []
        for item in run_batch.lane_items(plan, lane, lanes):
            scenario_id = Path(item.scenario).stem
            ref = refs[scenario_id]
            base, minutes, high = ref['reference']['credits'], ref['reference']['minutes'], ref['high']
            if item.mode == 'block' and ref['reference']['first_stop_step'] is not None:
                key = (scenario_id, 'block')
                if key not in per_item:
                    per_item[key] = until_stop(runs_root, ref['reference'])
                base, share = per_item[key]
                minutes = round(minutes * share, 2)
            items.append({'item': item.key, 'mode': item.mode, 'credits': round(base, 5), 'minutes': minutes,
                          'high': round(high, 5)})
        lane_rows.append({'lane': lane, 'sessions': len(items),
                          'credits': round(sum(i['credits'] for i in items), 2),
                          'high': round(sum(i['high'] for i in items), 2),
                          'hours': round(sum(i['minutes'] for i in items) / 60, 2), 'items': items})
    longest = max((r for rows in measured.values() for r in rows if r['steps'] == 30), key=lambda r: r['credits'])
    return {'script': 'tools/c18_6_estimate.py', 'status': 'estimated', 'plan_id': plan['plan_id'],
            'plan_sha256': hashlib.sha256(Path(plan_path).read_bytes()).hexdigest(), 'lanes': lane_rows,
            'total': {'sessions': sum(r['sessions'] for r in lane_rows),
                      'credits': round(sum(r['credits'] for r in lane_rows), 2),
                      'high': round(sum(r['high'] for r in lane_rows), 2),
                      'longest_lane_hours': max(r['hours'] for r in lane_rows),
                      'ceiling_30_steps': {'per_session': longest['credits'], 'session_id': longest['session_id'],
                                           'credits': round(longest['credits'] * sum(r['sessions'] for r in lane_rows), 2),
                                           'note': 'every session as long as the costliest measured 30-step trial'}},
            'references': refs,
            'limits': ['one trial session per scenario is the reference; a main-run session can end at any step up '
                       'to 30, so a normal run that does not finish can cost as much as a 30-step stall run',
                       'minutes are wall time of the trial between the gateway usage reads; parallel lanes and the '
                       'gateway load change them',
                       'block items assume the session takes the same path as the reference up to its first STOP']}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/c18-6/estimate-main.json')
    args = parser.parse_args()
    result = estimate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
