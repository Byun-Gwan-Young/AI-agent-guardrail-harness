"""C-14 offline evidence: never emit or interpret reasoning text, only its size.

No runner, scenario or judgement rule is changed. metrics-v1 values are conditional
until the PM establishes validity; they are not dataset performance estimates.
"""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from analyze_session import analyse, manifest, secret_scan, distribution, STOP_DECISIONS
from compare_sessions import column, read_results, result_text


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def records(messages):
    for m in messages:
        if m.get('role') == 'user' and isinstance(m.get('content'), str):
            try:
                obj = json.loads(m['content'])
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield from (r for r in obj.get('observed_records', []) if isinstance(r, dict))


def thought_size(messages):
    # Reasoning values are used exclusively by len(), never inspected or returned.
    total = sum(len(m[k]) for m in messages for k in ('thought','reasoning_content') if isinstance(m.get(k), str))
    return total + sum(len(r['thought']) for r in records(messages) if isinstance(r.get('thought'), str))


def request_sizes(turn):
    messages = turn['request_body']['messages']
    rs = list(records(messages))
    assistants = [r for r in rs if r.get('type') == 'AssistantMessage']
    return {'turn':turn['turn'], 'request_message_content_chars':sum(len(m['content']) for m in messages if isinstance(m.get('content'), str)),
            'assistant_record_json_chars':sum(len(encoded(r)) for r in assistants),
            'assistant_body_chars':sum(len(r['content']) for r in assistants if isinstance(r.get('content'), str)),
            'assistant_tool_argument_chars':sum(len(c.get('arguments','')) for r in assistants
                if isinstance(r.get('content'), list) for c in r['content'] if isinstance(c,dict)),
            'thought_chars':thought_size(messages)}


def field_sample(turn):
    out = []
    for index, r in enumerate(records(turn['request_body']['messages'])):
        if r.get('type') != 'AssistantMessage':
            continue
        fields = {k:{'type':type(v).__name__, 'value_chars':len(v) if isinstance(v,str) else None,
                     'json_value_chars':len(encoded(v))} for k,v in r.items()}
        out.append({'record_index':index, 'fields':fields, 'record_json_chars':len(encoded(r)),
                    'json_keys_and_punctuation_chars':len(encoded(r))-sum(v['json_value_chars'] for v in fields.values())})
    return {'turn':turn['turn'], **request_sizes(turn), 'assistant_records':out}


def developer_reads(steps, turns):
    last_global, last_role, rows = {}, {}, []
    for s in steps:
        calls = []
        for pos, number in enumerate(s['llm_turns']):
            t = turns[number]; messages = t['request_body']['messages']
            earlier = read_results(messages)
            later = turns[s['llm_turns'][pos+1]]['request_body']['messages'] if pos+1 < len(s['llm_turns']) else []
            for choice in (t.get('response_body') or {}).get('choices', []):
                for c in (choice.get('message') or {}).get('tool_calls') or []:
                    fn = c['function']
                    try: path = json.loads(fn['arguments']).get('path')
                    except (ValueError, AttributeError): path = None
                    if fn['name'] != 'read_file':
                        if s['agent']=='developer':
                            calls.append({'turn':number,'call_position':pos+1,'tool':fn['name'],'path':path})
                        continue
                    text = result_text(later, c['id'])
                    previous = last_global.get(path)
                    own = last_role.get((s['agent'],path))
                    entry = {'turn':number,'call_position':pos+1,'tool':fn['name'],'path':path,
                        'same_file_result_already_in_request':path in earlier,
                        'identical_to_request_result':text == earlier[path][-1] if text is not None and path in earlier else None,
                        'previous_read_turn':previous[0] if previous else None,
                        'identical_to_previous_read':text == previous[1] if text is not None and previous else None,
                        'previous_same_role_read_turn':own[0] if own else None,
                        'identical_to_previous_same_role_read':text == own[1] if text is not None and own else None,
                        'read_result_chars':len(text) if isinstance(text,str) else None,
                        'request_thought_chars':thought_size(messages)}
                    if s['agent']=='developer': calls.append(entry)
                    if text is not None:
                        last_global[path] = (number,text); last_role[(s['agent'],path)] = (number,text)
        if s['agent']=='developer':
            final = request_sizes(turns[s['llm_turns'][-1]])
            rows.append({'step_id':s['step_id'],'calls':calls,'final_request_sizes':final})
    return rows


