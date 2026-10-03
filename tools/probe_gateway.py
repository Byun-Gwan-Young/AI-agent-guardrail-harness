"""User-run provider probe for the configured upstream (D-27 gateway). Never imported by the runner.

Builds requests from the same code the runner uses: the v8 role system message, the runner's tool
definitions and the output-contract-v2 strict response format. Variant 1 is sent by default;
variants 2 and 3 are opt-in and differ only in reasoning_effort, so their reasoning_tokens can be
compared to see whether the gateway forwards that field. The opt-in reasoning set (C-11) sends one
multi-step arithmetic question four times: without tools at low/high, and with the runner's tools at
low/high. A large low/high gap without tools and a small one with tools is consistent with the gateway
dropping reasoning_effort when tools are present; the probe reports numbers only and decides nothing. HTTP uses the standard library only.
Model comparison (C-16, DM-12): --model (repeatable) sends the same requests to each named model — by default a
short tool-free request and the runner's tool request at the scenario's reasoning_effort — and reports tokens,
reasoning_tokens, whether a tool call came back and the credit difference per request. --list-models prints the
gateway's model IDs. Which models join the demo is decided by the PM.
Closed-list strict probe (C-17-7, DM-20, DM-40): --with-v3-strict takes a scenario-v2 dialogue task as --scenario and
sends its final output-contract-v3 request twice, once with the closed lists as enums in the strict schema
(provider_strict) and once without them (after_receipt), the two request shapes the dialogue runner can send.
Error bodies are read in the OpenAI shape ({"error": {...}}) and the gateway's own shape ({"detail": {...}}).
The API key is read from the environment variable named in the proxy config and never written.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiment_config import load_config, upstream
from experiments.dialogue_contract import for_dialogue_scenario
from experiments.dialogue_runner import SentContract
from experiments.issue_contract import V2, for_scenario
from experiments.run_scenario import Workspace, role_system_message, safe_path, schema_instructions
from experiments.step_execution import PROTOCOL_V8, PROTOCOL_V10, call_budget, final_instruction, harness_facts
from scenario_schema import load_scenario as load_scenario_file, resolve_run_conditions
from tools.probe_gateway_support import EXCERPT_CHARS, default_user_agent, redact

DEFAULT_SCENARIO = ROOT / 'scenarios/A-1-v3-ambiguous-task-query.yaml'
DEFAULT_CONFIG = ROOT / 'guardrail-deadlock-v0.2-kmu.yaml'
FINAL, TOOLS_LOW, TOOLS_HIGH = 'v8-final-strict', 'v8-tools-reasoning-low', 'v8-tools-reasoning-high'
CREDITS_PATH = '/credits/'
# The /credits/ body nests usage; the first field present is used and named in the result (C-11).
CREDIT_USED_FIELDS = (('monthly_allocated', 'used'), ('total', 'used'))
REASON_NO_TOOLS_LOW, REASON_NO_TOOLS_HIGH = 'reasoning-no-tools-low', 'reasoning-no-tools-high'
REASON_TOOLS_LOW, REASON_TOOLS_HIGH = 'reasoning-tools-low', 'reasoning-tools-high'
REASONING_SET = (REASON_NO_TOOLS_LOW, REASON_NO_TOOLS_HIGH, REASON_TOOLS_LOW, REASON_TOOLS_HIGH)
SHORT = 'short-no-tools'
SHORT_PROMPT = 'Reply with the single word OK.'
MODELS_PATH = '/models/'
# The two final-request shapes of a dialogue task (DM-20): closed lists sent as enums, or checked after receipt.
V3_STRICT_ENUMS, V3_STRICT_NO_ENUMS = 'v3-final-strict-enums', 'v3-final-strict-no-enums'
V3_STRICT = {V3_STRICT_NO_ENUMS: 'after_receipt', V3_STRICT_ENUMS: 'provider_strict'}
STRICT_VARIANTS = (FINAL, *V3_STRICT)
REASONING_QUESTION = ('How many integers n with 1 <= n <= 1000 are divisible by 3 or 5 but not by 7? '
                      'Work it out, then reply with the integer only. Do not call any tool.')


def load_scenario(path):
    """The scenario as the runner sends it: a demo scenario's model and reasoning effort come from its run-conditions
    file (DM-57, C-17-8), so a probe of a demo scenario uses the same values as its runs."""
    return resolve_run_conditions(load_scenario_file(path), ROOT)[0]


def role_tools(scenario, agent, workspace):
    """The exact tool definitions the runner sends, built from the scenario's own tool functions."""
    from autogen_core.tools import FunctionTool
    from autogen_ext.models.openai._openai_client import convert_tools
    functions = Workspace(scenario, workspace).tools(agent)
    return convert_tools([FunctionTool(f, description=f.__doc__) for f in functions]), [f.__name__ for f in functions]


