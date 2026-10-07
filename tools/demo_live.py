"""Live monitor of the demo (C-19-4, DM-77): a read-only local server over the files a running demo session writes.

  serve [--port 8010] [--runs-root runs/demo] [--logs-root logs/demo] [--aggregate reports/c19/aggregate-main.json]

The proxy, runner, batch runner and judgement code are not changed. While a session runs they already write, step by
step (C-19-4 part 0):
  runs/demo/<id>/conditions.json          runner, at session start: scenario, registration, batch item, account label
  runs/demo/<id>/steps.json               runner, after each step (atomic replace): agent, report fields, tools, tests
  runs/demo/<id>/observations/<n>.ack.json runner, after each observation: the proxy's judged record of step n
  logs/demo/<id>.json                     proxy, after every LLM turn and every observation (atomic replace, fsync):
                                          turns (usage, 403), observations (progress, decision, STOP sentence), mode
  runs/demo/<id>/summary.json, session.json   runner, at session end only
This server reads them only; it never writes a file. Per step it uses the same extraction as the replay records
(tools/replay_demo.py replay_rows) and the screen's step shape (tools/demo_ui.py slim_step), so a live session and its
later replay.json show the same values. Only structured values leave the server: no narrative, reasoning, raw log
line or key (DM-77 ②); every response is checked for the D-11 key patterns and the key values set here, and for the
narrative/reasoning field names, and is refused (500, no body) if any is found.

It binds 127.0.0.1 only (no --host option). / serves the demo screen (tools/demo_ui.py) with the live monitor turned
on; the same screen opened as a file shows "실시간 서버가 꺼져 있습니다" instead. Offline; no model call.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import aggregate_demo, demo_ui, replay_demo  # noqa: E402
from tools.analyze_session import SEARCH_SECRET_PATTERNS, SECRET_PATTERNS  # noqa: E402

VERSION = 'demo-live-v1'
HOST = '127.0.0.1'
DEFAULT_PORT = 8010
KEY_ENVS = ('KMU_API_KEY', 'TAVILY_API_KEY', 'GROQ_API_KEY')
FORBIDDEN_KEYS = ('narrative', 'reasoning', 'reasoning_content', 'thought', 'info_items',
                  'request_body', 'response_body', 'in', 'out')
SESSION_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,127}$')
LIST_LIMIT = 12


class Unsafe(Exception):
    """A response would have carried a key pattern or a narrative/reasoning field."""


def utc_iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='seconds')


class Reader:
    """JSON files read by (mtime_ns, size), so an unchanged file is not parsed again. Read-only; nothing on disk."""

    def __init__(self):
        self.cache = {}

    def json(self, path):
        path = Path(path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        hit = self.cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            # A writer replaces these files atomically; a failed read is shown as "not yet" and retried next poll.
            return hit[1] if hit else None
        self.cache[path] = (key, value)
        return value


def changed_at(folder, log_path):
    """The latest modification time among the files a running session writes (seconds since the epoch)."""
    times = []
    for path in (folder / 'conditions.json', folder / 'steps.json', folder / 'summary.json', log_path,
                 folder / 'observations'):
        try:
            times.append(path.stat().st_mtime)
        except FileNotFoundError:
            pass
    return max(times) if times else None


def empty_log():
    return {'status': 'active', 'meta': {}, 'turns': [], 'observations': []}


def session_view(folder, logs_root, reader, names, now=None):
    """The live session in the screen's session shape (demo_ui.session_entry keys) plus live fields."""
    folder = Path(folder)
    session_id = folder.name
    conditions = reader.json(folder / 'conditions.json')
    if conditions is None:
        return None
    steps = reader.json(folder / 'steps.json') or []
    summary = reader.json(folder / 'summary.json')
    log_path = Path(logs_root) / f'{session_id}.json'
    log = reader.json(log_path) or reader.json(folder / 'session.json') or empty_log()
    labels, model, rows = replay_demo.replay_rows(conditions, steps, log)
    scenario = conditions.get('scenario') or {}
    scenario_id = scenario.get('scenario_id') or session_id.rsplit('-', 1)[0]
    task, _ = aggregate_demo.task_of(scenario_id)
    batch = conditions.get('batch') or {}
    reason = (summary or {}).get('termination_reason') or (log.get('meta') or {}).get('termination_reason')
    ended = summary is not None or log.get('status') == 'ended'
    stops = [r['step_id'] for r in rows if r['stop']]
    first = next((r for r in rows if r['stop']), None)
    blocked = [r['step_id'] for r in rows if r['blocked']]
    assigned = {t for s in steps for t in s.get('llm_turns') or []}
    open_turns = [t for t in log.get('turns') or [] if t.get('turn') not in assigned]
    last = changed_at(folder, log_path)
    now = time.time() if now is None else now
    return {
        'id': session_id, 'short': session_id[-32:][:8], 'scenario': scenario_id, 'name': names.get(scenario_id),
        'title': scenario.get('title'), 'task': task, 'task_name': demo_ui.TASK_NAMES.get(task, task),
        'variant': demo_ui.variant_of(scenario_id), 'type': aggregate_demo.TASK_TYPES.get(task),
        'mode': batch.get('mode') or (log.get('meta') or {}).get('guardrail_mode') or conditions.get('guardrail_mode'),
        'class': aggregate_demo.termination_class(reason) if ended and reason else None,
        'termination': reason if ended else None, 'escalated_by': (summary or {}).get('escalated_by'),
        'escalated_by_label': labels.get((summary or {}).get('escalated_by'), (summary or {}).get('escalated_by')),
        'steps': len(rows), 'max_steps': (scenario.get('termination') or {}).get('max_steps'),
        'tokens': rows[-1]['cumulative_tokens'] if rows else 0,
        'credits': rows[-1]['cumulative_credits'] if rows else None,
        'first_stop': first['step_id'] if first else None,
        'template': first['stop']['template_id'] if first else None,
        'stop_text': first['stop']['text'] if first else None, 'stop_steps': stops,
        'blocked_step': blocked[0] if blocked else None,
        'if_stopped': None, 'started_at': (log.get('meta') or {}).get('started_at'),
        'account': conditions.get('account_label'), 'plan': batch.get('plan_id'),
        'replay': False, 'step_rows': [demo_ui.slim_step(r, labels) for r in rows],
        'live': {'status': 'ended' if ended else 'running', 'lane': batch.get('lane'), 'lanes': batch.get('lanes'),
                 'repeat': batch.get('repeat'), 'model': model,
                 'updated_at': None if last is None else utc_iso(last),
                 'idle_seconds': None if last is None else max(0, round(now - last)),
                 'in_progress': None if ended else {
                     'step': len(rows) + 1, 'llm_calls': len(open_turns),
                     'blocked_requests': sum(1 for t in open_turns if t.get('status_code') == 403)}},
    }


