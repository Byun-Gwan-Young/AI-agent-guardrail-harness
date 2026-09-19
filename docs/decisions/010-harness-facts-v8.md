# G0-14: 호출 예산과 쓰기 가능 파일을 사실로 알린다 (결함 6·7, 프로토콜 v8)

PM 결정 D-23 C. G0-8(`A-1-v2-b51f67df…`)에서 결함 6·7 이 재발했다. 판정 규칙이 아니라 하네스가
모델에게 숨긴 사실을 알려 인위적 정체를 없앤다. **사실만 알리고 행동을 코치하지 않는다.**

## v8 에서 모델에게 추가로 전달되는 것

- 역할 시스템 메시지(도구 안내 뒤) : `Files this role can write: <writable_paths 또는 none>.` 와
  `Each step allows at most <N> model calls for this role; the last call of a step has no tools and returns the final report.`
  `<writable_paths>` 는 시나리오 역할 설정, `<N>` 은 `termination.max_llm_calls_per_step`.
- 도구를 쓸 수 있는 매 호출 : 호출 번호와 남은 호출 수.
  - step 첫 호출(작업 문맥 JSON) : `call_budget` 필드 `{model_call, max_model_calls, remaining_after_this_call, last_call_has_no_tools}`.
    필드로 넣어 최종 보고 요청의 문맥 추출(`final_messages`)이 그대로 동작한다.
  - 이어지는 호출(도구 결과 후속, 교정 메시지) : 문장 한 줄.
  - 최종 호출은 기존 FINAL_ONLY 가 이미 알리므로 추가하지 않는다. 최종 보고 요청 본문은 v7 과 같다.
- 전략 조언("먼저 편집하라", "다시 읽지 마라" 등)은 넣지 않는다. 테스트가 조언 단어를 검사한다.

## 버전과 선택

- 실행기 프로토콜 `tool-capable-step-v8-budget-and-writable-paths`. output-contract-v2 의 기본값이다.
- `--runner-protocol tool-capable-step-v7-issue-ids` 로 v7 을 명시 선택하면 G0-8 과 같은 시스템 메시지가
  나온다(테스트가 G0-8 로그와 바이트 단위로 비교). v7 동작은 바꾸지 않았다.
- output-contract-v1 에는 `--runner-protocol` 을 줄 수 없다(실행 전 오류).
- conditions.json : `runner_protocol`, v8 이면 `harness_facts_policy`. v7·v8 모두
  `recent_messages_policy` 를 실제 G0-13 동작(검증된 최종 보고 narrative 전달)에 맞게 고쳤다(기록 문구만).
- 판정 규칙·지표·criteria(`deadlock-v0.2` / `progress-v2`), `max_llm_calls_per_step`(3), 권한 밖 쓰기의
  제어 흐름(G0-6 기록)은 그대로다.

## A-1-v3

- A-1-v2 는 G0-8 실행 기록이 있어 고치지 않는다. A-1-v3 = A-1-v2 + `max_tokens: 2400`(D-3 개정).
  차이는 `scenario_id`, 머리 주석, `max_tokens` 뿐이다(테스트). `max_tokens` 는 시나리오 필드이며
  실행기가 요청에 그대로 보낸다(`run_scenario.py` model options).
- 실행 전 기록 `reports/a-1-v3/preflight.json`. A-1·A-1-v2 와 다른 조건군이며 세션을 섞지 않는다.

## G0-8 확인 (오프라인)

`tools/check_harness_facts.py` → `reports/a-1-v3/g0-8-harness-facts.json`. G0-8 은 v7 이었고,
세 역할 모두 시스템 메시지에 쓰기 가능 파일·호출 한도가 없었으며, 도구 가능 호출 25회 중 예산 사실이
실린 호출은 0회였다. 세션은 다시 판정하지 않는다.
