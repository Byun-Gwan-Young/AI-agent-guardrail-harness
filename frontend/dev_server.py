"""Optional local composition; reuses backend and DB unchanged. Never deploy this adapter to AWS."""
import os
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'frontend'))

from dotenv import load_dotenv
load_dotenv(ROOT / 'frontend/.env.local', override=False)
os.environ.setdefault('GOOGLE_CLIENT_ID', os.getenv('VITE_GOOGLE_CLIENT_ID', ''))
os.environ.setdefault('GOOGLE_LOGIN_URI', 'http://localhost:5173/api/auth/google')
os.environ.setdefault('AUTH_COOKIE_SECURE', 'false')

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from backend.main import app
from backend.auth.dependencies import optional_account
from service.api import create_app
from tools.demo_live import create_app as create_live_app
from export_reference import collect_reference

@app.middleware('http')
async def gate_query_api(request: Request, call_next):
    if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/auth/'):
        try:
            user = optional_account(request)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        if not user:
            return JSONResponse({'detail': 'Login required'}, status_code=401)
        if user.get('account_status') != 'active' or user.get('session_scope') != 'full':
            return JSONResponse({'detail': 'Account recovery required'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    return response

# psycopg uses POSTGRES_* via storage. Service's legacy read-only Store accepts a connection factory.
from storage.db import get_connection
from service.store import Store

def read_connection():
    conn = get_connection(autocommit=True)
    conn.read_only = True
    return conn

app.include_router(create_app(Store(read_connection, 'postgres')).router)
live = create_live_app(page='Local React UI is served by Vite.')
# Reuse only the read-only live API; the old HTML root is kept in its original app.
for route in live.routes:
    if getattr(route, 'path', '').startswith('/api/live/'):
        app.router.routes.append(route)

@lru_cache(maxsize=1)
def reference():
    return collect_reference()

@app.get('/api/frontend/reference', include_in_schema=False)
def frontend_reference():
    return reference()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8040, access_log=False)
