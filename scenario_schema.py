"""Scenario-v1 and scenario-v2 contracts. Definitions only; loading never executes agents or commands.

scenario-v2 (C-17-3, demo track) adds T1 dialogue tasks: no files or acceptance tests, a completion judge,
an ordered status list with display names, per-role tool names and T1 metrics. scenario-v1 is unchanged.
"""
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

import json_subset
from progress_schema import Metrics, ObservedMetrics


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Agent(Definition):
    id: str
    role: str
    system_message: str = Field(min_length=1)
    permissions: list[Literal["read_files", "write_files", "run_tests"]]
    writable_paths: list[str] = Field(default_factory=list)


class Termination(Definition):
    mode: Literal["success_or_max_steps"]
    max_steps: int = Field(ge=1)
    max_llm_calls_per_step: int = Field(ge=1)
    require_completion_declaration: bool
    on_criteria_alert: Literal["observe_only"]


class TerminationCollection(Definition):
    source_kind: Literal["scenario_rule"]
    method: Literal["structured_completion_flag"]
    declarer_agent: str
    field: Literal["completion_declared"]
    missing_output: Literal["unknown"]
    preserve_first_declaration: Literal[True]
    evidence_fields: list[str]


class TestSuite(Definition):
    test_suite_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    test_roots: list[str] = Field(min_length=1)
    contract_files: list[str] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    expected_test_count: int = Field(ge=1)


class SuccessCriteria(Definition):
    kind: Literal["tests", "structured_constraints"]
    description: str
    test_suite: TestSuite | None = None
    structured_schema: str | None = None
    evaluator_command: list[str] | None = None
    require_all_tests_pass: Literal[True] = True
    require_unchanged_test_suite: Literal[True] = True

    @model_validator(mode="after")
    def valid_evaluator(self):
        if self.kind == "tests" and self.test_suite is None:
            raise ValueError("Test scenarios require an immutable acceptance suite")
        if self.kind == "structured_constraints" and (not self.structured_schema or not self.evaluator_command):
            raise ValueError("Conversation scenarios require a machine-checkable schema and evaluator")
        return self


class TokenEstimate(Definition):
    assumed: Literal[True]
    expected_llm_calls_min: int = Field(ge=1)
    expected_llm_calls_max: int = Field(ge=1)
    mean_input_tokens_per_call: int = Field(ge=0)
    mean_output_fraction_of_max_tokens: float = Field(gt=0, le=1)
    assumptions: list[str] = Field(min_length=1)


class AllowedIssue(Definition):
    id: str
    definition: str

    @model_validator(mode="after")
    def nonempty_single_line(self):
        if not self.id.strip() or self.id != self.id.strip() or any(c.isspace() for c in self.id):
            raise ValueError("Issue ID must be nonempty and contain no whitespace; no normalization")
        if not self.definition.strip() or len(self.definition.splitlines()) != 1:
            raise ValueError("Issue definition must be a nonempty single line")
        return self


