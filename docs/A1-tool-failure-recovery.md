# A-1 step 1 도구 오류: 증거와 수정

대상 세션: A-1-f869d9c183854e7e80d07e30216bdab8.
실패한 원본 세션·실험 폴더는 수정하지 않았다. 실제 A-1 재실행 및 외부 API 호출도 하지 않았다. 검증은 가짜 응답과 인메모리 프록시만 사용했다.

## 1. 실제 로그에서 확인한 것

`runs/A1-validation-257b799cd94b409c8c43a4932d1a6e5e/buffered/A-1-f869d9c183854e7e80d07e30216bdab8/session.json`과 `logs/A-1-f869d9c183854e7e80d07e30216bdab8.json`은 JSON 내용이 일치한다.

| LLM turn | HTTP | prompt_tokens | completion_tokens | total_tokens | 응답 도구 호출 수 |
|---|---:|---:|---:|---:|---:|
| 1 | 200 | 1,359 | 44 | 1,403 | 1 |
| 2 | 400 | null | null | null | null |

세션 총토큰은 **측정 불가(null)**, 확인된 소계는 **1,403**이다. 첫 턴의 도구 이름은 기존 프록시가 응답 도구 payload를 저장하지 않아 로그만으로 확정할 수 없다. 두 번째 요청의 마지막 content에는 ACCEPTANCE.md 내용이 저장되어 있다.

summary.json에 보존된 오류는 다음과 같다.

```json
{
  "message": "Tool choice is none, but model called a tool",
  "type": "invalid_request_error",
  "code": "tool_use_failed",
  "failed_generation": "{\"name\": \"print_tree\", \"arguments\": {\"path\": \"\", \"depth\": 2}}"
}
```

따라서 두 번째 생성에서 **미등록 print_tree를 호출하려 했다는 사실**은 오류 기록으로 확인된다. planner의 승인된 permissions는 read_files/write_files이며, 실행기에서 실제 구성하는 목록은 **read_file, write_file**이다. run_tests는 developer/reviewer에만 등록된다. 전체 도구 종류가 세 가지라는 설명과 역할별 등록 목록을 구분해야 한다.

**실패 당시 요청 본문을 그대로 제시할 수는 없다.** 기존 두 로그 모두 request_body/upstream_request_body/tools/tool_choice를 저장하지 않았다. request_params에는 모델·온도·seed 등만 있고, in에는 마지막 메시지 content만 있다. 원래 프록시는 오류 응답의 error 객체도 저장하지 않아 turn 2의 out은 빈 문자열이다.

| 필드 | 실제 turn 1 로그 | 실제 turn 2 로그 |
|---|---|---|
| tools | 미저장·확인 불가 | 미저장·확인 불가 |
| tool_choice | 미저장·확인 불가 | 미저장·확인 불가 |

## 2. 설치 코드 확인과 오프라인 재현

AutoGen 0.5.7 AssistantAgent의 `_reflect_on_tool_use_flow`는 다음 방식으로 두 번째 추론을 호출한다.

```python
reflection_result = await model_client.create(llm_messages, json_output=output_content_type)
```

도구 인자를 전달하지 않는다. OpenAIChatCompletionClient는 빈 도구 목록이면 SDK 요청의 tools 필드를 생략한다. 기존 실행기는 tool_choice를 지정하지 않았고, 조사한 AutoGen 경로도 none을 명시적으로 삽입하지 않는다.

설치된 AutoGen 0.5.7/OpenAI SDK 3.7.0으로 첫 응답에 read_file 도구 호출, 두 번째 응답에 해당 400 오류를 주입했다. **실제로 직렬화되어 MockTransport에 도착한 재현 요청**은 다음과 같다. 아래 표는 과거 실제 요청을 복구한 것이 아니다.

| 재현 호출 | tools | tool_choice |
|---|---|---|
| 첫 호출 | read_file, write_file의 함수 스키마 | 필드 생략 |
| reflection 호출 | 필드 생략 | 필드 생략 |

`이전호출경로-로컬재현.json`에 tools 배열 전체를 저장했다. 실행기 또는 AutoGen이 tool_choice="none"을 넣었다는 주장은 확인되지 않았다. 도구 없는 reflection 요청에 대해 업스트림이 none으로 해석했다는 설명이 코드 경로·재현·실제 오류와 부합하지만, 과거 요청 원문은 없으므로 이를 원문 확인과 동일시하지 않는다.

이 reflection은 원래 도구 결과를 **텍스트로 정리**하려는 호출이다. 그래서 도구를 생략하는 AutoGen 자체 동작이 일반적으로 모순인 것은 아니다. 다만 이번 실행기 시스템 메시지는 계속 도구 사용을 유도했고 모델은 그 단계에서 미등록 도구를 생성했다. 도구 작업을 계속 허용하려는 현재 목적에 맞게 호출 구조를 바꿨다.

## 3. 수정 내용

