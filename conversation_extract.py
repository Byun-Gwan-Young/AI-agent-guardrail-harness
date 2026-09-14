"""Conservative text-only rule extractor. Structured reference is never an input."""
import re

from progress_schema import Conversation

VERSION = "rules-v1"
NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
RULES = {
    "timeout_ms": rf"(?:timeout|타임아웃)\s*(?:is|은|는|:|=)?\s*{NUMBER}\s*ms\b",
    "ram_gb": rf"(?:RAM|메모리)\s*(?:is|은|는|:|=)?\s*{NUMBER}\s*GB\b",
    "budget_usd": rf"(?:budget|예산)\s*(?:is|은|는|:|=)?\s*\$\s*{NUMBER}",
}


def extract_conversation(text, previous=None):
    proposals, reasons, evidence = {}, {}, []
    for key, pattern in RULES.items():
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        values = {float(m.group(1)) for m in matches}
        if len(values) == 1:
            proposals[key] = values.pop()
            evidence.extend({"metric": key, "text": m.group(0)} for m in matches)
        elif len(values) > 1:
            reasons[key] = "ambiguous: multiple numeric values in one utterance"
    if not proposals:
        reasons["proposal_values"] = "no unambiguous supported numeric proposal"

    # Scope is explicitly observed issue IDs, never an assertion that all issues are known.
    previous_ids = (previous or {}).get("open_issue_ids")
    issue_ids = set(previous_ids or [])
    issue_pattern = r"\b(issue-[A-Za-z0-9_-]+)\s*(?:is|:)?\s*(reopened|open|resolved|closed|재개|미해결|해결|종료)\b"
    matches = list(re.finditer(issue_pattern, text, re.IGNORECASE))
    for match in matches:
        key, state = match.group(1).lower(), match.group(2).lower()
        if state in ("open", "reopened", "재개", "미해결"):
            issue_ids.add(key)
        else:
            issue_ids.discard(key)
        evidence.append({"metric": "open_issue_ids", "text": match.group(0)})
    if not matches:
        reasons["open_issue_ids"] = "no explicit issue-state evidence in this utterance"

    items = [m.group(1).strip() for m in re.finditer(r"(?:new info|새 정보)\s*:\s*([^\n]+)", text, re.I)]
    if not items:
        reasons["info_items"] = "no supported new-information expression"
    return Conversation(source_kind="extracted", proposal_values=proposals or None,
                        open_issue_ids=sorted(issue_ids) if matches else None,
                        info_items=items or None, extractor_version=VERSION,
                        reasons=reasons, evidence=evidence).model_dump()


def compare_extraction(reference, candidate):
    """Field exact-match against A; not ground-truth verification or dataset aggregation."""
    if reference.get("source_kind") != "structured" or candidate.get("source_kind") != "extracted":
        raise ValueError("Expected structured A reference and extracted B candidate")
    result = {}
    for field in ("proposal_values", "open_issue_ids", "info_items"):
        expected, actual = reference.get(field), candidate.get(field)
        if expected is None:
            result[field] = {"status": "unmeasured", "match": None}
        else:
            if isinstance(expected, list):
                expected = set(expected)
                actual = set(actual) if isinstance(actual, list) else actual
            result[field] = {"status": "measured", "match": expected == actual,
                             "extraction_missing": actual is None}
    return result
