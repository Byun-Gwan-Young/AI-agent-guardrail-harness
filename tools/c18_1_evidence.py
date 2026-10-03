"""C-18-1 evidence, from files only (no network; no model reasoning text is read).

prices: the gateway prices of tools/gateway_prices.py read again from the PM probes behind DM-57 / DM-58 ③. Input and output
        prices are the exact solution of two requests per model (probe gateway-probe-a41f8d51…, tools/probe_gateway.py
        token_rates). The glm-5.3-flash cached-input price is solved from the second request of probe
        gateway-probe-44ec8e43… (1,088 of 1,094 prompt tokens cached), with the input and output prices above:
            cached_rate = (credits - (prompt - cached) x prompt_rate - completion x completion_rate) / cached
        and the first request of the same probe (no cached tokens) is used as a check of the two prices.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import gateway_prices  # noqa: E402
from tools.probe_gateway import token_rates  # noqa: E402

GATEWAY = ROOT / 'runs/gateway-probes'
TOOLS_PROBE = 'gateway-probe-a41f8d517c7d4772a7ef72720f83cc48'
STRICT_PROBE = 'gateway-probe-44ec8e433e484bdca241870732522a6a'
CANDIDATES = ('glm-5.3-flash', 'qwen3.8-flash', 'gpt-5.4-nano')
GLM = 'glm-5.3-flash'


def probe_results(name):
    return json.loads((GATEWAY / name / 'result.json').read_text(encoding='utf-8'))['results']


def request_row(r):
    usage = r.get('usage') or {}
    return {'variant': r['variant'], 'prompt_tokens': usage.get('prompt_tokens'),
            'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens'),
            'completion_tokens': usage.get('completion_tokens'), 'credits': (r.get('credits') or {}).get('value')}


def prices():
    tools = probe_results(TOOLS_PROBE)
    solved = {m: token_rates([r for r in tools if r.get('model') == m and r.get('sent', True)]) for m in CANDIDATES}
    rates = {m: (s['credits_per_million_prompt_tokens'], s['credits_per_million_completion_tokens'])
             for m, s in solved.items()}
    strict = [request_row(r) for r in probe_results(STRICT_PROBE) if r.get('model') == GLM and r.get('sent', True)]
    prompt_rate, completion_rate = (v / 1e6 for v in rates[GLM])
    checks = []
    for row in strict:
        uncached = row['prompt_tokens'] - row['cached_tokens']
        rest = row['credits'] - uncached * prompt_rate - row['completion_tokens'] * completion_rate
        checks.append({**row, 'credits_without_cached_part': round(row['credits'] - rest, 10),
                       'cached_part': round(rest, 10),
                       'cached_rate_per_million': (round(rest / row['cached_tokens'] * 1e6, 6)
                                                   if row['cached_tokens'] else None)})
    no_cache = [c for c in checks if not c['cached_tokens']]
    cached = [c for c in checks if c['cached_tokens']]
    table = gateway_prices.CREDITS_PER_MILLION
    return {
        'tools_probe': TOOLS_PROBE, 'strict_probe': STRICT_PROBE,
        'solved_input_output': solved,
        'glm_strict_requests': checks,
        'glm_no_cache_check': {'requests': len(no_cache),
                               'residual_credits': [c['cached_part'] for c in no_cache],
                               'prices_reproduce_credits': all(abs(c['cached_part']) < 1e-9 for c in no_cache)},
        'glm_cached_rate_per_million': cached[0]['cached_rate_per_million'] if len(cached) == 1 else None,
        'formula': 'cached_rate = (credits - (prompt - cached) x prompt_rate - completion x completion_rate) / cached',
        'table_matches': {m: {'prompt': table[m]['prompt'] == round(rates[m][0], 6),
                              'completion': table[m]['completion'] == round(rates[m][1], 6)} for m in CANDIDATES}
                         | {GLM + ' cached_prompt': len(cached) == 1 and
                            table[GLM]['cached_prompt'] == round(cached[0]['cached_rate_per_million'], 6)},
        'limits': ['each price is the exact solution of one or two requests; no third request checks it',
                   'the cached price is solved from one request; the gateway documentation was not checked']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part', choices=('prices',))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prices()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