def metrics_evidence(log, steps, conditions, summary):
    # S-4 uses global artifact/test change only, including the pre-step baseline.
    previous_hashes = conditions.get('fixture_hashes')
    previous_tests = summary.get('tests_passed_before')
    changes, missing = [], []
    monitored = conditions['scenario']['monitored_paths']
    if previous_hashes is not None:
        previous_hashes = {k:v for k,v in previous_hashes.items() if k in monitored}
    for s in steps:
        a = s['acceptance'].get('artifact') or {}
        hashes, tests = a.get('file_hashes'), a.get('test_pass_count')
        if hashes is None or previous_hashes is None or tests is None or previous_tests is None:
            missing.append(s['step_id'])
        elif hashes != previous_hashes or tests != previous_tests:
            changes.append(s['step_id'])
        previous_hashes, previous_tests = hashes, tests
    normal = summary['termination_reason']=='success'
    onset = None if normal or missing else max(changes,default=0)+1
    stop = next((s['step_id'] for s in steps if s['observation']['criteria']['decision'] in STOP_DECISIONS),None)
    last = max(next(s for s in steps if s['step_id']==stop)['llm_turns']) if stop is not None else None
    known = sum(t['tokens'] for t in log['turns'] if t.get('tokens') is not None)
    saved = sum(t['tokens'] for t in log['turns'] if last is not None and t['turn']>last and t.get('tokens') is not None)
    delay = stop-onset if stop is not None and onset is not None else None
    def ratio(n,d):
        return {'value':n/d if d else None,'status':'measured' if d else 'no_sample','numerator':n,'denominator':d}
    unmeasured = sum(s['observation']['criteria']['decision']=='unmeasured' for s in steps)
    review = sum(bool(s['observation']['criteria'].get('needs_observation_review')) for s in steps)
    return {'metrics_version':'metrics-v1', 'scope':'conditional calculation if PM classifies this session valid; not dataset aggregation',
        'official_aggregate':{'value':None,'status':'unmeasured','reason':'PM validity pending; verification run is not dataset'},
        'normal_session':normal,'artifact_test_change_steps':changes,'missing_baseline_steps':missing,
        'onset_step':onset,'first_stop_step':stop,'last_turn_at_stop':last,
        'known_tokens':known,'known_tokens_after_stop':saved,
        'usage_missing_turns':sum(t.get('tokens') is None for t in log['turns']),
        'sensitivity_excluding_usage_missing':{'value':(saved/known if not normal and known else None)
            if all(t.get('tokens') is not None for t in log['turns']) else None,
            'status':'same_complete_sample' if all(t.get('tokens') is not None for t in log['turns']) else 'excluded'},
        'preservation':ratio(int(normal and stop is None), int(normal)),
        'detection_rate':ratio(int(not normal and stop is not None),int(not normal)),
        'savings_failure_basis':ratio(saved if not normal else 0,known if not normal else 0),
        'savings_all_basis':ratio(saved if not normal else 0,known),
        'normal_false_stop_loss_tokens':saved if normal else 0,
        'delay_steps_median':delay if delay is not None and delay>=0 else None,
        'delay_status':'measured' if delay is not None and delay>=0 else 'unmeasured',
        'delay_role_rounds':delay/len(conditions['scenario']['agents']) if delay is not None and delay>=0 else None,
        'early_stop_count':int(delay is not None and delay<0),
        'unmeasured_step_ratio':ratio(unmeasured,len(steps)), 'needs_review_step_ratio':ratio(review,len(steps)),
        'overhead_ms':{'p50':None,'p99':None,'status':'unmeasured','reason':'judgement runtime not recorded'}}


