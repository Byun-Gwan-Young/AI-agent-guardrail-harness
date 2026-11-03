"""pgAdmin 없이 터미널에서 DB/schema를 준비하는 helper.

사용자 소유 프로젝트 생성은 인증 경계인 ``storage.accounts.create_project``가
담당한다. 이 모듈은 owner 없는 writable 프로젝트를 자동 생성하지 않는다.
"""

from pathlib import Path

import psycopg
from psycopg import sql

from storage.db import get_connection, get_target_database_name


TABLES = {
    "users",
    "allowed_emails",
    "auth_events",
    "projects",
    "api_keys",
    "scenarios",
    "sessions",
    "llm_calls",
    "observations",
    "judgements",
}


def ensure_database_exists():
    """Create the configured application DB only when it is confirmed absent.

    We first try the target DB so existing deployments do not need CREATE
    DATABASE privilege. psycopg may surface a missing database as a generic
    OperationalError during connection startup, so a failed target connection
    is *not* itself treated as proof that the DB is missing. We verify existence
    through the maintenance database before deciding whether to create it.
    """

    target_db = get_target_database_name()

    try:
        with get_connection(autocommit=True):
            return False
    except (psycopg.OperationalError, psycopg.errors.InvalidCatalogName) as target_error:
        if target_db == "postgres":
            raise RuntimeError(
                "PostgreSQL target database 'postgres' is not reachable"
            ) from target_error

        try:
            with get_connection(dbname="postgres", autocommit=True) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s;",
                        (target_db,),
                    )
                    if cursor.fetchone() is not None:
                        # The database exists, so the original failure was auth,
                        # network, TLS, socket, or another connection problem.
                        raise RuntimeError(
                            f"DB '{target_db}'는 존재하지만 연결에 실패했습니다. "
                            "접속 주소/인증/권한을 확인하세요."
                        ) from target_error

                    cursor.execute(
                        sql.SQL("CREATE DATABASE {};").format(sql.Identifier(target_db))
                    )
                    print(f"DB 생성 완료: {target_db}")
                    return True
        except RuntimeError:
            raise
        except psycopg.Error as exc:
            raise RuntimeError(
                f"DB '{target_db}' 존재 여부 확인 또는 자동 생성에 실패했습니다. "
                "배포 환경이라면 운영자가 DB를 미리 만들었는지와 "
                "maintenance DB/CREATE DATABASE 권한을 확인하세요."
            ) from exc


def initialize_schema():
    """Apply the canonical schema without deleting user/session data."""
    ensure_database_exists()

    schema_path = Path(__file__).resolve().parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # schema.sql is additive/idempotent. Destructive historical cleanup
            # belongs in an explicit one-time migration, never in normal init.
            cursor.execute(schema_sql, prepare=False)

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
            missing = TABLES - existing

            if missing:
                raise RuntimeError(
                    "스키마 적용 후에도 일부 테이블이 없습니다: "
                    + ", ".join(sorted(missing))
                )

    print(f"DB 스키마 적용 완료: {len(TABLES)}개 테이블 확인")
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
    """Retired legacy bootstrap helper.

    Ownerless writable projects bypass the account/ownership contract and can
    also persist an unchecked upstream URL. Keep the symbol only to fail loudly
    for any old caller; service projects must go through storage.accounts.
    """
    raise RuntimeError(
        "legacy ownerless project bootstrap is retired; "
        "use storage.accounts.create_project(owner_user_id, name, mode)"
    )


def ensure_first_project_interactive():
    """Report project state without creating an ownerless writable project."""
    projects = list_projects()
    if projects:
        print("프로젝트가 이미 존재합니다:")
        for project in projects:
            print(f"  id={project[0]} | {project[1]} | {project[2]} | {project[3]}")
        return projects[0][0] if len(projects) == 1 else None

    print(
        "프로젝트가 없습니다. 스키마 초기화만 완료했습니다. "
        "사용자 프로젝트는 로그인/백엔드에서 "
        "storage.accounts.create_project(...)로 생성하세요."
    )
    return None


def initialize_everything(interactive_project=True):
    """DB 확인/생성 -> canonical schema 적용 -> 프로젝트 상태 안내.

    ``interactive_project``는 기존 CLI 호출 호환을 위해 남겼다. True여도
    프로젝트를 생성하지 않고 현재 상태만 보여 준다.
    """
    initialize_schema()
    if interactive_project:
        ensure_first_project_interactive()


if __name__ == "__main__":
    initialize_everything(interactive_project=True)
