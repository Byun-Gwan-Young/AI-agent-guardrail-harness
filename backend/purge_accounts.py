"""Account cleanup worker. Preview by default; --execute enables deletion."""
import argparse
import json
import time

from psycopg import Error as DatabaseError

from storage import accounts
from storage.db import get_connection


def preview_due_accounts(limit):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id FROM users
            WHERE account_status = 'pending_deletion'
              AND deletion_due_at <= CURRENT_TIMESTAMP
            ORDER BY deletion_due_at, id LIMIT %s
        """, (limit,)).fetchall()
    return {"execute": False, "candidate_count": len(rows),
            "user_ids": [row[0] for row in rows]}


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Permanently delete due accounts")
    parser.add_argument("--limit", type=positive_int, default=100)
    parser.add_argument("--interval", type=positive_int,
                        help="Repeat every N seconds; omit for a single batch")
    args = parser.parse_args(argv)
    try:
        while True:
            try:
                result = (accounts.purge_due_accounts(args.limit) if args.execute
                          else preview_due_accounts(args.limit))
                failed = bool(result.get("failed_count", 0))
            except (DatabaseError, RuntimeError):
                # Never emit DB exception text or credentials into worker logs.
                result = {"error": "Account cleanup database unavailable"}
                failed = True
            print(json.dumps(result, default=str), flush=True)
            if args.interval is None:
                return 1 if failed else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
