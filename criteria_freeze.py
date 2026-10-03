"""What freezes deadlock-v0.3 besides its parameters (DM-33, C-17-2): the sha256 of the files that compute progress-v3 /
deadlock-v0.3 / explain-v1 and the explanation record (templates, selection order, particle rules).

tools/write_criteria_snapshot.py writes them into docs/criteria/deadlock-v0.3.json and docs/criteria/explain-v1.json;
the proxy records the same values with each deadlock-v0.3 session (C-17-8), so a refreeze is another condition group
even though criteria_sha256 (the parameters) stays the same.
"""
import hashlib
import json
from pathlib import Path

import explain_v1

ROOT = Path(__file__).resolve().parent
V03 = "deadlock-v0.3"
# progress_signal.py and progress_signal_v1.py, which progress-v3 calls, are byte-fixed separately
# (tests/fixtures/c17-1-protected-files.json).
V03_IMPLEMENTATION = ("deadlock_policy_v03.py", "explain_v1.py", "progress_signal_v3.py")
EXPLANATION_RECORD = "docs/criteria/explain-v1.json"


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def explanation_record():
    """Templates, the E6 dialogue form, the E7 all-reverted form (DM-61 ①), the selection order, the DM-31 signal
    phrases, the DM-36 particle pairs, the DM-49 digit rule and the DM-50 required values, reduced sentences and
    fallback exactly as explain_v1 uses them."""
    frozen = {"explanation_version": explain_v1.VERSION, "unmeasured": explain_v1.UNMEASURED,
              "templates": explain_v1.TEMPLATES,
              "variants": {"E6": {"dialogue": explain_v1.E6_DIALOGUE}, "E7": {"all_reverted": explain_v1.E7_ALL}},
              "selection_order": [list(pair) for pair in explain_v1.SELECTION_ORDER],
              "signal_phrases": [list(pair) for pair in explain_v1.SIGNAL_PHRASES],
              "unrecorded_selection_phrases": explain_v1.UNRECORDED_SELECTION,
              "particles": list(explain_v1.PARTICLES),
              "digits_with_final_consonant": explain_v1.DIGITS_WITH_FINAL_CONSONANT,
              "required_values": {k: list(v) for k, v in explain_v1.REQUIRED_VALUES.items()},
              "reduced_templates": explain_v1.REDUCED, "fallback": explain_v1.FALLBACK}
    return {**frozen, "templates_sha256": canonical_sha256(frozen)}


def implementation_sha256(root=ROOT):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in V03_IMPLEMENTATION}


def freeze(criteria_version, root=ROOT):
    """The code and template identity of a deadlock-v0.3 judge, with one sha256 over both; None for the versions
    whose rules are fixed in code (v0.1, v0.2)."""
    if criteria_version != V03:
        return None
    values = {"implementation_sha256": implementation_sha256(root),
              "explanation_templates_sha256": explanation_record()["templates_sha256"]}
    return {**values, "sha256": canonical_sha256(values)}
