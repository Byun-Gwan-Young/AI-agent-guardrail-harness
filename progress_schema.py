"""Versioned observation input; computed verdicts are never accepted as input."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

CONVERSATION_METRICS = ["proposal_value_delta", "open_issues_count", "new_info_ratio"]
ARTIFACT_METRICS = ["test_pass_count", "files_changed", "build_status"]
# T1 dialogue metrics, judged only by progress-v3 (deadlock-v0.3). Scenario-v1 keeps the names above only.
T1_METRICS = ["status_advance", "adopted_items", "new_issue_ids"]
# T1 conversation fields (output-contract-v3). Omitted from the serialized record when None, so a legacy
# observation keeps exactly its earlier shape.
T1_FIELDS = ("status", "adopted_items", "handoff_to")


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Conversation(Record):
    source_kind: Literal["structured", "extracted"]
    proposal_values: dict[str, int | float] | None = None
    open_issue_ids: list[str] | None = None
    info_items: list[str] | None = None
    extractor_version: str | None = None
    reasons: dict[str, str] = Field(default_factory=dict)
    evidence: list[dict[str, str]] = Field(default_factory=list)
    status: str | None = Field(default=None, min_length=1)
    adopted_items: list[str] | None = None
    handoff_to: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_t1(self):
        items = self.adopted_items or []
        if any(not i.strip() or len(i.splitlines()) != 1 for i in items) or len(items) != len(set(items)):
            raise ValueError("adopted_items must be unique nonempty single-line IDs")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler):
        data = handler(self)
        for name in T1_FIELDS:
            if data.get(name) is None:
                data.pop(name, None)
        return data


class Artifact(Record):
    file_hashes: dict[str, str] | None = None
    files_scope_id: str | None = None
    test_pass_count: int | None = Field(default=None, ge=0)
    test_total_count: int | None = Field(default=None, ge=0)
    test_suite_id: str | None = None
    build_status: Literal["passed", "failed", "not_run"] | None = None
    reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.file_hashes is not None:
            if not self.files_scope_id:
                raise ValueError("files_scope_id required for a file snapshot")
            for path, digest in self.file_hashes.items():
                if (not path or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/")
                        or ":" in path or "\\" in path):
                    raise ValueError("Use safe relative POSIX file paths")
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("Expected SHA-256 file hash")
        if self.test_pass_count is not None:
            if self.test_total_count is None or not self.test_suite_id:
                raise ValueError("Test count requires total and suite identity")
            if self.test_pass_count > self.test_total_count:
                raise ValueError("Passed tests exceed total")
        return self


class Metrics(Record):
    conversation: list[Literal["proposal_value_delta", "open_issues_count", "new_info_ratio"]] = Field(
        default_factory=lambda: list(CONVERSATION_METRICS))
    artifact: list[Literal["test_pass_count", "files_changed", "build_status"]] = Field(
        default_factory=lambda: list(ARTIFACT_METRICS))


class ObservedMetrics(Record):
    """Metric selection of an observation and of scenario-v2: the scenario-v1 names plus the T1 names."""
    conversation: list[Literal["proposal_value_delta", "open_issues_count", "new_info_ratio",
                               "status_advance", "adopted_items", "new_issue_ids"]] = Field(
        default_factory=lambda: list(CONVERSATION_METRICS))
    artifact: list[Literal["test_pass_count", "files_changed", "build_status"]] = Field(
        default_factory=lambda: list(ARTIFACT_METRICS))

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.conversation)) != len(self.conversation) or len(set(self.artifact)) != len(self.artifact):
            raise ValueError("Metric names must not repeat")
        return self

    def uses_t1(self):
        return any(m in T1_METRICS for m in self.conversation)


class TerminationContext(Record):
    declaration: Literal["none", "declared", "unknown"]
    declared_step: int | None = Field(default=None, ge=1)
    source_kind: Literal["scenario_rule", "human_annotation"]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_declaration(self):
        if (self.declaration == "declared") != (self.declared_step is not None):
            raise ValueError("Only declared context requires declared_step")
        return self


class CollectionMetadata(Record):
    policy: Literal["legacy-failed-step-v1", "independent-sources-v1"]
    final_output_status: Literal["valid", "invalid", "unmeasured"]
    final_output_reason: str | None
    source_turn: int | None = Field(default=None, ge=1)
    measurement_status: Literal["observed", "partial", "unmeasured"]
    metric_status: dict[str, Literal["measured", "unmeasured"]]
    reasons: dict[str, str]


class IssueReport(Record):
    output_contract_version: Literal['output-contract-v2', 'output-contract-v3']
    allowed_issues_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    unlisted_issues: list[str] | None


class Observation(Record):
    # Evidence only: never selected by progress metrics or paired extraction.
    issue_report: IssueReport | None = None
    collection: CollectionMetadata | None = None
    # Runner-owned metadata; never requested from the model. Optional for legacy inputs.
    agent_id: str | None = Field(default=None, min_length=1)
    step_id: int = Field(ge=1)
    llm_turns: list[int] = Field(min_length=1)
    progress_source: Literal["conversation", "artifact", "both"]
    progress_metric: ObservedMetrics = Field(default_factory=ObservedMetrics)
    conversation: Conversation | None = None
    artifact: Artifact | None = None
    # Paired B output for evaluation against A; never used in A's progress verdict.
    extracted_conversation: Conversation | None = None
    termination_context: TerminationContext | None = None

    @model_serializer(mode='wrap')
    def preserve_legacy_shape(self, handler):
        data = handler(self)
        if self.issue_report is None:
            data.pop('issue_report', None)
        return data

    def uses_t1(self):
        """T1 metric names or T1 conversation fields: input only progress-v3 may judge."""
        return self.progress_metric.uses_t1() or any(
            getattr(c, name) is not None for c in (self.conversation, self.extracted_conversation) if c is not None
            for name in T1_FIELDS)

    @model_validator(mode="after")
    def validate_observation(self):
        if self.collection and self.collection.source_turn is not None and self.collection.source_turn not in self.llm_turns:
            raise ValueError("Collection source turn must belong to the observation")
        if self.termination_context and self.termination_context.declared_step is not None:
            if self.termination_context.declared_step > self.step_id:
                raise ValueError("Declaration cannot refer to a future step")
        if sorted(set(self.llm_turns)) != self.llm_turns or self.llm_turns[0] < 1:
            raise ValueError("llm_turns must be sorted, unique positive integers")
        if self.progress_source in ("conversation", "both") and not self.progress_metric.conversation:
            raise ValueError("Select at least one conversation metric")
        if self.progress_source in ("artifact", "both") and not self.progress_metric.artifact:
            raise ValueError("Select at least one artifact metric")
        if self.extracted_conversation is not None and (
            self.extracted_conversation.source_kind != "extracted" or self.conversation is None
            or self.conversation.source_kind != "structured"
        ):
            raise ValueError("Paired extraction requires a structured reference")
        return self


class StatusLabel(Record):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class SessionRegistration(Record):
    """DM-26, DM-29, DM-35: scenario settings registered once when a session starts (deadlock-v0.3 only).

    The status order is a judgement input of progress-v3; everything else only fills the STOP sentence.
    Display names are scenario settings, not model output (DM-9).
    """
    registration_version: Literal["session-registration-v1"]
    role_labels: dict[str, str]
    status_values: list[StatusLabel] = Field(default_factory=list)  # ordered
    terminal_statuses: list[StatusLabel] = Field(default_factory=list)  # outside the order, e.g. escalated
    required_adopted_items: int | None = Field(default=None, ge=1)
    progress_source: Literal["conversation", "artifact", "both"]
    progress_metric: ObservedMetrics

    @model_validator(mode="after")
    def validate_registration(self):
        if not self.role_labels or any(not k.strip() or not v.strip() for k, v in self.role_labels.items()):
            raise ValueError("role_labels must map nonempty role IDs to nonempty display names")
        ids = [s.id for s in self.status_values + self.terminal_statuses]
        if len(ids) != len(set(ids)):
            raise ValueError("Status IDs must be unique")
        if "status_advance" in self.progress_metric.conversation and not self.status_values:
            raise ValueError("status_advance needs the registered status order")
        if self.progress_source in ("conversation", "both") and not self.progress_metric.conversation:
            raise ValueError("Select at least one conversation metric")
        if self.progress_source in ("artifact", "both") and not self.progress_metric.artifact:
            raise ValueError("Select at least one artifact metric")
        return self
