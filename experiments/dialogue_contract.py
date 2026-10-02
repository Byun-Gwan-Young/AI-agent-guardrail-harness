"""output-contract-v3 (C-17-3): output-contract-v2 plus the T1 final-report fields of demo-runner-extension.md 4.

v2 is unchanged and reused as is: the v2 fields are parsed by the v2 contract, with its codes. The v3 fields are
status (closed list, sent to the provider as an enum), handoff_to, adopted_items, deliverable and spec_approved.
Only facts go into the instructions; no advice on what to report (C-9 principle).

A scenario-v2 artifact task (T2/T3, C-17-5) that picks v3 (DM-37) reports the v2 fields plus spec_approved only
(ArtifactContract): it has no status list, deliverable schema or router, so the other v3 fields cannot be defined.
"""
import copy
from dataclasses import dataclass
import hashlib
import json

import json_subset
from experiments.issue_contract import V2, IssueContract, IssueContractViolation, VOCABULARY_VIOLATIONS

V3 = 'output-contract-v3'
STATUS_NOT_ALLOWED = 'status_not_allowed'
HANDOFF_NOT_ALLOWED = 'handoff_to_not_allowed'
# Like D-17: well-formed output whose closed-list value is outside the scenario's list. The step fails, but the
# runner keeps these out of the consecutive strict-failure stop (experiments/dialogue_runner.py, C-17-4).
VOCABULARY_VIOLATIONS_V3 = VOCABULARY_VIOLATIONS + (STATUS_NOT_ALLOWED, HANDOFF_NOT_ALLOWED)
T1_FIELDS = ('status', 'handoff_to', 'adopted_items', 'deliverable', 'spec_approved')


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