def request_bodies(scenario, agent, workspace, variants):
    contract = for_scenario(V2, scenario)
    tools, names = role_tools(scenario, agent, workspace)
    system = role_system_message(agent, names, scenario, schema_instructions(contract), facts=True)
    records = [{'task': scenario.task, 'initial_issue_ids': scenario.initial_issue_ids}]
    context = json.dumps({'task': scenario.task, 'monitored_paths': scenario.monitored_paths,
                          'registered_tools': names, 'initial_issue_ids': scenario.initial_issue_ids,
                          'call_budget': call_budget(1, scenario.termination.max_llm_calls_per_step)},
                         ensure_ascii=False)
    common = {'model': scenario.model, 'temperature': scenario.temperature,
              'max_tokens': scenario.max_tokens, 'stream': False}
    bodies = {}
    for variant in variants:
        if variant == SHORT:
            # Plain request: no tools, no response_format, no reasoning_effort, so any chat model can answer it.
            bodies[variant] = {**common, 'messages': [{'role': 'user', 'content': SHORT_PROMPT}]}
        elif variant == FINAL:
            bodies[variant] = {**common, 'reasoning_effort': 'low',
                               'messages': [{'role': 'system', 'content': final_instruction(contract)},
                                            {'role': 'user', 'content': json.dumps({'observed_records': records},
                                                                                   ensure_ascii=False)}],
                               'response_format': contract.response_format()}
        elif variant in REASONING_SET:
            # Same question and settings; only reasoning_effort and the presence of tools differ.
            body = {**common, 'reasoning_effort': 'high' if variant.endswith('-high') else 'low',
                    'messages': [{'role': 'user', 'content': REASONING_QUESTION}]}
            if variant in (REASON_TOOLS_LOW, REASON_TOOLS_HIGH):
                body.update(tools=copy.deepcopy(tools), tool_choice='auto')
            bodies[variant] = body
        else:
            bodies[variant] = {**common, 'reasoning_effort': 'high' if variant == TOOLS_HIGH else 'low',
                               'messages': [{'role': 'system', 'content': system},
                                            {'role': 'user', 'content': context}],
                               'tools': copy.deepcopy(tools), 'tool_choice': 'auto'}
    return bodies, contract


def is_dialogue(scenario):
    return scenario.schema_version != 'scenario-v1' and scenario.task_kind == 'dialogue'


def dialogue_request_bodies(scenario, variants):
    """The dialogue runner's final request (v10 sends reasoning_effort on every call) in each closed-list mode.

    Same system text, schema and settings as the runner's final call; the observed record is the task and its
    initial issue IDs only, as in the v2 final variant. Returns the bodies and the contract each one is checked with.
    """
    unsupported = [v for v in variants if v not in V3_STRICT]
    if unsupported:
        raise ValueError('A dialogue scenario takes only the v3 strict variants, not: ' + ', '.join(unsupported))
    contract = for_dialogue_scenario(scenario)
    records = [{'task': scenario.task, 'initial_issue_ids': scenario.initial_issue_ids}]
    bodies = {}
    for variant in variants:
        sent = SentContract(contract, V3_STRICT[variant])
        bodies[variant] = {'model': scenario.model, 'temperature': scenario.temperature,
                           'max_tokens': scenario.max_tokens, 'stream': False,
                           'reasoning_effort': scenario.reasoning_effort,
                           'messages': [{'role': 'system', 'content': final_instruction(contract)},
                                        {'role': 'user', 'content': json.dumps({'observed_records': records},
                                                                               ensure_ascii=False)}],
                           'response_format': sent.response_format()}
    return bodies, contract


def error_text(body):
    """The error message of an error body: OpenAI {"error": {"message"}} or the gateway's {"detail": {"message"}}.

    The probe of 2026-09-29 (gateway-probe-9d2b2053…) got the gateway shape for its HTTP 400s and kept no message.
    """
    for field in ('error', 'detail'):
        value = body.get(field)
        if isinstance(value, dict) and value.get('message') is not None:
            return str(value['message'])
        if value is not None:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return None


def send(url, api_key, body, user_agent, method='POST'):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json',
                 'User-Agent': user_agent})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8', 'replace')


