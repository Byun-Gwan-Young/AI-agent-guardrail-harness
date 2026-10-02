"""PM search check (C-17-6 part 3): one Tavily request and one arXiv request with fixed queries, no LLM call.

Run by the PM, not by the coding agent (no external call in offline work). Saves both responses as received under
runs/search-probes/search-probe-<id>/ and compares each response's shape with the offline fixtures in
tests/fixtures/search/ (the shapes experiments/search_tools.py was written against). Also normalizes each response
with the tool's own normalizer. The Tavily key is read from TAVILY_API_KEY only; it is never written, and the probe
folder is checked for it at the end. Without the key nothing is sent.

    venv/bin/python tools/probe_search.py
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments import search_tools  # noqa: E402

PROBE_VERSION = 'search-probe-v1'
OUTPUT_ROOT = ROOT / 'runs' / 'search-probes'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'search'
# Fixed probe requests: small, the tool's own request builder, settings recorded with the result.
PROBES = {
    'tavily': {'tool': 'web_search', 'query': 'multi-agent LLM system failure causes',
               'settings': {'provider': 'tavily', 'max_results': 5, 'search_depth': 'basic', 'topic': 'general',
                            'max_result_chars': 4000, 'max_calls_per_session': 1, 'timeout_seconds': 30.0},
               'fixture': 'tavily-search-200.json', 'file': 'tavily-response.json'},
    'arxiv': {'tool': 'academic_search', 'query': 'all:"multi-agent" AND all:failure',
              'settings': {'provider': 'arxiv', 'max_results': 5, 'sort_by': 'relevance', 'sort_order': 'descending',
                           'max_result_chars': 6000, 'max_calls_per_session': 1, 'timeout_seconds': 30.0,
                           'min_interval_seconds': 3.0},
              'fixture': 'arxiv-query-200.xml', 'file': 'arxiv-response.xml'},
}
# Fields search_tools reads; the probe fails without them.
TOOL_FIELDS = {'tavily': {'results', 'results[]', 'results[].url', 'results[].title', 'results[].content'},
               'arxiv': {'feed', 'feed/entry', 'feed/entry/id', 'feed/entry/title', 'feed/entry/summary',
                         'feed/entry/author/name', 'feed/entry/published', 'feed/opensearch:totalResults'}}
# arXiv entry elements the manual lists that a given entry may not have; absent from five results is not a change.
OPTIONAL = {'arxiv': {'feed/entry/arxiv:comment', 'feed/entry/arxiv:journal_ref', 'feed/entry/arxiv:doi',
                      'feed/entry/author/arxiv:affiliation'}, 'tavily': set()}
PREFIXES = {search_tools.ATOM: '', search_tools.OPENSEARCH: 'opensearch:', '{http://arxiv.org/schemas/atom}': 'arxiv:'}


def json_shape(value, path=''):
    """{path: sorted type names}; list items share the path "<list>[]"."""
    kind = {dict: 'object', list: 'array', str: 'string', bool: 'boolean', type(None): 'null'}.get(
        type(value), 'number' if isinstance(value, (int, float)) else type(value).__name__)
    shape = {path: {kind}} if path else {}
    if isinstance(value, dict):
        for key, child in value.items():
            for p, kinds in json_shape(child, (path + '.' if path else '') + key).items():
                shape.setdefault(p, set()).update(kinds)
    elif isinstance(value, list):
        for child in value:
            for p, kinds in json_shape(child, path + '[]').items():
                shape.setdefault(p, set()).update(kinds)
    return shape


def tag(name):
    for uri, prefix in PREFIXES.items():
        if name.startswith(uri):
            return prefix + name[len(uri):]
    return name


def xml_shape(element, path=''):
    """{element path (and path@attribute): {'element'|'attribute'}} with atom:/opensearch:/arxiv: prefixes."""
    here = (path + '/' if path else '') + tag(element.tag)
    shape = {here: {'element'}}
    for attribute in element.attrib:
        shape[here + '@' + tag(attribute)] = {'attribute'}
    for child in element:
        for p, kinds in xml_shape(child, here).items():
            shape.setdefault(p, set()).update(kinds)
    return shape


def shape_of(provider, body):
    if provider == 'tavily':
        return json_shape(json.loads(body.decode('utf-8')))
    return xml_shape(ET.fromstring(body))


def compare(provider, body, fixture_body):
    """Shape of the live response against the fixture's: missing / extra paths and type differences."""
    try:
        live = shape_of(provider, body)
    except (ValueError, ET.ParseError) as exc:
        return {'readable': False, 'error': type(exc).__name__, 'same_shape': False, 'tool_fields_present': False}
    fixture = shape_of(provider, fixture_body)
    missing = sorted(set(fixture) - set(live))
    return {'readable': True, 'missing_in_response': [p for p in missing if p not in OPTIONAL[provider]],
            'optional_absent': [p for p in missing if p in OPTIONAL[provider]],
            'extra_in_response': sorted(set(live) - set(fixture)),
            'type_differences': {p: {'fixture': sorted(fixture[p]), 'response': sorted(live[p])}
                                 for p in sorted(set(live) & set(fixture)) if live[p] != fixture[p]},
            'tool_fields_present': TOOL_FIELDS[provider] <= set(live),
            'same_shape': not [p for p in missing if p not in OPTIONAL[provider]]
                          and all(live[p] == fixture[p] for p in set(live) & set(fixture))}


