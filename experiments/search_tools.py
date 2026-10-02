"""Search tools of the research tasks (C-17-6 part 2; DM-13, DM-21): web_search (Tavily, DEMO-MR) and
academic_search (arXiv API, DEMO-LR). Every response is stored in the session folder exactly as received.

One call = one line of <run>/search/records.jsonl: the query, the request as sent (without the key), the outcome,
the stored response (by sha256, the file is search/responses/<sha256>.<ext>), the results normalized from it, and the
text the model got (with the truncation rule, limit and result). The tool call record (tool-dispatch.json) refers to
it by record seq and response sha256 and carries the normalized results for the judge.

Replay (judge recomputation, session replay) reads only these stored responses: load_records() checks every file
against its sha256, normalizes it again and rebuilds the model text; replay_tool_records() gives the judge the same
tool records from them. Nothing is searched again.

Settings come from the scenario's tool_settings (no code default): result count, Tavily depth and topic, arXiv sort,
the longest model text, the per-session call limit, the timeout and the arXiv request interval. The Tavily key is read
from TAVILY_API_KEY only and is never written: requests are recorded without it, and a stored response or error text
that contains it has it replaced. A network error, an HTTP error or a timeout is a fact-sentence error result with an
error record instead of a stored response; there is no automatic retry.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from experiments.tool_results import Result, ToolFactError

TAVILY_ENDPOINT = 'https://api.tavily.com/search'
ARXIV_ENDPOINT = 'https://export.arxiv.org/api/query'
TAVILY_KEY_ENV = 'TAVILY_API_KEY'
PROVIDERS = {'web_search': 'tavily', 'academic_search': 'arxiv'}
PROVIDER_NAMES = {'tavily': 'Tavily', 'arxiv': 'arXiv'}
# Environment variables a tool needs; arXiv has no key.
KEY_ENVS = {'web_search': TAVILY_KEY_ENV}
# Tavily request fields fixed by the tool: the model gets search results only, not Tavily's generated answer,
# page dumps or images.
TAVILY_FIXED = {'include_answer': False, 'include_raw_content': False, 'include_images': False}
NORMALIZERS = {'tavily': 'tavily-results-v1', 'arxiv': 'arxiv-atom-v1'}
TRUNCATION_RULE = 'uniform-excerpt-cut-v1'
RECORDS_FILE = 'search/records.jsonl'
RESPONSES_DIR = 'search/responses'
EXTENSIONS = {'tavily': '.json', 'arxiv': '.xml'}
USER_AGENT = 'agent-guardrail-harness-demo-search/1'
REDACTED = '[REDACTED]'
ERROR_CHARS = 300
DETAIL_CHARS = 200
CUT_MARK = '…'
ATOM = '{http://www.w3.org/2005/Atom}'
OPENSEARCH = '{http://a9.com/-/spec/opensearch/1.1/}'
ARXIV_ERROR_ID = 'http://arxiv.org/api/errors'
ABS_ID = re.compile(r'^https?://arxiv\.org/abs/(\S+)$')
OUTCOMES = ('ok', 'invalid_arguments', 'limit_reached', 'missing_key', 'timeout', 'network_error', 'http_error',
            'parse_error', 'provider_error')


def urllib_transport(method, url, headers, body, timeout):
    """(status, content type, body bytes). An HTTP error returns its status and body; a network failure raises."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get('Content-Type'), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get('Content-Type') if exc.headers else None, exc.read()


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# Read when a SearchSession is made; offline tests replace them.
TRANSPORT, CLOCK, SLEEP, NOW = urllib_transport, time.monotonic, time.sleep, utc_now


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def collapse(text):
    return ' '.join(text.split()) if isinstance(text, str) else ''


class ParseError(ValueError):
    pass


class ProviderError(ValueError):
    pass


