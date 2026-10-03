"""C-18-2 part 3: the credits expected for the C-18-2 trial plan, from the C-18-1 measured credits (an estimate,
tools/c18_2_evidence.py trial -> reports/c18-2/estimate-trial.json). Offline."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TrialEstimate(unittest.TestCase):
    def test_estimate_from_the_c18_1_measured_credits(self):
        from tools import c18_2_evidence
        result = c18_2_evidence.trial_estimate()
        self.assertEqual(result["status"], "estimated")
        self.assertEqual([(r["item"], r["low"], r["high"]) for r in result["sessions"]],
                         [("DEMO-CT-normal-v1:observe:1", 16.35269, 126.5433),
                          ("DEMO-CT-stall-v1:observe:1", 126.5433, 126.5433),
                          ("DEMO-CT-N-v1:observe:1", 16.35269, 126.5433)])
        self.assertEqual(result["total"], {"low": 159.24868, "high": 379.6299})
        stored = json.loads((ROOT / "reports/c18-2/estimate-trial.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, result)


if __name__ == "__main__":
    unittest.main()
