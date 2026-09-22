# C-14 — A-1-v4 재검증 사후 분석

## 0. 인수 상태

시작 HEAD 5925a42. 이후 커밋 없음, tracked diff 없음. docs/handoff/ 외 미추적 파일은 지정 v4 로그뿐이었다.
reports/a-1-v4에는 preflight.json, tests-c13.json만 존재했다. 기존 C-14 분석 산출물은 없었다.
원본 실행 파일은 변경하지 않았다. reasoning 문장은 읽거나 해석하지 않았고 크기만 계산했다.

## 1. 매니페스트

[manifest-c14.json](manifest-c14.json). verify, 데이터셋 아님. 유효성은 PM 결정 전 unclassified.
C-14 출력에만 S-1 정상 정의와 S-23 scenario.version 제거를 적용했다. 출력 식별자는 session-manifest-v0.2-c14이며 Stage 2 v0.3 구현이 아니다.
실행 시 git_commit/dirty는 미기록이므로 null/unmeasured. 분석 시 HEAD를 실행 코드로 대신 기록하지 않았다.

## 2. 종료·조건 비교

바뀐 조건: v9의 모든 호출 high, max_tokens, max_steps. 제공자·모델 동일. 1회 대 1회로 인과를 단정하지 않는다.

| 항목 | A-1-v3 | A-1-v4 |
|---|---|---|
| runner_protocol | "tool-capable-step-v8-budget-and-writable-paths" | "tool-capable-step-v9-reasoning-all-calls" |
| max_tokens | 2400 | 16384 |
| max_steps | 18 | 30 |
| termination_reason | "success" | "max_steps" |
| steps_reached | 9 | 30 |
| tests_before | 7 | 7 |
| tests_after | 16 | 7 |
| llm_calls | 23 | 74 |
| wall_seconds | 87.433252 | 574.348379 |
| credit_measured_decimal | "16.43025" | "130.81500" |
| first_stop_step | null | 9 |
| stagnant_runs | [[4], [9]] | [[7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]] |
| completion_max | 1814 | 9421 |
| finish_reason_counts | {"stop": 13, "tool_calls": 10} | {"stop": 46, "tool_calls": 28} |
| failed_steps | [4] | [] |
| vocabulary_violations | 0 | 0 |
| budget_exhausted_without_edit_steps | [1, 2] | [1, 2, 5, 7, 8, 11, 14, 17, 20, 23, 26, 29] |
| read_summary | {"rereads_in_context": 1, "identical_rereads": 1, "developer_edit_attempts": 1, "developer_read_calls": 3} | {"rereads_in_context": 6, "identical_rereads": 6, "developer_edit_attempts": 0, "developer_read_calls": 20} |
| edit_attempts_outside_writable_paths | [{"step_id": 4, "agent": "planner", "tool": "write_file", "path": "src/task_query.py", "argument_chars": 3406}] | [] |
| harness_facts_confirmed | true | true |

## 3. 토큰·크레딧

| 항목 | A-1-v3 | A-1-v4 |
|---|---|---|
| known_prompt | 80115 | 444636 |
| known_completion | 7355 | 106866 |
| known_total | 87470 | 551502 |
| usage_missing_turns | 0 | 0 |
| total | 87470 | 551502 |
| total_status | "measured" | "measured" |

크레딧은 사용자 기록 monthly_allocated.used 차이다. 다른 사용과 겹치지 않았는지는 사용자 확인 사항이다.

| reasoning_tokens 요청 구분 | A-1-v3 n/min/median/max | A-1-v4 n/min/median/max |
|---|---|---|
| tool_capable | 14 / 0 / 177.0 / 907 | 44 / 18 / 458.5 / 9301 |
| final | 9 / 8 / 80 / 255 | 30 / 438 / 1178.5 / 5592 |
| tool_call_response | 10 / 16 / 101.5 / 907 | 28 / 18 / 144.0 / 9301 |

