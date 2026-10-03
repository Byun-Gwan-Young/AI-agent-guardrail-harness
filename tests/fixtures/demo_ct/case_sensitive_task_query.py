"""DEMO-CT stall variant, the other side of the pair (C-18-2): the reference with a case-sensitive search
(ACCEPTANCE 7 instead of the casefold of ACCEPTANCE 2). Shows that side is reachable too, never both."""
import unicodedata


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def select_tasks(tasks, query="", status="open", offset=0, limit=20):
    if offset < 0 or limit < 0:
        raise ValueError("offset and limit must not be negative")
    if status not in ("open", "done", "all"):
        raise ValueError("unknown status: " + str(status))
    selected = [task for task in tasks if status == "all" or task["status"] == status]
    needle = _normalized(query)
    if needle:
        selected = [task for task in selected
                    if needle in _normalized(task["title"]) or needle in _normalized(task["description"])]
    selected = sorted(selected, key=lambda task: (-task["priority"], str(task["id"])))
    return selected[offset:offset + limit]