class Scenario(Definition):
    schema_version: Literal["scenario-v1"]
    scenario_id: str
    # Bumped whenever execution conditions change; runs of different revisions are not compared.
    scenario_revision: int = Field(default=1, ge=1)
    group: Literal["A", "B", "C"]
    title: str
    model: str
    agents: list[Agent] = Field(min_length=1)
    task: str = Field(min_length=1)
    termination: Termination
    seed: int | None
    seed_support: Literal["supported", "unsupported", "unverified"]
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1)
    # Protocol v9 sends this on every model call (D-29). None keeps the v8 and earlier behaviour.
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    # Repository path of the probe result that indicates the upstream applies reasoning_effort.
    reasoning_effort_evidence: str | None = None
    context_buffer_messages: int | None = Field(default=None, ge=1)
    progress_source: Literal["conversation", "artifact", "both"]
    progress_metric: Metrics
    conversation_collection: Literal["structured_with_paired_extraction", "extracted"]
    expected_outcome: Literal["unknown", "success", "deadlock", "termination_failure"]
    success_criteria: SuccessCriteria
    termination_context_collection: TerminationCollection
    criteria_version: Literal["deadlock-v0.1", "deadlock-v0.2"]
    fixture_dir: str | None = None
    monitored_paths: list[str] = Field(default_factory=list)
    initial_issue_ids: list[str] = Field(default_factory=list)
    # None identifies a legacy scenario with no closed vocabulary.
    allowed_issues: list[AllowedIssue] | None = None
    token_estimate: TokenEstimate

    @model_validator(mode="after")
    def consistency(self):
        initial = self.initial_issue_ids
        if any(not i.strip() or any(c.isspace() for c in i) for i in initial) or len(initial) != len(set(initial)):
            raise ValueError("Initial issue IDs must be nonempty, whitespace-free and unique")
        if self.allowed_issues is not None:
            allowed = [i.id for i in self.allowed_issues]
            if len(allowed) != len(set(allowed)):
                raise ValueError("Allowed issue IDs must be unique")
            if not set(initial) <= set(allowed):
                raise ValueError("Initial issue IDs must be a subset of allowed issue IDs")
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)) or self.termination_context_collection.declarer_agent not in ids:
            raise ValueError("Agent IDs must be unique and declarer must exist")
        if self.reasoning_effort_evidence is not None and self.reasoning_effort is None:
            raise ValueError("reasoning_effort_evidence requires reasoning_effort")
        if self.seed_support != "supported" and self.seed is not None:
            raise ValueError("Do not claim a fixed seed unless support is confirmed")
        if self.group == "A" and (self.progress_source != "both" or not self.fixture_dir
                                 or self.success_criteria.kind != "tests"):
            raise ValueError("Group A requires both sources and executable acceptance tests")
        if self.group == "B" and (self.progress_source != "conversation" or self.fixture_dir is not None):
            raise ValueError("Group B is conversation-only")
        if self.progress_source in ("conversation", "both") and not self.progress_metric.conversation:
            raise ValueError("Conversation metrics required")
        if self.progress_source in ("artifact", "both") and not self.progress_metric.artifact:
            raise ValueError("Artifact metrics required")
        e = self.token_estimate
        if not e.expected_llm_calls_min <= e.expected_llm_calls_max <= (
                self.termination.max_steps * self.termination.max_llm_calls_per_step):
            raise ValueError("Expected calls must fit the declared maximum")
        return self


ID = r"^[a-z][a-z0-9_-]{0,31}$"
ARTIFACT_TOOLS = ("read_file", "write_file", "replace_in_file", "run_tests")
WRITE_TOOLS = ("write_file", "replace_in_file")
# Tool names of the T1 tasks (demo-runner-extension.md 5). Their implementation is a later unit.
DIALOGUE_TOOLS = ("lookup_order", "read_policy", "web_search", "academic_search")
JUDGE_PATH = re.compile(r"^scenario_judges/[A-Za-z0-9_.-]+\.py$")
# The one terminal status of a dialogue task (DM-18, DM-46).
ESCALATED = "escalated"


class AgentV2(Definition):
    id: str = Field(pattern=ID)
    # Korean display name, registered for the STOP sentence (DM-26). Scenario setting, not model output.
    role: str = Field(min_length=1)
    system_message: str = Field(min_length=1)
    tools: list[Literal["read_file", "write_file", "replace_in_file", "run_tests",
                        "lookup_order", "read_policy", "web_search", "academic_search"]]
    writable_paths: list[str] = Field(default_factory=list)


class StatusValue(Definition):
    id: str = Field(pattern=ID)
    label: str = Field(min_length=1)


def relative_path(value, name):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(name + " must be a relative POSIX path inside the repository")


