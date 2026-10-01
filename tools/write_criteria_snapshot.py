"""Generate the new pinned snapshot; never overwrite a previous version.

Without arguments: deadlock-v0.2 (parameters fixed in code). With --config: the configured version and its
criteria_parameters (deadlock-v0.3 reads them from the configuration).
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from criteria_policy import pin_criteria
from experiment_config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.config is None:
        pin = pin_criteria("deadlock-v0.2")
    else:
        config = load_config(args.config)
        pin = pin_criteria(config["criteria_version"], config.get("criteria_parameters"))
    target = Path(__file__).resolve().parents[1] / f"docs/criteria/{pin['criteria_version']}.json"
    content = json.dumps(pin, ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != content:
        raise ValueError("Existing version snapshot differs; create a new criteria version")
    target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