def credits(base_url, api_key, user_agent, transport):
    status, text = transport(base_url + CREDITS_PATH, api_key, None, user_agent, 'GET')
    try:
        return {'status': status, 'body': json.loads(text)}
    except ValueError:
        return {'status': status, 'body': None, 'excerpt': text[:EXCERPT_CHARS]}


def used_credits(snapshot):
    """(value, 'parent.used') from the first CREDIT_USED_FIELDS entry present, else (None, None)."""
    body = (snapshot or {}).get('body')
    for parent, field in CREDIT_USED_FIELDS:
        section = body.get(parent) if isinstance(body, dict) else None
        if isinstance(section, dict) and isinstance(section.get(field), (int, float)):
            return section[field], parent + '.' + field
    return None, None


def credit_delta(before, after):
    (start, start_field), (end, end_field) = used_credits(before), used_credits(after)
    if start is None or end is None:
        return {'value': None, 'status': 'unmeasured', 'field': start_field or end_field,
                'reason': 'none of ' + ', '.join(p + '.' + f for p, f in CREDIT_USED_FIELDS)
                          + ' present in both /credits/ responses'}
    if start_field != end_field:
        return {'value': None, 'status': 'unmeasured', 'field': None,
                'reason': 'before and after used different fields: ' + start_field + ', ' + end_field}
    return {'value': round(end - start, 10), 'status': 'measured', 'field': start_field,
            'used_before': start, 'used_after': end}


def list_models(base_url, api_key, user_agent, transport=send):
    """Model IDs from the gateway's /models/ listing (OpenAI list shape); nothing else is kept."""
    status, text = transport(base_url + MODELS_PATH, api_key, None, user_agent, 'GET')
    try:
        data = json.loads(text).get('data')
    except (ValueError, AttributeError):
        data = None
    ids = sorted(m['id'] for m in data if isinstance(m, dict) and isinstance(m.get('id'), str)) \
        if isinstance(data, list) else None
    return {'status': status, 'model_ids': ids}


def token_rates(results):
    """Credits per 1M prompt and completion tokens for one model, from two measured requests.

    Solves credits = prompt * a + completion * b exactly (C-11 found this form matched to the last digit).
    Two requests give one solution with no error estimate; it is reported as such, never as a verified price.
    """
    rows = [(r['usage'].get('prompt_tokens'), r['usage'].get('completion_tokens'), r['credits']['value'])
            for r in results if (r.get('credits') or {}).get('status') == 'measured' and isinstance(r.get('usage'), dict)]
    rows = [row for row in rows if all(isinstance(v, (int, float)) for v in row)]
    if len(rows) < 2:
        return {'status': 'unmeasured', 'reason': 'fewer than two requests with usage and measured credits'}
    (p1, c1, k1), (p2, c2, k2) = rows[:2]
    det = p1 * c2 - p2 * c1
    if det == 0:
        return {'status': 'unmeasured', 'reason': 'the two requests have proportional token counts'}
    prompt_rate, completion_rate = (k1 * c2 - k2 * c1) / det, (p1 * k2 - p2 * k1) / det
    return {'status': 'solved_from_two_requests', 'requests_used': 2,
            'credits_per_million_prompt_tokens': round(prompt_rate * 1e6, 6),
            'credits_per_million_completion_tokens': round(completion_rate * 1e6, 6),
            'note': 'Exact solution of two equations; not checked against a third request. Cached tokens not separated.'}


def model_summary(results):
    """Per model: status, tokens, reasoning_tokens, tool call returned, credits, and solved token rates."""
    summary = {}
    for model in dict.fromkeys(r['model'] for r in results if 'model' in r):
        rows = [r for r in results if r.get('model') == model and r.get('sent', True)]
        summary[model] = {
            'requests': [{'variant': r['variant'], 'http_status': r.get('http_status'),
                          'error_message': r.get('error_message'),
                          'prompt_tokens': (r.get('usage') or {}).get('prompt_tokens'),
                          'completion_tokens': (r.get('usage') or {}).get('completion_tokens'),
                          'reasoning_tokens': ((r.get('usage') or {}).get('completion_tokens_details') or {})
                                              .get('reasoning_tokens'),
                          'tool_call_returned': None if r.get('tool_calls') is None else bool(r['tool_calls']),
                          'credits': (r.get('credits') or {}).get('value')} for r in rows],
            'token_rates': token_rates(rows)}
    return summary