tool_capable은 최종 호출 외 전체이며, tool_call_response는 실제 도구를 반환한 호출의 부분집합이다.
요청·업스트림 전송 확인: `{"request_body": {"high": 74}, "upstream_request_body": {"high": 74}}`

## 4. 판정·metrics-v1

정상 여부는 실행기 success와 같은 S-1 정의다. 아래는 PM이 valid로 확정할 경우의 조건부 계산이며 공식 집계가 아니다.
```json
{
  "metrics_version": "metrics-v1",
  "scope": "conditional calculation if PM classifies this session valid; not dataset aggregation",
  "official_aggregate": {
    "value": null,
    "status": "unmeasured",
    "reason": "PM validity pending; verification run is not dataset"
  },
  "normal_session": false,
  "artifact_test_change_steps": [
    4
  ],
  "missing_baseline_steps": [],
  "onset_step": 5,
  "first_stop_step": 9,
  "last_turn_at_stop": 25,
  "known_tokens": 551502,
  "known_tokens_after_stop": 400598,
  "usage_missing_turns": 0,
  "sensitivity_excluding_usage_missing": {
    "value": 0.7263763322707806,
    "status": "same_complete_sample"
  },
  "preservation": {
    "value": null,
    "status": "no_sample",
    "numerator": 0,
    "denominator": 0
  },
  "detection_rate": {
    "value": 1.0,
    "status": "measured",
    "numerator": 1,
    "denominator": 1
  },
  "savings_failure_basis": {
    "value": 0.7263763322707806,
    "status": "measured",
    "numerator": 400598,
    "denominator": 551502
  },
  "savings_all_basis": {
    "value": 0.7263763322707806,
    "status": "measured",
    "numerator": 400598,
    "denominator": 551502
  },
  "normal_false_stop_loss_tokens": 0,
  "delay_steps_median": 4,
  "delay_status": "measured",
  "delay_role_rounds": 1.3333333333333333,
  "early_stop_count": 0,
  "unmeasured_step_ratio": {
    "value": 0.0,
    "status": "measured",
    "numerator": 0,
    "denominator": 30
  },
  "needs_review_step_ratio": {
    "value": 0.0,
    "status": "measured",
    "numerator": 0,
    "denominator": 30
  },
  "overhead_ms": {
    "p50": null,
    "p99": null,
    "status": "unmeasured",
    "reason": "judgement runtime not recorded"
  }
}
```

S-4 시작점은 산출물/인수 결과가 마지막으로 바뀐 다음 step이다. stagnant 시작점으로 바꾸지 않았다.
S-20 조기 STOP도 탐지·절감에 포함하고 음수 지연은 중앙값에서 제외한다.

## 5. 가상 판정

| step | progress | criteria |
|---|---|---|
| 1 | baseline | continue |
| 2 | baseline | continue |
| 3 | baseline | continue |
| 4 | progress | continue |
| 5 | progress | continue |
| 6 | progress | continue |
| 7 | stagnant | continue |
| 8 | stagnant | continue |
| 9 | stagnant | deadlock |
| 10 | stagnant | deadlock |
| 11 | stagnant | deadlock |
| 12 | stagnant | deadlock |
| 13 | stagnant | deadlock |
| 14 | stagnant | deadlock |
| 15 | stagnant | deadlock |
| 16 | stagnant | deadlock |
| 17 | stagnant | deadlock |
| 18 | stagnant | deadlock |
| 19 | stagnant | deadlock |
| 20 | stagnant | deadlock |
| 21 | stagnant | deadlock |
| 22 | stagnant | deadlock |
| 23 | stagnant | deadlock |
| 24 | stagnant | deadlock |
| 25 | stagnant | deadlock |
| 26 | stagnant | deadlock |
| 27 | stagnant | deadlock |
| 28 | stagnant | deadlock |
| 29 | stagnant | deadlock |
| 30 | stagnant | deadlock |

## 6. 실행기 결함·PM 결정

