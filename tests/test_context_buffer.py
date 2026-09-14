import json
from pathlib import Path
import tempfile
import unittest
from autogen_core.models import UserMessage
from experiments.run_scenario import make_model_context, prompt_trace
from experiments.compare_context import compare
from experiment_config import conditions


class BufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_buffer_limits_each_agent_independently(self):
        first, second, unlimited = make_model_context(12), make_model_context(12), make_model_context(None)
        for i in range(20):
            await first.add_message(UserMessage(content=str(i), source='user'))
            await unlimited.add_message(UserMessage(content=str(i), source='user'))
        self.assertEqual([m.content for m in await first.get_messages()], [str(i) for i in range(8, 20)])
        self.assertEqual(await second.get_messages(), [])
        self.assertEqual(len(await unlimited.get_messages()), 20)

    async def test_message_limit_not_token_limit(self):
        ctx = make_model_context(1)
        await ctx.add_message(UserMessage(content='x' * 100000, source='user'))
        self.assertEqual(len((await ctx.get_messages())[0].content), 100000)


class TraceTests(unittest.TestCase):
    def test_missing_usage_not_zero_and_turn_mapping(self):
        steps = [{'step_id':1, 'agent':'planner', 'llm_calls':2, 'llm_turns':[2, 3]}]
        row = prompt_trace(steps, {'turns':[{'turn':1,'prompt_tokens':999},
            {'turn':2,'prompt_tokens':50}, {'turn':3,'prompt_tokens':None}]})[0]
        self.assertEqual(row['prompt_tokens_per_call'], [50, None])
        self.assertIsNone(row['prompt_tokens_sum'])
        self.assertEqual(row['known_prompt_tokens_subtotal'], 50)

    def test_buffer_conditions(self):
        self.assertEqual(conditions({}, {'X-Guardrail-Context-Buffer-Messages':'12'}, {})['context_buffer_messages'], 12)
        self.assertIsNone(conditions({}, {'X-Guardrail-Context-Buffer-Messages':'none'}, {})['context_buffer_messages'])
        with self.assertRaises(ValueError): conditions({}, {'X-Guardrail-Context-Buffer-Messages':'0'}, {})

    def test_comparison_offline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, count in [('b', 12), ('u', None)]:
                p = root / name; p.mkdir()
                (p / 'conditions.json').write_text(json.dumps({'context_buffer_messages':count, 'temperature':0.0}))
                (p / 'prompt-trend.json').write_text(json.dumps([{'step_id':1,'agent':'planner',
                    'llm_turns':[1,2], 'prompt_tokens_per_call':[100,None]}]))
            result = compare(root/'b', root/'u', root/'comparison')
            self.assertTrue(result['other_conditions_equal'])
            self.assertEqual(result['missing_prompt_tokens'], [1,1])
            self.assertTrue((root/'comparison/prompt-comparison.svg').exists())
