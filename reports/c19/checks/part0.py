"""C-19-2 part 0: main-run integrity, from small record files and lane logs only (no session.json opened here)."""
import json, re, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLANS = ['demo-main-v1', 'demo-main-v1-lr2', 'demo-main-v1-mr2']
out = {}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


# plan items
items = []
for line in (ROOT / 'batch_plans/demo-main-v1.yaml').read_text().splitlines():
    m = re.match(r"- \{scenario: scenarios/(\S+)\.yaml, mode: (\w+), repeats: \[([\d, ]+)\]", line)
    if m:
        for r in m.group(3).split(','):
            items.append(f'{m.group(1)}:{m.group(2)}:{int(r)}')
out['plan_items'] = len(items)

# lane logs: per session event, key scan, and lane end state
lane_sessions, lane_ends = {}, {}
for plan in PLANS:
    for f in sorted((ROOT / 'runs/demo-batches' / plan).glob('lane-*.jsonl')):
        evs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        lane_ends[f'{plan}/{f.name}'] = [e['event'] for e in evs if e['event'] != 'session'][-1]
        for e in evs:
            if e['event'] == 'session':
                lane_sessions[e['session_id']] = {'plan': plan, 'lane_file': f.name, 'item': e['item'],
                                                  'termination': e['termination_reason'], 'rerun_of': e['rerun_of'],
                                                  'key_scan_clean': (e.get('summary') or {}).get('key_scan_clean'),
                                                  'key_values_checked': (e.get('summary') or {}).get('key_values_checked'),
                                                  'freeze': e.get('final_freeze_sha256'), 'plan_sha256': e['plan_sha256']}
out['lane_last_event'] = lane_ends

# session folders of the three plans
sessions = {}
for folder in sorted((ROOT / 'runs/demo').iterdir()):
    c = folder / 'conditions.json'
    if not c.is_file():
        continue
    cond = load(c)
    b = cond.get('batch') or {}
    if b.get('plan_id') not in PLANS:
        continue
    summ = load(folder / 'summary.json') if (folder / 'summary.json').is_file() else {}
    ds = folder / 'record/demo-summary.json'
    demo = load(ds) if ds.is_file() else None
    man = load(folder / 'record/manifest.json') if (folder / 'record/manifest.json').is_file() else None
    gf = ((man or {}).get('condition') or {}).get('group', {}).get('fields', {}) if man else {}
    sessions[folder.name] = {
        'plan': b['plan_id'], 'item': b.get('item'), 'rerun_of': b.get('rerun_of'),
        'termination': summ.get('termination_reason'), 'steps': summ.get('steps'),
        'git_commit': cond.get('git_commit'), 'git_dirty': cond.get('git_dirty'),
        'model': (cond.get('model') or {}).get('name'), 'proxy_model': (cond.get('proxy_pinned_model') or {}).get('name'),
        'reasoning': (cond.get('reasoning_effort') or {}).get('requested'),
        'run_conditions_sha256': (cond.get('run_conditions') or {}).get('sha256'),
        'final_freeze': b.get('final_freeze_sha256'), 'plan_sha256': b.get('plan_sha256'),
        'criteria_version': cond.get('scenario', {}).get('criteria_version'),
        'criteria_freeze': gf.get('criteria_freeze_sha256'), 'criteria_sha256': gf.get('criteria_sha256'),
        'condition_group': (demo or {}).get('condition_group'), 'mode': b.get('mode'),
        'recorded': demo is not None, 'record_key_clean': ((demo or {}).get('key_scan') or {}).get('clean'),
        'account_label': cond.get('account_label'), 'upstream_config': (cond.get('upstream') or {}).get('config_file'),
        'guardrail_mode': cond.get('guardrail_mode')}
out['session_folders'] = len(sessions)
out['by_plan'] = dict(Counter(s['plan'] for s in sessions.values()))
out['git'] = dict(Counter(f"{s['git_commit'][:7]} dirty={s['git_dirty']}" for s in sessions.values()))
out['git_by_plan'] = {p: dict(Counter(s['git_commit'][:7] for s in sessions.values() if s['plan'] == p)) for p in PLANS}
for k in ('model', 'proxy_model', 'reasoning', 'run_conditions_sha256', 'final_freeze', 'criteria_version',
          'criteria_freeze', 'criteria_sha256', 'upstream_config'):
    out[f'distinct_{k}'] = dict(Counter(str(s[k]) for s in sessions.values()))
out['guardrail_mode_vs_batch_mode'] = dict(Counter(f"{s['mode']}->{s['guardrail_mode']}" for s in sessions.values()))
out['plan_sha256_by_plan'] = {p: sorted({s['plan_sha256'] for s in sessions.values() if s['plan'] == p}) for p in PLANS}
# condition group per scenario+mode
cg = defaultdict(Counter)
for sid, s in sessions.items():
    if s['condition_group']:
        cg[f"{s['item'].rsplit(':', 1)[0]}"][s['condition_group']] += 1
out['condition_groups_per_scenario_mode'] = {k: dict(v) for k, v in sorted(cg.items())}
out['distinct_condition_groups'] = len({s['condition_group'] for s in sessions.values() if s['condition_group']})

# lane log vs folder agreement + key scans
out['folders_not_in_lane_log'] = sorted(set(sessions) - set(lane_sessions))
out['lane_sessions_without_folder'] = sorted(set(lane_sessions) - set(sessions))
out['lane_vs_folder_termination_mismatch'] = sorted(k for k in sessions if k in lane_sessions and
                                                    lane_sessions[k]['termination'] != sessions[k]['termination'])
out['lane_key_scan'] = dict(Counter(f"clean={v['key_scan_clean']} checked={','.join(v['key_values_checked'] or [])}"
                                    for v in lane_sessions.values()))
out['record_key_scan'] = dict(Counter(str(s['record_key_clean']) for s in sessions.values()))
out['unrecorded_sessions'] = sorted(k for k, s in sessions.items() if not s['recorded'])

# per item table
excl = load(ROOT / 'reports/c18-8/exclusions.json')
per_item = {}
for it in items:
    tried = sorted(((k, s) for k, s in sessions.items() if s['item'] == it), key=lambda kv: kv[0])
    rows = []
    for k, s in tried:
        e = excl['sessions'].get(k, {})
        rows.append({'session': k[len(it.split(':')[0]) + 1:][:8], 'plan': s['plan'].replace('demo-main-v1', 'main'),
                     'end': s['termination'], 'steps': s['steps'], 'rerun_of': (s['rerun_of'] or '')[-32:][:8] or None,
                     'commit': s['git_commit'][:7], 'excluded': e.get('excluded'),
                     'replaced_by': (e.get('replaced_by') or '')[-32:][:8] or None})
    per_item[it] = {'state': excl['items'][it]['state'], 'tries': rows}
out['items_missing_from_exclusion_items'] = [i for i in items if i not in excl['items']]
out['item_states'] = dict(Counter(v['state'] for v in per_item.values()))
out['items_with_more_than_one_try'] = {k: v for k, v in per_item.items() if len(v['tries']) > 1}
out['items_without_valid'] = {k: v for k, v in per_item.items() if v['state'] != 'valid'}
Path(sys.argv[1]).write_text(json.dumps({'summary': out, 'per_item': per_item}, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