def list_item(view):
    keys = ('id', 'short', 'scenario', 'name', 'task', 'task_name', 'variant', 'type', 'mode', 'class', 'termination',
            'steps', 'max_steps', 'tokens', 'first_stop', 'template', 'blocked_step', 'account', 'plan')
    return {**{k: view[k] for k in keys}, 'live': {k: view['live'][k] for k in
                                                   ('status', 'lane', 'lanes', 'repeat', 'updated_at', 'idle_seconds',
                                                    'in_progress')}}


def recent_folders(runs_root, logs_root, limit=LIST_LIMIT):
    """Session folders by the time their files last changed, newest first."""
    found = []
    root = Path(runs_root)
    if not root.is_dir():
        return []
    for folder in root.iterdir():
        if folder.is_dir() and SESSION_ID.match(folder.name) and (folder / 'conditions.json').is_file():
            when = changed_at(folder, Path(logs_root) / f'{folder.name}.json')
            if when is not None:
                found.append((when, folder))
    found.sort(key=lambda x: (x[0], x[1].name), reverse=True)
    return [f for _, f in found[:limit]]


def keys_in(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys_in(v)


def checked(payload):
    """The JSON text of a response, or Unsafe when it holds a key pattern, a key value set here or a forbidden field."""
    text = json.dumps(payload, ensure_ascii=False)
    patterns = {**SECRET_PATTERNS, **SEARCH_SECRET_PATTERNS}
    hits = [name for name, pattern in patterns.items() if pattern.search(text)]
    hits += ['env:' + env for env in KEY_ENVS if os.environ.get(env) and os.environ[env] in text]
    hits += ['field:' + k for k in set(keys_in(payload)) if k in FORBIDDEN_KEYS]
    if hits:
        raise Unsafe(sorted(hits))
    return text


def live_page(aggregate_path, runs_root_for_records, root=ROOT):
    data = demo_ui.collect(demo_ui.load(aggregate_path), runs_root=runs_root_for_records, root=root)
    return demo_ui.page(data, root, live=True)


def create_app(*, runs_root=ROOT / 'runs' / 'demo', logs_root=ROOT / 'logs' / 'demo',
               aggregate=ROOT / 'reports' / 'c19' / 'aggregate-main.json', records_root=None, page=None, clock=time.time):
    """FastAPI app (the proxy's framework). page: the HTML for /, built once from the committed records if not given."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, Response

    runs_root, logs_root = Path(runs_root), Path(logs_root)
    reader = Reader()
    names = demo_ui.korean_names(ROOT)
    app = FastAPI(title='agent-guardrail live monitor', docs_url=None, redoc_url=None, openapi_url=None)
    state = {'page': page}

    def respond(payload):
        try:
            text = checked(payload)
        except Unsafe:
            return Response(status_code=500, content=b'', media_type='application/json')
        return Response(text, media_type='application/json; charset=utf-8', headers={'Cache-Control': 'no-store'})

    @app.get('/', response_class=HTMLResponse)
    def index():
        if state['page'] is None:
            state['page'] = live_page(aggregate, records_root or runs_root)
        return HTMLResponse(state['page'], headers={'Cache-Control': 'no-store'})

    @app.get('/api/live/sessions')
    def sessions(limit: int = LIST_LIMIT):
        now = clock()
        views = [session_view(f, logs_root, reader, names, now) for f in
                 recent_folders(runs_root, logs_root, max(1, min(limit, 50)))]
        return respond({'version': VERSION, 'now': utc_iso(now),
                        'sessions': [list_item(v) for v in views if v is not None]})

    @app.get('/api/live/sessions/{session_id}')
    def session(session_id: str):
        folder = runs_root / session_id
        if not SESSION_ID.match(session_id) or folder.parent != runs_root or not folder.is_dir():
            raise HTTPException(404, 'unknown session')
        view = session_view(folder, logs_root, reader, names, clock())
        if view is None:
            raise HTTPException(404, 'session has no conditions.json yet')
        return respond({'version': VERSION, 'now': utc_iso(clock()), 'session': view})

    return app


def serve(port=DEFAULT_PORT, runner=None, **kwargs):
    app = create_app(**kwargs)
    if runner is None:
        import uvicorn
        runner = uvicorn.run
    # Loopback only: there is no authentication (DM-77, DM-89 ④).
    runner(app, host=HOST, port=port, log_level='warning')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    one = sub.add_parser('serve')
    one.add_argument('--port', type=int, default=DEFAULT_PORT)
    one.add_argument('--runs-root', type=Path, default=ROOT / 'runs' / 'demo')
    one.add_argument('--logs-root', type=Path, default=ROOT / 'logs' / 'demo')
    one.add_argument('--aggregate', type=Path, default=ROOT / 'reports' / 'c19' / 'aggregate-main.json')
    args = parser.parse_args(argv)
    print(json.dumps({'url': f'http://{HOST}:{args.port}/', 'runs_root': str(args.runs_root),
                      'logs_root': str(args.logs_root)}, ensure_ascii=False), flush=True)
    serve(args.port, runs_root=args.runs_root, logs_root=args.logs_root, aggregate=args.aggregate,
          records_root=ROOT / 'runs' / 'demo')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
