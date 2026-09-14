import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import httpx
from experiments.run_scenario import CallBudget, Workspace, deliver, parse_output, safe_path, termination_context


class RunnerHelpers(unittest.TestCase):
    def test_call_limit_and_reset(self):
        b = CallBudget(2)
        b.consume(); b.consume()
        with self.assertRaises(RuntimeError): b.consume()
        b.reset(); b.consume()
        self.assertEqual(b.used, 1)

    def test_scope_and_role_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError): safe_path(root, '../outside')
            tools = Workspace(None, root).tools(SimpleNamespace(permissions=['write_files'], writable_paths=['SPEC.md']))
            with self.assertRaises(ValueError): tools[0]('tests.py', 'changed')
            tools[0]('SPEC.md', 'allowed')
            self.assertEqual((root / 'SPEC.md').read_text(), 'allowed')

    def test_replace_in_file_requires_single_match_and_role_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'SPEC.md').write_text('a = 1\nb = 2\nb = 2\n', encoding='utf-8')
            (root / 'other.py').write_text('x', encoding='utf-8')
            tools = Workspace(None, root).tools(SimpleNamespace(permissions=['write_files'], writable_paths=['SPEC.md']))
            self.assertEqual([t.__name__ for t in tools], ['write_file', 'replace_in_file'])
            replace = tools[1]
            self.assertEqual(replace('SPEC.md', 'a = 1', 'a = 3'), 'replaced in: SPEC.md')
            self.assertEqual((root / 'SPEC.md').read_text(encoding='utf-8'), 'a = 3\nb = 2\nb = 2\n')
            with self.assertRaises(ValueError): replace('SPEC.md', 'b = 2', 'b = 4')
            with self.assertRaises(ValueError): replace('SPEC.md', 'missing', 'z')
            with self.assertRaises(ValueError): replace('SPEC.md', '', 'z')
            with self.assertRaises(ValueError): replace('other.py', 'x', 'y')
            with self.assertRaises(ValueError): replace('../SPEC.md', 'a', 'b')
            self.assertEqual((root / 'SPEC.md').read_text(encoding='utf-8'), 'a = 3\nb = 2\nb = 2\n')
            self.assertEqual((root / 'other.py').read_text(encoding='utf-8'), 'x')

    def test_edit_instruction_only_for_roles_with_replace(self):
        from experiments.step_execution import edit_instructions
        self.assertEqual(edit_instructions(['read_file', 'run_tests']), '')
        text = edit_instructions(['read_file', 'write_file', 'replace_in_file'])
        self.assertIn('replace_in_file', text)
        self.assertIn('docstrings', text)
        self.assertIn('U+2011', text)
        self.assertTrue(text.isascii())

    def test_invalid_structured_output(self):
        with self.assertRaises(ValueError): parse_output('{}')

    def test_review_declaration_preserved(self):
        output = {'agent_id': 'reviewer', 'completion_declared': True}
        first, ctx = termination_context(None, output, 3, 'reviewer')
        self.assertEqual(first, 3)
        first, ctx = termination_context(first, None, 4, 'reviewer')
        self.assertEqual(ctx['declared_step'], 3)

    def test_nonreviewer_cannot_declare(self):
        first, ctx = termination_context(None, {'agent_id':'developer', 'completion_declared':True}, 2, 'reviewer')
        self.assertIsNone(first)
        self.assertEqual(ctx['declaration'], 'none')

    def test_missing_output_unknown(self):
        self.assertEqual(termination_context(None, None, 1, 'reviewer')[1]['declaration'], 'unknown')


class SubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_payload_after_lost_response_and_save_failure(self):
        received, waits = [], []
        async def handler(request):
            received.append(json.loads(request.content))
            if len(received) == 1:
                raise httpx.ReadTimeout('response lost', request=request)
            return httpx.Response(200, json={'persisted':len(received) == 3, 'duplicate':True})
        async def sleep(delay): waits.append(delay)
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handler)) as client:
            result = await deliver(client, 'session', {'step_id':1}, sleep)
        self.assertTrue(result['persisted'])
        self.assertEqual(received, [{'step_id':1}] * 3)
        self.assertEqual(waits, [1, 2])

    async def test_conflict_not_retried(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(409)
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(httpx.HTTPStatusError): await deliver(client, 's', {'step_id':1})
        self.assertEqual(len(calls), 1)

    async def test_retry_exhaustion(self):
        async def sleep(_): pass
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(
                lambda request: httpx.Response(503))) as client:
            with self.assertRaises(RuntimeError): await deliver(client, 's', {'step_id':1}, sleep)

    async def test_error_response_turn_header(self):
        budget = CallBudget(2)
        await budget.capture(httpx.Response(500, headers={'X-Guardrail-Turn':'2'}))
        self.assertEqual(budget.turns, [2])
