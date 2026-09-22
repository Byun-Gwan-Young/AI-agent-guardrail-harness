import copy
import json
import unittest

from tools.analyze_c14 import thought_size, request_sizes, field_sample, metrics_evidence, developer_reads


class C14EvidenceTests(unittest.TestCase):
    def test_reasoning_is_size_only_never_returned(self):
        secret_thought = 'SYNTHETIC_DO_NOT_EMIT_THOUGHT'
        record={'type':'AssistantMessage','content':'report','thought':secret_thought,'source':'role'}
        turn={'turn':1,'request_body':{'messages':[{'role':'user','content':json.dumps({'observed_records':[record]})}]}}
        result=field_sample(turn)
        self.assertEqual(result['thought_chars'],len(secret_thought))
        self.assertEqual(result['assistant_body_chars'],len('report'))
        self.assertNotIn(secret_thought,json.dumps(result))
        self.assertNotIn('report',json.dumps(result))

    def test_tool_arguments_and_body_are_distinct_sizes(self):
        record={'type':'AssistantMessage','thought':None,'content':[{'arguments':'{"path":"a"}'}]}
        turn={'turn':1,'request_body':{'messages':[{'role':'user','content':json.dumps({'observed_records':[record]})}]}}
        result=request_sizes(turn)
        self.assertEqual(result['assistant_body_chars'],0)
        self.assertEqual(result['assistant_tool_argument_chars'],len('{"path":"a"}'))
        self.assertEqual(result['thought_chars'],0)

    def fixture(self):
        conditions={'fixture_hashes':{'a':'original'},'scenario':{'monitored_paths':['a'],'agents':[{}, {}, {}]}}
        steps=[]
        for n in range(1,5):
            steps.append({'step_id':n,'llm_turns':[n],
                'acceptance':{'artifact':{'file_hashes':{'a':'changed' if n>=2 else 'original'},'test_pass_count':1}},
                'observation':{'criteria':{'decision':'deadlock' if n>=3 else 'continue'}}})
        log={'turns':[{'turn':n,'tokens':n*10} for n in range(1,5)]}
        summary={'tests_passed_before':1,'termination_reason':'max_steps'}
        return log,steps,conditions,summary

    def test_onset_uses_artifacts_not_stagnant_labels_and_excludes_stop_call_tokens(self):
        args=self.fixture();r=metrics_evidence(*args)
        self.assertEqual(r['artifact_test_change_steps'],[2])
        self.assertEqual(r['onset_step'],3)
        self.assertEqual(r['first_stop_step'],3)
        self.assertEqual(r['known_tokens_after_stop'],40)
        self.assertEqual(r['delay_steps_median'],0)
        self.assertEqual(r['savings_failure_basis']['value'],0.4)

    def test_early_stop_detected_saved_but_excluded_from_delay(self):
        log,steps,c,s=self.fixture()
        for row in steps: row['observation']['criteria']['decision']='deadlock'
        r=metrics_evidence(log,steps,c,s)
        self.assertEqual(r['early_stop_count'],1)
        self.assertIsNone(r['delay_steps_median'])
        self.assertEqual(r['detection_rate']['value'],1)
        self.assertEqual(r['known_tokens_after_stop'],90)

    def test_missing_artifact_or_usage_never_filled(self):
        log,steps,c,s=self.fixture()
        steps[1]['acceptance']['artifact']['file_hashes']=None
        log['turns'][2]['tokens']=None
        r=metrics_evidence(log,steps,c,s)
        self.assertIsNone(r['onset_step'])
        self.assertEqual(r['usage_missing_turns'],1)
        self.assertEqual(r['sensitivity_excluding_usage_missing']['status'],'excluded')

    def test_no_change_onset_one_and_normal_session_no_detection_sample(self):
        log,steps,c,s=self.fixture()
        for row in steps: row['acceptance']['artifact']['file_hashes']={'a':'original'}
        self.assertEqual(metrics_evidence(log,steps,c,s)['onset_step'],1)
        s['termination_reason']='success'
        r=metrics_evidence(log,steps,c,s)
        self.assertIsNone(r['onset_step']);self.assertIsNone(r['detection_rate']['value'])
        self.assertEqual(r['normal_false_stop_loss_tokens'],40)

    def test_read_result_identity_and_request_presence_are_separate(self):
        call=lambda ident:{'id':ident,'function':{'name':'read_file','arguments':'{"path":"a"}'}}
        turns={1:{'turn':1,'request_body':{'messages':[]},'response_body':{'choices':[{'message':{'tool_calls':[call('x')]}}]}},
               2:{'turn':2,'request_body':{'messages':[{'role':'assistant','tool_calls':[call('x')]},
                    {'role':'tool','tool_call_id':'x','content':'same'}]},'response_body':{'choices':[{'message':{'tool_calls':[call('y')]}}]}},
               3:{'turn':3,'request_body':{'messages':[{'role':'tool','tool_call_id':'y','content':'same'}]},'response_body':{}}}
        steps=[{'step_id':1,'agent':'developer','llm_turns':[1,2,3]}]
        result=developer_reads(steps,turns)[0]['calls']
        self.assertFalse(result[0]['same_file_result_already_in_request'])
        self.assertTrue(result[1]['same_file_result_already_in_request'])
        self.assertTrue(result[1]['identical_to_previous_read'])