def build_request(provider, query, settings, key=None):
    """(request as recorded, headers as sent, body bytes). The recorded request never holds the key."""
    if provider == 'tavily':
        body = {'query': query, 'search_depth': settings['search_depth'], 'topic': settings['topic'],
                'max_results': settings['max_results'], **TAVILY_FIXED}
        headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
        recorded = {'method': 'POST', 'url': TAVILY_ENDPOINT, 'params': None, 'body': body, 'headers': headers,
                    'auth': 'Authorization: Bearer <' + TAVILY_KEY_ENV + '> (value not recorded)'}
        return recorded, {**headers, 'Authorization': 'Bearer ' + (key or '')}, json.dumps(body).encode('utf-8')
    params = {'search_query': query, 'start': 0, 'max_results': settings['max_results'],
              'sortBy': settings['sort_by'], 'sortOrder': settings['sort_order']}
    headers = {'User-Agent': USER_AGENT}
    url = ARXIV_ENDPOINT + '?' + urllib.parse.urlencode(params)
    return {'method': 'GET', 'url': url, 'params': params, 'body': None, 'headers': headers, 'auth': None}, headers, None


def normalize(provider, body):
    """{results, total_results} from a stored 200 response. ParseError for an unreadable one, ProviderError for an
    arXiv error feed."""
    if provider == 'tavily':
        try:
            value = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ParseError('not UTF-8 JSON') from exc
        if not isinstance(value, dict) or not isinstance(value.get('results'), list):
            raise ParseError('no results list')
        results = []
        for rank, item in enumerate(value['results'], 1):
            if not isinstance(item, dict) or not isinstance(item.get('url'), str) or not item['url']:
                raise ParseError('a result without url')
            results.append({'rank': rank, 'title': collapse(item.get('title')), 'url': item['url'],
                            'excerpt': collapse(item.get('content'))})
        return {'results': results, 'total_results': None}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ParseError('not XML') from exc
    if root.tag != ATOM + 'feed':
        raise ParseError('not an Atom feed')
    entries = root.findall(ATOM + 'entry')
    for entry in entries:
        if (entry.findtext(ATOM + 'id') or '').strip().startswith(ARXIV_ERROR_ID):
            raise ProviderError(collapse(entry.findtext(ATOM + 'summary')))
    results = []
    for rank, entry in enumerate(entries, 1):
        match = ABS_ID.match((entry.findtext(ATOM + 'id') or '').strip())
        if not match:
            raise ParseError('an entry id is not an arXiv abstract URL')
        published = (entry.findtext(ATOM + 'published') or '').strip()
        results.append({'rank': rank, 'id': match.group(1), 'title': collapse(entry.findtext(ATOM + 'title')),
                        'authors': [collapse(a.findtext(ATOM + 'name')) for a in entry.findall(ATOM + 'author')],
                        'year': int(published[:4]) if re.match(r'^\d{4}-', published) else None,
                        'excerpt': collapse(entry.findtext(ATOM + 'summary'))})
    total = (root.findtext(OPENSEARCH + 'totalResults') or '').strip()
    return {'results': results, 'total_results': int(total) if total.isdigit() else None}


def provider_detail(provider, body):
    """A provider's own short error message, if its error body has one (Tavily detail.error, arXiv error summary)."""
    try:
        if provider == 'tavily':
            detail = json.loads(body.decode('utf-8')).get('detail')
            text = detail.get('error') if isinstance(detail, dict) else detail
        else:
            normalize(provider, body)
            text = None
    except ProviderError as exc:
        text = str(exc)
    except (ValueError, AttributeError, UnicodeDecodeError):
        text = None
    return collapse(text)[:DETAIL_CHARS] if isinstance(text, str) and text.strip() else None


def model_item(provider, result, cap):
    excerpt = result['excerpt']
    if cap is not None and len(excerpt) > cap:
        excerpt = excerpt[:cap] + CUT_MARK
    if provider == 'tavily':
        return {'title': result['title'], 'url': result['url'], 'excerpt': excerpt}
    return {'id': result['id'], 'title': result['title'], 'authors': result['authors'], 'year': result['year'],
            'excerpt': excerpt}


def render(provider, normalized, results, cap, left_out):
    payload = {'result_count': len(results), 'results': [model_item(provider, r, cap) for r in results],
               'excerpts_cut_to_chars': cap, 'results_left_out': left_out}
    if normalized['total_results'] is not None:
        payload['total_results'] = normalized['total_results']
    return json.dumps(payload, ensure_ascii=False)