| 인수인계 결함 | 이번 세션 확인 |
|---|---|
| 1 역할 간 비교 | 동일 역할 비교 검사: True |
| 2 회복 관측 폐기 | failed step 목록: []; 실패 회복 분기의 실제 검증 기회는 없음 |
| 3 ID 불일치 | 어휘 위반: 0 |
| 4 info_items null | 선택 지표: ["artifact.files_changed", "artifact.test_pass_count", "conversation.open_issues_count"]; info_items는 판정에서 제외 |
| 5 편집 절단 | length는 finish_reason 분포 참조. developer 편집 시도 없음으로 편집 절단 원인은 검증 불가 |
| 6 쓰기 경로 미전달 | 경로·예산 사실 확인: True; 권한 밖 쓰기 목록: [] |
| 7 예산 미고지 | 사실 문장은 전달됨. 반복 읽기로 소진한 step은 비교표 참조; 행동 원인은 미확정 |
| 8 도구 오류 completed | 도구 실행 오류 기록: []; 오류 분기 실제 검증 기회 없음 |
| 9 입력 중복 | 과거 AssistantMessage.thought가 최종 요청에 직렬화되는 경로 확인. 아래 A 참조 |

### A. AssistantMessage 필드

동일한 planner step의 최종 요청을 비교했다. 값은 Python 문자열의 글자 수이며 토큰 환산은 하지 않는다.
| 기록 | A-1-v3 | A-1-v4 |
|---|---|---|
| turn | 12 | 12 |
| request_message_content_chars | 12805 | 25604 |
| assistant_record_json_chars | 6078 | 15772 |
| assistant_body_chars | 555 | 1145 |
| assistant_tool_argument_chars | 3452 | 2579 |
| thought_chars | 1216 | 10989 |

v4 요청의 AssistantMessage별 필드 크기:

| record | content 타입/문자열 길이/JSON 길이 | thought 문자열 길이/JSON 길이 | source 문자열 길이 | type 문자열 길이 | JSON 키·구두점 |
|---|---|---|---|---|---|
| 0 | list/None/111 | None/4 | 7 | 16 | 48 |
| 2 | str/1145/1197 | 10989/11283 | 7 | 16 | 48 |
| 4 | list/None/118 | None/4 | 7 | 16 | 48 |
| 6 | list/None/2751 | None/4 | 7 | 16 | 48 |

유입 경로: autogen_ext/models/openai/_openai_client.py:698–700에서 reasoning_content → thought; autogen_agentchat/agents/_assistant_agent.py:852–857에서 AssistantMessage에 저장; experiments/step_execution.py:111의 model_dump()가 thought까지 포함하고 :113에서 user 메시지 문자열로 직렬화한다. :145/:147은 최종 호출에 이 경로를 적용한다. v8/v9 공통이며 v3에도 존재했다.

### B. developer 호출·파일·재읽기

직전 읽기는 세션 전체에서 같은 파일을 마지막으로 읽은 호출이다. 같은 역할 기준은 JSON에 별도로 기록했다. 요청 내 존재는 call ID로 연결된 read_file 결과 기준이다. false는 그 기록이 없다는 뜻이며 파일 지식 전체의 부재를 뜻하지 않는다.
| step | turn/호출 | 도구 | 파일 | 요청에 이미 있음 | 직전 읽기 turn | 결과 동일 | 요청 thought 글자 |
|---|---|---|---|---|---|---|---|
| 2 | 4/1 | read_file | src/task_query.py | False | 2 | True | 0 |
| 2 | 5/2 | read_file | SPEC.md | False | 1 | True | 0 |
| 5 | 13/1 | read_file | tests/test_task_query.py | False | 10 | True | 0 |
| 5 | 14/2 | read_file | ACCEPTANCE.md | False | None | None | 0 |
| 8 | 21/1 | read_file | src/task_query.py | False | 19 | True | 0 |
| 8 | 22/2 | read_file | SPEC.md | False | 7 | False | 0 |
| 11 | 28/1 | read_file | tests/test_task_query.py | False | 13 | True | 0 |
| 11 | 29/2 | read_file | src/task_query.py | True | 21 | True | 0 |
| 14 | 35/1 | read_file | SPEC.md | False | 22 | True | 0 |
| 14 | 36/2 | read_file | src/task_query.py | True | 29 | True | 0 |
| 17 | 42/1 | read_file | tests/test_task_query.py | False | 28 | True | 0 |
| 17 | 43/2 | read_file | src/task_query.py | True | 36 | True | 0 |
| 20 | 49/1 | read_file | SPEC.md | False | 35 | True | 0 |
| 20 | 50/2 | read_file | src/task_query.py | True | 43 | True | 0 |
| 23 | 56/1 | read_file | tests/test_task_query.py | False | 42 | True | 0 |
| 23 | 57/2 | read_file | ACCEPTANCE.md | False | 14 | True | 0 |
| 26 | 63/1 | read_file | src/task_query.py | False | 50 | True | 0 |
| 26 | 64/2 | read_file | SPEC.md | False | 49 | True | 0 |
| 29 | 70/1 | read_file | tests/test_task_query.py | False | 56 | True | 0 |
| 29 | 71/2 | read_file | src/task_query.py | True | 63 | True | 0 |

