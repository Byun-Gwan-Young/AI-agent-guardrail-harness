"""Model-owned fields only. Agent and step identifiers are runner metadata."""
import json
from pydantic import BaseModel, ConfigDict


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    narrative: str
    open_issue_ids: list[str] | None
    info_items: list[str] | None
    completion_declared: bool


def output_schema():
    return AgentOutput.model_json_schema()


def strict_response_format():
    # Keep this envelope identical to the successful endpoint probe, including its name.
    return {'type':'json_schema','json_schema':{
        'name':'state_report_probe','strict':True,'schema':output_schema()}}


def parse_output(text):
    if text.startswith('```') and text.rstrip().endswith('```'):
        text = '\n'.join(text.strip().splitlines()[1:-1])
    value = AgentOutput.model_validate(json.loads(text))
    if value.open_issue_ids is not None and len(set(value.open_issue_ids)) != len(value.open_issue_ids):
        raise ValueError('Duplicate issue IDs')
    return value.model_dump()
