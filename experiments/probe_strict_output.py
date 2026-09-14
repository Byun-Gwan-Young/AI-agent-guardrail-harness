"""User-run, single-request Groq strict-schema probe. Never imported by the scenario runner."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from experiments.output_contract import strict_response_format, parse_output

ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = 'openai/gpt-oss-120b'


def request_body():
    return {'model': MODEL, 'temperature': 0.0, 'max_tokens': 256, 'reasoning_effort':'low',
        'messages':[{'role':'user','content':'Return narrative="probe", open_issue_ids=[], info_items=[], completion_declared=false.'}],
        'response_format':strict_response_format()}


def assess(status, body):
    result = {'outcome':'inconclusive', 'strict_request_accepted':False, 'schema_valid':False}
    if status != 200:
        result['reason'] = 'Inspect response error; authentication, rate limits and server errors do not establish lack of support'
        return result
    try:
        choice = body['choices'][0]
        if choice.get('finish_reason') != 'stop' or choice['message'].get('tool_calls'):
            raise ValueError('Incomplete response or unexpected tool call')
        value = parse_output(choice['message']['content'])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        result['reason'] = 'Response did not validate: ' + type(exc).__name__
        return result
    result.update(outcome='probe_passed', strict_request_accepted=True, schema_valid=True, value=value,
        reason='One strict request accepted with a valid response; this does not prove reliability or token-level enforcement')
    return result


def probe(client, api_key, output_root):
    folder = output_root / ('strict-probe-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    payload = request_body()
    (folder/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        # Exactly one HTTP request. No SDK retries, redirects, proxy retry loop or fallback.
        response = client.post(ENDPOINT, headers={'Authorization':'Bearer '+api_key}, json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {'non_json_response':response.text}
        (folder/'response.json').write_text(json.dumps({'status':response.status_code,'body':body},
            ensure_ascii=False,indent=2),encoding='utf-8')
        result = assess(response.status_code, body)
        result['usage'] = body.get('usage') if isinstance(body,dict) else None
    except httpx.TransportError as exc:
        result = {'outcome':'inconclusive','reason':'transport_error:'+type(exc).__name__}
    result.update(model=MODEL, endpoint=ENDPOINT, created_at=datetime.now(timezone.utc).isoformat(),
                  runner_config_changed=False)
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root',type=Path,default=Path('runs/strict-probes'))
    args = parser.parse_args()
    key = os.environ.get('GROQ_API_KEY')
    if not key:
        parser.error('Set GROQ_API_KEY in the process environment')
    with httpx.Client(timeout=60,follow_redirects=False,transport=httpx.HTTPTransport(retries=0)) as client:
        folder, result = probe(client,key,args.output_root)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    print('output:',folder)
    return 0 if result['outcome']=='probe_passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