def reasoning_comparison(results):
    """reasoning_tokens of the reasoning set side by side; high minus low with and without tools."""
    results = [r for r in results if r['variant'] in REASONING_SET and r.get('sent', True)]
    tokens = {r['variant']: ((r.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
              for r in results}
    if not tokens:
        return None
    def gap(high, low):
        return None if tokens.get(high) is None or tokens.get(low) is None else tokens[high] - tokens[low]
    return {'reasoning_tokens': tokens,
            'high_minus_low_without_tools': gap(REASON_NO_TOOLS_HIGH, REASON_NO_TOOLS_LOW),
            'high_minus_low_with_tools': gap(REASON_TOOLS_HIGH, REASON_TOOLS_LOW),
            'tool_calls_made': {r['variant']: r.get('tool_calls') for r in results},
            'note': 'One request each. Numbers only; whether the gateway drops reasoning_effort is decided by the PM.'}


def closed_list_comparison(results):
    """The two closed-list modes side by side (DM-20). One request each; which mode the demo uses is the PM's (DM-40)."""
    rows = {}
    for r in results:
        if r['variant'] in V3_STRICT and r.get('sent', True):
            rows.setdefault(r.get('model'), {})[V3_STRICT[r['variant']]] = {
                k: r.get(k) for k in ('http_status', 'error_message', 'finish_reason', 'contract_valid',
                                      'contract_violation')}
    if not rows:
        return None
    return {'by_model': rows if any(m is not None for m in rows) else rows[None],
            'note': 'One request per mode. provider_strict sends the closed lists as enums; after_receipt sends the '
                    'same schema without them and checks after receipt. DM-20 is decided by the PM (DM-40).'}


def assess(contract, variant, status, body):
    result = {'http_status': status, 'error_message': None, 'finish_reason': None, 'usage': None,
              'tool_calls': None, 'contract_valid': None, 'contract_violation': None,
              'reasoning_content_present': None}
    if not isinstance(body, dict):
        result['error_message'] = 'non-JSON response'
        return result
    result['usage'] = body.get('usage')
    result['error_message'] = error_text(body)
    if status != 200:
        return result
    try:
        choice = body['choices'][0]
        message = choice['message']
    except (KeyError, IndexError, TypeError):
        result['error_message'] = 'no choices in response'
        return result
    result['finish_reason'] = choice.get('finish_reason')
    result['reasoning_content_present'] = bool(message.get('reasoning_content') or message.get('reasoning'))
    result['tool_calls'] = [{'name': c['function']['name'], 'argument_chars': len(c['function']['arguments'])}
                            for c in message.get('tool_calls') or []]
    if variant not in STRICT_VARIANTS:
        return result
    try:
        contract.parse(message['content'])
        result['contract_valid'] = True
    except (KeyError, TypeError, ValueError) as exc:
        result['contract_valid'] = False
        result['contract_violation'] = getattr(exc, 'code', None) or type(exc).__name__ + ': ' + str(exc)[:200]
    return result


def probe(scenario_path, config_path, variants, output_root, role, api_key=None, transport=send, user_agent=None,
          models=None):
    """api_key=None builds and saves request bodies only (dry run); no network call is made.

    models=None keeps the scenario's model and the original file names. With models, every variant is sent
    once per model; only the 'model' field of the body differs, and files are prefixed with the model slug.
    """
    scenario = load_scenario(scenario_path)
    settings = upstream(load_config(config_path))
    user_agent = user_agent or default_user_agent()
    dialogue = is_dialogue(scenario)
    if dialogue:
        # No workspace, tools or role: only the final request of a dialogue task is probed (C-17-7).
        bodies, contract = dialogue_request_bodies(scenario, variants)
        role = None
    elif any(v in V3_STRICT for v in variants):
        raise ValueError('The v3 strict variants need a scenario-v2 dialogue task as the scenario')
    folder = output_root / ('gateway-probe-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    if not dialogue:
        agent = next(a for a in scenario.agents if a.id == role)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'workspace'
            shutil.copytree(safe_path(ROOT, scenario.fixture_dir), workspace,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            bodies, contract = request_bodies(scenario, agent, workspace, variants)
    endpoint = settings['base_url'] + settings['chat_path']
    results = []
    plan = [(None, v) for v in variants] if models is None else [(m, v) for m in models for v in variants]
    for model, variant in plan:
        body = bodies[variant] if model is None else {**bodies[variant], 'model': model}
        name = variant if model is None else model_slug(model) + '--' + variant
        tag = {} if model is None else {'model': model}
        (folder / (name + '.request.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2),
                                                       encoding='utf-8')
        if api_key is None:
            results.append({'variant': variant, **tag, 'sent': False})
            continue
        before = credits(settings['base_url'], api_key, user_agent, transport)
        try:
            status, text = transport(endpoint, api_key, body, user_agent)
        except (urllib.error.URLError, OSError) as exc:
            results.append({'variant': variant, **tag, 'sent': True, 'transport_error': type(exc).__name__})
            continue
        text = redact(text, api_key)
        (folder / (name + '.response.json')).write_text(text, encoding='utf-8')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        after = credits(settings['base_url'], api_key, user_agent, transport)
        result = {'variant': variant, **tag, 'sent': True, **assess(contract, variant, status, parsed),
                  'credits': credit_delta(before, after)}
        if not isinstance(parsed, dict):
            result['non_json_body_excerpt'] = text[:EXCERPT_CHARS]
        results.append(result)
    report = {'scenario_id': scenario.scenario_id, 'model': scenario.model, 'role': role,
              'config_file': Path(config_path).name, 'endpoint': endpoint,
              'api_key_env': settings['api_key_env'], 'user_agent': user_agent,
              'runner_protocol': PROTOCOL_V10 if dialogue else PROTOCOL_V8, 'output_contract_version': contract.version,
              'allowed_issues_sha256': contract.sha256, 'max_tokens': scenario.max_tokens,
              'created_at': datetime.now(timezone.utc).isoformat(), 'dry_run': api_key is None,
              'note': 'One request per variant does not establish reliability. Compare the '
                      'reasoning_tokens of the two tool variants to see whether reasoning_effort was applied.',
              'results': results, 'reasoning_comparison': reasoning_comparison(results),
              'closed_list_comparison': closed_list_comparison(results) if dialogue else None}
    if models is not None:
        report['models'] = list(models)
        report['model_summary'] = model_summary(results)
    (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder, report


def model_slug(model):
    return ''.join(c if c.isalnum() or c in '.-' else '_' for c in model)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--role', default='developer')
    parser.add_argument('--with-tools-low', action='store_true', help='also send the tool variant (reasoning low)')
    parser.add_argument('--with-tools-high', action='store_true', help='also send the tool variant (reasoning high)')
    parser.add_argument('--with-reasoning-set', action='store_true',
                        help='also send the four reasoning_effort discriminator requests (C-11)')
    parser.add_argument('--with-v3-strict', action='store_true',
                        help='send the dialogue final request with and without closed-list enums (C-17-7, DM-20); '
                             '--scenario must be a scenario-v2 dialogue task. No other variant is sent')
    parser.add_argument('--model', action='append', default=None,
                        help='send the requests to this model (repeatable, C-16). Default variants per model: '
                             'short tool-free request + tool request at the scenario reasoning_effort')
    parser.add_argument('--list-models', action='store_true', help='print the gateway model IDs and exit')
    parser.add_argument('--dry-run', action='store_true', help='build and save request bodies only')
    parser.add_argument('--user-agent', default=None)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'runs/gateway-probes')
    args = parser.parse_args()
    variants = ([FINAL] + [TOOLS_LOW] * args.with_tools_low + [TOOLS_HIGH] * args.with_tools_high
                + list(REASONING_SET) * args.with_reasoning_set)
    if args.with_v3_strict:
        if args.with_tools_low or args.with_tools_high or args.with_reasoning_set:
            parser.error('--with-v3-strict sends only the two v3 strict variants')
        if not is_dialogue(load_scenario(args.scenario)):
            parser.error('--with-v3-strict needs a scenario-v2 dialogue task as --scenario')
        variants = [V3_STRICT_NO_ENUMS, V3_STRICT_ENUMS]
    elif args.model:
        effort = load_scenario(args.scenario).reasoning_effort
        variants = [SHORT, TOOLS_HIGH if effort == 'high' else TOOLS_LOW]
    key = None
    if args.list_models or not args.dry_run:
        name = upstream(load_config(args.config))['api_key_env']
        key = os.environ.get(name)
        if not key:
            parser.error('Set ' + name + ' in the process environment, or use --dry-run')
    if args.list_models:
        listing = list_models(upstream(load_config(args.config))['base_url'], key,
                              args.user_agent or default_user_agent())
        print(json.dumps(listing, ensure_ascii=True, indent=2))
        return 0 if listing['model_ids'] is not None else 1
    folder, report = probe(args.scenario, args.config, variants, args.output_root, args.role, key,
                           user_agent=args.user_agent, models=args.model)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('output:', folder)
    return 0 if report['dry_run'] or all(r.get('http_status') == 200 for r in report['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
