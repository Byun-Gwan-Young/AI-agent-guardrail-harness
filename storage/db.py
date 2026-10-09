"""PostgreSQL connection helpers for local development and deployed service use.

Connection contract (highest priority first):

1. ``GUARDRAIL_DB_URL``
   The deployment/server connection string.  This may be a normal TCP URI or
   a Unix-socket URI such as::

       postgresql:///guardrail_demo?host=/var/run/postgresql

   A password is intentionally *not* required.  On AWS/Linux the service may
   use PostgreSQL peer authentication over a Unix socket.

2. ``POSTGRES_*`` fallback
   Kept for the existing local ``.env`` workflow.  ``POSTGRES_DB`` is the only
   required value; host/port/user/password are passed only when configured so
   libpq defaults (including local socket/peer auth) remain usable.

Do not log either the URL or password here.  They may contain credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ``override=False`` is python-dotenv's default: real runtime/AWS environment
# variables win over values from the developer's local .env file.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def get_guardrail_db_url() -> str | None:
    """Return the deployment DSN when configured, otherwise ``None``.

    Keeping this lookup inside a function is deliberate: tests, CLI tools, and
    deployment wrappers may set environment variables after module import.
    """

    return _clean_env("GUARDRAIL_DB_URL")


def get_target_database_name() -> str:
    """Return the canonical application database name without exposing secrets.

    ``python -m storage init`` needs the target name when it checks/creates a
    database.  When the URL path is used we parse it through psycopg/libpq
    rather than manually splitting the URI, which also supports Unix-socket
    query parameters safely.
    """

    db_url = get_guardrail_db_url()
    if db_url:
        try:
            dbname = conninfo_to_dict(db_url).get("dbname")
        except psycopg.Error as exc:
            raise RuntimeError("GUARDRAIL_DB_URL is not a valid PostgreSQL connection string") from exc

        if not dbname:
            raise RuntimeError(
                "GUARDRAIL_DB_URL must identify a database, e.g. "
                "postgresql:///guardrail_demo?host=/var/run/postgresql"
            )
        return dbname

    dbname = _clean_env("POSTGRES_DB")
    if not dbname:
        raise RuntimeError(
            "PostgreSQL database is not configured. Set GUARDRAIL_DB_URL "
            "or POSTGRES_DB."
        )
    return dbname


def _fallback_connection_kwargs(dbname: str | None = None) -> dict:
    """Build safe libpq kwargs for the legacy/local ``POSTGRES_*`` path.

    Password, host, port and user are optional on purpose.  Omitting them lets
    libpq use its normal defaults and permits passwordless Unix-socket/peer
    authentication.  Existing Windows/local .env files that specify every
    value continue to work unchanged.
    """

    target_db = dbname or _clean_env("POSTGRES_DB")
    if not target_db:
        raise RuntimeError(
            "POSTGRES_DB is required when GUARDRAIL_DB_URL is not configured."
        )

    kwargs = {"dbname": target_db}
    env_to_kwarg = (
        ("POSTGRES_HOST", "host"),
        ("POSTGRES_PORT", "port"),
        ("POSTGRES_USER", "user"),
        ("POSTGRES_PASSWORD", "password"),
    )
    for env_name, kwarg in env_to_kwarg:
        value = _clean_env(env_name)
        if value is not None:
            kwargs[kwarg] = value

    return kwargs


def get_connection(dbname=None, autocommit=False):
    """Open a PostgreSQL connection using the unified 2-6 precedence contract.

    ``dbname`` is an internal override used by ``init_db`` when it needs the
    maintenance ``postgres`` database.  All other connection details still
    come from the chosen deployment/local source.
    """

    db_url = get_guardrail_db_url()
    if db_url:
        # Keyword parameters override values embedded in conninfo, so init_db
        # can switch only the database while preserving socket/host/user/etc.
        kwargs = {"autocommit": autocommit}
        if dbname is not None:
            kwargs["dbname"] = dbname
        return psycopg.connect(db_url, **kwargs)

    kwargs = _fallback_connection_kwargs(dbname)
    kwargs["autocommit"] = autocommit
    return psycopg.connect(**kwargs)


def get_project_id(explicit_project_id=None):
    """
    사용할 project_id를 결정한다.

    우선순위:
    1) 명령어에서 직접 받은 값
    2) .env/환경변수의 POSTGRES_PROJECT_ID
    3) DB에 쓰기 가능한 프로젝트가 정확히 1개면 그 id 자동 선택

    read_only 데모 프로젝트는 raw importer의 자동 선택 대상에서 제외한다.
    명시적으로 read_only id를 넘겨도 import_run.verify_project()가 다시 거부한다.

    ``POSTGRES_PROJECT_ID``는 접속 정보가 아니라 CLI/importer 편의 설정이므로
    ``GUARDRAIL_DB_URL``을 사용하는 서버에서도 그대로 사용할 수 있다.
    """
    raw = explicit_project_id or os.getenv("POSTGRES_PROJECT_ID")

    if raw is not None:
        try:
            project_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("project_id는 정수여야 합니다.") from exc

        if project_id < 1:
            raise ValueError("project_id는 1 이상의 정수여야 합니다.")
        return project_id

    # raw importer는 사용자/서비스의 writable project에만 써야 한다.
    # 데모 프로젝트(read_only=TRUE)가 유일한 행이어도 자동 선택하지 않는다.
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM projects WHERE read_only = FALSE ORDER BY id;"
            )
            rows = cursor.fetchall()

    if len(rows) == 1:
        return rows[0][0]
    if not rows:
        raise RuntimeError(
            "쓰기 가능한 프로젝트가 없습니다. 사용자 프로젝트는 로그인/백엔드에서 "
            "storage.accounts.create_project(...)로 생성하세요."
        )

    raise RuntimeError(
        "쓰기 가능한 프로젝트가 여러 개라 자동 선택할 수 없습니다. "
        "POSTGRES_PROJECT_ID를 지정하세요."
    )
