"""C-17-8 part 0: the C-17-6 decisions DM-52 ① (search call limit default 20), ④ (one LR session at a time, stated by
the pre-run check) and ⑥ (a particle after the unit word "step" is attached, "step" taking the after-final-consonant
form), and the arXiv fixture corrected to the shape of the PM search probe search-probe-46ec37a0… (2026-10-02)."""
import copy
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import yaml

from experiments import dialogue_runner, search_tools
from explain_v1 import E6_DIALOGUE, REDUCED, TEMPLATES, explain
from scenario_schema import DEFAULT_SEARCH_CALLS_PER_SESSION, ScenarioV2
from search_fixtures import ACADEMIC, ARXIV_200, LR, MR, WEB, FakeClock, FakeTransport
from t1_harness import FIXTURE, FIXTURES
import test_c17_6_part0 as c176
from tools import probe_search

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "runs/search-probes/search-probe-46ec37a046664b988be9e3075ce43c89"
SENTENCES = {**TEMPLATES, "E6-dialogue": E6_DIALOGUE, **{"reduced-" + k: v for k, v in REDUCED.items()}}
# Particles that change with a final consonant, as "after a final consonant" / "otherwise", plus the fixed ones.
AFTER_FINAL = ("은", "이", "을", "과")
OTHERWISE = ("는", "가", "를", "와")
FIXED = ("의", "에서", "에", "도", "만", "으로", "로")


class UnitParticleTests(unittest.TestCase):
    def test_e7_attaches_the_particle_to_step(self):
        result = explain(c176.signals(consecutive_states=["stagnant", "oscillating", "stagnant"],
                                      test_plateau_in_streak=False))
        self.assertEqual((result["template_id"], result["text"]),
                         ("E7", "최근 3 step 중 1 step은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다."))

    def test_no_template_leaves_a_space_between_step_and_a_particle(self):
        # "step 동안", "step 이후", "step 중" are nouns after the unit and keep their space.
        particle = "|".join(AFTER_FINAL + OTHERWISE + FIXED)
        for name, text in SENTENCES.items():
            with self.subTest(sentence=name):
                self.assertIsNone(re.search(r"step (" + particle + r")(?![가-힣])", text))

    def test_step_takes_the_after_final_consonant_form(self):
        # 스텝 ends in a final consonant: 은/이/을/과, never 는/가/를/와.
        for name, text in SENTENCES.items():
            with self.subTest(sentence=name):
                self.assertIsNone(re.search(r"step(" + "|".join(OTHERWISE) + r")(?![가-힣])", text))
        self.assertIn("{o} step은", TEMPLATES["E7"])
        # Units after a number still keep their space (DM-42, DM-49).
        self.assertIn("{n} step 중", TEMPLATES["E7"])


class SearchLimitDefaultTests(unittest.TestCase):
    def scenario(self, changes, tool):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data.update(copy.deepcopy(changes))
        del data["tool_settings"][tool]["max_calls_per_session"]
        return ScenarioV2.model_validate(data)

    def test_an_omitted_limit_is_20_and_is_recorded(self):
        self.assertEqual(DEFAULT_SEARCH_CALLS_PER_SESSION, 20)
        for changes, tool in ((MR, "web_search"), (LR, "academic_search")):
            with self.subTest(tool=tool):
                settings = self.scenario(changes, tool).tool_settings.model_dump(exclude_none=True)
                self.assertEqual(settings[tool]["max_calls_per_session"], 20)
                # What the runner keeps in conditions.json and the manifest carries the value used.
                self.assertEqual(search_tools.conditions_record(settings)[tool]["settings"]["max_calls_per_session"], 20)

    def test_a_scenario_value_still_wins(self):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data.update(copy.deepcopy(MR))
        self.assertEqual(ScenarioV2.model_validate(data).tool_settings.web_search.max_calls_per_session,
                         WEB["max_calls_per_session"])

    def test_the_twenty_first_call_is_refused_without_a_request(self):
        transport = FakeTransport(*[(200, ARXIV_200)] * 21)
        with tempfile.TemporaryDirectory() as directory:
            settings = {"academic_search": {**{k: v for k, v in ACADEMIC.items() if k != "max_calls_per_session"},
                                            "max_calls_per_session": DEFAULT_SEARCH_CALLS_PER_SESSION}}
            clock = FakeClock()
            session = search_tools.SearchSession(settings, Path(directory), transport=transport, clock=clock.clock,
                                                 sleep=clock.sleep, now=lambda: "2026-10-03T00:00:00+00:00")
            for _ in range(20):
                session.search("academic_search", {"query": "all:x"}, {"step_id": 1})
            with self.assertRaisesRegex(Exception, "limit of 20 academic_search calls"):
                session.search("academic_search", {"query": "all:x"}, {"step_id": 1})
        self.assertEqual(len(transport.calls), 20)


