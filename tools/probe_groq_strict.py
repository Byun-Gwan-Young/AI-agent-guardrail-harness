"""User-run Groq strict-schema probe for output-contract-v2. Never imported by the scenario runner.

Builds the same response_format and final system text as the runner's v2 final request for the
given scenario and sends each selected variant exactly once (no retry, no fallback). HTTP uses the
standard library only. The API key is read from GROQ_API_KEY and never written or printed.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.issue_contract import V2, for_scenario
from experiments.step_execution import final_instruction
from scenario_schema import load_scenario

ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
DEFAULT_SCENARIO = ROOT / 'scenarios/A-1-v2-ambiguous-task-query.yaml'
BASE, ENUM, NO_LENGTH = 'v2', 'v2-open-issue-enum', 'v2-without-length'


def strip_lengths(node):
    if isinstance(node, dict):
        return {k: strip_lengths(v) for k, v in node.items() if k not in ('minLength', 'maxLength')}
    if isinstance(node, list):
        return [strip_lengths(v) for v in node]
    return node


def response_format(contract, variant):
    fmt = copy.deepcopy(contract.response_format())
    schema = fmt['json_schema']['schema']
    if variant == ENUM:
        # Review-only variant: the runner itself sends no vocabulary enum (D-13).
        items = next(a for a in schema['properties']['open_issue_ids']['anyOf'] if a.get('type') == 'array')
        items['items']['enum'] = [i for i, _ in contract.allowed]
    elif variant == NO_LENGTH:
        fmt['json_schema']['schema'] = strip_lengths(schema)
    return fmt


def request_body(scenario, contract, variant=BASE):
    # Same field set as the runner's final call: model, messages, max_tokens, temperature,
    # reasoning_effort, response_format, stream. Observed records are a short synthetic stand-in.
    records = [{'task': scenario.task, 'initial_issue_ids': scenario.initial_issue_ids}]
    return {'model': scenario.model, 'temperature': scenario.temperature, 'max_tokens': scenario.max_tokens,
            'reasoning_effort': 'low', 'stream': False,
            'messages': [{'role': 'system', 'content': final_instruction(contract)},
                         {'role': 'user', 'content': json.dumps({'observed_records': records}, ensure_ascii=False)}],
            'response_format': response_format(contract, variant)}


def assess(contract, status, body):
    result = {'http_status': status, 'error_message': None, 'finish_reason': None,
              'contract_valid': False, 'contract_violation': None, 'usage': None}
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
        result['finish_reason'] = choice.get('finish_reason')
        message = choice['message']
        if result['finish_reason'] != 'stop' or message.get('tool_calls') or not isinstance(message.get('content'), str):
            raise ValueError('Incomplete response or unexpected tool call')
        contract.parse(message['content'])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        result['contract_violation'] = getattr(exc, 'code', None) or type(exc).__name__ + ': ' + str(exc)[:300]
        return result
    result['contract_valid'] = True
    return result


def send(url, api_key, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8', 'replace')


def redact(text, api_key):
    return text.replace(api_key, '[REDACTED]') if api_key else text


def probe(scenario_path, variants, output_root, api_key=None, transport=send):
    """api_key=None builds and saves request bodies only (dry run); no network call is made."""
    scenario = load_scenario(scenario_path)
    contract = for_scenario(V2, scenario)
    folder = output_root / ('groq-strict-probe-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for variant in variants:
        body = request_body(scenario, contract, variant)
        (folder / (variant + '.request.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
        if api_key is None:
            results.append({'variant': variant, 'sent': False})
            continue
        try:
            status, text = transport(ENDPOINT, api_key, body)
        except (urllib.error.URLError, OSError) as exc:
            results.append({'variant': variant, 'sent': True, 'transport_error': type(exc).__name__})
            continue
        text = redact(text, api_key)
        (folder / (variant + '.response.json')).write_text(text, encoding='utf-8')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        results.append({'variant': variant, 'sent': True, **assess(contract, status, parsed)})
    report = {'scenario_id': scenario.scenario_id, 'model': scenario.model, 'endpoint': ENDPOINT,
              'output_contract_version': contract.version, 'allowed_issues_sha256': contract.sha256,
              'created_at': datetime.now(timezone.utc).isoformat(), 'dry_run': api_key is None,
              'note': 'One request per variant does not establish reliability or token-level enforcement.',
              'results': results}
    (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument('--with-enum', action='store_true', help='also send the open_issue_ids enum variant')
    parser.add_argument('--without-length', action='store_true', help='also send the minLength/maxLength-free variant')
    parser.add_argument('--dry-run', action='store_true', help='build and save request bodies only')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'runs/strict-probes')
    args = parser.parse_args()
    variants = [BASE] + [ENUM] * args.with_enum + [NO_LENGTH] * args.without_length
    key = None
    if not args.dry_run:
        key = os.environ.get('GROQ_API_KEY')
        if not key:
            parser.error('Set GROQ_API_KEY in the process environment, or use --dry-run')
    folder, report = probe(args.scenario, variants, args.output_root, key)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print('output:', folder)
    return 0 if report['dry_run'] or all(r.get('contract_valid') for r in report['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
