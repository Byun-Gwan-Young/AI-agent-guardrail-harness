from psycopg import Connection


def fetch_sessions(conn: Connection, project_id: int, limit: int, offset: int, owner_user_id: int):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM sessions AS s
            JOIN scenarios AS sc ON sc.id = s.scenario_id
            JOIN projects AS p ON p.id = sc.project_id
            WHERE sc.project_id = %s AND p.owner_user_id = %s
            """,
            (project_id, owner_user_id),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT
                s.id, s.scenario_id, s.status, s.termination_reason,
                s.phase, s.guardrail_mode, s.model, s.steps_reached,
                s.total_tokens, s.first_stop_step, s.started_at, s.ended_at
            FROM sessions AS s
            JOIN scenarios AS sc ON sc.id = s.scenario_id
            JOIN projects AS p ON p.id = sc.project_id
            WHERE sc.project_id = %s AND p.owner_user_id = %s
            ORDER BY s.started_at DESC, s.id
            LIMIT %s OFFSET %s
            """,
            (project_id, owner_user_id, limit, offset),
        )
        return {"items": cursor.fetchall(), "total": total, "limit": limit, "offset": offset}


def fetch_session_detail(conn: Connection, project_id: int, session_id: str, owner_user_id: int):
    """Only return a session belonging to the requested project."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                s.id, s.scenario_id, s.status, s.termination_reason,
                s.phase, s.guardrail_mode, s.model, s.steps_reached,
                s.total_tokens, s.first_stop_step, s.started_at, s.ended_at
            FROM sessions AS s
            JOIN scenarios AS sc ON sc.id = s.scenario_id
            JOIN projects AS p ON p.id = sc.project_id
            WHERE sc.project_id = %s AND s.id = %s AND p.owner_user_id = %s
            """,
            (project_id, session_id, owner_user_id),
        )
        return cursor.fetchone()
