"""C-18-4 part 1 (DM-67 ②): the DEMO-MR judge (shared by the normal and stall pair) compares a cited URL with the
stored web_search results after url_key, so the same page written differently matches (http/https, host letter case,
a trailing "/", a "#..." fragment, tracking query parameters) and anything else does not. The trial refusal
"https://codeassist.google/" against the result "https://codeassist.google" now passes. Offline."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scenario_schema import load_scenario  # noqa: E402
from t1_harness import report  # noqa: E402
from test_c18_3_part2 import PRODUCTS, SHARE_URLS, URLS, search_call, table  # noqa: E402

JUDGE = ROOT / "scenario_judges/DEMO-MR-v1.py"


def module():
    spec = importlib.util.spec_from_file_location("demo_mr_judge_c18_4", JUDGE)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


MR = module()


class UrlKey(unittest.TestCase):
    def test_the_same_page_written_differently_has_one_key(self):
        base = "https://cursor.com/pricing"
        for variant in ("https://cursor.com/pricing/", "http://cursor.com/pricing", "https://Cursor.COM/pricing",
                        "https://cursor.com/pricing#pro", "https://cursor.com/pricing?utm_source=x&utm_medium=y",
                        "https://cursor.com/pricing/?gclid=1#top", " https://cursor.com/pricing "):
            self.assertEqual(MR.url_key(variant), MR.url_key(base), variant)
        self.assertEqual(MR.url_key("https://codeassist.google/"), MR.url_key("https://codeassist.google"))

    def test_other_pages_keep_other_keys(self):
        base = MR.url_key("https://cursor.com/pricing")
        for other in ("https://cursor.com/pricing/teams", "https://docs.cursor.com/pricing",
                      "https://www.cursor.com/pricing", "https://cursor.com/pricing?plan=pro",
                      "https://cursor.com/Pricing", "https://cursor.com/help/account-and-billing/pricing"):
            self.assertNotEqual(MR.url_key(other), base, other)
        self.assertEqual(MR.url_key("https://a.example/p?b=2&utm_x=1&a=1"), MR.url_key("https://a.example/p?b=2&a=1"))
        self.assertNotEqual(MR.url_key("https://a.example/p?a=1&b=2"), MR.url_key("https://a.example/p?b=2&a=1"))


class JudgeWithUrlKey(unittest.TestCase):
    def judged(self, deliverable, results):
        return MR.judge(report("completed", deliverable=deliverable),
                        tool_records=[search_call("web_search", [{"url": u} for u in results])], inputs_dir=None)

    def test_the_trial_refusal_passes_now(self):
        cited = table()
        for row in cited["rows"]:
            row["pricing"]["source_url"] = row["features"]["source_url"] = URLS[row["product"]] + "/"
        self.assertEqual(self.judged(cited, URLS.values()), {"machine_success": True, "result": "resolved",
                                                              "missing": []})
        cited["rows"][2]["pricing"]["source_url"] = "https://codeassist.google/"
        self.assertEqual(self.judged(cited, list(URLS.values()) + ["https://codeassist.google"])["missing"], [])

    def test_a_url_not_among_the_results_is_still_refused(self):
        cited = table()
        cited["rows"][0]["pricing"]["source_url"] = "https://docs.github.com/en/copilot/get-started/plans-for-github-copilot"
        results = list(URLS.values()) + ["https://docs.github.com/en/copilot/get-started/plans"]
        self.assertEqual(self.judged(cited, results)["missing"], ["github-copilot:pricing:source_not_in_search_results"])

    def test_the_stall_pairs_source_urls_use_the_same_key(self):
        shown = list(URLS.values()) + SHARE_URLS
        written = [u + "/#section" for u in SHARE_URLS]
        self.assertTrue(self.judged(table(written), shown)["machine_success"])
        self.assertEqual(self.judged(table([SHARE_URLS[0], SHARE_URLS[0] + "/"]), shown)["missing"],
                         [f"{p}:market_share:two_independent_sources" for p in PRODUCTS])

    def test_both_scenarios_still_name_this_judge(self):
        for name in ("DEMO-MR-normal-v1", "DEMO-MR-stall-v1"):
            self.assertEqual(load_scenario(ROOT / "scenarios" / f"{name}.yaml").judge, "scenario_judges/DEMO-MR-v1.py")


if __name__ == "__main__":
    unittest.main()
