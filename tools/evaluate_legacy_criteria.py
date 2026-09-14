"""Read-only legacy audit. Conditional projections are NOT real step observations."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if Path(__file__).parent.name == "tools":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conversation_extract import extract_conversation
from deadlock_policy import evaluate_criteria, pin_criteria
from progress_schema import Observation
from progress_signal import calculate_progress


def load(path):
    raw = Path(path).read_bytes()
    rows = json.loads(raw)
    return rows, hashlib.sha256(raw).hexdigest()


def observation(index, conversation, metric, context):
    return Observation.model_validate({"step_id": index, "llm_turns": [index],
        "progress_source": "conversation", "progress_metric": {"conversation": [metric]},
        "conversation": conversation, "termination_context": context}).model_dump()


def append(history, item):
    item["progress"] = calculate_progress(history, item)
    history.append(item)


def audit_raw(rows):
    history = []
    for index, row in enumerate(rows, 1):
        item = observation(index, extract_conversation(row.get("out", "")),
                           "proposal_value_delta", None)
        append(history, item)
    return {"assumed": True, "assumptions": ["one logged request is provisionally mapped to one step"],
            "result": evaluate_criteria(history, pin_criteria()),
            "states": [h["progress"]["state"] for h in history]}


def proposal_projection(rows):
    history, evidence = [], []
    for index, row in enumerate(rows, 1):
        text = row["out"]
        # Audit-only projection of explicitly proposed RAM, after the final proposal verb.
        # Never deployed as rules-v1, never read expected outcomes from the filename.
        verbs = list(re.finditer(r"\b(?:recommend|propose|provide|offer|proposal (?:is|remains))\b", text, re.I))
        fragment = text[verbs[-1].start():] if verbs else ""
        match = re.search(r"(\d+)\s*GB[\s\-‑–]*RAM", fragment, re.I)
        value = int(match.group(1)) if match else None
        conv = {"source_kind": "extracted", "extractor_version": "legacy-audit-proposed-ram-v1",
                "proposal_values": {"ram_gb": value} if value is not None else None}
        context = {"declaration": "none", "source_kind": "human_annotation",
                   "evidence": "Manual review of this legacy file found repeated rejection, no completion declaration"}
        append(history, observation(index, conv, "proposal_value_delta", context))
        evidence.append({"logged_turn": row["turn"], "ram_gb": value, "proposal_fragment": fragment,
                         "state": history[-1]["progress"]["state"]})
    return {"assumed": True, "assumptions": ["one logged request equals one provisional step",
            "only explicitly proposed RAM is evaluated; other possible progress is excluded",
            "absence of declaration is a manual transcript annotation, not a detected signal"],
            "result": evaluate_criteria(history, pin_criteria()), "evidence": evidence}


def termination_projection(rows, declaration_turn):
    positions = [i for i, row in enumerate(rows, 1) if row["turn"] == declaration_turn]
    if len(positions) != 1:
        raise ValueError("Manual declaration annotation must reference one existing log record")
    declared = positions[0]
    history = []
    for index, row in enumerate(rows, 1):
        # Before the manual anchor, retain unknown. No outcome label is inferred.
        items = [row["out"]] if index == declared else (
            [] if index > declared and row["out"].strip() == "" else None)
        conv = {"source_kind": "extracted", "extractor_version": "legacy-audit-empty-output-v1",
                "info_items": items}
        context = ({"declaration": "declared", "declared_step": declared,
                    "source_kind": "human_annotation", "evidence": rows[declared - 1]["out"]}
                   if index >= declared else None)
        append(history, observation(index, conv, "new_info_ratio", context))
    return {"assumed": True, "assumptions": ["one logged request equals one provisional step",
            "declaration anchor is manually annotated, not automatically detected",
            "empty output after the anchor is treated as no new conversational information",
            "artifact activity and pre-declaration failure cannot be verified"],
            "declaration_logged_turn": declaration_turn, "declaration_evidence": rows[declared - 1]["out"],
            "result": evaluate_criteria(history, pin_criteria()),
            "trace": [{"logged_turn": row["turn"], "step": h["step_id"], "state": h["progress"]["state"]}
                      for row, h in zip(rows, history)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deadlock", required=True)
    parser.add_argument("--termination", required=True)
    parser.add_argument("--termination-declaration-turn", required=True, type=int,
                        help="Human annotation; not a tuned or automatically detected threshold")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {"criteria": pin_criteria(), "role": "legacy development audit, not independent evaluation",
              "files": {}}
    for profile, path in [("proposal_audit", args.deadlock), ("post_declaration_audit", args.termination)]:
        rows, digest = load(path)
        report["files"][profile] = {"path": str(Path(path).resolve()), "sha256": digest,
            "logged_records": len(rows), "formal_result": {"decision": "unmeasured",
                "reason": "No original observations, task step mapping, criteria pin or termination context"},
            "current_extractor_projection": audit_raw(rows),
            "conditional_projection": proposal_projection(rows) if profile == "proposal_audit"
            else termination_projection(rows, args.termination_declaration_turn)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {"formal": v["formal_result"], "conditional": v["conditional_projection"]["result"]}
                      for k, v in report["files"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
