"""What a dialogue (T1) tool hands back to experiments.dialogue_tools.ToolDispatch (C-17-6).

A tool returns a plain value (text or JSON), or Result when the call record should also say where the value came
from. It raises ToolFactError for a call that produced no value: the message is a fact sentence the model receives as
an is_error tool result (AutoGen turns the exception text into the result), never strategy advice.
"""


class ToolFactError(Exception):
    def __init__(self, message, record=None):
        super().__init__(message)
        # Extra fields for the dispatch record (e.g. which input file was read, the stored search record).
        self.record = dict(record or {})


class Result:
    def __init__(self, value, record):
        self.value, self.record = value, dict(record)
