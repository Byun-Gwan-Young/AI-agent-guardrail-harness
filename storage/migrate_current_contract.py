"""Preview/apply the explicit current Storage contract migration.

Default invocation is read-only preview.  Applying requires an explicit confirmation
token so `python -m storage init` can never delete legacy data by accident.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from storage.db import get_connection

CONFIRM_TOKEN = "DROP-SCENARIO-V1"
MIGRATION = Path(__file__).resolve().parent / "migrations" / "20261009_current_contract.sql"


def _scalar(cursor, sql, params=()):
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return None if row is None else row[0]


def preview():
    """Show exactly what the migration would remove/change.  No writes."""
    print("=== STORAGE CURRENT-CONTRACT MIGRATION PREVIEW ===")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT sc.id, sc.project_id, sc.scenario_key, sc.schema_version,
                       COUNT(s.id) AS sessions
                FROM scenarios sc
                LEFT JOIN sessions s ON s.scenario_id = sc.id
                WHERE sc.schema_version = 'scenario-v1'
                GROUP BY sc.id, sc.project_id, sc.scenario_key, sc.schema_version
                ORDER BY sc.id
                """
            )
            obsolete = cursor.fetchall()
            print("obsolete scenario-v1 rows:", len(obsolete))
            for row in obsolete:
                print("  ", row)

            cursor.execute(
                """
                SELECT s.id, sc.scenario_key,
                       (SELECT COUNT(*) FROM observations o WHERE o.session_id=s.id),
                       (SELECT COUNT(*) FROM judgements j WHERE j.session_id=s.id),
                       (SELECT COUNT(*) FROM llm_calls l WHERE l.session_id=s.id)
                FROM sessions s
                JOIN scenarios sc ON sc.id=s.scenario_id
                WHERE sc.schema_version='scenario-v1'
                ORDER BY s.id
                """
            )
            victims = cursor.fetchall()
            print("obsolete sessions to delete:", len(victims))
            for row in victims:
                print("  ", row)

            cursor.execute(
                """
                SELECT id, session_data ->> 'import_source'
                FROM sessions
                WHERE source IS NULL
                ORDER BY id
                """
            )
            null_sources = cursor.fetchall()
            print("source=NULL sessions before migration:", len(null_sources))
            for row in null_sources:
                print("  ", row)

            cursor.execute(
                """
                SELECT schema_version, COUNT(*)
                FROM scenarios
                WHERE schema_version IS DISTINCT FROM 'scenario-v1'
                GROUP BY schema_version
                ORDER BY schema_version NULLS FIRST
                """
            )
            preserved = cursor.fetchall()
            print("non-v1 scenario versions preserved:")
            for row in preserved:
                print("  ", row)

            null_checks = {
                "scenario_hash": _scalar(cursor, "SELECT COUNT(*) FROM scenarios WHERE scenario_hash IS NULL AND schema_version <> 'scenario-v1'"),
                "scenario.config": _scalar(cursor, "SELECT COUNT(*) FROM scenarios WHERE config IS NULL AND schema_version <> 'scenario-v1'"),
                "observation_data": _scalar(cursor, "SELECT COUNT(*) FROM observations o JOIN sessions s ON s.id=o.session_id JOIN scenarios sc ON sc.id=s.scenario_id WHERE o.observation_data IS NULL AND sc.schema_version <> 'scenario-v1'"),
                "result_data": _scalar(cursor, "SELECT COUNT(*) FROM judgements j JOIN sessions s ON s.id=j.session_id JOIN scenarios sc ON sc.id=s.scenario_id WHERE j.result_data IS NULL AND sc.schema_version <> 'scenario-v1'"),
            }
            print("current/future-version NULL payload checks:", null_checks)

    print()
    print("PREVIEW ONLY: no rows or schema objects were changed.")


def apply(confirm):
    if confirm != CONFIRM_TOKEN:
        raise SystemExit(
            "Migration not applied. Re-run with "
            f"--apply --confirm {CONFIRM_TOKEN}"
        )

    migration_sql = MIGRATION.read_text(encoding="utf-8")
    print("Applying explicit current-contract migration...")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(migration_sql, prepare=False)

    print("Migration committed successfully.")
    print("Only explicit scenario-v1 data was eligible for deletion.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply the migration")
    parser.add_argument("--confirm", help="required explicit confirmation token")
    args = parser.parse_args()

    if args.apply:
        apply(args.confirm)
    else:
        preview()


if __name__ == "__main__":
    main()
