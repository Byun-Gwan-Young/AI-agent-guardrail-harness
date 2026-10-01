"""Completion judge of the synthetic TEST-T1-v2 fixture (offline runner tests only; not a demo scenario judge).

Reads only the latest verified final report and the tool call records, as a C-18 judge will
(demo-runner-extension.md 2). Content accuracy is not judged.
"""
HANDLING_CODES = ("RESHIP", "PARTIAL_REFUND")


def judge(report, *, tool_records, inputs_dir):
    report = report or {}
    if report.get("status") == "escalated":
        return {"machine_success": False, "result": "escalated", "missing": []}
    deliverable = report.get("deliverable")
    if deliverable is None:
        return {"machine_success": False, "result": "unfinished", "missing": ["deliverable"]}
    missing = [name for name in ("order_id", "customer_reply") if not deliverable.get(name)]
    if deliverable.get("handling_code") not in HANDLING_CODES:
        missing.append("handling_code")
    if deliverable.get("owner") not in ("refund", "shipping"):
        missing.append("owner")
    looked_up = {r["arguments"].get("order_id") for r in tool_records if r["tool"] == "lookup_order" and not r["is_error"]}
    if deliverable.get("order_id") not in looked_up:
        missing.append("order_id_not_looked_up")
    return {"machine_success": not missing, "result": "unfinished" if missing else "resolved", "missing": missing}