### C. 분류와 시점

**최종 요청의 reasoning 재유입은 하네스 입력 구성 문제다. 반복 읽기의 원인은 판단 불가다.** 실제 편집 없는 반복 행동·산출물 정체는 확인되지만, developer 도구 선택 요청에는 thought가 없었다. 최종 보고 요청의 크기가 커진 사실만으로 그 이전 도구 선택의 원인이라고 할 수 없다.
크기 변화도 단조 누적이 아니다. 아래 값은 각 developer step의 최종 요청이고, 두 읽기 호출 뒤에 전송됐다.

| step | 최종 turn | 최종 요청 thought 글자 | 최종 요청 메시지 본문 글자 |
|---|---|---|---|
| 2 | 6 | 0 | 6893 |
| 5 | 15 | 7686 | 20069 |
| 8 | 23 | 19197 | 31640 |
| 11 | 30 | 7418 | 21767 |
| 14 | 37 | 6641 | 18760 |
| 17 | 44 | 6758 | 19022 |
| 20 | 51 | 6648 | 18777 |
| 23 | 58 | 7737 | 20389 |
| 26 | 65 | 6895 | 19329 |
| 29 | 72 | 5987 | 20442 |

수정 선택지만 제시: (a) 새 프로토콜에서 final_messages 직렬화 시 thought 필드 제외 (b) 새 프로토콜에서 최종 보고용 AssistantMessage 필드 허용 목록을 정의하여 명시적으로 재구성. 과거 프로토콜과 로그는 보존한다. 현재 파일·프롬프트는 수정하지 않았다.

PM 결정: 유효성은 unclassified 제안. invalid_runner 확정에는 행동 영향 근거가 부족하다. 파일럿 조건 동결은 이 입력 문제를 수용할지, 새 프로토콜에서 제거 후 재검증할지 결정 후 진행할 것을 제안한다. Stage 2 도구·B군 실행기·B-6/C-9 준비는 이번에 진행하지 않았다.

## 7. 유효성 분류 제안

unclassified. 기존 A-1-v3의 PM valid 결정을 소급 변경하지 않는다. 이번 세션을 공식 탐지율/절감률 집계에 넣지 않는다.

## 8. 특이 사항·한계

기존 analyze_session의 prompt_checks는 v8 사실 문장을 놓치는 휴리스틱이므로 이 보고에서는 제거하고 compare_sessions의 명시 문장 확인 결과를 사용했다. 기존 도구는 변경하지 않았다.
기존 counterfactual.first_step_with_all_tests는 최대 관측 통과 수를 전체 통과로 취급하는 문제가 있어 이번 출력에서만 test_total_count와 직접 비교했다. 판정기는 변경하지 않았다.
metrics_v1_check 참조 구현은 음수 지연을 중앙값에서 빼지 않으므로 그대로 재사용하지 않았다. 새 분석은 S-20 정의를 적용하고 테스트로 검증한다.
