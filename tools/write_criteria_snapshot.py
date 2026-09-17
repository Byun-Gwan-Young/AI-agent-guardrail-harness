"""Generate the new pinned snapshot; never overwrite a previous version."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deadlock_policy import pin_criteria


def main():
    target = Path(__file__).resolve().parents[1] / "docs/criteria/deadlock-v0.2.json"
    content = json.dumps(pin_criteria("deadlock-v0.2"), ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != content:
        raise ValueError("Existing version snapshot differs; create a new criteria version")
    target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
