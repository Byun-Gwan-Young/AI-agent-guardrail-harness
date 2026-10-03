"""Gateway token prices (credits per 1M tokens) and the token x price credit estimate (DM-58 ③, C-18-1).

1 credit = $0.001 on the gateway (C-11). Every price is a solution of PM probe readings, never a guess; a model that is
not listed has no estimate (unmeasured). The cached-input price is known only for glm-5.3-flash (decision 020): for the
other models cached input is charged at the full input price, which is an upper value.

The estimate is an upper value even with a cached price: it is computed from the proxy log usage, and the gateway's
discounts that usage does not show are not modelled. The measured value is the /credits/ difference the runner records
(experiments/gateway_usage.py, manifest credits_measured).
"""

PRICES_VERSION = 'gateway-prices-v1'
GPT_OSS = 'accounts/fireworks/models/gpt-oss-120b'
# credits per 1M tokens: prompt (uncached input), cached_prompt (cached input; None = not known), completion.
CREDITS_PER_MILLION = {
    GPT_OSS: {'prompt': 150, 'cached_prompt': None, 'completion': 600,
              'source': 'C-11: A-1-v3 session credits matched $0.15/$0.60 per 1M x 1000'},
    'glm-5.3-flash': {'prompt': 150, 'cached_prompt': 30, 'completion': 500,
                      'source': 'prompt, completion: probe gateway-probe-a41f8d51 (DM-57); cached_prompt: probe '
                                'gateway-probe-44ec8e43 second request (cached 1,088), decision 020'},
    'qwen3.8-flash': {'prompt': 150, 'cached_prompt': None, 'completion': 470,
                      'source': 'probe gateway-probe-a41f8d51 (DM-57)'},
    'gpt-5.4-nano': {'prompt': 200, 'cached_prompt': None, 'completion': 1250,
                     'source': 'probe gateway-probe-a41f8d51 (DM-57)'},
}


def turn_usage(turn):
    """(prompt, cached, completion, reasoning) of one proxy log turn, or None when its usage is missing."""
    if turn.get('tokens') is None:
        return None
    usage = (turn.get('response_body') or {}).get('usage') or {}
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
    reasoning = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
    return turn.get('prompt_tokens') or 0, cached, turn.get('completion_tokens') or 0, reasoning


def usage_totals(turns):
    """Token sums of the turns with usage, and how many turns had none (they make the totals a lower value)."""
    rows = [turn_usage(t) for t in turns]
    known = [r for r in rows if r is not None]
    return {'prompt': sum(r[0] for r in known), 'cached_prompt': sum(r[1] for r in known),
            'completion': sum(r[2] for r in known), 'reasoning': sum(r[3] for r in known),
            'turns': len(rows), 'usage_missing_turns': len(rows) - len(known)}


def estimate(model, turns):
    """credits_estimated: tokens x price. Unmeasured without a price; incomplete when some turn has no usage."""
    price = CREDITS_PER_MILLION.get(model)
    if price is None:
        return {'status': 'unmeasured', 'value': None, 'model': model, 'prices_version': PRICES_VERSION,
                'reason': 'no price recorded for this model'}
    counts = usage_totals(turns)
    cached_rate = price['cached_prompt'] if price['cached_prompt'] is not None else price['prompt']
    value = ((counts['prompt'] - counts['cached_prompt']) * price['prompt'] + counts['cached_prompt'] * cached_rate
             + counts['completion'] * price['completion']) / 1e6
    return {'status': 'computed' if counts['usage_missing_turns'] == 0 else 'incomplete',
            'value': round(value, 5), 'model': model, 'prices_version': PRICES_VERSION,
            'credits_per_million': {k: price[k] for k in ('prompt', 'cached_prompt', 'completion')},
            'price_source': price['source'], 'tokens': counts,
            'cached_price': 'known' if price['cached_prompt'] is not None else
                            'unknown: cached input charged at the full input price (upper value)',
            'basis': 'proxy log usage x credits per 1M; an upper value (discounts not in the usage are not modelled)'
                     + ('' if counts['usage_missing_turns'] == 0 else '; turns without usage are not counted')}