class OneLrSessionNoticeTests(unittest.TestCase):
    def scenario(self, changes):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data.update(copy.deepcopy(changes))
        return ScenarioV2.model_validate(data)

    def test_the_pre_run_check_states_it_for_academic_search_only(self):
        lr = dialogue_runner.tool_preflight(self.scenario(LR), FIXTURES, {})
        self.assertEqual(lr["notices"], [dialogue_runner.LR_ONE_AT_A_TIME])
        self.assertIn("one academic_search (LR) session at a time", lr["notices"][0])
        mr = dialogue_runner.tool_preflight(self.scenario(MR), FIXTURES, {"TAVILY_API_KEY": "x"})
        cs = dialogue_runner.tool_preflight(self.scenario({}), FIXTURES, {})
        # Runs without academic_search keep the record they had (C-17-6).
        self.assertNotIn("notices", mr)
        self.assertNotIn("notices", cs)


class ArxivLiveShapeTests(unittest.TestCase):
    def test_the_fixture_now_has_the_probe_response_shape(self):
        live = (PROBE / "arxiv-response.xml").read_bytes()
        shape = probe_search.compare("arxiv", live, ARXIV_200)
        self.assertEqual((shape["missing_in_response"], shape["extra_in_response"], shape["type_differences"],
                          shape["tool_fields_present"], shape["same_shape"]), ([], [], {}, True, True))
        # Optional per entry (arXiv manual): absent from all five live results, kept in the fixture for both cases.
        self.assertEqual(shape["optional_absent"], ["feed/entry/arxiv:doi", "feed/entry/arxiv:journal_ref",
                                                    "feed/entry/author/arxiv:affiliation"])

    def test_the_three_attributes_the_live_feed_lacks_are_gone(self):
        fixture = set(probe_search.shape_of("arxiv", ARXIV_200))
        for path in ("feed/link@rel", "feed/title@type", "feed/entry/arxiv:primary_category@scheme"):
            self.assertNotIn(path, fixture)

    def test_the_live_response_normalizes(self):
        live = search_tools.normalize("arxiv", (PROBE / "arxiv-response.xml").read_bytes())
        self.assertEqual((len(live["results"]), live["total_results"]), (5, 1056))
        self.assertTrue(all(r["id"] and r["title"] and r["authors"] and r["year"] for r in live["results"]))


ATOM = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><title>q</title>'
        '<opensearch:totalResults>{total}</opensearch:totalResults>{entries}</feed>')


def entry(identifier, inner):
    return "<entry><id>http://arxiv.org/abs/" + identifier + "</id>" + inner + "</entry>"


class ArxivFieldsPerEntryTests(unittest.TestCase):
    """An entry may have or lack each optional element; the parser keeps going and reports what is there."""

    def normalize(self, *entries, total="3"):
        return search_tools.normalize("arxiv", ATOM.format(total=total, entries="".join(entries)).encode())

    def test_entries_with_and_without_the_optional_elements(self):
        full = entry("2601.00001v1", "<title>Full</title><summary>s</summary><published>2026-01-02T00:00:00Z</published>"
                     "<updated>2026-01-05T00:00:00Z</updated><author><name>A</name>"
                     "<arxiv:affiliation>U</arxiv:affiliation></author><arxiv:comment>c</arxiv:comment>"
                     "<arxiv:journal_ref>j</arxiv:journal_ref><arxiv:doi>10.0/x</arxiv:doi>"
                     '<arxiv:primary_category term="cs.MA"/><category term="cs.MA" scheme="s"/>'
                     '<link href="https://arxiv.org/abs/2601.00001v1" rel="alternate" type="text/html"/>')
        bare = entry("2601.00002v2", "<title>Bare</title>")
        no_summary = entry("cs/0101001v3", "<title>Old id</title><author><name>B</name></author>"
                           "<published>2001-01-01T00:00:00Z</published>")
        result = self.normalize(full, bare, no_summary)
        self.assertEqual(result, {"total_results": 3, "results": [
            {"rank": 1, "id": "2601.00001v1", "title": "Full", "authors": ["A"], "year": 2026, "excerpt": "s"},
            {"rank": 2, "id": "2601.00002v2", "title": "Bare", "authors": [], "year": None, "excerpt": ""},
            {"rank": 3, "id": "cs/0101001v3", "title": "Old id", "authors": ["B"], "year": 2001, "excerpt": ""}]})

    def test_missing_title_author_name_or_total_do_not_stop_the_parser(self):
        result = self.normalize(entry("2601.00003v1", "<author></author><published>not a date</published>"),
                                total="")
        self.assertEqual(result, {"total_results": None, "results": [
            {"rank": 1, "id": "2601.00003v1", "title": "", "authors": [""], "year": None, "excerpt": ""}]})

    def test_an_entry_without_an_abstract_id_is_still_a_parse_error(self):
        # The id is what the judge checks against (decision 018); without it the response is not usable.
        with self.assertRaises(search_tools.ParseError):
            self.normalize(entry("x", "<title>t</title>").replace("http://arxiv.org/abs/x", "not-an-id"))
        with self.assertRaises(search_tools.ParseError):
            self.normalize("<entry><title>no id</title></entry>")


if __name__ == "__main__":
    unittest.main()
