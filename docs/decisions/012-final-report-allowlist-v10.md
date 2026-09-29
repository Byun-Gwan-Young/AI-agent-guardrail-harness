# S-25 · S-31: 최종 보고 요청은 허용 필드만 싣는다 (프로토콜 v10)

PM 결정 S-25 (2026-09-22), S-31 (2026-09-29). A-1-v4 재검증(`A-1-v4-e174aafe…`)에서 최종 보고 요청에
모델 자신의 이전 추론이 들어간 것이 발견됐다. 최종 보고가 자기 추론을 읽는 것은 사실 전달이 아니다.

## 경로 (v8·v9)

SDK 가 응답의 `reasoning_content` 를 `thought` 로 보관 → `step_execution.final_messages` 가 AssistantMessage 를
`model_dump()` 그대로 넣음 → 최종 요청 user 본문(`observed_records`)으로 직렬화.

## v10 에서 최종 보고 요청에 남는 것

`allowlisted_final_record` (`experiments/step_execution.py`). 필드 하나를 빼는 방식이 아니라 허용 목록이다.
이후 SDK 가 필드를 추가해도 최종 요청에 들어가지 않는다.

- 모든 기록 : `source`, `type`
- 도구 호출 (`AssistantMessage`·`ToolCallRequestEvent`, 목록 본문) : 항목마다 `name`, `arguments`
- 도구 결과 (`FunctionExecutionResultMessage`·`ToolCallExecutionEvent`) : 항목마다 `name`, `content`, **`is_error`**
- 문자열 본문 : `content`
- 빠지는 것 : `thought`, `models_usage`, `metadata`, 호출 `id`, 결과 `call_id` 등 목록 밖 전부
- 사용자 메시지에서 만든 사실(`task`, `initial_issue_ids`, `acceptance`, `recent_messages`)은 v9 와 같다

## S-31 : `is_error` 추가 (v10 자리에서 수정)

- C-15 의 v10 은 도구 결과에서 `is_error` 도 버렸다. 도구가 실패했다는 것은 실행의 사실이고, S-25 의 목적은
  모델 추론 제거뿐이었다.
- v10 으로 실행된 세션이 0 개이므로 새 프로토콜 번호 없이 v10 에서 고쳤다. 식별자
  `tool-capable-step-v10-final-report-allowlist` 는 그대로다.
- `id`·`call_id` 는 계속 뺀다 (호출과 결과는 기록 순서로 이어진다).

## 버전과 불변

- v10 = v9 (모든 호출 `reasoning_effort`) + 위 허용 목록. v10 도 시나리오 `reasoning_effort` 가 있어야 한다.
- v7·v8·v9 동작 불변 (기존 바이트 동일 테스트 유지).
- 테스트 `tests/test_final_report_allowlist.py` :
  - 같은 가짜 응답(thought 포함)으로 v9·v10 을 돌리면 차이는 최종 요청의 thought 부재뿐
  - 없는 파일 읽기(도구 실패) 후 v10 최종 요청에 `is_error: true` 가 남고 thought 는 없음
  - 허용 목록 단위 테스트

## A-1-v4 에 적용한 오프라인 추정 (실행 아님)

`tools/estimate_v10_context.py` → `reports/c15/`. 최종 요청 30 건의 user 본문 문자 수.

| 파일 | 기준 | v9 | v10 추정 |
|---|---|---|---|
| `v10-context-estimate.json` (v1) | 사용자 사실까지 허용 목록 적용 — **잘못됨** | 882,578 | 170,383 |
| `v10-context-estimate-v2.json` | 수정 (`8069a7d`), `is_error` 제외 | 882,578 | 365,853 |
| `v10-context-estimate-v3.json` | S-31 반영 | 882,578 | 366,708 |
