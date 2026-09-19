# G0-6: 도구 실행 오류를 step 기록에 반영 (결함 8)

PM 결정 D-15. G0-8 전에 수정하되 기록만 바꾸고 제어 흐름은 바꾸지 않는다.

## 변경

- `perform_step` 은 매 모델 호출의 `ToolCallExecutionEvent` 에서 실행된 도구 결과를 모아
  `tool_executions` 로 돌려준다. 항목 : `llm_call_in_step`, `tool`, `call_id`, `is_error`,
  `error_summary`(오류일 때 결과 앞 300자, 아니면 null).
- steps.json 기록 : `tool_executions` 를 남기고, 하나라도 `is_error` 면 `step_status: failed`,
  `failure_reasons` 에 `tool_execution_error` 를 더한다. summary 의 `failed_steps` 에도 나온다.
- v1·v2 계약과 legacy·independent 수집 정책 모두에 같은 기록 규칙을 적용한다.

## 바꾸지 않은 것

- `perform_step` 의 `failed`/`failure_reasons` 와 재시도·중단·호출 수 규칙, strict 연속 카운터.
- 실행기 제어에 쓰는 실패 여부(`outcome['failed']`)는 출력 유효성만 뜻한다. 최종 출력 파싱,
  다른 역할에 보내는 narrative, legacy 정책의 관측 선택, legacy `measurement_status`,
  성공 종료 판정이 모두 이 값을 쓰므로 도구 오류가 있어도 그대로다. 도구 오류가 있던 step 에서
  reviewer 가 완료를 선언하고 인수 판정이 통과하면 지금처럼 success 로 끝난다.
- P0-2 원칙 : 출력 유효성과 작업 성공은 별개다. 도구 오류 step 도 유효한 최종 출력이면 대화
  관측을 보존하고, 산출물은 실제 수집값을 보존한다. 관측·progress·criteria 입력은 바뀌지 않는다.

## 기존 로그 적용 (오프라인)

`tools/audit_tool_execution_errors.py` → `reports/g0-6/tool-execution-audit.json`.
A-1 4차 로그에서 `is_error` 가 확인되는 실행 결과는 step 7 planner 의 `replace_in_file`
(`Role is not authorized to edit this file`) 하나다. 이 규칙이었다면 step 7 은 failed 로 기록됐다.
`is_error` 는 최종 요청 observed_records 에 직렬화된 결과에서만 읽으며, 없으면 unmeasured 로 둔다.
