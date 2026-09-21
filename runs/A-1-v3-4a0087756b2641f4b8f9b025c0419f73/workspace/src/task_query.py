"""Implementation of task selection according to acceptance criteria.
It supports status filtering, search with normalization, priority sorting,
stable id tiebreak, and pagination with validation. Input data is not mutated.
"""

import unicodedata
import re


def _normalize_text(text: str) -> str:
    # Apply NFKC, casefold, strip, and collapse whitespace to a single space.
    normalized = unicodedata.normalize('NFKC', text)
    normalized = normalized.casefold()
    normalized = normalized.strip()
    # Collapse any sequence of whitespace characters to a single space.
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def select_tasks(tasks, query="", status="open", offset=0, limit=20):
    # Validate pagination parameters.
    if offset < 0:
        raise ValueError("offset must be non‑negative")
    if limit < 0:
        raise ValueError("limit must be non‑negative")
    if limit == 0:
        return []

    # Validate status.
    if status not in ("open", "done", "all"):
        raise ValueError("invalid status")

    # Work on a shallow copy of the task list to avoid mutating the input.
    tasks_list = list(tasks)

    # Status filter.
    if status != "all":
        tasks_list = [t for t in tasks_list if t.get("status") == status]

    # Search filter.
    if query:
        norm_query = _normalize_text(query)
        if norm_query:
            filtered = []
            for t in tasks_list:
                title_norm = _normalize_text(t.get("title", ""))
                desc_norm = _normalize_text(t.get("description", ""))
                if norm_query in title_norm or norm_query in desc_norm:
                    filtered.append(t)
            tasks_list = filtered

    # Sorting: priority descending, then id ascending.
    tasks_list.sort(key=lambda t: (-t.get("priority", 0), t.get("id", "")))

    # Pagination after filtering and sorting.
    return tasks_list[offset:offset + limit]

