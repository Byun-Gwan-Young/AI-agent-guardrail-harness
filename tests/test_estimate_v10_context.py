import unittest

from tools.estimate_v10_context import v10_record


class V10EstimateRecordTests(unittest.TestCase):
    def test_user_facts_pass_through_like_final_messages(self):
        facts = {'task': 't', 'initial_issue_ids': ['requirements'], 'acceptance': {'passed': 7},
                 'recent_messages': ['m']}
        self.assertEqual(v10_record(facts), facts)

    def test_assistant_record_loses_thought(self):
        record = {'type': 'AssistantMessage', 'source': 'developer', 'thought': 'hidden', 'content': 'report'}
        self.assertEqual(v10_record(record), {'source': 'developer', 'type': 'AssistantMessage', 'content': 'report'})


if __name__ == '__main__':
    unittest.main()
