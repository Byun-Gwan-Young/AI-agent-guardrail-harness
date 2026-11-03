"""Read account access state using the database clock (db-unify schema)."""
from storage.db import get_connection


def fetch_account_state(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT account_status, deletion_requested_at, deletion_due_at,
                       CURRENT_TIMESTAMP < deletion_due_at AS can_restore
                FROM users WHERE id = %s
            """, (user_id,))
            row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(("account_status", "deletion_requested_at", "deletion_due_at", "can_restore"), row))
