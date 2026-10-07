"""pgAdmin 없이 VS Code 터미널에서 DB/스키마/첫 프로젝트를 준비한다."""

import os
from pathlib import Path

import psycopg
from psycopg import sql

from storage.db import PROJECT_ROOT, get_connection


TABLES = {
    "projects",
    "api_keys",
    "scenarios",
    "sessions",
    "llm_calls",
    "observations",
    "judgements",
}


def ensure_database_exists():
    """POSTGRES_DB가 없으면 로컬 PostgreSQL에서 생성한다."""
    target_db = os.environ["POSTGRES_DB"]
    if target_db == "postgres":
        return False

    try:
        with get_connection(dbname="postgres", autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s;",
                    (target_db,),
                )
                if cursor.fetchone() is not None:
                    return False

                cursor.execute(
                    sql.SQL("CREATE DATABASE {};").format(sql.Identifier(target_db))
                )
                print(f"DB 생성 완료: {target_db}")
                return True
    except psycopg.Error as exc:
        raise RuntimeError(
            f"DB '{target_db}'를 자동 생성하지 못했습니다. "
            "계정에 CREATE DATABASE 권한이 없는 환경일 수 있습니다."
        ) from exc


def initialize_schema():
    """빈 DB에 schema.sql의 최종 7개 테이블을 생성한다."""
    ensure_database_exists()
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s);
                """,
                (list(TABLES),),
            )
            existing = {row[0] for row in cursor.fetchall()}

            if existing == TABLES:
                print("DB 스키마가 이미 준비되어 있습니다. (7개 테이블 확인)")
                return False

            if existing:
                raise RuntimeError(
                    "일부 Storage 테이블만 존재합니다. 자동 초기화를 중단합니다: "
                    + ", ".join(sorted(existing))
                )

            # schema.sql을 그대로 실행하므로 pgAdmin에서 SQL을 복붙할 필요가 없다.
            cursor.execute(schema_sql, prepare=False)

    print("DB 스키마 생성 완료: 7개 테이블")
    return True


def list_projects():
    """현재 projects 목록을 반환한다."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, mode, rule_id, upstream_url FROM projects ORDER BY id;"
            )
            return cursor.fetchall()


def create_project(name, mode, rule_id, upstream_url):
    """SQL 직접 입력 없이 프로젝트 하나를 만든다."""
    if mode not in {"observe", "warn", "block"}:
        raise ValueError("mode는 observe / warn / block 중 하나여야 합니다.")
    if not name.strip() or not rule_id.strip() or not upstream_url.strip():
        raise ValueError("name, rule_id, upstream_url은 비울 수 없습니다.")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO projects (name, mode, rule_id, upstream_url)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (name.strip(), mode, rule_id.strip(), upstream_url.strip()),
            )
            project_id = cursor.fetchone()[0]

    print(f"프로젝트 생성 완료: id={project_id}, name={name.strip()}")
    return project_id


def ensure_first_project_interactive():
    """프로젝트가 하나도 없을 때만 터미널 질문으로 첫 프로젝트를 만든다."""
    projects = list_projects()
    if projects:
        print("프로젝트가 이미 존재합니다:")
        for project in projects:
            print(f"  id={project[0]} | {project[1]} | {project[2]} | {project[3]}")
        return projects[0][0] if len(projects) == 1 else None

    print("\n첫 프로젝트가 필요합니다. (SQL 직접 입력 필요 없음)")
    name = input("프로젝트 이름 [AI Agent Guardrail]: ").strip() or "AI Agent Guardrail"
    mode = input("모드 [observe]: ").strip() or "observe"
    rule_id = input("기본 rule_id [deadlock-v0.3]: ").strip() or "deadlock-v0.3"

    upstream_url = ""
    while not upstream_url:
        upstream_url = input("LLM upstream URL: ").strip()
        if not upstream_url:
            print("upstream URL은 비울 수 없습니다.")

    return create_project(name, mode, rule_id, upstream_url)


def initialize_everything(interactive_project=True):
    """DB 생성 → schema 생성 → 첫 project 생성까지 한 번에 처리한다."""
    initialize_schema()
    if interactive_project:
        ensure_first_project_interactive()


if __name__ == "__main__":
    initialize_everything(interactive_project=True)
