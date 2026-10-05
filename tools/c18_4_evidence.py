"""C-18-4 evidence from the stored T1 trial sessions (DM-67). Read-only: the runner's records and the stored search
responses only, no search, no model call. Model text is not printed: report fields are counted or compared, URLs and
gate reasons are shown.

  mr   DEMO-MR-normal-v1 trial (DM-67 ②): per completion claim, which judge check refused it, before and after the
       URL normalisation (scenario_judges/DEMO-MR-v1.py url_key); search calls against the cap; every cited URL
       against the stored results (exact / normalised / absent); how many result URLs each role's requests carried.
       -> reports/c18-4/mr-normal-diagnosis.json
  cs   DEMO-CS trial pair (DM-67 ①): the recorded claims and the claims judged again with the current judge, which now
       needs the owner role's own verified report. -> reports/c18-4/cs-rejudge.json
  trial  credits the retest plan (batch_plans/demo-trial-c18-4.yaml) is expected to use, from the measured T1 trial
       sessions' committed summaries (record/demo-summary.json). An estimate. -> reports/c18-4/estimate-retest.json
"""
import argparse
import collections
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments import search_tools  # noqa: E402
from tools.rejudge_dialogue import rejudge  # noqa: E402

MR_NORMAL = ROOT / 'runs/demo/DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b'
CS_TRIALS = (ROOT / 'runs/demo/DEMO-CS-normal-v1-47da0f11c48f407abb18959ba283433d',
             ROOT / 'runs/demo/DEMO-CS-stall-v1-89187184d4cb46b09b6e173a1a264ffa')
OUTPUTS = {'mr': ROOT / 'reports/c18-4/mr-normal-diagnosis.json', 'cs': ROOT / 'reports/c18-4/cs-rejudge.json',
           'trial': ROOT / 'reports/c18-4/estimate-retest.json'}