def fit(provider, normalized, limit):
    """(model text, truncation record). uniform-excerpt-cut-v1: when the full text is longer than limit characters,
    every excerpt is cut to the same largest length that fits (cut ones end with "…"); if even empty excerpts do not
    fit, results are left out from the end. The text stays valid JSON."""
    results = normalized['results']
    full = render(provider, normalized, results, None, 0)
    text, cap, kept = full, None, len(results)
    if len(full) > limit:
        low, high, best = 0, max((len(r['excerpt']) for r in results), default=0), None
        while low <= high:
            middle = (low + high) // 2
            if len(render(provider, normalized, results, middle, 0)) <= limit:
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best is not None:
            cap, text = best, render(provider, normalized, results, best, 0)
        else:
            cap = 0
            kept = next(k for k in range(len(results) - 1, -1, -1)
                        if len(render(provider, normalized, results[:k], 0, len(results) - k)) <= limit)
            text = render(provider, normalized, results[:kept], 0, len(results) - kept)
    cut = cap is not None and any(len(r['excerpt']) > cap for r in results[:kept])
    return text, {'rule': TRUNCATION_RULE, 'max_result_chars': limit, 'full_chars': len(full), 'sent_chars': len(text),
                  'truncated': cut or kept < len(results), 'excerpts_cut_to_chars': cap,
                  'results_total': len(results), 'results_sent': kept}