def probe(provider, key, transport, out, secret):
    spec = PROBES[provider]
    recorded, headers, body = search_tools.build_request(provider, spec['query'], spec['settings'], key)
    fixture_path = FIXTURES / spec['fixture']
    fixture_body = fixture_path.read_bytes()
    result = {'tool': spec['tool'], 'query': spec['query'], 'settings': spec['settings'], 'request': recorded,
              'requested_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'fixture': {'path': fixture_path.relative_to(ROOT).as_posix(), 'sha256': search_tools.sha256(fixture_body)}}
    try:
        status, content_type, data = transport(recorded['method'], recorded['url'], headers, body,
                                               spec['settings']['timeout_seconds'])
    except Exception as exc:
        message = str(exc).replace(secret, search_tools.REDACTED)
        return {**result, 'outcome': 'no_response', 'error': {'type': type(exc).__name__, 'message': message[:300]}}
    stored = data.replace(secret.encode('utf-8'), search_tools.REDACTED.encode('utf-8'))
    (out / spec['file']).write_bytes(stored)
    result.update(http_status=status, content_type=content_type,
                  response={'file': spec['file'], 'sha256': search_tools.sha256(stored), 'bytes': len(stored),
                            'redacted': stored != data})
    if status != 200:
        return {**result, 'outcome': 'http_error'}
    try:
        normalized = search_tools.normalize(provider, data)
        result['normalized'] = {'ok': True, 'results': len(normalized['results']),
                                'total_results': normalized['total_results'],
                                'first': normalized['results'][0] if normalized['results'] else None}
    except ValueError as exc:
        result['normalized'] = {'ok': False, 'error': type(exc).__name__ + ': ' + str(exc)}
    result['shape'] = compare(provider, data, fixture_body)
    return {**result, 'outcome': 'ok'}


def main(argv=None, transport=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-root', type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    transport = transport or search_tools.TRANSPORT
    key = environ.get(search_tools.TAVILY_KEY_ENV)
    if not key:
        print(search_tools.TAVILY_KEY_ENV + ' is not set; nothing was sent.', file=sys.stderr)
        return 2
    out = args.output_root / ('search-probe-' + uuid.uuid4().hex)
    out.mkdir(parents=True, exist_ok=False)
    providers = {name: probe(name, key if name == 'tavily' else None, transport, out, key) for name in PROBES}
    report = {'probe_version': PROBE_VERSION, 'probe_id': out.name, 'llm_calls': 0,
              'requests_sent': len(providers),
              'key_env': search_tools.TAVILY_KEY_ENV, 'providers': providers,
              'all_ok': all(p['outcome'] == 'ok' and p['normalized']['ok'] and p['shape']['same_shape']
                            and p['shape']['tool_fields_present'] for p in providers.values())}
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    leaked = sorted(p.name for p in out.iterdir() if p.is_file() and key.encode('utf-8') in p.read_bytes())
    report['secret_scan'] = {'key_value_found_in': leaked, 'clean': not leaked}
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    summary = {'probe_dir': str(out), 'all_ok': report['all_ok'], 'secret_scan_clean': not leaked,
               **{name: {'outcome': p['outcome'], 'http_status': p.get('http_status'),
                         'same_shape': (p.get('shape') or {}).get('same_shape'),
                         'tool_fields_present': (p.get('shape') or {}).get('tool_fields_present'),
                         'results': (p.get('normalized') or {}).get('results')} for name, p in providers.items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if report['all_ok'] and not leaked else 1


if __name__ == '__main__':
    raise SystemExit(main())
