"""C-19-6 (DM-89) : read-only query API over the demo database, on 127.0.0.1:8020 only.

  GUARDRAIL_DB_URL=... venv/bin/python -m service.api [--port 8020]

GET only : /api/summary, /api/scenarios, /api/sessions (filters), /api/sessions/{id}, /api/sessions/{id}/steps.
Automatic API pages : /docs (Swagger UI) and /redoc. Response shapes follow the data the C-19-3 screen reads (the
aggregate's headline and replay.json steps) so the screen can switch from files to this API later.
No write endpoint, no authentication, so the server binds to the loopback address only. Every response is checked for
model text fields (narrative, reasoning) and key patterns before it leaves; a hit returns 500 without the body.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from service import queries  # noqa: E402
from service.store import RecordError, forbidden_fields, key_hits, postgres_store, redact_url  # noqa: E402

API_VERSION = 'demo-api-v1'
HOST = '127.0.0.1'
PORT = 8020
LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def guarded(payload):
    """The payload as a JSON response, unless it carries model text fields or a key pattern."""
    text = json.dumps(payload, ensure_ascii=False)
    if forbidden_fields(payload) or key_hits(text):
        return JSONResponse({'detail': 'response withheld: model text field or key pattern found'}, status_code=500)
    return JSONResponse(payload)


def create_app(store):
    app = FastAPI(title='agent-guardrail demo records API', version=API_VERSION,
                  description='데모 기록 조회 (읽기 전용). 데모 세션 기준 · 유도한 교착 (DM-2·DM-5). '
                              'C-19-6, DM-89. 쓰기 엔드포인트 없음.')

    @app.get('/api/summary', summary='발표 숫자 (SQL 로 다시 셈) · 제외 사유 · 판정 시간')
    def summary():
        return guarded({'api_version': API_VERSION, **queries.summary(store)})

    @app.get('/api/scenarios', summary='시나리오 목록 (한국어 이름 · 유형 · 짝 · 세션 수 · 집계 표)')
    def scenarios():
        return guarded({'api_version': API_VERSION, 'scenarios': queries.scenarios(store)})

    @app.get('/api/sessions', summary='세션 목록 (필터 : 시나리오 · 정상/교착 · 모드 · 유효)')
    def sessions(scenario_id: str | None = None, task: str | None = None, task_type: str | None = None,
                 variant: str | None = Query(None, description='normal · stall · natural'),
                 mode: str | None = Query(None, description='observe · block'),
                 validity: str | None = Query(None, description='valid · excluded · not_counted'),
                 plan_id: str | None = None, plan_kind: str | None = None,
                 klass: str | None = Query(None, alias='class', description='success · stalled · escalated · other')):
        filters = {'scenario_id': scenario_id, 'task': task, 'task_type': task_type, 'variant': variant,
                   'mode': mode, 'validity': validity, 'plan_id': plan_id, 'plan_kind': plan_kind, 'class': klass}
        rows = queries.sessions(store, filters)
        return guarded({'api_version': API_VERSION, 'filters': {k: v for k, v in filters.items() if v is not None},
                        'count': len(rows), 'sessions': rows})

    @app.get('/api/sessions/{session_id}', summary='세션 하나')
    def session(session_id: str):
        row = queries.session(store, session_id)
        if row is None:
            raise HTTPException(404, 'no such session')
        return guarded({'api_version': API_VERSION, 'session': row})

    @app.get('/api/sessions/{session_id}/steps', summary='세션의 step 별 구조화 값 (replay.json 그대로 + 판정 값)')
    def steps(session_id: str):
        if queries.session(store, session_id) is None:
            raise HTTPException(404, 'no such session')
        return guarded({'api_version': API_VERSION, 'session_id': session_id,
                        'steps': queries.steps(store, session_id)})

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--host', default=HOST)
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        print(json.dumps({'error': f'refusing to bind {args.host!r}: no authentication, loopback only'}))
        return 2
    try:
        store = postgres_store()
        store.scalar('SELECT 1')
    except RecordError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
    except Exception as error:
        print(json.dumps({'error': type(error).__name__ + ': ' + redact_url(error)}, ensure_ascii=False))
        return 2
    import uvicorn
    uvicorn.run(create_app(store), host=args.host, port=args.port, log_level='info')
    return 0


if __name__ == '__main__':
    sys.exit(main())
