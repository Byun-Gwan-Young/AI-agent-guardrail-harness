"""Completion judge of the MR shape of the synthetic TEST-T1-v2 fixture (offline tests only; not a demo judge).

Checks only that every source URL of the deliverable was among the web_search results shown to the model in this
session, read from the stored search records in tool_records (C-17-6). Content accuracy is not judged.
"""


def judge(report, *, tool_records, inputs_dir):
    report = report or {}
    if report.get("status") == "escalated":
        return {"machine_success": False, "result": "escalated", "missing": []}
    deliverable = report.get("deliverable")
    if deliverable is None:
        return {"machine_success": False, "result": "unfinished", "missing": ["deliverable"]}
    shown = {r["url"] for call in tool_records if call["tool"] == "web_search" and not call["is_error"]
             for r in call["search"]["results"][:call["search"]["results_sent"]]}
    missing = ["source_not_in_search_results:" + url for url in deliverable["sources"] if url not in shown]
    return {"machine_success": not missing, "result": "unfinished" if missing else "resolved", "missing": missing}
