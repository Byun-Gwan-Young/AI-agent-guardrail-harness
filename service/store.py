"""C-19-6 : one SQL layer for the demo database, used by the loader (service/load_demo.py) and the API (service/api.py).

The statements are written once with '?' parameters and plain SQL so that the same text runs on PostgreSQL (psycopg,
'%s' parameters) and, in the offline tests, on an in-memory SQLite database built from service/schema.sql with the
type names substituted. The API only reads; PostgreSQL connections for the API are opened read only.
"""
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.analyze_session import SEARCH_SECRET_PATTERNS, SECRET_PATTERNS  # noqa: E402

SCHEMA = Path(__file__).resolve().parent / 'schema.sql'
DB_URL_ENV = 'GUARDRAIL_DB_URL'
DB_NAME = 'guardrail_demo'
KEY_ENVS = ('KMU_API_KEY', 'TAVILY_API_KEY', 'GROQ_API_KEY')
TABLES = ('aggregates', 'steps', 'sessions', 'scenarios')   # delete order (children first)
JSON_COLUMNS = {'stop_steps', 'failure_reasons', 'changed_paths', 'facts', 'plans', 'inputs', 'body', 'role_labels'}
BOOL_COLUMNS = {'frozen', 'git_dirty', 'counted', 'blocked'}
SQLITE_TYPES = (('DOUBLE PRECISION', 'REAL'), ('TIMESTAMPTZ', 'TEXT'), ('JSONB', 'TEXT'), ('BOOLEAN', 'INTEGER'))
# Keys that would carry model text. 'reasoning' is allowed only as a token count (an integer or null).
FORBIDDEN_KEYS = {'narrative', 'reasoning_content', 'thought', 'thoughts', 'content', 'messages'}


class RecordError(ValueError):
    pass


def forbidden_fields(value, path='$'):
    """Paths in a JSON value whose key would carry model text (narrative, reasoning, message content)."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f'{path}.{key}'
            if key in FORBIDDEN_KEYS or (key == 'reasoning' and not (item is None or isinstance(item, int))):
                found.append(here)
            found += forbidden_fields(item, here)
    elif isinstance(value, list):
        for item in value:
            found += forbidden_fields(item, path + '[]')
    return found


def key_hits(text):
    """D-11 key patterns (with the search key pattern) and the key values set in this environment."""
    hits = [name for name, pattern in {**SECRET_PATTERNS, **SEARCH_SECRET_PATTERNS}.items() if pattern.search(text)]
    hits += ['env:' + env for env in KEY_ENVS if os.environ.get(env) and os.environ[env] in text]
    return hits


def sqlite_schema(text=None):
    text = SCHEMA.read_text(encoding='utf-8') if text is None else text
    for pg, lite in SQLITE_TYPES:
        text = text.replace(pg, lite)
    return text


class Store:
    """Rows in and out of the demo tables. `connect` returns a DB-API connection; dialect is 'postgres' or 'sqlite'."""

    def __init__(self, connect, dialect):
        if dialect not in ('postgres', 'sqlite'):
            raise ValueError(dialect)
        self.connect, self.dialect = connect, dialect

    # -- helpers --------------------------------------------------------------------------------------------------
    def sql(self, statement):
        return statement.replace('?', '%s') if self.dialect == 'postgres' else statement

    def to_db(self, column, value):
        if column in JSON_COLUMNS and value is not None:
            if self.dialect == 'postgres':
                from psycopg.types.json import Jsonb
                return Jsonb(value)
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if column in BOOL_COLUMNS and value is not None and self.dialect == 'sqlite':
            return int(bool(value))
        return value

    def from_db(self, column, value):
        if value is None:
            return None
        if column in JSON_COLUMNS and isinstance(value, str):
            return json.loads(value)
        if column in BOOL_COLUMNS:
            return bool(value)
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        if type(value).__name__ == 'Decimal':
            return float(value)
        return value

    def query(self, statement, params=()):
        """A list of dicts (column -> Python value)."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(self.sql(statement), tuple(params))
            names = [d[0] for d in cur.description]
            return [{n: self.from_db(n, v) for n, v in zip(names, row)} for row in cur.fetchall()]
        finally:
            self.release(conn)

    def scalar(self, statement, params=()):
        rows = self.query(statement, params)
        return None if not rows else next(iter(rows[0].values()))

    def release(self, conn):
        if self.dialect == 'postgres':
            conn.close()

    # -- writing (loader only) ------------------------------------------------------------------------------------
    def apply_schema(self):
        conn = self.connect()
        try:
            if self.dialect == 'postgres':
                conn.execute(SCHEMA.read_text(encoding='utf-8'))
                conn.commit()
            else:
                conn.executescript(sqlite_schema())
        finally:
            self.release(conn)

    def replace_all(self, rows):
        """Delete every demo row and insert `rows` ({table: [row dict]}) in one transaction: the same input gives the
        same tables however often it runs."""
        conn = self.connect()
        try:
            cur = conn.cursor()
            for table in TABLES:
                cur.execute(f'DELETE FROM {table}')
            for table in reversed(TABLES):
                for row in rows.get(table, []):
                    columns = list(row)
                    cur.execute(self.sql(f'INSERT INTO {table} ({", ".join(columns)}) VALUES '
                                         f'({", ".join("?" for _ in columns)})'),
                                tuple(self.to_db(c, row[c]) for c in columns))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release(conn)


def postgres_store(url=None, *, read_only=True):
    """A Store on GUARDRAIL_DB_URL. The URL (and any password in it) is never printed or written."""
    url = url or os.environ.get(DB_URL_ENV)
    if not url:
        raise RecordError(f'{DB_URL_ENV} is not set (e.g. postgresql://127.0.0.1:5432/{DB_NAME})')
    import psycopg

    def connect():
        conn = psycopg.connect(url)
        if read_only:
            conn.read_only = True
            conn.autocommit = True
        return conn
    return Store(connect, 'postgres')


def sqlite_store(rows=None):
    """An in-memory SQLite Store with the schema (and `rows`) loaded — the offline stand-in for PostgreSQL."""
    import sqlite3
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    store = Store(lambda: conn, 'sqlite')
    store.apply_schema()
    if rows is not None:
        store.replace_all(rows)
    return store


def database_name(store):
    return store.scalar('SELECT current_database()') if store.dialect == 'postgres' else DB_NAME


def redact_url(text):
    """Error text with any URL password removed (psycopg errors may echo the connection string)."""
    return re.sub(r'(://[^:/@\s]+:)[^@\s]+@', r'\1***@', str(text))
