"""Shared offline pieces for the search tool tests (C-17-6): settings, a fake HTTP layer serving the fixtures in
tests/fixtures/search/, and the MR / LR shapes of the synthetic TEST-T1-v2 fixture (edited in test code; the
demo scenarios are C-18)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH = ROOT / "tests/fixtures/search"
TAVILY_200 = (SEARCH / "tavily-search-200.json").read_bytes()
TAVILY_432 = (SEARCH / "tavily-error-432.json").read_bytes()
ARXIV_200 = (SEARCH / "arxiv-query-200.xml").read_bytes()
ARXIV_400 = (SEARCH / "arxiv-error-400.xml").read_bytes()
KEY = "tvly-OFFLINE-TEST-KEY-0123456789"
WEB = {"provider": "tavily", "max_results": 3, "search_depth": "basic", "topic": "general",
       "max_result_chars": 4000, "max_calls_per_session": 5, "timeout_seconds": 20.0}
ACADEMIC = {"provider": "arxiv", "max_results": 3, "sort_by": "relevance", "sort_order": "descending",
            "max_result_chars": 6000, "max_calls_per_session": 5, "timeout_seconds": 20.0,
            "min_interval_seconds": 3.0}


class FakeTransport:
    """Answers each request with the next scripted (status, body) or raises a scripted exception. Keeps every call."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, data = item
        kind = "application/json" if data.lstrip().startswith(b"{") else "application/atom+xml; charset=utf-8"
        return status, kind, data


class NoNetwork:
    """A transport for replay: any request is a test failure."""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append(a)
        raise AssertionError("replay must not search again")


class FakeClock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def research_changes(tool, judge, settings):
    """scenario_changes for t1_harness: lead / searcher / writer in the fixed order, the searcher with one search tool."""
    return {
        "turn_order": "fixed",
        "agents": [{"id": "lead", "role": "조사 책임", "system_message": "당신은 조사 책임입니다.", "tools": []},
                   {"id": "searcher", "role": "검색 담당", "system_message": "당신은 검색 담당입니다.", "tools": [tool]},
                   {"id": "writer", "role": "작성 담당", "system_message": "당신은 작성 담당입니다.", "tools": []}],
        "deliverable_schema": {"type": "object", "additionalProperties": False, "required": ["sources"],
                               "properties": {"sources": {"type": "array", "minItems": 1,
                                                          "items": {"type": "string", "minLength": 1}}}},
        "judge": "scenario_judges/" + judge + ".py",
        "tool_settings": {tool: settings},
        "termination_context_collection": {"source_kind": "scenario_rule", "method": "structured_completion_flag",
                                           "declarer_agent": "writer", "field": "completion_declared",
                                           "missing_output": "unknown", "preserve_first_declaration": True,
                                           "evidence_fields": ["agent_id", "step_id", "completion_declared",
                                                               "narrative"]},
    }


MR = research_changes("web_search", "TEST-MR-v2", WEB)
LR = research_changes("academic_search", "TEST-LR-v2", ACADEMIC)
