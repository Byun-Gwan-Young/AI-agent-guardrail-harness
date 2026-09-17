"""Scenario-v1 contract. Definitions only; loading never executes agents or commands."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from progress_schema import Metrics


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
    token_estimate: TokenEstimate

    @model_validator(mode="after")
    def consistency(self):
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)) or self.termination_context_collection.declarer_agent not in ids:
            raise ValueError("Agent IDs must be unique and declarer must exist")
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


def load_scenario(path):
    return Scenario.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


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
