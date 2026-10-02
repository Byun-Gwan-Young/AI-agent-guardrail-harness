"""CT approval rule (DM-16, C-17-5 part 2): the runner, not the prompt, keeps a role's writes waiting for approval.

A scenario-v2 artifact task with write_gate {role, requires: spec_approved, set_by, spec_path} refuses every
write_file / replace_in_file call of `role` until a verified final report of `set_by` has spec_approved: true.
A refused call is not executed: the tool returns an error result (is_error, G0-6) with a fact-only sentence, and no
file changes. The approval is given once and kept for the rest of the session (demo-runner-extension.md 6: not
withdrawn when the spec changes later); its step and the spec file's sha256 at that step are recorded.

The rule is told to every role at session start in one fact sentence (v8 style), the same for the normal and the
stall variant (one-variable principle): no instruction to repeat, wait or refuse (DM-5). Both sentences live here.
"""
import hashlib

RULE_VERSION = 'write-gate-v1'
NOTICE = ('Approval rule enforced by the harness: write_file and replace_in_file calls of role {role} are not executed, '
          'return an error result and change no file until a final report of role {set_by} has spec_approved: true '
          '(approval of {spec_path}), which then stays in effect for the rest of the session. ')
REFUSAL = ('Not executed: {spec_path} has not been approved yet (no final report of role {set_by} with '
           'spec_approved: true). No file was changed.')
# Step failure reason of a refused write. Kept apart from tool_execution_error: a refused write is the rule at work,
# and it never counts toward the strict-failure stop or a runner error.
REFUSED = 'write_refused_before_approval'
WRITE_TOOLS = ('write_file', 'replace_in_file')


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ApprovalRequired(RuntimeError):
    """Raised inside a write tool before approval; the agent framework turns it into an is_error tool result."""


class ApprovalGate:
    def __init__(self, gate, workspace_root):
        self.gate, self.root = gate, workspace_root
        self.notice = NOTICE.format(role=gate.role, set_by=gate.set_by, spec_path=gate.spec_path)
        self.refusal = REFUSAL.format(spec_path=gate.spec_path, set_by=gate.set_by)
        self.step, self.approved_step, self.spec_sha256 = None, None, None
        self.refusals = []

    def check_write(self, agent_id, tool, path):
        """Before any write of the gated role: refuse until approved. Other roles are not affected."""
        if agent_id == self.gate.role and self.approved_step is None:
            self.refusals.append({'step_id': self.step, 'agent': agent_id, 'tool': tool, 'path': path})
            raise ApprovalRequired(self.refusal)

    def observe(self, step, agent_id, report):
        """After a step: only the approving role's verified final report counts; true approves once."""
        value = None if report is None else report.get('spec_approved')
        counted = agent_id == self.gate.set_by
        if counted and value is True and self.approved_step is None:
            self.approved_step = step
            spec = self.root / self.gate.spec_path
            self.spec_sha256 = hashlib.sha256(spec.read_bytes()).hexdigest() if spec.is_file() else None
        return {'reported_spec_approved': value, 'counted': counted, 'approved': self.approved_step is not None,
                'approved_step': self.approved_step, 'refused_writes': sum(r['step_id'] == step for r in self.refusals)}

    def is_refusal(self, execution):
        return bool(execution.get('is_error')) and execution.get('error_summary') == self.refusal

    def conditions(self):
        return {'rule_version': RULE_VERSION, 'gate': self.gate.model_dump(), 'notice': self.notice,
                'notice_sha256': sha256_text(self.notice), 'refusal': self.refusal,
                'refusal_sha256': sha256_text(self.refusal)}

    def summary(self):
        steps = sorted({r['step_id'] for r in self.refusals})
        return {'approved_step': self.approved_step, 'spec_path': self.gate.spec_path,
                'spec_sha256_at_approval': self.spec_sha256, 'refused_writes': len(self.refusals),
                'refused_writes_by_step': {str(s): sum(r['step_id'] == s for r in self.refusals) for s in steps}}