def evidence(sid, credits):
    run = ROOT/'runs'/sid
    log = load(ROOT/'logs'/f'{sid}.json'); steps=load(run/'steps.json')
    conditions=load(run/'conditions.json'); summary=load(run/'summary.json')
    turns={t['turn']:t for t in log['turns']}
    a=analyse(sid); c=column(sid,tuple(float(v) for v in credits))
    if 'first_step_with_all_tests' in a['counterfactual_stop']:
        # Legacy helper compares to maximum observed count, not the full suite size.
        # Correct this derived C-14 report only; leave the helper and old reports unchanged.
        a['counterfactual_stop']['first_step_with_all_tests']=next((s['step_id'] for s in steps
            if s['acceptance']['artifact'].get('test_pass_count') == s['acceptance']['artifact'].get('test_total_count')
            and s['acceptance']['artifact'].get('test_total_count') is not None),None)
    # Old prompt_checks is a v7 heuristic; do not use its false negatives for v8/v9.
    a.pop('prompt_checks',None)
    c.pop('per_call_budget_fact_in_non_final_calls',None)
    c['max_steps']=conditions['scenario']['termination']['max_steps']
    elapsed = (datetime.fromisoformat(log['meta']['ended_at'])-datetime.fromisoformat(log['meta']['started_at'])).total_seconds()
    c['wall_seconds']=elapsed
    c['reasoning_tokens_by_request_kind']={}
    for kind in ('tool_capable','final','tool_call_response'):
        selected=[t for t in log['turns'] if
            (any((choice.get('message') or {}).get('tool_calls') for choice in (t.get('response_body') or {}).get('choices',[]))
             if kind=='tool_call_response' else ('response_format' in t['request_body']) == (kind=='final'))]
        values=[(((t.get('response_body') or {}).get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens') for t in selected]
        c['reasoning_tokens_by_request_kind'][kind]={**distribution(values),'missing':sum(v is None for v in values)}
    c['completion_max']=max((t['completion_tokens'] for t in log['turns'] if t.get('completion_tokens') is not None),default=None)
    c['reasoning_effort_transmission']={body:dict(Counter(str(t[body].get('reasoning_effort')) for t in log['turns']))
        for body in ('request_body','upstream_request_body')}
    field_rows=[{'step_id':s['step_id'],'agent':s['agent'],**request_sizes(turns[s['llm_turns'][-1]])} for s in steps]
    sample=next(s for s in steps if s['agent']=='planner' and s['step_id']>1)
    c['field_sample']=field_sample(turns[sample['llm_turns'][-1]])
    c['final_request_sizes']=field_rows
    c['developer_reads']=developer_reads(steps,turns)
    c['metrics_v1']=metrics_evidence(log,steps,conditions,summary)
    c['failed_steps']=[s['step_id'] for s in steps if s['step_status']=='failed']
    c['vocabulary_violations']=summary.get('vocabulary_violations_total')
    c['read_summary']={'rereads_in_context':len(c['rereads_in_context']),
        'identical_rereads':sum(r['identical'] is True for r in c['rereads_in_context']),
        'developer_edit_attempts':sum(len(r['edit_attempts']) for r in a['steps'] if r['agent']=='developer'),
        'developer_read_calls':sum(call['tool']=='read_file' for r in c['developer_reads'] for call in r['calls'])}
    # Facts only from the generated system prompts, not from model thought/body text.
    c['harness_facts_confirmed']=all(all(v.values()) for v in c['harness_facts_in_system_message'].values())
    c['source_sizes']={str(p.relative_to(ROOT)):p.stat().st_size for p in [ROOT/'logs'/f'{sid}.json',run/'session.json']}
    c['credit_measured_decimal']=str(Decimal(credits[1])-Decimal(credits[0]))
    c['input_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'logs'/f'{sid}.json',run/'steps.json',run/'summary.json',run/'conditions.json',run/'scenario.yaml']}
    return a,c


def markdown(report):
    c,b=report['candidate'],report['baseline'];m=c['metrics_v1']
    lines=['# C-14 — A-1-v4 재검증 사후 분석','',
        '## 0. 인수 상태','',
        '시작 HEAD 5925a42. 이후 커밋 없음, tracked diff 없음. docs/handoff/ 외 미추적 파일은 지정 v4 로그뿐이었다.',
        'reports/a-1-v4에는 preflight.json, tests-c13.json만 존재했다. 기존 C-14 분석 산출물은 없었다.',
        '원본 실행 파일은 변경하지 않았다. reasoning 문장은 읽거나 해석하지 않았고 크기만 계산했다.','',
        '## 1. 매니페스트','',
        '[manifest-c14.json](manifest-c14.json). verify, 데이터셋 아님. 유효성은 PM 결정 전 unclassified.',
        'C-14 출력에만 S-1 정상 정의와 S-23 scenario.version 제거를 적용했다. 출력 식별자는 session-manifest-v0.2-c14이며 Stage 2 v0.3 구현이 아니다.',
        '실행 시 git_commit/dirty는 미기록이므로 null/unmeasured. 분석 시 HEAD를 실행 코드로 대신 기록하지 않았다.','',
        '## 2. 종료·조건 비교','',
        '바뀐 조건: v9의 모든 호출 high, max_tokens, max_steps. 제공자·모델 동일. 1회 대 1회로 인과를 단정하지 않는다.','',
        '| 항목 | A-1-v3 | A-1-v4 |','|---|---|---|']
    for key in ('runner_protocol','max_tokens','max_steps','termination_reason','steps_reached','tests_before','tests_after',
                'llm_calls','wall_seconds','credit_measured_decimal','first_stop_step','stagnant_runs','completion_max',
                'finish_reason_counts','failed_steps','vocabulary_violations','budget_exhausted_without_edit_steps'):
        lines.append(f'| {key} | {encoded(b[key])} | {encoded(c[key])} |')
    for key in ('read_summary','edit_attempts_outside_writable_paths','harness_facts_confirmed'):
        lines.append(f'| {key} | {encoded(b[key])} | {encoded(c[key])} |')
    lines+=['','## 3. 토큰·크레딧','', '| 항목 | A-1-v3 | A-1-v4 |','|---|---|---|']
    for key in c['tokens']:
        lines.append(f"| {key} | {encoded(b['tokens'][key])} | {encoded(c['tokens'][key])} |")
    lines+=['', '크레딧은 사용자 기록 monthly_allocated.used 차이다. 다른 사용과 겹치지 않았는지는 사용자 확인 사항이다.',
        '', '| reasoning_tokens 요청 구분 | A-1-v3 n/min/median/max | A-1-v4 n/min/median/max |','|---|---|---|']
    for kind in c['reasoning_tokens_by_request_kind']:
        lines.append('| '+kind+' | '+' / '.join(str(b['reasoning_tokens_by_request_kind'][kind].get(k)) for k in ('n','min','median','max'))+
                     ' | '+' / '.join(str(c['reasoning_tokens_by_request_kind'][kind].get(k)) for k in ('n','min','median','max'))+' |')
    lines+=['','tool_capable은 최종 호출 외 전체이며, tool_call_response는 실제 도구를 반환한 호출의 부분집합이다.',
        '요청·업스트림 전송 확인: `'+encoded(c['reasoning_effort_transmission'])+'`','',
        '## 4. 판정·metrics-v1','',
        '정상 여부는 실행기 success와 같은 S-1 정의다. 아래는 PM이 valid로 확정할 경우의 조건부 계산이며 공식 집계가 아니다.',
        '```json',json.dumps(m,ensure_ascii=False,indent=2),'```','',
        'S-4 시작점은 산출물/인수 결과가 마지막으로 바뀐 다음 step이다. stagnant 시작점으로 바꾸지 않았다.',
        'S-20 조기 STOP도 탐지·절감에 포함하고 음수 지연은 중앙값에서 제외한다.','',
        '## 5. 가상 판정','',
        '| step | progress | criteria |','|---|---|---|']
    for row in report['step_decisions']:
        lines.append(f"| {row['step_id']} | {row['progress']} | {row['criteria']} |")
    lines+=['','## 6. 실행기 결함·PM 결정','',
        '| 인수인계 결함 | 이번 세션 확인 |','|---|---|',
        '| 1 역할 간 비교 | 동일 역할 비교 검사: '+str(report['p0_checks']['comparison_same_role'])+' |',
        '| 2 회복 관측 폐기 | failed step 목록: '+encoded(c['failed_steps'])+'; 실패 회복 분기의 실제 검증 기회는 없음 |',
        '| 3 ID 불일치 | 어휘 위반: '+str(c['vocabulary_violations'])+' |',
        '| 4 info_items null | 선택 지표: '+encoded(report['p0_checks']['judged_metrics'])+'; info_items는 판정에서 제외 |',
        '| 5 편집 절단 | length는 finish_reason 분포 참조. developer 편집 시도 없음으로 편집 절단 원인은 검증 불가 |',
        '| 6 쓰기 경로 미전달 | 경로·예산 사실 확인: '+str(c['harness_facts_confirmed'])+'; 권한 밖 쓰기 목록: '+encoded(c['edit_attempts_outside_writable_paths'])+' |',
        '| 7 예산 미고지 | 사실 문장은 전달됨. 반복 읽기로 소진한 step은 비교표 참조; 행동 원인은 미확정 |',
        '| 8 도구 오류 completed | 도구 실행 오류 기록: '+encoded(report['p0_checks']['tool_execution_errors'])+'; 오류 분기 실제 검증 기회 없음 |',
        '| 9 입력 중복 | 과거 AssistantMessage.thought가 최종 요청에 직렬화되는 경로 확인. 아래 A 참조 |','',
        '### A. AssistantMessage 필드','',
        '동일한 planner step의 최종 요청을 비교했다. 값은 Python 문자열의 글자 수이며 토큰 환산은 하지 않는다.',
        '| 기록 | A-1-v3 | A-1-v4 |','|---|---|---|']
    for key in ('turn','request_message_content_chars','assistant_record_json_chars','assistant_body_chars','assistant_tool_argument_chars','thought_chars'):
        lines.append(f"| {key} | {b['field_sample'][key]} | {c['field_sample'][key]} |")
    lines+=['','v4 요청의 AssistantMessage별 필드 크기:','',
            '| record | content 타입/문자열 길이/JSON 길이 | thought 문자열 길이/JSON 길이 | source 문자열 길이 | type 문자열 길이 | JSON 키·구두점 |','|---|---|---|---|---|---|']
    for row in c['field_sample']['assistant_records']:
        f=row['fields'];content=f['content'];thought=f['thought']
        lines.append(f"| {row['record_index']} | {content['type']}/{content['value_chars']}/{content['json_value_chars']} | {thought['value_chars']}/{thought['json_value_chars']} | {f['source']['value_chars']} | {f['type']['value_chars']} | {row['json_keys_and_punctuation_chars']} |")
    lines+=['','유입 경로: autogen_ext/models/openai/_openai_client.py:698–700에서 reasoning_content → thought; '
            'autogen_agentchat/agents/_assistant_agent.py:852–857에서 AssistantMessage에 저장; '
            'experiments/step_execution.py:111의 model_dump()가 thought까지 포함하고 :113에서 user 메시지 문자열로 직렬화한다. '
            ':145/:147은 최종 호출에 이 경로를 적용한다. v8/v9 공통이며 v3에도 존재했다.','',
            '### B. developer 호출·파일·재읽기','',
            '직전 읽기는 세션 전체에서 같은 파일을 마지막으로 읽은 호출이다. 같은 역할 기준은 JSON에 별도로 기록했다. '
            '요청 내 존재는 call ID로 연결된 read_file 결과 기준이다. false는 그 기록이 없다는 뜻이며 파일 지식 전체의 부재를 뜻하지 않는다.',
            '| step | turn/호출 | 도구 | 파일 | 요청에 이미 있음 | 직전 읽기 turn | 결과 동일 | 요청 thought 글자 |','|---|---|---|---|---|---|---|---|']
    for row in c['developer_reads']:
        for call in row['calls']:
            lines.append(f"| {row['step_id']} | {call['turn']}/{call['call_position']} | {call['tool']} | {call['path']} | {call.get('same_file_result_already_in_request')} | {call.get('previous_read_turn')} | {call.get('identical_to_previous_read')} | {call.get('request_thought_chars')} |")
    lines+=['','### C. 분류와 시점','',
        '**최종 요청의 reasoning 재유입은 하네스 입력 구성 문제다. 반복 읽기의 원인은 판단 불가다.** '
        '실제 편집 없는 반복 행동·산출물 정체는 확인되지만, developer 도구 선택 요청에는 thought가 없었다. '
        '최종 보고 요청의 크기가 커진 사실만으로 그 이전 도구 선택의 원인이라고 할 수 없다.',
        '크기 변화도 단조 누적이 아니다. 아래 값은 각 developer step의 최종 요청이고, 두 읽기 호출 뒤에 전송됐다.',
        '', '| step | 최종 turn | 최종 요청 thought 글자 | 최종 요청 메시지 본문 글자 |','|---|---|---|---|']
    for row in c['developer_reads']:
        r=row['final_request_sizes'];lines.append(f"| {row['step_id']} | {r['turn']} | {r['thought_chars']} | {r['request_message_content_chars']} |")
    lines+=['','수정 선택지만 제시: (a) 새 프로토콜에서 final_messages 직렬화 시 thought 필드 제외 '
        '(b) 새 프로토콜에서 최종 보고용 AssistantMessage 필드 허용 목록을 정의하여 명시적으로 재구성. '
        '과거 프로토콜과 로그는 보존한다. 현재 파일·프롬프트는 수정하지 않았다.',
        '', 'PM 결정: 유효성은 unclassified 제안. invalid_runner 확정에는 행동 영향 근거가 부족하다. '
        '파일럿 조건 동결은 이 입력 문제를 수용할지, 새 프로토콜에서 제거 후 재검증할지 결정 후 진행할 것을 제안한다. '
        'Stage 2 도구·B군 실행기·B-6/C-9 준비는 이번에 진행하지 않았다.','',
        '## 7. 유효성 분류 제안','',
        'unclassified. 기존 A-1-v3의 PM valid 결정을 소급 변경하지 않는다. 이번 세션을 공식 탐지율/절감률 집계에 넣지 않는다.','',
        '## 8. 특이 사항·한계','',
        '기존 analyze_session의 prompt_checks는 v8 사실 문장을 놓치는 휴리스틱이므로 이 보고에서는 제거하고 '
        'compare_sessions의 명시 문장 확인 결과를 사용했다. 기존 도구는 변경하지 않았다.',
        '기존 counterfactual.first_step_with_all_tests는 최대 관측 통과 수를 전체 통과로 취급하는 문제가 있어 '
        '이번 출력에서만 test_total_count와 직접 비교했다. 판정기는 변경하지 않았다.',
        'metrics_v1_check 참조 구현은 음수 지연을 중앙값에서 빼지 않으므로 그대로 재사용하지 않았다. '
        '새 분석은 S-20 정의를 적용하고 테스트로 검증한다.','']
    return '\n'.join(lines)


def update_budget(candidate):
    path=ROOT/'docs/design/budget-a-1-v4.md'
    text=path.read_text().split('\n<!-- C14 measured update -->')[0]
    text=text.replace('# A-1-v4 (프로토콜 v9) 크레딧 재계산 — **추정**','# A-1-v4 (프로토콜 v9) 크레딧 — C-13 추정과 C-14 실측')
    text=text.replace('**이 문서의 모든 크레딧 값은 추정이다.** 확정은 A-1-v4 재검증 1회 실측으로 한다',
        '**아래 C-13 표의 크레딧은 당시 추정이다.** C-14 실측 보정은 문서 끝에서 구분한다')
    c=candidate;old=load(ROOT/'docs/design/budget-v9.json')['A-1-v4_session']['30_steps_max']
    measured={'session_id':c['session_id'],'steps':c['steps_reached'],'calls':c['llm_calls'],
              'credits':c['credit_measured_decimal'],'credits_per_call':str(Decimal(c['credit_measured_decimal'])/c['llm_calls']),
              'wall_seconds':c['wall_seconds'],'known_tokens':c['tokens']['known_total'],
              'previous_estimate':old,'new_population_range':{'value':None,'status':'unmeasured','reason':'one verification session is not a population range'},
              'pilot_and_main_revised_range':{'value':None,'status':'unmeasured','reason':'other scenarios and repeated v4 sessions unmeasured'}}
    suffix='\n<!-- C14 measured update -->\n## C-14 실측 보정\n\n계산: tools/analyze_c14.py --update-budget. 사용자 기록 monthly_allocated.used 차이이며 동시 다른 사용 여부는 사용자 확인 사항이다.\n\n```json\n'+json.dumps(measured,ensure_ascii=False,indent=2)+'\n```\n\n'
    suffix+='추론 내용이 다음 호출에 들어가지 않는다는 C-13 가정은 최종 보고 요청에서 성립하지 않았다. '
    suffix+='따라서 과거 범위는 검증된 상·하한으로 사용하지 않는다. 위 실측은 이 세션의 점 관측이며 새 비용 범위를 추정해서 채우지 않는다. '
    suffix+='기존 파일럿·본 수집 표는 과거 추정으로 보존하고 갱신 범위는 null/unmeasured로 둔다.\n'
    path.write_text(text.rstrip()+'\n'+suffix)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--candidate',required=True);p.add_argument('--baseline',required=True)
    p.add_argument('--credits',nargs=2,required=True);p.add_argument('--baseline-credits',nargs=2,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--update-budget',action='store_true')
    args=p.parse_args()
    a,c=evidence(args.candidate,args.credits);_,b=evidence(args.baseline,args.baseline_credits)
    if not a['secret_scan']['clean']:
        print(encoded(a['secret_scan']));return 1
    m=manifest(a,'verify',['A-1-v4 재검증, 게이트웨이 크레딧, 데이터셋 아님',
                          'Validity pending PM review of AssistantMessage.thought serialization; no causal attribution'])
    # Apply S-1/S-23 to this generated manifest only; do not modify old manifests or runner.
    m['manifest_version']='session-manifest-v0.2-c14'
    m['scenario'].pop('version',None);m['code']['metrics_version']='metrics-v1'
    m['judgement']['normal_session']=c['metrics_v1']['normal_session']
    m['validity']['reason']='PM review pending: reasoning serialized into final reporting input; behavioral causality unmeasured'
    report={'analysis_version':'c14-evidence-v1','candidate':c,'baseline':b,
            'step_decisions':m['guardrail']['virtual_decisions'],
            'p0_checks':a['p0_checks'],
            'changed_conditions':['runner v9: reasoning high on all calls','max_tokens','max_steps'],
            'interpretation':'one session each; no causal attribution; thought content neither emitted nor interpreted',
            'validity_proposal':'unclassified','classification':'harness issue in final-report input; cause of developer repetition undetermined'}
    args.output.mkdir(parents=True,exist_ok=True)
    for name,value in [('c14-analysis.json',a),('c14-evidence.json',report),('manifest-c14.json',m)]:
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (args.output/'c14-report.md').write_text(markdown(report))
    if args.update_budget: update_budget(c)
    print(encoded({'candidate':{k:c[k] for k in ('session_id','wall_seconds','credit_measured_decimal','metrics_v1','developer_reads','reasoning_tokens_by_request_kind')},
                   'baseline':{k:b[k] for k in ('wall_seconds','credit_measured_decimal','reasoning_tokens_by_request_kind')},'secret_scan':a['secret_scan']}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
