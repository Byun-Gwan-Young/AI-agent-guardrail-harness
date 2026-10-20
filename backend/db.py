"""Request-scoped PostgreSQL connections using the existing storage settings."""

from contextlib import contextmanager

from fastapi import HTTPException
from psycopg import OperationalError
from psycopg.rows import dict_row

from storage.db import get_connection


def get_db():
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            yield conn
    except (OperationalError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc


# Explicit scope for endpoints that must validate input before connecting.
db_connection = contextmanager(get_db)
