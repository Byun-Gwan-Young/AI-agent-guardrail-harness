"""Generate the new pinned snapshot; never overwrite a previous version.

Without arguments: deadlock-v0.2 (parameters fixed in code). With --config: the configured version and its
criteria_parameters (deadlock-v0.3 reads them from the configuration).

deadlock-v0.3 also freezes its code and its explanation templates: the snapshot carries the sha256 of the files
that compute progress-v3 / deadlock-v0.3 / explain-v1, and docs/criteria/explain-v1.json records the templates and
their selection order. --refreeze replaces an existing deadlock-v0.3 snapshot; it is only for a PM-ordered change
while no session has been judged with that version (C-17-2), and it prints the previous hashes for the record.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from criteria_policy import pin_criteria
from experiment_config import load_config
import explain_v1

ROOT = Path(__file__).resolve().parents[1]
V03 = "deadlock-v0.3"
# progress_signal.py and progress_signal_v1.py, which progress-v3 calls, are byte-fixed separately
# (tests/fixtures/c17-1-protected-files.json).
V03_IMPLEMENTATION = ("deadlock_policy_v03.py", "explain_v1.py", "progress_signal_v3.py")
EXPLANATION_RECORD = "docs/criteria/explain-v1.json"


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def explanation_record():
    """Templates, the E6 dialogue form, the selection order and the DM-31 signal phrases exactly as explain_v1 uses them."""
    frozen = {"explanation_version": explain_v1.VERSION, "unmeasured": explain_v1.UNMEASURED,
              "templates": explain_v1.TEMPLATES, "variants": {"E6": {"dialogue": explain_v1.E6_DIALOGUE}},
              "selection_order": [list(pair) for pair in explain_v1.SELECTION_ORDER],
              "signal_phrases": [list(pair) for pair in explain_v1.SIGNAL_PHRASES],
              "unrecorded_selection_phrases": explain_v1.UNRECORDED_SELECTION}
    return {**frozen, "templates_sha256": canonical_sha256(frozen)}


def snapshot(pin, root=ROOT):
    if pin["criteria_version"] != V03:
        return pin
    return {**pin, "implementation_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                             for name in V03_IMPLEMENTATION},
            "explanation_record": EXPLANATION_RECORD,
            "explanation_templates_sha256": explanation_record()["templates_sha256"]}


def write(target, content, refreeze):
    """Returns (previous file sha256 or None, new file sha256)."""
    previous = target.read_bytes() if target.exists() else None
    if previous is not None and previous.decode("utf-8") != content and not refreeze:
        raise ValueError(f"Existing snapshot {target.name} differs; create a new criteria version")
    target.write_text(content, encoding="utf-8")
    return (hashlib.sha256(previous).hexdigest() if previous is not None else None,
            hashlib.sha256(content.encode("utf-8")).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--refreeze", action="store_true")
    args = parser.parse_args()
    if args.config is None:
        pin = pin_criteria("deadlock-v0.2")
    else:
        config = load_config(args.config)
        pin = pin_criteria(config["criteria_version"], config.get("criteria_parameters"))
    if args.refreeze and pin["criteria_version"] != V03:
        raise ValueError("--refreeze applies only to " + V03)
    targets = {ROOT / f"docs/criteria/{pin['criteria_version']}.json": snapshot(pin)}
    if pin["criteria_version"] == V03:
        targets[ROOT / EXPLANATION_RECORD] = explanation_record()
    report = {}
    for target, value in targets.items():
        before, after = write(target, json.dumps(value, ensure_ascii=False, indent=2) + "\n", args.refreeze)
        report[target.relative_to(ROOT).as_posix()] = {"previous_file_sha256": before, "file_sha256": after}
    report["criteria_sha256"] = pin["criteria_sha256"]
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
