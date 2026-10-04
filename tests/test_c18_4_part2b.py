"""C-18-4 (DM-68): the offline tests never wait without end. A fake upstream with no scripted report left answers 400
at once (not retried), so a flow given too few reports ends quickly; tools/run_offline_tests.py runs each module under
a time limit and reports the module that passed it. Offline."""
import io
import time
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tools import run_offline_tests  # noqa: E402
from t1_harness import report, run_t1  # noqa: E402
from test_c18_3_part1 import NORMAL, REAL  # noqa: E402


class ExhaustedUpstream(unittest.IsolatedAsyncioTestCase):
    async def test_too_few_reports_end_the_run_quickly(self):
        start = time.monotonic()
        run = await run_t1([report("triage", handoff="refund", issues=("ownership",))], tools={},
                           implementations=REAL, scenario_path=NORMAL, scenario_root=ROOT, tests=self)
        self.assertLess(time.monotonic() - start, 20)
        self.assertNotEqual(run["summary"]["termination_reason"], "success")
        self.assertLess(run["summary"]["steps"], 30)


def slow_case():
    """Built inside the tests so that discovery does not run it on its own."""
    class Slow(unittest.TestCase):
        def test_sleeps(self):
            time.sleep(5)

        def test_after(self):
            pass

        def test_z_left(self):
            pass
    return Slow


class ModuleTimeLimit(unittest.TestCase):
    def test_a_slow_module_is_interrupted_and_named(self):
        timed_out = []
        suite = run_offline_tests.TimedModule(unittest.defaultTestLoader.loadTestsFromTestCase(slow_case()), "slow", 0.3,
                                              timed_out)
        result = unittest.TextTestResult(io.StringIO(), False, 0)
        start = time.monotonic()
        suite.run(result)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(timed_out, ["slow"])
        # test_after passes, test_sleeps is interrupted, test_z_left is reported without running
        self.assertEqual(result.testsRun, 3)
        self.assertEqual([t.id().rsplit(".", 1)[1] for t, _ in result.errors], ["test_sleeps", "test_z_left"])
        self.assertIn("ModuleTimeout", result.errors[0][1])

    def test_a_quick_module_runs_as_before(self):
        timed_out = []
        suite = run_offline_tests.TimedModule([slow_case()("test_after")], "quick", 5, timed_out)
        result = unittest.TextTestResult(io.StringIO(), False, 0)
        suite.run(result)
        self.assertEqual((timed_out, result.testsRun, result.wasSuccessful()), ([], 1, True))


if __name__ == "__main__":
    unittest.main()
