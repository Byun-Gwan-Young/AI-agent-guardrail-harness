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
import criteria_freeze
from criteria_policy import pin_criteria
from experiment_config import load_config

ROOT = Path(__file__).resolve().parents[1]
V03 = criteria_freeze.V03
V03_IMPLEMENTATION = criteria_freeze.V03_IMPLEMENTATION
EXPLANATION_RECORD = criteria_freeze.EXPLANATION_RECORD
canonical_sha256 = criteria_freeze.canonical_sha256
# C-17-8: moved to criteria_freeze.py so the proxy records the same freeze with each deadlock-v0.3 session.
explanation_record = criteria_freeze.explanation_record


def snapshot(pin, root=ROOT):
    if pin["criteria_version"] != V03:
        return pin
    return {**pin, "implementation_sha256": criteria_freeze.implementation_sha256(root),
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
