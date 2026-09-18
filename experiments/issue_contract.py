"""Versioned local issue vocabulary contract; legacy implementation is unchanged."""
from dataclasses import dataclass
import hashlib
import json
from typing import Annotated

from pydantic import Field
from experiments import output_contract as legacy

V1 = 'output-contract-v1'
V2 = 'output-contract-v2'
VERSIONS = (V1, V2)
PROTOCOL_V2 = 'tool-capable-step-v7-issue-ids'
# Distinct from every other contract violation (D-13 collision rule).
ISSUE_ID_COLLISION = 'unlisted_issue_id_collision'


class IssueContractViolation(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


class AgentOutputV2(legacy.AgentOutput):
    unlisted_issues: list[Annotated[str, Field(min_length=1, max_length=240)]] | None


@dataclass(frozen=True)
class IssueContract:
    version: str = V1
    # Immutable execution snapshot: exact ID and definition, never normalized.
    allowed: tuple[tuple[str, str], ...] | None = None

    def __post_init__(self):
        if self.version not in VERSIONS:
            raise ValueError('Unsupported output contract')
        if self.version == V2 and self.allowed is None:
            raise ValueError('output-contract-v2 requires scenario.allowed_issues')

    @property
    def vocabulary(self):
        return [{'id': i, 'definition': d} for i, d in (self.allowed or ())]

    @property
    def sha256(self):
        if self.version == V1:
            return None
        canonical = json.dumps(sorted(self.vocabulary, key=lambda x:x['id']),
                               ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def schema(self):
        return legacy.output_schema() if self.version == V1 else AgentOutputV2.model_json_schema()

    def response_format(self):
        if self.version == V1:
            return legacy.strict_response_format()
        # Only shape is provider-strict. No vocabulary enum is sent to the provider.
        return {'type':'json_schema', 'json_schema':{
            'name':'state_report_v2', 'strict':True, 'schema':self.schema()}}

    def parse(self, text):
        if self.version == V1:
            return legacy.parse_output(text)
        if text.startswith('```') and text.rstrip().endswith('```'):
            text = '\n'.join(text.strip().splitlines()[1:-1])
        value = AgentOutputV2.model_validate(json.loads(text)).model_dump()
        ids = value['open_issue_ids']
        allowed = {i for i, _ in self.allowed}
        if ids is not None and (len(ids) != len(set(ids)) or not set(ids) <= allowed):
            raise ValueError('Duplicate or unlisted open issue ID')
        unlisted = value['unlisted_issues'] or []
        if any(not item.strip() or len(item.splitlines()) != 1 for item in unlisted):
            raise ValueError('Unlisted issues must be nonempty short single-line descriptions')
        if len(unlisted) != len(set(unlisted)):
            raise ValueError('Duplicate unlisted issue')
        # Exact string equality only: no move, deletion or normalization.
        if set(unlisted) & allowed:
            raise IssueContractViolation(ISSUE_ID_COLLISION, 'Allowed issue ID reported in unlisted_issues')
        return value

    def instructions(self):
        if self.version == V1:
            return ''
        return ('Report open_issue_ids using only exact IDs from allowed_issues; '
                'use their definitions and do not invent IDs or normalize spellings. '
                'Report issues outside this vocabulary as short single-line descriptions '
                '(at most 240 characters each, no duplicates) in unlisted_issues; [] means none and null means unknown. '
                'Never put an allowed issue ID in unlisted_issues: if any unlisted_issues entry exactly equals '
                'an allowed ID, the whole output is rejected as a contract violation. '
                'unlisted_issues is recorded only and is not a progress metric. '
                'Allowed issues: ' + json.dumps(self.vocabulary, ensure_ascii=False))

    def report(self, parsed):
        if self.version == V1:
            return None
        return {'output_contract_version':self.version, 'allowed_issues_sha256':self.sha256,
                'unlisted_issues':parsed['unlisted_issues'] if parsed is not None else None}


def for_scenario(version, scenario):
    allowed = scenario.allowed_issues
    return IssueContract(version, tuple((i.id, i.definition) for i in allowed) if allowed is not None else None)