@dataclass(frozen=True)
class DialogueContract:
    allowed: tuple[tuple[str, str], ...]
    statuses: tuple[str, ...]          # ordered statuses, then terminal statuses
    terminal: tuple[str, ...]
    agents: tuple[str, ...]
    deliverable_schema_json: str       # canonical JSON, so the contract stays hashable and immutable
    version: str = V3

    def __post_init__(self):
        if not self.statuses or len(set(self.statuses)) != len(self.statuses) or not set(self.terminal) <= set(self.statuses):
            raise ValueError('output-contract-v3 needs unique statuses that include the terminal ones')
        json_subset.check_schema(self.deliverable_schema)

    @property
    def issues(self):
        return IssueContract(V2, self.allowed)

    @property
    def deliverable_schema(self):
        return json.loads(self.deliverable_schema_json)

    @property
    def sha256(self):
        """Allowed issues hash, unchanged from v2 so IssueReport keeps one meaning."""
        return self.issues.sha256

    @property
    def contract_sha256(self):
        canonical = json.dumps({'allowed_issues_sha256': self.sha256, 'statuses': self.statuses,
                                'terminal': self.terminal, 'agents': self.agents,
                                'deliverable_schema': self.deliverable_schema},
                               ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def schema(self):
        # A copy: the v2 schema object is never changed through v3.
        schema = copy.deepcopy(self.issues.schema())
        schema['properties'].update({
            'status': {'type': 'string', 'enum': list(self.statuses)},
            'handoff_to': nullable({'type': 'string', 'enum': list(self.agents)}),
            'adopted_items': nullable({'type': 'array', 'items': {'type': 'string'}}),
            'deliverable': nullable(self.deliverable_schema),
            'spec_approved': nullable({'type': 'boolean'})})
        schema['required'] = schema['required'] + list(T1_FIELDS)
        schema['title'] = 'AgentOutputV3'
        return schema

    def response_format(self):
        return {'type': 'json_schema', 'json_schema': {'name': 'state_report_v3', 'strict': True, 'schema': self.schema()}}

    def parse(self, text):
        if text.startswith('```') and text.rstrip().endswith('```'):
            text = '\n'.join(text.strip().splitlines()[1:-1])
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError('Final report must be a JSON object')
        missing = [name for name in T1_FIELDS if name not in data]
        if missing:
            raise ValueError('Missing output-contract-v3 fields: ' + ', '.join(missing))
        t1 = {name: data.pop(name) for name in T1_FIELDS}
        value = self.issues.parse(json.dumps(data, ensure_ascii=False))
        # A wrong type is a shape error; only a well-formed value outside the closed list is a vocabulary violation.
        if not isinstance(t1['status'], str) or (t1['handoff_to'] is not None and not isinstance(t1['handoff_to'], str)):
            raise ValueError('status must be a string and handoff_to a string or null')
        if t1['status'] not in self.statuses:
            raise IssueContractViolation(STATUS_NOT_ALLOWED, 'status outside status_values')
        if t1['handoff_to'] is not None and t1['handoff_to'] not in self.agents:
            raise IssueContractViolation(HANDOFF_NOT_ALLOWED, 'handoff_to is not a role of this scenario')
        items = t1['adopted_items']
        if items is not None and (not isinstance(items, list) or any(
                not isinstance(i, str) or not i.strip() or len(i.splitlines()) != 1 for i in items)
                or len(items) != len(set(items))):
            raise ValueError('adopted_items must be unique nonempty single-line IDs or null')
        if t1['deliverable'] is not None:
            problems = json_subset.errors(t1['deliverable'], self.deliverable_schema)
            if problems:
                raise ValueError('deliverable does not match deliverable_schema: ' + '; '.join(problems[:5]))
        if t1['spec_approved'] is not None and not isinstance(t1['spec_approved'], bool):
            raise ValueError('spec_approved must be true, false or null')
        return {**value, **t1}

    def instructions(self):
        ordered = [s for s in self.statuses if s not in self.terminal]
        return (self.issues.instructions() + ' '
                'Report status as exactly one of ' + json.dumps(list(self.statuses), ensure_ascii=False) + '; '
                'the processing order is ' + json.dumps(ordered, ensure_ascii=False) + ' and '
                + json.dumps(list(self.terminal), ensure_ascii=False) + ' end the task outside that order. '
                'Report handoff_to as one role ID of ' + json.dumps(list(self.agents), ensure_ascii=False) + ' or null. '
                'Report adopted_items as the full list of item IDs adopted so far, not only new ones; '
                '[] means none and null means unknown. '
                'Report deliverable as an object matching this schema, or null if there is none yet: '
                + json.dumps(self.deliverable_schema, ensure_ascii=False) + '. '
                'spec_approved is null unless the scenario has an approval rule.')

    def report(self, parsed):
        return {'output_contract_version': V3, 'allowed_issues_sha256': self.sha256,
                'unlisted_issues': parsed['unlisted_issues'] if parsed is not None else None}


APPROVAL_FIELD = 'spec_approved'


@dataclass(frozen=True)
class ArtifactContract:
    """output-contract-v3 of a scenario-v2 artifact task: the v2 report plus spec_approved (bool or null).

    approval is (approving role, spec path) of the scenario's write gate, or None without one; it only changes the
    fact sentence about spec_approved. The v2 fields are parsed by the v2 contract, with its codes.
    """
    allowed: tuple[tuple[str, str], ...]
    approval: tuple[str, str] | None = None
    version: str = V3
    task_kind: str = 'artifact'

    @property
    def issues(self):
        return IssueContract(V2, self.allowed)

    @property
    def sha256(self):
        """Allowed issues hash, as in v2, so IssueReport keeps one meaning."""
        return self.issues.sha256

    @property
    def contract_sha256(self):
        canonical = json.dumps({'allowed_issues_sha256': self.sha256, 'task_kind': self.task_kind,
                                'fields': [APPROVAL_FIELD], 'approval': self.approval},
                               ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def schema(self):
        schema = copy.deepcopy(self.issues.schema())
        schema['properties'][APPROVAL_FIELD] = nullable({'type': 'boolean'})
        schema['required'] = schema['required'] + [APPROVAL_FIELD]
        schema['title'] = 'AgentOutputV3Artifact'
        return schema

    def response_format(self):
        return {'type': 'json_schema', 'json_schema': {'name': 'state_report_v3_artifact', 'strict': True,
                                                       'schema': self.schema()}}

    def parse(self, text):
        if text.startswith('```') and text.rstrip().endswith('```'):
            text = '\n'.join(text.strip().splitlines()[1:-1])
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError('Final report must be a JSON object')
        if APPROVAL_FIELD not in data:
            raise ValueError('Missing output-contract-v3 field: ' + APPROVAL_FIELD)
        approved = data.pop(APPROVAL_FIELD)
        if approved is not None and not isinstance(approved, bool):
            raise ValueError('spec_approved must be true, false or null')
        value = self.issues.parse(json.dumps(data, ensure_ascii=False))
        return {**value, APPROVAL_FIELD: approved}

    def instructions(self):
        if self.approval is None:
            return self.issues.instructions() + ' spec_approved is null unless the scenario has an approval rule.'
        approver, spec = self.approval
        return (self.issues.instructions() + ' Report spec_approved as true, false or null. Only the spec_approved '
                'of role ' + approver + ' is read: true from that role approves ' + spec + ' under the approval rule.')

    def report(self, parsed):
        return {'output_contract_version': V3, 'allowed_issues_sha256': self.sha256,
                'unlisted_issues': parsed['unlisted_issues'] if parsed is not None else None}


def for_artifact_scenario(scenario):
    """The output contract a scenario-v2 artifact task picks (DM-37): v2 as is, or the artifact form of v3."""
    if getattr(scenario, 'schema_version', None) != 'scenario-v2' or scenario.task_kind != 'artifact':
        raise ValueError('for_artifact_scenario is for scenario-v2 artifact tasks')
    allowed = tuple((i.id, i.definition) for i in scenario.allowed_issues)
    if scenario.output_contract == V2:
        return IssueContract(V2, allowed)
    gate = getattr(scenario, 'write_gate', None)
    return ArtifactContract(allowed, (gate.set_by, gate.spec_path) if gate is not None else None)


def for_dialogue_scenario(scenario):
    """output-contract-v3 of a scenario-v2 dialogue task. The order of the scenario's lists is kept."""
    if getattr(scenario, 'schema_version', None) != 'scenario-v2' or scenario.task_kind != 'dialogue':
        raise ValueError('output-contract-v3 is for scenario-v2 dialogue tasks')
    return DialogueContract(
        allowed=tuple((i.id, i.definition) for i in scenario.allowed_issues),
        statuses=tuple(s.id for s in scenario.status_values + scenario.terminal_statuses),
        terminal=tuple(s.id for s in scenario.terminal_statuses),
        agents=tuple(a.id for a in scenario.agents),
        deliverable_schema_json=json.dumps(scenario.deliverable_schema, ensure_ascii=False, sort_keys=True))
