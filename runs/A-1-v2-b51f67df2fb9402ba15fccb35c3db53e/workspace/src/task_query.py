"""Implementation of task selection with filtering, searching, sorting, and pagination.

The function does not modify the input list or its task dictionaries.
"""

import unicodedata


def _normalize(text: str) -> str:
    # NFKC, casefold, strip, collapse whitespace
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    # collapse whitespace and strip
    normalized = " ".join(normalized.split())
    return normalized


def select_tasks(tasks, query="", status="open", offset=0, limit=20):
    # Validate pagination parameters
    if offset < 0:
        raise ValueError("offset must be non‑negative")
    if limit < 0:
        raise ValueError("limit must be non‑negative")

    # Validate status
    if status not in ("open", "done", "all"):
        raise ValueError("unknown status")

    # Work on a shallow copy to avoid mutating input
    filtered = list(tasks)

    # Status filter
    if status != "all":
        filtered = [t for t in filtered if t.get("status") == status]

    # Search filter
    if query is not None:
        qnorm = _normalize(query)
        if qnorm:
            def matches(task):
                title = _normalize(task.get("title", ""))
                description = _normalize(task.get("description", ""))
                return qnorm in title or qnorm in description
            filtered = [t for t in filtered if matches(t)]

    # Sorting: priority descending, then id ascending
    filtered.sort(key=lambda t: (-t.get("priority", 0), t.get("id", "")))

    # Pagination
    if limit == 0:
        return []
    return filtered[offset:offset + limit]
