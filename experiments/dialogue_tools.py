"""Dialogue-task (T1) tools: the per-role tool list goes into the request and each call is handed on (C-17-4).

The implementations are C-17-6 (demo-runner-extension.md 5, decision 018): lookup_order and read_policy read the
scenario's inputs_dir (experiments/cs_tools.py); web_search (Tavily) and academic_search (arXiv) store every response
in the session folder (experiments/search_tools.py, resource "search"). A name without an implementation in
IMPLEMENTATIONS is refused before a run. Offline tests may put fake implementations in it.

An implementation is called as implementation(arguments, context) and returns text, a JSON value or
experiments.tool_results.Result; it raises ToolFactError (or any exception) for an error result. context is
{"step_id", "agent_id", "inputs_dir"} plus the session's tool resources, if any. Every call is recorded (arguments,
result or error, and what the implementation adds) for the judge.
"""
import json
import threading

from experiments import cs_tools, search_tools
from experiments.tool_results import Result

TOOL_VOCABULARY = ('lookup_order', 'read_policy', 'web_search', 'academic_search')
ERROR_CHARS = 300
# name -> callable. A role naming a tool missing here cannot start a run.
IMPLEMENTATIONS = {'lookup_order': cs_tools.lookup_order, 'read_policy': cs_tools.read_policy,
                   'web_search': search_tools.web_search, 'academic_search': search_tools.academic_search}


def tool_instructions(names):
    """Facts about this role's tools, as the artifact path states them, without the file-tree wording."""
    return ('Available tool vocabulary is ' + ', '.join(TOOL_VOCABULARY) + '. '
            'For THIS role only these tools are registered: ' + (', '.join(names) if names else 'none') + '. '
            "Call only this role's registered tools. Do not call any other tool. ")


def correction(kind, names, allowed):
    if kind == 'unknown_tool':
        return ('해당 도구는 없다: ' + ', '.join(n for n in names if n) +
                '. 등록된 도구만 사용하라: ' + (', '.join(allowed) if allowed else '없음') + '.')
    return '인자가 JSON 으로 파싱되지 않았다. 더 짧은 단위로 나눠 호출하라.'


def missing_implementations(scenario, implementations=None):
    implementations = IMPLEMENTATIONS if implementations is None else implementations
    return sorted({t for a in scenario.agents for t in a.tools} - set(implementations))


class ToolDispatch:
    """Hands each model tool call to its implementation and keeps the call record.

    AutoGen runs the tool calls of one model response concurrently (sync tools in threads), so calls are taken one
    at a time: records get their order without races and a provider sees one connection at a time.
    """

    def __init__(self, implementations, inputs_dir, resources=None):
        self.implementations, self.inputs_dir = dict(implementations), str(inputs_dir)
        self.resources = dict(resources or {})
        self.records, self.step_id, self.agent_id = [], None, None
        self.lock = threading.Lock()

    def identity(self):
        return {name: getattr(f, '__module__', '?') + '.' + getattr(f, '__qualname__', repr(f))
                for name, f in sorted(self.implementations.items())}

    def call(self, name, arguments):
        with self.lock:
            record = {'seq': len(self.records) + 1, 'step_id': self.step_id, 'agent_id': self.agent_id,
                      'tool': name, 'arguments': arguments}
            self.records.append(record)
            context = {'step_id': self.step_id, 'agent_id': self.agent_id, 'inputs_dir': self.inputs_dir,
                       **self.resources}
            if self.resources:
                context['dispatch_seq'] = record['seq']
            try:
                result = self.implementations[name](arguments, context)
            except Exception as exc:
                record.update(is_error=True, error=(type(exc).__name__ + ': ' + str(exc))[:ERROR_CHARS], result=None,
                              **getattr(exc, 'record', {}))
                raise
            if isinstance(result, Result):
                record.update(result.record)
                result = result.value
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            record.update(is_error=False, error=None, result=text)
            return text

    def tools(self, names):
        """Functions with the interface of demo-runner-extension.md 5, in the role's order."""
        def lookup_order(order_id: str) -> str:
            """Return the order record (JSON) for order_id from the task's order data. An order_id that is not in
            the data returns an error result."""
            return self.call('lookup_order', {'order_id': order_id})

        def read_policy(name: str) -> str:
            """Return the text of the task's policy document called name. A name that is not a policy document of
            the task returns an error result."""
            return self.call('read_policy', {'name': name})

        # C-17-6: the number of results is the scenario's setting (tool_settings), not a model argument.
        def web_search(query: str) -> str:
            """Search the web (Tavily) for query. Returns JSON results with title, url and excerpt; the number of
            results is set by the task."""
            return self.call('web_search', {'query': query})

        def academic_search(query: str) -> str:
            """Search arXiv for query, sent unchanged as the arXiv API search_query (field prefixes such as all:,
            ti:, abs: and AND, OR, ANDNOT may be used). Returns JSON results with id (arXiv ID), title, authors,
            year and excerpt; the number of results is set by the task."""
            return self.call('academic_search', {'query': query})
        available = {f.__name__: f for f in (lookup_order, read_policy, web_search, academic_search)}
        return [available[name] for name in names]

    def records_for(self, step_id):
        return [r for r in self.records if r['step_id'] == step_id]