- 시스템 메시지에 전체 도구 어휘 read_file/write_file/run_tests와 **현재 역할의 허용 목록**을 명시했다. print_tree 등 다른 도구를 금지하고 monitored_paths를 참조하도록 안내한다. planner에게 run_tests 권한을 새로 주지는 않았다.
- step context에 monitored_paths, registered_tools, 이전 도구 오류 교정 메시지를 전달한다. 실제 역할별 목록도 registered-tools.json으로 저장한다.
- AutoGen reflection을 끄고 실행기가 **step당 최대 2개의 도구 사용 가능한 호출**을 관리한다. 각 on_messages 호출은 LLM 추론 1회이며 도구가 있는 요청에는 `tool_choice: auto`를 명시한다. 두 번째 호출에도 역할의 tools 배열이 유지된다. 도구가 없는 호출은 none이지만 현재 세 역할의 작업 호출에는 모두 도구가 있다.
- 일반 도구 결과 이후 남은 호출 슬롯에서 작업을 이어가거나 최종 구조화 출력으로 마무리한다. 18 step·최대 36 LLM 호출, 온도·seed·버퍼·max_tokens 설정은 유지한다.
- 프로토콜 변경은 conditions.json의 `runner_protocol: tool-capable-step-v2`와 unknown_tool_policy로 기록한다. 이전 reflection 방식의 실행과 같은 실행 조건으로 취급하지 않는다.
- 프록시 turn마다 request_body, upstream_request_body, response_body를 보존한다. Authorization 등 HTTP 헤더는 여기에 기록하지 않는다. body의 tools 배열·tool_choice 유무와 공급자 오류를 직접 확인할 수 있다. 기존 log.truncate는 in/out 요약 필드에 적용되며 새 body 증거는 원문으로 저장한다.

## 4. 실패 내성과 관측

인증·seed·기타 파라미터 400을 무조건 회복시키지 않는다. 회복 대상은 (a) 정상 200 tool_calls에 등록되지 않은 이름이 있는 경우, (b) 공급자 400 `tool_use_failed`의 failed_generation에서 미등록 이름이 확인되는 경우다.

같은 step에서 발생한 **잘못된 모델 응답 횟수**를 센다. 응답 한 개에 미등록 도구가 여러 개 묶여 있어도 오류 응답 1회다.

1. 첫 오류: step은 failed로 기록한다. “해당 도구는 없다. 등록된 도구만 사용하라”와 정확한 목록을 돌려준다. step의 2회 호출 한도에 여유가 있으면 교정 메시지로 한 번 더 호출한다. 여유가 없으면 교정을 다음 step/해당 역할의 다음 차례에 전달한다.
2. 두 번째 오류가 **같은 step**에서 발생: 관측과 pending/ack를 저장한 뒤 중단한다. 새로운 step의 오류를 이전 step의 횟수에 합치지 않는다.
3. 첫 오류 이후 교정 호출이 성공하더라도 그 step을 성공 관측으로 바꾸지 않는다. 실패 이력을 보존하고 다음 step으로 진행한다. 같은 step ID로 관측 payload를 여러 번 바꾸지 않는다.

**unmeasured 처리에 동의한다.** 도구 오류는 교착·정체의 근거가 아니고 신뢰할 대화 상태가 확보되지 않은 실패다. steps.json의 step_status=failed, measurement_status=unmeasured, tool_errors와 교정 메시지를 저장한다. 실제 파일 해시·테스트 결과는 steps.json의 acceptance에 그대로 보존한다.

교착 판정용 관측에서는 실패 step의 conversation 값을 null로, artifact를 null로 보내 성공·정체를 추론하지 않게 한다. 이는 실제 파일에 변화가 없었다는 주장이 아니다. 종결 선언도 오류 출력에서 추출하지 않는다. 기존 선언은 보존한다. 기존 판정 기준에서 이 관측은 **criteria.decision=unmeasured**가 된다. 첫 관측의 progress.state는 기존 baseline 규칙을 유지할 수 있으며 이를 stagnant로 바꾸지 않는다. criteria_version은 변경하지 않았다. 관측이 정상 전송된 실패 step은 missing_observation_count에 넣지 않는다.

실패 step 뒤에는 비교 가능한 관측이 다시 쌓여야 한다. 이 보수적인 보류를 교착 탐지 성능 향상으로 보고하지 않는다.

## 5. 외부 API 없는 검증

- 미등록 200 도구 호출 → 실패/교정 기록 → 다음 step 진행
- 미등록 400 한 번 → 회복 후 다음 step 허용
- 같은 step 미등록 400 두 번 → 중단, 호출 수 2 유지
- 두 번째 호출에서 첫 오류 → 세 번째 호출 추가하지 않음
- 정상 도구 호출 뒤 두 번째 요청도 tools 배열 유지 + tool_choice auto
- 관련 없는 400은 즉시 중단
- 실패 관측은 stagnant가 아니라 criteria unmeasured
- 인메모리 프록시 통합: 실패 step 기록·pending/ack·다음 step·종료·실제 직렬화 요청의 auto 확인
- 프록시 요청/업스트림 요청/오류 응답 원문 저장

관련 테스트 총 **35개 통과**(복구·통합 8, 프록시 기록 12, 실행기 helper 10, 버퍼/곡선 5). 통합 테스트는 공급자·인수 검사 모두 가짜이며 실제 A-1 실험을 수행하지 않았다.

## 6. 사용자 재실행

프록시를 재시작해야 요청 원문 기록이 적용된다. 실패한 세션은 ended 상태로 보존하고 새 output-root로 시작한다. 기존 검증 폴더·session ID를 재사용하지 않는다. 이전 점검표의 새 taskBatch를 만든 후 buffered 검증 명령을 다시 실행한다. 재실행 후 확인할 추가 항목:

- registered-tools.json의 planner 목록이 read_file/write_file인지
- session.json의 turn별 request_body.tools와 tool_choice가 역할 목록/auto인지
- 오류 발생 시 failed_steps와 tool_errors, 관측 ack, 다음 step 진행 여부
- total_tokens에 null이 있으면 소계와 구분하고 실패 실행 비용도 남길 것

실제 재실행과 외부 API 호출은 사용자에게 남겨 두었다.
