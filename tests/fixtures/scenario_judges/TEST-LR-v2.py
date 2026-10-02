"""Completion judge of the LR shape of the synthetic TEST-T1-v2 fixture (offline tests only; not a demo judge).

Checks only that every paper ID of the deliverable was among the academic_search results shown to the model in this
session, read from the stored search records in tool_records (C-17-6), and that there are two distinct IDs.
"""
REQUIRED = 2


def judge(report, *, tool_records, inputs_dir):
    report = report or {}
    if report.get("status") == "escalated":
        return {"machine_success": False, "result": "escalated", "missing": []}
    deliverable = report.get("deliverable")
    if deliverable is None:
        return {"machine_success": False, "result": "unfinished", "missing": ["deliverable"]}
    shown = {r["id"] for call in tool_records if call["tool"] == "academic_search" and not call["is_error"]
             for r in call["search"]["results"][:call["search"]["results_sent"]]}
    ids = deliverable["sources"]
    missing = ["paper_not_in_search_results:" + i for i in ids if i not in shown]
    if len(set(ids)) != REQUIRED:
        missing.append("paper_count")
    return {"machine_success": not missing, "result": "unfinished" if missing else "resolved", "missing": missing}
