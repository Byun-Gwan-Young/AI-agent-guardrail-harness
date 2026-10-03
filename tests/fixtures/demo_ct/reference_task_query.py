"""DEMO-CT answer path (C-18-2, guideline 5-2): the normal variant's acceptance tests all pass with this file as
src/task_query.py and the starting SPEC.md approved as it is. Kept out of every scenario fixture: agents never see it."""
import unicodedata


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


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