class ScenarioV2(Definition):
    schema_version: Literal["scenario-v2"]
    scenario_id: str = Field(min_length=1)
    title: str
    task_kind: Literal["artifact", "dialogue"]
    model: str
    agents: list[AgentV2] = Field(min_length=1)
    turn_order: Literal["fixed", "router"]
    task: str = Field(min_length=1)
    termination: Termination
    seed: int | None
    seed_support: Literal["supported", "unsupported", "unverified"]
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    reasoning_effort_evidence: str | None = None
    context_buffer_messages: int | None = Field(default=None, ge=1)
    progress_source: Literal["conversation", "artifact", "both"]
    progress_metric: ObservedMetrics
    # Outcome is always judged after the run (5-1); demo variants are not labelled here.
    expected_outcome: Literal["unknown"]
    termination_context_collection: TerminationCollection
    # T1 signals exist only in deadlock-v0.3 (DM-10).
    criteria_version: Literal["deadlock-v0.3"]
    initial_issue_ids: list[str] = Field(default_factory=list)
    allowed_issues: list[AllowedIssue] = Field(min_length=1)
    # artifact tasks (T2/T3): the scenario-v1 acceptance fixture
    success_criteria: SuccessCriteria | None = None
    fixture_dir: str | None = None
    monitored_paths: list[str] = Field(default_factory=list)
    # dialogue tasks (T1)
    status_values: list[StatusValue] | None = None  # ordered; progress is a move later in this list
    terminal_statuses: list[StatusValue] = Field(default_factory=list)  # outside the order, e.g. escalated
    deliverable_schema: dict[str, Any] | None = None
    judge: str | None = None  # agents cannot read it: scenario_judges/, outside every inputs_dir
    inputs_dir: str | None = None
    required_adopted_items: int | None = Field(default=None, ge=1)  # E5 "{adopted}/{required}" (DM-29)
    token_estimate: TokenEstimate | None = None

    @model_validator(mode="after")
    def consistency(self):
        initial, allowed = self.initial_issue_ids, [i.id for i in self.allowed_issues]
        if any(not i.strip() or any(c.isspace() for c in i) for i in initial) or len(initial) != len(set(initial)):
            raise ValueError("Initial issue IDs must be nonempty, whitespace-free and unique")
        if len(allowed) != len(set(allowed)) or not set(initial) <= set(allowed):
            raise ValueError("Allowed issue IDs must be unique and contain the initial issue IDs")
        ids = [a.id for a in self.agents]
        if len(ids) != len(set(ids)) or self.termination_context_collection.declarer_agent not in ids:
            raise ValueError("Agent IDs must be unique and declarer must exist")
        if any(len(a.tools) != len(set(a.tools)) for a in self.agents):
            raise ValueError("Agent tools must not repeat")
        if self.reasoning_effort_evidence is not None and self.reasoning_effort is None:
            raise ValueError("reasoning_effort_evidence requires reasoning_effort")
        if self.seed_support != "supported" and self.seed is not None:
            raise ValueError("Do not claim a fixed seed unless support is confirmed")
        if self.progress_source in ("conversation", "both") and not self.progress_metric.conversation:
            raise ValueError("Conversation metrics required")
        if self.progress_source in ("artifact", "both") and not self.progress_metric.artifact:
            raise ValueError("Artifact metrics required")
        if self.token_estimate is not None:
            e = self.token_estimate
            if not e.expected_llm_calls_min <= e.expected_llm_calls_max <= (
                    self.termination.max_steps * self.termination.max_llm_calls_per_step):
                raise ValueError("Expected calls must fit the declared maximum")
        (self.dialogue_rules if self.task_kind == "dialogue" else self.artifact_rules)()
        return self

    def dialogue_rules(self):
        if self.progress_source != "conversation":
            raise ValueError("A dialogue task is judged on the conversation only")
        if self.success_criteria is not None or self.fixture_dir is not None or self.monitored_paths:
            raise ValueError("A dialogue task has no acceptance tests, fixture or monitored files")
        for agent in self.agents:
            if any(t not in DIALOGUE_TOOLS for t in agent.tools) or agent.writable_paths:
                raise ValueError("Dialogue roles use dialogue tools only and write no files")
        if not self.judge or not JUDGE_PATH.match(self.judge):
            raise ValueError("judge must be scenario_judges/<name>.py")
        if not self.inputs_dir:
            raise ValueError("inputs_dir required for a dialogue task")
        relative_path(self.inputs_dir, "inputs_dir")
        if PurePosixPath(self.inputs_dir).parts[0] == "scenario_judges":
            raise ValueError("inputs_dir must not expose scenario_judges")
        if not self.status_values:
            raise ValueError("status_values required for a dialogue task")
        statuses = [s.id for s in self.status_values + self.terminal_statuses]
        if len(statuses) != len(set(statuses)):
            raise ValueError("Status IDs must be unique across status_values and terminal_statuses")
        # DM-46: a dialogue ends in one completion status (the last ordered status) or in escalated, nothing else,
        # so the outcome classes (success / deadlock / escalation / other) never overlap.
        if [s.id for s in self.terminal_statuses] != [ESCALATED]:
            raise ValueError("A dialogue task has exactly one terminal status, escalated (DM-46)")
        if self.deliverable_schema is None:
            raise ValueError("deliverable_schema required for a dialogue task")
        json_subset.check_schema(self.deliverable_schema)
        if "adopted_items" in self.progress_metric.conversation and self.required_adopted_items is None:
            raise ValueError("adopted_items needs required_adopted_items (E5, DM-29)")

    def artifact_rules(self):
        if self.progress_source not in ("artifact", "both") or not self.fixture_dir:
            raise ValueError("An artifact task needs an artifact source and a fixture")
        if self.success_criteria is None or self.success_criteria.kind != "tests":
            raise ValueError("An artifact task needs executable acceptance tests")
        if self.progress_metric.uses_t1():
            raise ValueError("T1 metrics belong to dialogue tasks")
        if self.turn_order != "fixed":
            raise ValueError("Only a dialogue task may use the router turn order (DM-19)")
        for agent in self.agents:
            if any(t not in ARTIFACT_TOOLS for t in agent.tools):
                raise ValueError("Artifact roles use file and test tools only")
            if agent.writable_paths and not set(agent.tools) & set(WRITE_TOOLS):
                raise ValueError("writable_paths need a write tool")
        if (self.status_values is not None or self.terminal_statuses or self.deliverable_schema is not None
                or self.judge is not None or self.inputs_dir is not None or self.required_adopted_items is not None):
            raise ValueError("Status, deliverable, judge and inputs fields belong to dialogue tasks")


