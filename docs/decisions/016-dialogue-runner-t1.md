# 실행기 T1 대화 흐름 (C-17-4)

설계 `docs/design/demo-runner-extension.md` 2~4 절(실행기·라우터), 결정 문서 015, 작업 단위 `demo-work-plan.md` 17-5 의 대화 과제 부분
(DM-39 : 산출물 과제 CT·CL·CT-N 은 C-17-5, 도구 4 종은 C-17-6). 13 장 DM-16~DM-20·DM-26~DM-39 가 설계 문서보다 우선한다.

## 파트 1 — scenario-v2 대화 과제 실행 (`experiments/dialogue_runner.py`)

- `run_scenario.run` 은 scenario-v2 **대화 과제만** 이 모듈로 넘긴다. scenario-v2 산출물 과제는 계속 실행 전 거절 (C-17-5).
  그 아래 scenario-v1 경로는 손대지 않았다 : A-1-v4 오프라인 실행의 업스트림 요청 12 건이 C-17-4 이전 캡처
  (`tests/fixtures/c17-4-v1-requests.json`, `7ef2e5c` 에서 생성)와 바이트 동일 (테스트)
- 공유 코드의 변경은 기본값이 이전과 같은 것뿐 : `perform_step(…, tool_text=None, correct=None)` (대화 과제의 도구 안내·교정 문구),
  `collection_metadata` 의 T1 지표 → 필드 이름 (`status_advance`→`status`, `adopted_items`, `new_issue_ids`→`open_issue_ids`, progress-v3 와 같은 대응)
- **실행 조건** (모두 실행 폴더를 만들기 전에 검사)
  - `--output-contract output-contract-v3`, `--runner-protocol tool-capable-step-v10-…`, 독립 수집 정책, 시나리오 `reasoning_effort` 필수
    (데모 공통 조건 v10, 명시 강제 D-25). scenario-v1 에 v3 계약·`--closed-list-check` 를 주면 오류
  - **`--phase demo` 필수, `--dataset-run` 거절** : v0.3 은 데모 전용이고(DM-10, DM-37) scenario-v2 는 데모 트랙이다.
    phase 없이 돌면 실행 폴더가 데이터셋 경로 `runs/` 에 생기고 v0.3 으로 판정된다 (14 장 금지 "데이터셋 경로에서 v0.3"). 지시에 없던 안전장치
  - DM-34 (`runs/demo/` 밖이면 오류), `--dataset-run` + `--phase demo` 오류, 차단 프록시의 비데모 거절(DM-32)은 그대로 적용된다
  - 시나리오의 도구에 구현이 없으면 오류 (`dialogue_tools.IMPLEMENTATIONS` 는 C-17-6 까지 비어 있다 → 실제 실행은 C-17-6 전에는 시작되지 않는다)
- **세션 등록** : `registration_for(scenario)` 를 `POST /sessions` 본문 `{"registration": …}` 로 한 번 보낸다. 응답이 오류이거나
  `registered: true` 가 아니거나 프록시가 저장한 등록이 보낸 것과 다르면 모델 호출 전 `runner_error`. 등록과 정규 JSON 해시를
  `conditions.json` 에 남긴다. 등록 없는 v2 세션은 없다 (v0.2 프록시는 422 로 거절 → 테스트)
- **출력 계약** : 각 차례의 최종 보고는 output-contract-v3. **DM-20 은 실행 조건 `--closed-list-check`** :
  - `after_receipt` (기본, probe 전) : 제공자에게 v3 strict 스키마에서 `enum` 만 뺀 모양을 보내고(상태·`handoff_to`·산출물 스키마의 닫힌 목록),
    받은 뒤 계약이 전부 검사한다. D-13 이 쟁점 ID enum 을 보내지 않은 것과 같은 방식
  - `provider_strict` : v3 strict 스키마(enum 포함) 그대로
  - 응답 형식 자체를 빼지 않은 이유 : 최종 보고 검증(`validate_final_response`)이 strict json_schema 요청만 유효 보고로 인정한다.
    빼면 모든 관측이 unmeasured 가 된다
  - 지시문의 스키마·상태 목록은 두 모드 모두 enum 포함 (사실 고지). 기록 : `conditions.closed_list_check`
- **역할 시스템 메시지** (사실만) : 시나리오 역할 문장 + 대화 도구 안내(어휘 4 종, 이 역할에 등록된 도구) + v8 사실 문장(쓰기 가능 파일 없음, 호출 예산)
  + 산출물 경로와 같은 계약 문장 + v3 스키마·지시문. 산출물 경로의 "workspace"·"monitored_paths"·테스트 문구는 넣지 않는다
- **차례 사이 전달** (설계 문서에 명시가 없어 산출물 경로 규칙을 따름) : 다음 역할의 `recent_messages` 항목 =
  검증된 최종 보고(파싱 성공 또는 G0-13 검증 보고)의 `narrative` + `status`·`handoff_to`·`adopted_items`·`deliverable`. 보고가 없으면 placeholder
  narrative 만. 도구 원문·reasoning 은 넘기지 않는다. `recent_messages` 는 v10 최종 요청이 이미 남기는 키라 **v10 허용 목록을 바꾸지 않았고**
  프로토콜 번호도 그대로 v10 이다
- **T1 관측** : 검증된 보고의 구조화 필드(`open_issue_ids`, `info_items`, `status`, `adopted_items`, `handoff_to`)로만 만든다. narrative 추출
  (`extracted_conversation`)도 넣지 않는다. 검증 보고가 없으면 필드 전부 null — 판정에서 unmeasured
