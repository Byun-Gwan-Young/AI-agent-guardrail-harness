"""Acceptance identity excludes implementation files, includes tests, contract and command."""
import hashlib
import json
from pathlib import Path


def compute_test_suite_id(workspace, test_roots, contract_files, command):
    root = Path(workspace).resolve(strict=True)
    files = set()

    def contained(relative):
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Suite paths must remain within the workspace")
        return path

    for relative in test_roots:
        directory = contained(relative)
        if not directory.is_dir():
            raise ValueError("test_roots must be directories")
        for path in directory.rglob("*"):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError("Test symlink leaves workspace")
            if resolved.is_file():
                files.add(resolved)
    for relative in contract_files:
        files.add(contained(relative))
    records = []
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        records.append({"path": path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    value = {"format": "acceptance-suite-v1", "files": records, "command": command}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return "sha256:" + digest
