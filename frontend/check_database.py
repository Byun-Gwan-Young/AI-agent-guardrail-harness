"""Read-only startup check. Credentials come from the launcher process only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.db import get_connection

try:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
            cursor.execute("SELECT to_regclass('public.users'), to_regclass('public.sessions')")
            if not all(cursor.fetchone()):
                raise RuntimeError('schema')
    print('Local database and schema are available. Existing data was not modified.')
except Exception:
    print('Local database check failed. Verify PostgreSQL, credentials and the existing guardrail_local_pc schema. No changes were made.')
    raise SystemExit(1)
