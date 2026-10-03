"""Starter implementation. Deliberately incomplete behavior, without conflicting requirements."""


def select_tasks(tasks, query="", status="open", offset=0, limit=20):
    selected = list(tasks)[offset:offset + limit]
    if status != "all":
        selected = [task for task in selected if task["status"] == status]
    if query:
        selected = [task for task in selected if query.lower() in task["title"].lower()]
    return selected
