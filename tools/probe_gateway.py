"""User-run provider probe for the configured upstream (D-27 gateway). Never imported by the runner.

Builds requests from the same code the runner uses: the v8 role system message, the runner's tool
definitions and the output-contract-v2 strict response format. Variant 1 is sent by default;
variants 2 and 3 are opt-in and differ only in reasoning_effort, so their reasoning_tokens can be
compared to see whether the gateway forwards that field. The opt-in reasoning set (C-11) sends one
multi-step arithmetic question four times: without tools at low/high, and with the runner's tools at
low/high. A large low/high gap without tools and a small one with tools is consistent with the gateway
dropping reasoning_effort when tools are present; the probe reports numbers only and decides nothing. HTTP uses the standard library only.
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
from experiments.issue_contract import V2, for_scenario
from experiments.run_scenario import Workspace, role_system_message, safe_path, schema_instructions
from experiments.step_execution import PROTOCOL_V8, call_budget, final_instruction, harness_facts
from scenario_schema import load_scenario
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
REASONING_QUESTION = ('How many integers n with 1 <= n <= 1000 are divisible by 3 or 5 but not by 7? '
                      'Work it out, then reply with the integer only. Do not call any tool.')


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
        if variant == FINAL:
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


def assess(contract, variant, status, body):
    result = {'http_status': status, 'error_message': None, 'finish_reason': None, 'usage': None,
              'tool_calls': None, 'contract_valid': None, 'contract_violation': None,
              'reasoning_content_present': None}
    if not isinstance(body, dict):
        result['error_message'] = 'non-JSON response'
        return result
    result['usage'] = body.get('usage')
    error = body.get('error')
    if error is not None:
        result['error_message'] = error.get('message') if isinstance(error, dict) else str(error)
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
    if variant != FINAL:
        return result
    try:
        contract.parse(message['content'])
        result['contract_valid'] = True
    except (KeyError, TypeError, ValueError) as exc:
        result['contract_valid'] = False
        result['contract_violation'] = getattr(exc, 'code', None) or type(exc).__name__ + ': ' + str(exc)[:200]
    return result


def probe(scenario_path, config_path, variants, output_root, role, api_key=None, transport=send, user_agent=None):
    """api_key=None builds and saves request bodies only (dry run); no network call is made."""
    scenario = load_scenario(scenario_path)
    settings = upstream(load_config(config_path))
    agent = next(a for a in scenario.agents if a.id == role)
    user_agent = user_agent or default_user_agent()
    folder = output_root / ('gateway-probe-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory) / 'workspace'
        shutil.copytree(safe_path(ROOT, scenario.fixture_dir), workspace,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        bodies, contract = request_bodies(scenario, agent, workspace, variants)
    endpoint = settings['base_url'] + settings['chat_path']
    results = []
    for variant in variants:
        body = bodies[variant]
        (folder / (variant + '.request.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2),
                                                          encoding='utf-8')
        if api_key is None:
            results.append({'variant': variant, 'sent': False})
            continue
        before = credits(settings['base_url'], api_key, user_agent, transport)
        try:
            status, text = transport(endpoint, api_key, body, user_agent)
        except (urllib.error.URLError, OSError) as exc:
            results.append({'variant': variant, 'sent': True, 'transport_error': type(exc).__name__})
            continue
        text = redact(text, api_key)
        (folder / (variant + '.response.json')).write_text(text, encoding='utf-8')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        after = credits(settings['base_url'], api_key, user_agent, transport)
        result = {'variant': variant, 'sent': True, **assess(contract, variant, status, parsed),
                  'credits': credit_delta(before, after)}
        if not isinstance(parsed, dict):
            result['non_json_body_excerpt'] = text[:EXCERPT_CHARS]
        results.append(result)
    report = {'scenario_id': scenario.scenario_id, 'model': scenario.model, 'role': role,
              'config_file': Path(config_path).name, 'endpoint': endpoint,
              'api_key_env': settings['api_key_env'], 'user_agent': user_agent,
              'runner_protocol': PROTOCOL_V8, 'output_contract_version': contract.version,
              'allowed_issues_sha256': contract.sha256, 'max_tokens': scenario.max_tokens,
              'created_at': datetime.now(timezone.utc).isoformat(), 'dry_run': api_key is None,
              'note': 'One request per variant does not establish reliability. Compare the '
                      'reasoning_tokens of the two tool variants to see whether reasoning_effort was applied.',
              'results': results, 'reasoning_comparison': reasoning_comparison(results)}
    (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--role', default='developer')
    parser.add_argument('--with-tools-low', action='store_true', help='also send the tool variant (reasoning low)')
    parser.add_argument('--with-tools-high', action='store_true', help='also send the tool variant (reasoning high)')
    parser.add_argument('--with-reasoning-set', action='store_true',
                        help='also send the four reasoning_effort discriminator requests (C-11)')
    parser.add_argument('--dry-run', action='store_true', help='build and save request bodies only')
    parser.add_argument('--user-agent', default=None)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'runs/gateway-probes')
    args = parser.parse_args()
    variants = ([FINAL] + [TOOLS_LOW] * args.with_tools_low + [TOOLS_HIGH] * args.with_tools_high
                + list(REASONING_SET) * args.with_reasoning_set)
    key = None
    if not args.dry_run:
        name = upstream(load_config(args.config))['api_key_env']
        key = os.environ.get(name)
        if not key:
            parser.error('Set ' + name + ' in the process environment, or use --dry-run')
    folder, report = probe(args.scenario, args.config, variants, args.output_root, args.role, key,
                           user_agent=args.user_agent)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('output:', folder)
    return 0 if report['dry_run'] or all(r.get('http_status') == 200 for r in report['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