class SearchSession:
    """The search tools' state for one run: settings, the per-session call count, the arXiv interval, the store.
    ToolDispatch hands calls over one at a time."""

    def __init__(self, settings, session_dir, *, environ=None, transport=None, clock=None, sleep=None, now=None):
        self.settings, self.session_dir = settings, Path(session_dir)
        self.environ = os.environ if environ is None else environ
        self.transport, self.clock = transport or TRANSPORT, clock or CLOCK
        self.sleep, self.now = sleep or SLEEP, now or NOW
        self.sent = {tool: 0 for tool in settings}
        self.last_done, self.records = {}, []

    def search(self, tool, arguments, context):
        settings = self.settings[tool]
        provider = settings['provider']
        record = {'seq': len(self.records) + 1, 'dispatch_seq': context.get('dispatch_seq'),
                  'step_id': context.get('step_id'), 'agent_id': context.get('agent_id'), 'tool': tool,
                  'provider': provider, 'query': arguments.get('query'), 'requested_at': self.now(),
                  'settings': settings, 'settings_sha256': canonical_sha256(settings), 'request': None,
                  'outcome': None, 'http_status': None, 'waited_seconds': 0.0, 'elapsed_ms': None, 'response': None,
                  'error': None, 'normalizer': NORMALIZERS[provider], 'results': None, 'total_results': None,
                  'truncation': None, 'model_text': None, 'model_text_sha256': None}
        self.records.append(record)
        try:
            text = self.attempt(tool, settings, provider, record)
        except ToolFactError as exc:
            record.update(model_text=str(exc), model_text_sha256=sha256(str(exc).encode('utf-8')))
            self.write(record)
            exc.record['search'] = self.reference(record)
            raise
        record.update(outcome='ok', model_text=text, model_text_sha256=sha256(text.encode('utf-8')))
        self.write(record)
        return Result(text, {'search': self.reference(record)})

    def attempt(self, tool, settings, provider, record):
        name = PROVIDER_NAMES[provider]
        query = record['query']
        if not isinstance(query, str) or not query.strip():
            record['outcome'] = 'invalid_arguments'
            raise ToolFactError(tool + ' needs query as a non-empty string.')
        limit = settings['max_calls_per_session']
        if self.sent[tool] >= limit:
            record['outcome'] = 'limit_reached'
            raise ToolFactError(f'{tool} was not run: the limit of {limit} {tool} calls for this session is reached.')
        key = None
        if tool in KEY_ENVS:
            key = self.environ.get(KEY_ENVS[tool])
            if not key:
                record['outcome'] = 'missing_key'
                raise ToolFactError(tool + ' was not run: the search key is not configured.')
        recorded, headers, body = build_request(provider, query, settings, key)
        record['request'] = recorded
        if provider == 'arxiv' and 'arxiv' in self.last_done:
            wait = self.last_done['arxiv'] + settings['min_interval_seconds'] - self.clock()
            if wait > 0:
                self.sleep(wait)
                record['waited_seconds'] = wait
        self.sent[tool] += 1
        started = self.clock()
        try:
            status, content_type, data = self.transport(recorded['method'], recorded['url'], headers, body,
                                                        settings['timeout_seconds'])
        except Exception as exc:
            kind = 'timeout' if (isinstance(exc, TimeoutError)
                                 or isinstance(getattr(exc, 'reason', None), TimeoutError)) else 'network_error'
            record.update(outcome=kind, error={'type': type(exc).__name__,
                                               'message': self.redact(str(exc), key)[:ERROR_CHARS]})
            raise ToolFactError(f'{tool} failed: no response from {name} '
                                f'({"timed out" if kind == "timeout" else "network error"}). No results.') from exc
        finally:
            self.last_done[provider] = self.clock()
            record['elapsed_ms'] = round((self.last_done[provider] - started) * 1000, 3)
        record['http_status'] = status
        if status != 200:
            detail = provider_detail(provider, data)
            record.update(outcome='http_error', error={
                'type': 'http_status', 'content_type': content_type,
                'message': self.redact(data.decode('utf-8', errors='replace'), key)[:ERROR_CHARS]})
            raise ToolFactError(f'{tool} failed: HTTP {status} from {name}.'
                                + (' ' + self.redact(detail, key) if detail else '') + ' No results.')
        record['response'] = self.store(provider, data, content_type, key)
        try:
            normalized = normalize(provider, data)
        except ProviderError as exc:
            record.update(outcome='provider_error', error={'type': 'provider_error',
                                                           'message': self.redact(str(exc), key)[:ERROR_CHARS]})
            raise ToolFactError(f'{tool} failed: {name} returned an error: '
                                + self.redact(str(exc), key)[:DETAIL_CHARS] + ' No results.') from exc
        except ParseError as exc:
            record.update(outcome='parse_error', error={'type': 'parse_error', 'message': str(exc)})
            raise ToolFactError(f'{tool} failed: the {name} response could not be read. No results.') from exc
        text, truncation = fit(provider, normalized, settings['max_result_chars'])
        record.update(results=normalized['results'], total_results=normalized['total_results'],
                      truncation=truncation)
        return text

    def secrets(self):
        return [v for v in (self.environ.get(env) for env in sorted(set(KEY_ENVS.values()))) if v]

    def redact(self, text, key=None):
        """Every configured search key replaced, whichever provider the text came from."""
        for secret in self.secrets() + ([key] if key else []):
            text = text.replace(secret, REDACTED) if isinstance(text, str) else text
        return text

    def store(self, provider, data, content_type, key):
        """Write the response body as received (any search key replaced if it is in it) under its sha256."""
        stored = data
        for secret in self.secrets() + ([key] if key else []):
            stored = stored.replace(secret.encode('utf-8'), REDACTED.encode('utf-8'))
        digest = sha256(stored)
        path = RESPONSES_DIR + '/' + digest + EXTENSIONS[provider]
        target = self.session_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(stored)
        return {'sha256': digest, 'bytes': len(stored), 'path': path, 'content_type': content_type,
                'redacted': stored != data, 'received_sha256': sha256(data) if stored != data else None}

    def write(self, record):
        path = self.session_dir / RECORDS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')

    @staticmethod
    def reference(record):
        """What the tool call record keeps: the stored record by seq and hash, and the results for the judge."""
        truncation = record['truncation'] or {}
        return {'record_seq': record['seq'], 'provider': record['provider'], 'outcome': record['outcome'],
                'response_sha256': (record['response'] or {}).get('sha256'), 'results': record['results'],
                'results_sent': truncation.get('results_sent'), 'total_results': record['total_results']}

    def summary(self):
        path = self.session_dir / RECORDS_FILE
        outcomes = {}
        for record in self.records:
            outcomes[record['outcome']] = outcomes.get(record['outcome'], 0) + 1
        return {'requests_sent': dict(self.sent), 'calls_recorded': len(self.records), 'outcomes': outcomes,
                'responses_stored': len({r['response']['sha256'] for r in self.records if r['response']}),
                'records_file': RECORDS_FILE if path.exists() else None,
                'records_sha256': sha256(path.read_bytes()) if path.exists() else None}