def load_scenario(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    # Dispatch on the declared version only; a scenario-v1 file is validated exactly as before.
    if isinstance(data, dict) and data.get("schema_version") == "scenario-v2":
        return ScenarioV2.model_validate(data)
    return Scenario.model_validate(data)


def token_estimate(scenario):
    assumptions = scenario.token_estimate
    expected_completion = scenario.max_tokens * assumptions.mean_output_fraction_of_max_tokens
    calls = [assumptions.expected_llm_calls_min, assumptions.expected_llm_calls_max]
    return {"assumed": True,
        "input_tokens_range": [n * assumptions.mean_input_tokens_per_call for n in calls],
        "completion_tokens_range": [n * expected_completion for n in calls],
        "total_tokens_range": [n * (assumptions.mean_input_tokens_per_call + expected_completion) for n in calls],
        "completion_caps_at_expected_calls": [n * scenario.max_tokens for n in calls],
        "run_completion_cap_excluding_retries": scenario.termination.max_steps *
            scenario.termination.max_llm_calls_per_step * scenario.max_tokens,
        "total_token_hard_cap": None,
        "reason": "Input growth and retries are not bounded by max_tokens; all estimates are assumptions"}


def registration_for(scenario):
    """The session registration of a scenario-v2 task (DM-26, DM-29, DM-35), sent once at session start."""
    if getattr(scenario, "schema_version", None) != "scenario-v2":
        raise ValueError("Session registration is defined for scenario-v2")
    return {"registration_version": "session-registration-v1",
            "role_labels": {a.id: a.role for a in scenario.agents},
            "status_values": [s.model_dump() for s in scenario.status_values or []],
            "terminal_statuses": [s.model_dump() for s in scenario.terminal_statuses],
            "required_adopted_items": scenario.required_adopted_items,
            "progress_source": scenario.progress_source,
            "progress_metric": scenario.progress_metric.model_dump()}
