"""Dialogue-task (T1) tool seam (C-17-4): the per-role tool list goes into the request and each call is handed on.

No tool is implemented here; lookup_order, read_policy, web_search and academic_search are C-17-6
(demo-runner-extension.md 5). IMPLEMENTATIONS stays empty until then, so the runner refuses a scenario whose roles
name a tool without one. Offline tests put fake implementations in it.

An implementation is called as implementation(arguments, context) and returns text or a JSON value; context is
{"step_id", "agent_id", "inputs_dir"}. Every call is recorded (arguments, result or error) for the judge.
"""
import json

TOOL_VOCABULARY = ('lookup_order', 'read_policy', 'web_search', 'academic_search')
ERROR_CHARS = 300
# name -> callable; filled by C-17-6. Empty means no T1 run can start with a tool-using role.
IMPLEMENTATIONS = {}


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
    """Hands each model tool call to its implementation and keeps the call record."""

    def __init__(self, implementations, inputs_dir):
        self.implementations, self.inputs_dir = dict(implementations), str(inputs_dir)
        self.records, self.step_id, self.agent_id = [], None, None

    def identity(self):
        return {name: getattr(f, '__module__', '?') + '.' + getattr(f, '__qualname__', repr(f))
                for name, f in sorted(self.implementations.items())}

    def call(self, name, arguments):
        record = {'seq': len(self.records) + 1, 'step_id': self.step_id, 'agent_id': self.agent_id,
                  'tool': name, 'arguments': arguments}
        self.records.append(record)
        try:
            result = self.implementations[name](arguments, {'step_id': self.step_id, 'agent_id': self.agent_id,
                                                            'inputs_dir': self.inputs_dir})
        except Exception as exc:
            record.update(is_error=True, error=(type(exc).__name__ + ': ' + str(exc))[:ERROR_CHARS], result=None)
            raise
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        record.update(is_error=False, error=None, result=text)
        return text

    def tools(self, names):
        """Functions with the interface of demo-runner-extension.md 5, in the role's order."""
        def lookup_order(order_id: str) -> str:
            """Return the order record for order_id from the task's order data, or "not found"."""
            return self.call('lookup_order', {'order_id': order_id})

        def read_policy(name: str) -> str:
            """Return the text of the named policy document of the task."""
            return self.call('read_policy', {'name': name})

        def web_search(query: str, max_results: int = 5) -> str:
            """Return web search results (title, URL, excerpt) for query."""
            return self.call('web_search', {'query': query, 'max_results': max_results})

        def academic_search(query: str, max_results: int = 5) -> str:
            """Return academic search results (ID, title, authors, year, abstract excerpt) for query."""
            return self.call('academic_search', {'query': query, 'max_results': max_results})
        available = {f.__name__: f for f in (lookup_order, read_policy, web_search, academic_search)}
        return [available[name] for name in names]

    def records_for(self, step_id):
        return [r for r in self.records if r['step_id'] == step_id]
