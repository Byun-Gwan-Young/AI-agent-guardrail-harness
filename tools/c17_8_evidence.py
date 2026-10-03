"""C-17-8 evidence, from files only (no network; no model reasoning text is read or written).

search: the PM search probe search-probe-46ec37a0… (2026-10-02) — the arXiv and Tavily shape comparison against the
        fixtures as committed before C-17-8 and as they are now, and the D-11 secret scan of the probe folder before it
        is committed (patterns, the Tavily pattern, and the TAVILY_API_KEY value when it is set here).
models: the PM gateway probes behind DM-57 (gateway-probe-a41f8d51… tools, -44ec8e43… strict, -e38debde… nano,
        -8f022e0a… / -2992b509… gpt-oss 404): every value DM-57 states, read again and compared; the 30-step cost
        conversion with the A-1-v4 token counts; every gpt-oss-120b reference at the C-17-8 base commit, classified,
        and what is left now; the D-11 secret scan of the five probe folders (KMU_API_KEY value when set here).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_session import SEARCH_KEY_ENVS, SEARCH_SECRET_PATTERNS, secret_scan  # noqa: E402
from tools import probe_search  # noqa: E402

GATEWAY = ROOT / 'runs/gateway-probes'
PROBES = {'tools': 'gateway-probe-a41f8d517c7d4772a7ef72720f83cc48',
          'strict': 'gateway-probe-44ec8e433e484bdca241870732522a6a',
          'nano': 'gateway-probe-e38debdea39e4facbe74808762aec984',
          'gpt_oss_strict': 'gateway-probe-8f022e0a96b845afbc433e48f2b14140',
          'gpt_oss_general': 'gateway-probe-2992b509a32a4127a715934f575a5260'}
CANDIDATES = ('glm-5.3-flash', 'qwen3.8-flash', 'gpt-5.4-nano')
GPT_OSS = 'accounts/fireworks/models/gpt-oss-120b'
# DM-57 as the guideline states it (2026-10-03); compared, never used to fill a value.
DM57 = {'rates': {'glm-5.3-flash': [150, 500], 'qwen3.8-flash': [150, 470], 'gpt-5.4-nano': [200, 1250]},
        'thirty_step_credits': {'glm-5.3-flash': 120, 'qwen3.8-flash': 117, 'gpt-5.4-nano': 222},
        'strict_final_completion_tokens': {'qwen3.8-flash': 5239, 'glm-5.3-flash': 204, 'gpt-5.4-nano': 376},
        'tool_calls_per_response': [3, 4], 'second_strict_cached_tokens': [1024, 1088]}
# A-1-v4 (30 steps): the token counts DM-57 ② converts with (docs/design/demo-budget.json rate_check).
A1V4_TOKENS = ('A-1-v4-e174aafe805b4f59bb62d7c95716b8b7', 444636, 106866)
BASE = '4d425e5'  # the last commit before C-17-8
SEARCH_PROBE = ROOT / 'runs/search-probes/search-probe-46ec37a046664b988be9e3075ce43c89'
FIXTURES = {'tavily': 'tests/fixtures/search/tavily-search-200.json', 'arxiv': 'tests/fixtures/search/arxiv-query-200.xml'}
RESPONSES = {'tavily': 'tavily-response.json', 'arxiv': 'arxiv-response.xml'}
# The fixtures as they were when the probe ran (last commit before C-17-8).
BEFORE = '4d425e5'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def committed(revision, path):
    return subprocess.run(['git', 'show', revision + ':' + path], cwd=ROOT, capture_output=True, check=True).stdout


def search_evidence():
    result = load(SEARCH_PROBE / 'result.json')
    providers = {}
    for provider, fixture in FIXTURES.items():
        live = (SEARCH_PROBE / RESPONSES[provider]).read_bytes()
        recorded = result['providers'][provider]
        providers[provider] = {
            'http_status': recorded['http_status'], 'normalized': recorded['normalized'],
            'probe_recorded_shape': recorded['shape'],
            'shape_against_fixture_before': probe_search.compare(provider, live, committed(BEFORE, fixture)),
            'shape_against_fixture_now': probe_search.compare(provider, live, (ROOT / fixture).read_bytes())}
    return {'folder': SEARCH_PROBE.relative_to(ROOT).as_posix(), 'probe_id': result['probe_id'],
            'requests_sent': result['requests_sent'], 'all_ok_recorded': result['all_ok'], 'providers': providers,
            'secret_scan': secret_scan([SEARCH_PROBE], set(SEARCH_KEY_ENVS), SEARCH_SECRET_PATTERNS)}


def rows(name):
    result = load(GATEWAY / PROBES[name] / 'result.json')
    out = []
    for item in result['results']:
        usage = item.get('usage') or {}
        out.append({'model': item.get('model') or result.get('model'), 'variant': item['variant'],
                    'http_status': item.get('http_status'), 'finish_reason': item.get('finish_reason'),
                    'error_message': item.get('error_message'), 'tool_calls': len(item.get('tool_calls') or []),
                    'contract_valid': item.get('contract_valid'), 'prompt_tokens': usage.get('prompt_tokens'),
                    'completion_tokens': usage.get('completion_tokens'),
                    'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                    'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens'),
                    'credits': (item.get('credits') or {}).get('value'),
                    'credits_used_after': (item.get('credits') or {}).get('used_after')})
    return {'folder': (GATEWAY / PROBES[name]).relative_to(ROOT).as_posix(), 'created_at': result.get('created_at'),
            'scenario_id': result.get('scenario_id'), 'requests': out,
            'token_rates': {m: v.get('token_rates') for m, v in (result.get('model_summary') or {}).items()}}


def one(requests, model, variant):
    return next(r for r in requests if r['model'] == model and r['variant'] == variant)


def model_evidence():
    probes = {name: rows(name) for name in PROBES}
    tools, strict = probes['tools']['requests'], probes['strict']['requests']
    rates = {m: [probes['tools']['token_rates'][m]['credits_per_million_prompt_tokens'],
                 probes['tools']['token_rates'][m]['credits_per_million_completion_tokens']] for m in CANDIDATES}
    _, prompt, completion = A1V4_TOKENS
    thirty = {m: round((prompt * rates[m][0] + completion * rates[m][1]) / 1e6, 2) for m in CANDIDATES}
    calls = {m: one(tools, m, 'v8-tools-reasoning-high')['tool_calls'] for m in CANDIDATES}
    no_enums = {m: one(strict, m, 'v3-final-strict-no-enums') for m in CANDIDATES}
    enums = {m: one(strict, m, 'v3-final-strict-enums') for m in CANDIDATES}
    gate = {m: {'tools_reasoning_high_200_with_tool_calls': one(tools, m, 'v8-tools-reasoning-high')['http_status'] == 200
                                                            and calls[m] > 0,
                'strict_no_enums_200_contract_valid': no_enums[m]['http_status'] == 200 and no_enums[m]['contract_valid'] is True,
                'strict_enums_200_contract_valid': enums[m]['http_status'] == 200 and enums[m]['contract_valid'] is True}
            for m in CANDIDATES}
    nano_alone = one(probes['nano']['requests'], 'gpt-5.4-nano', 'v8-tools-reasoning-high')
    gpt_oss = [dict(r, probe=name) for name in ('gpt_oss_strict', 'gpt_oss_general') for r in probes[name]['requests']]
    cached = {m: enums[m]['cached_tokens'] for m in CANDIDATES}
    checks = {
        'gate_1_all_pass': all(all(v.values()) for v in gate.values()),
        'rates': {m: {'probe': rates[m], 'dm57': DM57['rates'][m], 'same': rates[m] == DM57['rates'][m]} for m in CANDIDATES},
        'nano_alone_rates': probes['nano']['token_rates']['gpt-5.4-nano'],
        'thirty_step_credits': {m: {'computed': thirty[m], 'dm57_about': DM57['thirty_step_credits'][m],
                                    # DM-57 writes these as "약" (about): within one credit counts as the same.
                                    'within_one_credit': abs(thirty[m] - DM57['thirty_step_credits'][m]) < 1}
                                for m in CANDIDATES},
        'strict_final_completion_tokens': {m: {'probe': no_enums[m]['completion_tokens'],
                                               'dm57': DM57['strict_final_completion_tokens'][m],
                                               'same': no_enums[m]['completion_tokens'] == DM57['strict_final_completion_tokens'][m]}
                                           for m in CANDIDATES},
        'tool_calls_per_response': {'probe': calls, 'dm57_range': DM57['tool_calls_per_response'],
                                    'within': all(DM57['tool_calls_per_response'][0] <= c <= DM57['tool_calls_per_response'][1]
                                                  for c in calls.values()),
                                    'nano_alone_probe': nano_alone['tool_calls']},
        'second_strict_request_cached_tokens': {'probe': cached, 'dm57_range': DM57['second_strict_cached_tokens'],
                                                'models_in_range': sorted(m for m, c in cached.items() if c and
                                                                          DM57['second_strict_cached_tokens'][0] <= c
                                                                          <= DM57['second_strict_cached_tokens'][1])},
        'gpt_oss_404': {'requests': [{k: r[k] for k in ('probe', 'model', 'variant', 'http_status', 'error_message')}
                                     for r in gpt_oss],
                        'all_404_model_not_found': all(r['http_status'] == 404 and 'not found' in (r['error_message'] or '')
                                                       for r in gpt_oss)},
        # The strict probe solves rates from its two requests, but the second one had cached prompt tokens, so its
        # solution is not a price; DM-57 takes the rates from the tool probe (no cached tokens there).
        'strict_probe_token_rates_not_prices': probes['strict']['token_rates'],
        'model_list_change': 'not in these probe files (the PM read /models/); recorded from DM-57 only'}
    checks['all_same_as_dm57'] = (checks['gate_1_all_pass'] and all(v['same'] for v in checks['rates'].values())
                                  and all(v['within_one_credit'] for v in checks['thirty_step_credits'].values())
                                  and all(v['same'] for v in checks['strict_final_completion_tokens'].values())
                                  and checks['tool_calls_per_response']['within']
                                  and checks['gpt_oss_404']['all_404_model_not_found'])
    last = max((r for p in probes.values() for r in p['requests'] if r['credits_used_after'] is not None),
               key=lambda r: r['credits_used_after'])
    return {'probes': probes, 'gate_1': gate, 'checks': checks,
            'a1v4_tokens': {'session': A1V4_TOKENS[0], 'prompt': prompt, 'completion': completion,
                            'source': 'docs/design/demo-budget.json rate_check (proxy log usage)'},
            'monthly_used_after_last_probe_request': last['credits_used_after'],
            'secret_scan': secret_scan([GATEWAY / f for f in PROBES.values()], {'KMU_API_KEY'})}


# Where a gpt-oss-120b reference lives decides what C-17-8 does with it (guideline C-17-8 part 2).
CLASSES = (('demo', ('guardrail-deadlock-v0.3-kmu.yaml', 'guardrail-deadlock-v0.3-kmu-block.yaml',
                     'docs/design/demo-scenarios.md')),
           ('dataset_scenario_c20', ('scenarios/', 'guardrail-deadlock-v0.2-kmu.yaml')),
           ('record', ('logs/', 'runs/', 'reports/', 'docs/', 'tests/', 'tools/analyze_session.py',
                       'tools/c17_8_evidence.py', 'experiments/probe_strict_output.py', 'test.py', 'deadlock_test.py')))
NOTES = {'guardrail-deadlock-v0.2-kmu.yaml': 'header comment; byte-protected (C-17-1), changed with the dataset model (C-20)',
         'tools/analyze_session.py': 'price table for the recorded gpt-oss sessions; a glm price is a PM decision (C-17-7)',
         'experiments/probe_strict_output.py': 'Groq-era strict probe (G0-3); Groq clean-up after the demo track',
         'test.py': 'Groq-era script; Groq clean-up after the demo track',
         'deadlock_test.py': 'Groq-era script; Groq clean-up after the demo track',
         'tests/': 'constants and C-17 fixtures (TEST-T1-v2, TEST-T2-v2, the DM-37 copy of A-1-v4) kept as written',
         'docs/design/demo-scenarios.md': 'C-18 follows its common conditions line',
         'tools/c17_8_evidence.py': 'this script (the probe evidence names the removed model)'}


def classify(path):
    return next(name for name, prefixes in CLASSES if any(path == p or path.startswith(p) for p in prefixes))


def references(revision=None):
    command = ['git', 'grep', '-n', '-I', 'gpt-oss'] + ([revision] if revision else []) + ['--']
    lines = subprocess.run(command, cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    found = []
    for line in lines:
        if revision:
            line = line.split(':', 1)[1]
        path, number, _ = line.split(':', 2)
        found.append((path, int(number)))
    return found


def gpt_oss_evidence():
    def table(found):
        by_class = {}
        for path, number in found:
            kind = classify(path)
            if path.startswith(('logs/', 'runs/', 'reports/')):
                by_class.setdefault(kind, {}).setdefault(path.split('/')[0] + '/ (files)', set()).add(path)
            else:
                by_class.setdefault(kind, {}).setdefault(path, set()).add(number)
        return {kind: {k: (len(v) if k.endswith('(files)') else sorted(v)) for k, v in sorted(group.items())}
                for kind, group in by_class.items()}
    return {'base_commit': BASE, 'at_base': table(references(BASE)), 'now_tracked': table(references()),
            'notes': NOTES,
            'rule': 'demo = used by demo runs (replaced in C-17-8); dataset_scenario_c20 = dataset path, a new '
                    'scenario version with the dataset model (C-20); record = recorded sessions, reports, decisions, '
                    'test fixtures and constants, Groq-era scripts (left as they are)'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part', choices=('search', 'models'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.part == 'models':
        evidence = {'dm57': model_evidence(), 'gpt_oss_references': gpt_oss_evidence()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        checks = evidence['dm57']['checks']
        print(json.dumps({'all_same_as_dm57': checks['all_same_as_dm57'],
                          'thirty_step_credits': {m: v['computed'] for m, v in checks['thirty_step_credits'].items()},
                          'cached_in_range': checks['second_strict_request_cached_tokens']['models_in_range'],
                          'monthly_used_after_last_probe_request': evidence['dm57']['monthly_used_after_last_probe_request'],
                          'gpt_oss_now_demo': evidence['gpt_oss_references']['now_tracked'].get('demo'),
                          'secret_scan': {k: evidence['dm57']['secret_scan'][k] for k in
                                          ('files_scanned', 'environment_variables_checked', 'clean')}},
                         ensure_ascii=False, indent=1))
        return 0 if evidence['dm57']['secret_scan']['clean'] else 2
    evidence = search_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    arxiv = evidence['providers']['arxiv']
    print(json.dumps({'arxiv_missing_before': arxiv['shape_against_fixture_before']['missing_in_response'],
                      'arxiv_same_shape_now': arxiv['shape_against_fixture_now']['same_shape'],
                      'tavily_same_shape_now': evidence['providers']['tavily']['shape_against_fixture_now']['same_shape'],
                      'secret_scan': {k: evidence['secret_scan'][k] for k in
                                      ('files_scanned', 'environment_variables_checked', 'clean')}},
                     ensure_ascii=False, indent=1))
    return 0 if evidence['secret_scan']['clean'] else 2


if __name__ == '__main__':
    sys.exit(main())
