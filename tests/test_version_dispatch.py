import json
from pathlib import Path
import unittest

from progress_signal import calculate_progress
from deadlock_policy import pin_criteria, evaluate_criteria, progress_version_for

ROOT = Path(__file__).resolve().parents[1]


class VersionDispatchTests(unittest.TestCase):
    def test_v1_serialized_results_are_byte_identical(self):
        log = json.loads((ROOT / "logs/A-1-82c393c248a34286b318f344f2e181e4.json").read_text())
        expected = json.loads((ROOT / "tests/fixtures/v1-calculation-bytes.json").read_text())
        history = []
        self.assertEqual(len(log["observations"]), len(expected))
        for observation, row in zip(log["observations"], expected):
            progress = calculate_progress(history, observation, version="progress-v1")
            record = {**observation, "progress": progress}
            criteria = evaluate_criteria(history + [record], log["meta"])
            self.assertEqual(json.dumps(progress, ensure_ascii=False).encode(), row["progress_bytes"].encode())
            self.assertEqual(json.dumps(criteria, ensure_ascii=False).encode(), row["criteria_bytes"].encode())
            history.append(record)

    def test_legacy_pin_matches_preserved_snapshot_bytes(self):
        expected = json.loads((ROOT / "docs/criteria/deadlock-v0.1.json").read_text())
        self.assertEqual(json.dumps(pin_criteria()).encode(), json.dumps(expected).encode())
        self.assertEqual(progress_version_for(expected), "progress-v1")

    def test_invalid_pin_or_unknown_version_never_falls_back(self):
        self.assertIsNone(progress_version_for({}))
        pin = pin_criteria(); pin["criteria_sha256"] = "invalid"
        self.assertIsNone(progress_version_for(pin))
        self.assertEqual(calculate_progress([], {}, version=None)["state"], "unmeasured")
        with self.assertRaises(ValueError):
            pin_criteria("unknown")