- **어휘 위반** (`VOCABULARY_VIOLATIONS_V3` : 허용 밖 쟁점 ID·충돌·`status`·`handoff_to`) : step failed, 위반 수 별도 카운터,
  strict 연속 카운터에서 제외(D-17 : 0 으로 되돌림), 위반 값은 관측에 넣지 않는다 (상태 전진도 후퇴도 아님). 형태 오류(JSON·타입·누락)는
  지금처럼 strict 연속 카운터 → 2 회 연속이면 `strict_output_failures`. 위반 step 수는 summary·매니페스트에
- **판정 함수** : `scenario.judge` (`SCENARIO_ROOT` 기준 경로, 테스트는 `tests/fixtures/` 로 바꾼다)의 `judge(report, *, tool_records, inputs_dir)`
  를 매 step 끝에 최신 검증 보고와 도구 호출 기록으로 부른다. 반환 `{machine_success, result: resolved|escalated|unfinished, missing}`
  모양을 검사(`machine_success` 는 resolved 일 때만). step 기록 `completion_gate`, 파일 해시는 `conditions.judge`
- **종료** (summary `termination_reason`, 프록시 `/sessions/end`)
  - `success` : 실패하지 않은 step 의 보고가 순서 목록의 **마지막 상태**이고, 판정 함수 통과, 선언 규칙 충족 (선언 역할의 첫 선언 이후. 산출물 경로와 같은 규칙)
  - `escalated` : 상태가 `escalated` (DM-18). 순서 밖의 다른 종료 상태는 `terminal_status` + `terminal_status` 값 (지시 목록에 없던 구분)
  - `max_steps`, `guardrail_stop` (차단 403, 산출물 경로와 같은 처리), `strict_output_failures`, `runner_error`, `user_interrupted`
  - 성공·에스컬레이션·교착 분류 집계는 C-19
- **도구 자리** (`experiments/dialogue_tools.py`) : 역할의 도구 이름 목록으로 설계 5 절 인터페이스의 함수(`lookup_order(order_id)`,
  `read_policy(name)`, `web_search(query, max_results=5)`, `academic_search(query, max_results=5)`)를 요청에 싣고, 호출은
  `IMPLEMENTATIONS[name](arguments, context)` 로 넘긴다 (`context` = step·역할·`inputs_dir`). 호출마다 인자·결과(또는 오류)를 기록
  (`tool-dispatch.json`, step 의 `tool_dispatch_seq`) — 판정 함수의 입력. 테스트는 가짜 구현. `inputs_dir` 는 아직 읽지 않는다 (C-17-6)
- **기록** : `conditions.json` 에 계약 버전·`contract_sha256`·`closed_list_check`·등록·등록 해시·`task_kind`·`turn_order`·`dialogue_flow`·판정 함수·도구·
  도구 구현 식별자. **매니페스트 `session-manifest-v0.6`** = v0.5 + `task`, `registration` (값·해시·재계산 해시·프록시 저장 일치),
  `vocabulary_violations`, `run.final_status`·`terminal_status`, 대화 과제용 `judgement`, `routing`. 대화 과제 세션에만 쓰고 이전 세션 매니페스트는
  그대로 (v0.5 테스트 유지). `analyze_session` 은 대화 step 의 `completion_gate` 를 판정 결과로 읽는다

## 파트 2 — CS 라우터 (DM-19)

- `turn_order: router` (scenario-v2 가 대화 과제에만 허용. "CS 만" 은 시나리오 작성(C-18) 규칙이다 — 스키마는 과제 이름을 모른다)
- 다음 차례 = 그 step 의 **검증된 최종 보고**의 `handoff_to` (관측·공유에 쓰는 것과 같은 값. G0-13 검증 보고가 있는 실패 step 포함).
  설계 문서 3 절 (b) 와 같다 : LLM 을 따로 부르지 않고 모델 reasoning 을 읽지 않는다
- 쓸 수 없는 `handoff_to` 는 **고정 순서로 되돌아간다** (= 시나리오 역할 목록에서 현재 역할의 다음. 같은 역할이 연달아 오지 않게 step 번호가 아니라
  현재 역할 기준) :
  - 역할 목록 밖 값 → 계약 단계에서 어휘 위반 `handoff_to_not_allowed` (step failed, 위반 수, 관측 제외. 설계 3 절과 같음), fallback 사유 같은 이름
  - 자기 자신 → 보고는 유효(관측·공유 그대로), 차례만 무시. fallback 사유 `self_handoff`
  - null → `no_handoff`. 검증 보고 없음 → 그 step 의 strict 실패 코드, 없으면 `no_verified_final_report`
- step 기록 `route` = `{turn_order, from_agent, handoff_to, basis, next_agent, rule: handoff_to|fixed_order_fallback|fixed_order, fallback_reason}`,
  summary `route_fallbacks`. 고정 순서에서도 `handoff_to` 는 관측에 기록만 한다
- step 정의(한 역할의 한 차례), step 당 최대 호출 3, `max_steps` 는 고정 순서와 같다. 업스트림 요청 수 = step 호출 수 합 (테스트)
- 왕복 수는 progress-v3 의 기록(`progress.handoff`, H = 4)만. 판정에 영향 없음 : 같은 관측에서 `handoff_to` 만 지운 재판정의 상태·결정이 같다 (테스트).
  설명 문장만 E4 ↔ E5 로 달라진다