RETEST_PLAN = ROOT / 'batch_plans/demo-trial-c18-4.yaml'
T1_TRIALS = {'DEMO-CS-normal-v1': CS_TRIALS[0].name, 'DEMO-CS-stall-v1': CS_TRIALS[1].name,
             'DEMO-MR-normal-v1': MR_NORMAL.name, 'DEMO-MR-stall-v1': 'DEMO-MR-stall-v1-d454a7cd328e4cbd919539f4ccb60d2a'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def url_count(text, urls):
    """How many of these URLs appear in the text as a whole URL (not as the prefix of a longer one)."""
    return sum(bool(re.search(re.escape(u) + r'(?=$|[\s"\'\\<>)\],])', text)) for u in urls)


def mr_judge():
    spec = importlib.util.spec_from_file_location('demo_mr_judge', ROOT / 'scenario_judges/DEMO-MR-v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mr_diagnosis(run_dir=MR_NORMAL):
    run_dir = Path(run_dir)
    judge = mr_judge()
    steps, summary, conditions = load(run_dir / 'steps.json'), load(run_dir / 'summary.json'), load(run_dir / 'conditions.json')
    records = search_tools.replay_tool_records(run_dir)
    searches = [r for r in records if r['tool'] == 'web_search']
    shown = [r['url'] for c in searches if not c['is_error'] for r in c['search']['results'][:c['search']['results_sent']]]
    shown_keys = {judge.url_key(u): u for u in shown}
    search_settings = (conditions.get('tool_settings') or {}).get('web_search') or {}
    judged = rejudge(run_dir)
    again = {r['step_id']: r for r in judged['steps']}
    claims = []
    for claim in summary['completion_claims']:
        row = again[claim['step_id']]
        claims.append({'step_id': claim['step_id'], 'agent': claim['agent'], 'reasons': claim['reasons'],
                       'recorded_missing': row['recorded_claim_gate']['missing'],
                       'recomputed_missing': row['recomputed_claim_gate']['missing'],
                       'recomputed_result': row['recomputed_claim_gate']['result']})
    cells = collections.OrderedDict()
    deliverables = set()
    for step in steps:
        deliverable = (step['observed_final_report'] or {}).get('deliverable')
        if not deliverable:
            continue
        deliverables.add(json.dumps(deliverable, sort_keys=True, ensure_ascii=False))
        for row in deliverable.get('rows') or []:
            for column, cell in row.items():
                if column == 'product' or cell is None:  # null cell: partial report (C-18-5, DM-72)
                    continue
                url = cell.get('source_url')
                entry = cells.setdefault((row.get('product'), column, url), {'steps': []})
                entry['steps'].append(step['step_id'])
    cell_rows = []
    for (product, column, url), entry in cells.items():
        match = ('exact' if url in shown else 'normalised' if judge.url_key(url) in shown_keys else 'absent')
        cell_rows.append({'cell': f'{product}:{column}', 'source_url': url, 'match': match,
                          'matching_result_url': shown_keys.get(judge.url_key(url)) if match != 'absent' else None,
                          'first_step': entry['steps'][0], 'last_step': entry['steps'][-1],
                          'steps': len(entry['steps'])})
    log = load(run_dir / 'session.json')
    turns = {t['turn']: t for t in log['turns']}
    reach = []
    for step in steps:
        counts = []
        for turn in step['llm_turns']:
            body = json.dumps(turns[turn].get('upstream_request_body') or turns[turn].get('request_body'),
                              ensure_ascii=False)
            counts.append(url_count(body, set(shown)))
        report = step['observed_final_report'] or {}
        carried = json.dumps({k: report.get(k) for k in ('narrative', 'deliverable')}, ensure_ascii=False)
        reach.append({'step_id': step['step_id'], 'agent': step['agent'],
                      'result_urls_in_requests': counts,
                      'result_urls_in_handed_off_fields': url_count(carried, set(shown)),
                      'result_urls_in_info_items': url_count(json.dumps(report.get('info_items'), ensure_ascii=False),
                                                                set(shown))})
    reasons = collections.Counter(m.split(':')[-1] for c in claims for m in c['recomputed_missing'])
    return {'script': 'tools/c18_4_evidence.py mr', 'session_id': run_dir.name,
            'termination_reason': summary['termination_reason'], 'steps': len(steps),
            'search': {'calls': len(searches), 'errors': sum(c['is_error'] for c in searches),
                       'cap': search_settings.get('max_calls_per_session'),
                       'cap_reached': search_settings.get('max_calls_per_session') is not None
                       and len(searches) >= search_settings['max_calls_per_session'],
                       'calls_by_step': dict(collections.Counter(c['step_id'] for c in searches)),
                       'result_urls_shown': len(set(shown))},
            'claims': {'count': len(claims),
                       'recorded_missing_kinds': sorted({m.split(':')[-1] for c in claims for m in c['recorded_missing']}),
                       'accepted_after_normalisation': sum(c['recomputed_result'] == 'resolved'
                                                           and 'not_declarer' not in c['reasons'] for c in claims),
                       'recomputed_missing_kinds': dict(reasons), 'rows': claims},
            'deliverables_distinct': len(deliverables), 'cells': cell_rows,
            'handoff_reach': reach,
            'judge': judged['judge']}


def cs_rejudge(run_dirs=CS_TRIALS):
    rows = []
    for run_dir in run_dirs:
        result = rejudge(run_dir)
        summary = load(Path(run_dir) / 'summary.json')
        rows.append({'session_id': Path(run_dir).name, 'termination_reason': summary['termination_reason'],
                     'judge': result['judge'],
                     'claims': [{'step_id': r['step_id'], 'recorded': r['recorded_claim_gate'],
                                 'recomputed': r['recomputed_claim_gate']}
                                for r in result['steps'] if 'recomputed_claim_gate' in r]})
    return {'script': 'tools/c18_4_evidence.py cs', 'sessions': rows,
            'any_claim_passes_now': any(c['recomputed']['machine_success'] for r in rows for c in r['claims'])}


def retest_estimate(plan_path=RETEST_PLAN, runs=ROOT / 'runs/demo'):
    """Each retest session: its C-18-3 trial value (measured) for reference, and as the upper value the largest
    measured T1 trial session that ran all 30 steps (MR normal), since the changed CS and MR can now run longer."""
    from tools import run_batch
    plan = run_batch.load_plan(plan_path)
    measured = {}
    for scenario_id, session in T1_TRIALS.items():
        summary = load(Path(runs) / session / 'record/demo-summary.json')
        measured[scenario_id] = {'session_id': session, 'steps': summary['steps'],
                                 'termination_reason': summary['termination_reason'],
                                 'credits_measured': summary['credits_measured']['value']}
    full = max((m for m in measured.values() if m['steps'] == 30), key=lambda m: m['credits_measured'])
    rows = []
    for item in plan['items']:
        scenario_id = load_scenario_id(item.scenario)
        rows.append({'item': item.key, 'c18_3_trial': measured[scenario_id], 'high': full['credits_measured']})
    return {'script': 'tools/c18_4_evidence.py trial', 'status': 'estimated', 'plan_id': plan['plan_id'],
            'plan_sha256': plan['plan_sha256'], 'upper_reference': full, 'sessions': rows,
            'lanes': {k: [i.key for i in run_batch.lane_items(plan, k, 2)] for k in (1, 2)},
            'total': {'c18_3_trial_sum': round(sum(r['c18_3_trial']['credits_measured'] for r in rows), 5),
                      'high': round(sum(r['high'] for r in rows), 5)},
            'limits': ['the C-18-3 values are of the scenarios before the C-18-4 changes (CS ended at step 1, MR '
                       'normal ran 30 steps); a retest session can end at any step up to 30',
                       'the upper value is one measured 30-step MR session; a 30-step session with more search text '
                       'in context can cost more']}


def load_scenario_id(path):
    from scenario_schema import load_scenario
    return load_scenario(ROOT / path).scenario_id


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('part', choices=sorted(OUTPUTS))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = {'mr': mr_diagnosis, 'cs': cs_rejudge, 'trial': retest_estimate}[args.part]()
    output = args.output or OUTPUTS[args.part]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
