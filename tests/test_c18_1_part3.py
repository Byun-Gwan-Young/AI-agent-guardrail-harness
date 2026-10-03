"""C-18-1 part 3: the demo session summary the PM pastes back (tools/summarize_demo_session.py) on offline DEMO-CL runs,
and the pre-run credit estimate of the trial pair. Offline."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from experiments import gateway_usage  # noqa: E402
from tools import c18_1_evidence, summarize_demo_session  # noqa: E402
import t2_harness  # noqa: E402
import test_c18_1_part2 as cl  # noqa: E402


def reading(used, at):
    return {"read_at": at, "http_status": 200, "used": used, "field": "monthly_allocated.used"}


class Summary(unittest.IsolatedAsyncioTestCase):
    async def run_cl(self, scenario, reports, tools):
        readings = [reading(10.0, "2026-10-03T00:00:00+00:00"), reading(11.25, "2026-10-03T00:05:00+00:00")]

        async def fake(upstream, key):
            return readings.pop(0)
        with mock.patch.object(gateway_usage, "reading", fake):
            return await t2_harness.run_t2(reports, tools=tools, contract=cl.V2, tests=self, scenario_path=scenario,
                                           real_acceptance=True)

    async def test_normal_run(self):
        notes = ("write_file", {"path": "NOTES.md", "content": "계획\n"})
        run = await self.run_cl(cl.NORMAL, [cl.report(), cl.report(), cl.report(declared=True, issues=())],
                                {1: notes, 2: cl.write(cl.REFERENCE)})
        with mock.patch.dict("os.environ", {"KMU_API_KEY": "kmu-value-for-the-scan-test"}):
            result = summarize_demo_session.summarize(run["out"])
        self.assertEqual((result["termination_reason"], result["steps"], result["first_stop"]), ("success", 3, None))
        self.assertEqual(result["tests_passed"], {"before": 6, "after": 15, "max": 15})
        self.assertEqual((result["credits_measured"]["status"], result["credits_measured"]["value"]), ("measured", 1.25))
        self.assertEqual(result["credits_measured"]["read_at"],
                         ["2026-10-03T00:00:00+00:00", "2026-10-03T00:05:00+00:00"])
        self.assertEqual(result["credits_estimated"]["status"], "computed")
        # Two of the fake upstream's responses carry one tool call each (steps 1 and 2); the others none.
        turns = len(run["session"]["turns"])
        self.assertEqual(result["tool_calls_per_response"], {"0": turns - 2, "1": 2})
        self.assertEqual(result["tokens"]["turns"], turns)
        self.assertEqual((result["tool_results"]["executed"], result["tool_results"]["error_results"]), (2, 0))
        self.assertEqual(result["strict_output"]["format_failures"], 0)
        self.assertEqual((result["model"], result["reasoning_effort"], result["phase"], result["guardrail_mode"]),
                         ("glm-5.3-flash", "medium", "demo", "observe"))
        self.assertTrue(result["condition_group"].startswith("cg-"))
        self.assertEqual(result["key_scan"]["key_values_checked"], ["KMU_API_KEY"])
        self.assertTrue(result["key_scan"]["clean"])
        # The printed form is JSON; exit code 0 when the scan is clean.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "argv", ["s", str(run["out"])]):
            self.assertEqual(summarize_demo_session.main(), 0)
        self.assertEqual(json.loads(out.getvalue())["session_id"], run["session_id"])

    async def test_stall_run_and_key_hit(self):
        tools = {s: cl.write(cl.REFERENCE if (s - 2) // 3 % 2 == 0 else cl.NO_SHORTHAND) for s in range(2, 31, 3)}
        run = await self.run_cl(cl.STALL, [cl.report() for _ in range(30)], tools)
        result = summarize_demo_session.summarize(run["out"])
        self.assertEqual((result["termination_reason"], result["steps"]), ("max_steps", 30))
        stop = result["first_stop"]
        self.assertEqual((stop["step_id"], stop["criteria_version"], stop["decision"], stop["template_id"]),
                         (10, "deadlock-v0.3", "deadlock", "E7"))
        self.assertEqual(result["stop_steps"], list(range(10, 31)))
        self.assertEqual(result["tests_passed"]["max"], 14)
        (run["out"] / "leak.txt").write_text("Bearer abcdefghijklmnop", encoding="utf-8")
        self.assertEqual(summarize_demo_session.summarize(run["out"])["key_scan"]["hits"], {"leak.txt": ["bearer_value"]})


class TrialEstimate(unittest.TestCase):
    def test_trial_pair(self):
        estimate = c18_1_evidence.trial()
        self.assertEqual(estimate["status"], "ESTIMATE")
        # glm 150/500 per 1M on A-1-v3 (80,115 / 7,355) and A-1-v4 (444,636 / 106,866) token counts.
        self.assertEqual(estimate["per_session"], {"normal_if_like_A-1-v3": 15.69,
                                                   "any_run_to_30_steps_like_A-1-v4": 120.13})
        self.assertEqual(estimate["trial"]["both"], [135.82, 240.26])


if __name__ == "__main__":
    unittest.main()