def web_search(arguments, context):
    return context['search'].search('web_search', arguments, context)


def academic_search(arguments, context):
    return context['search'].search('academic_search', arguments, context)


def conditions_record(settings):
    """What a run records about its search tools (conditions.json, manifest)."""
    return {tool: {'provider': PROVIDERS[tool], 'endpoint': TAVILY_ENDPOINT if tool == 'web_search' else ARXIV_ENDPOINT,
                   'key_env': KEY_ENVS.get(tool), 'fixed_parameters': TAVILY_FIXED if tool == 'web_search' else {},
                   'normalizer': NORMALIZERS[PROVIDERS[tool]], 'truncation_rule': TRUNCATION_RULE,
                   'settings': value, 'settings_sha256': canonical_sha256(value),
                   'interval_scope': 'per runner process' if tool == 'academic_search' else None,
                   'retry': 'none'} for tool, value in settings.items()}


class ReplayMismatch(ValueError):
    pass


def load_records(run_dir):
    """The run's search records, each checked against its stored response: the file hash, the results normalized
    again from it and the model text rebuilt from them. Raises ReplayMismatch; never searches."""
    run_dir = Path(run_dir)
    path = run_dir / RECORDS_FILE
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    for record in records:
        if record['model_text_sha256'] != sha256(record['model_text'].encode('utf-8')):
            raise ReplayMismatch(f"search record {record['seq']}: model text hash")
        response = record['response']
        if response is None:
            if record['outcome'] in ('ok', 'parse_error', 'provider_error'):
                raise ReplayMismatch(f"search record {record['seq']}: no stored response for {record['outcome']}")
            continue
        data = (run_dir / response['path']).read_bytes()
        if sha256(data) != response['sha256']:
            raise ReplayMismatch(f"search record {record['seq']}: stored response hash")
        if record['outcome'] != 'ok':
            continue
        normalized = normalize(record['provider'], data)
        if (normalized['results'], normalized['total_results']) != (record['results'], record['total_results']):
            raise ReplayMismatch(f"search record {record['seq']}: results differ from the stored response")
        text, truncation = fit(record['provider'], normalized, record['truncation']['max_result_chars'])
        if (text, truncation) != (record['model_text'], record['truncation']):
            raise ReplayMismatch(f"search record {record['seq']}: model text differs from the stored response")
        record['results'] = normalized['results']
    return records


def replay_tool_records(run_dir):
    """tool-dispatch.json with every search reference rebuilt from the stored responses (load_records)."""
    run_dir = Path(run_dir)
    by_seq = {r['seq']: r for r in load_records(run_dir)}
    path = run_dir / 'tool-dispatch.json'
    dispatch = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    for call in dispatch:
        if 'search' not in call:
            continue
        stored = by_seq.get(call['search']['record_seq'])
        if stored is None or stored['dispatch_seq'] != call['seq'] or stored['tool'] != call['tool']:
            raise ReplayMismatch(f"tool call {call['seq']}: no matching search record")
        rebuilt = SearchSession.reference(stored)
        if {k: v for k, v in rebuilt.items() if k != 'results'} != {k: v for k, v in call['search'].items()
                                                                    if k != 'results'}:
            raise ReplayMismatch(f"tool call {call['seq']}: search reference differs from the stored record")
        if call['result'] is not None and call['result'] != stored['model_text']:
            raise ReplayMismatch(f"tool call {call['seq']}: result differs from the stored model text")
        call['search'] = rebuilt
    return dispatch
