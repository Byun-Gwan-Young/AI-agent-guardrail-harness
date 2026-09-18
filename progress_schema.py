"""Versioned observation input; computed verdicts are never accepted as input."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

CONVERSATION_METRICS = ["proposal_value_delta", "open_issues_count", "new_info_ratio"]
ARTIFACT_METRICS = ["test_pass_count", "files_changed", "build_status"]


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
    output_contract_version: Literal['output-contract-v2']
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
    progress_metric: Metrics = Field(default_factory=Metrics)
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
