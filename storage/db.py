"""PostgreSQL 연결과 기본 프로젝트 선택을 담당하는 모듈."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

_REQUIRED_DB_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)


def get_connection(dbname=None, autocommit=False):
    """.env의 PostgreSQL 설정으로 연결한다."""
    missing = [name for name in _REQUIRED_DB_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "PostgreSQL 환경변수가 없습니다: " + ", ".join(missing)
        )

    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=dbname or os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=autocommit,
    )


def get_project_id(explicit_project_id=None):
    """
    사용할 project_id를 결정한다.

    우선순위:
    1) 명령어에서 직접 받은 값
    2) .env의 POSTGRES_PROJECT_ID
    3) DB에 프로젝트가 정확히 1개면 그 id 자동 선택
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

    # 프로젝트가 하나뿐이면 --project-id 없이도 바로 사용할 수 있게 한다.
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects ORDER BY id;")
            rows = cursor.fetchall()

    if len(rows) == 1:
        return rows[0][0]
    if not rows:
        raise RuntimeError(
            "projects 테이블에 프로젝트가 없습니다. "
            "먼저 `python -m storage`에서 DB/프로젝트 초기화를 실행하세요."
        )

    raise RuntimeError(
        "프로젝트가 여러 개라 자동 선택할 수 없습니다. "
        ".env에 POSTGRES_PROJECT_ID를 지정하세요."
    )
