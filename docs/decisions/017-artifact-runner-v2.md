# 실행기 v2 산출물 과제 경로 (C-17-5)

작업 단위 `demo-work-plan.md` 17-5 의 산출물 과제 부분 (DM-39 : CT·CL·CT-N). 설계 `docs/design/demo-runner-extension.md`,
`docs/design/demo-scenarios.md` 4~6 절, 결정 문서 015·016. 13 장 DM-16·DM-17·DM-37·DM-40~DM-47 이 설계 문서보다 우선한다.
데모 시나리오 파일 자체는 C-18 이다. 테스트는 합성 fixture `tests/fixtures/scenario-v2-artifact.yaml` (`TEST-T2-v2`) 를 쓴다.

## 파트 1 — scenario-v2 산출물 과제 실행

- `run_scenario.run` 의 "scenario-v2 산출물 과제 실행 전 거절" 을 풀었다. 대화 과제만 `dialogue_runner` 로 가고, 산출물 과제는
  **scenario-v1 과 같은 함수의 같은 코드**로 돈다 (작업 공간 복사, 파일 도구 4 종, 인수 테스트 `Workspace.acceptance`, 산출물 관측,
  G0-13 공유, 어휘 위반, 종료). 판정·관측 로직을 복제하지 않았다. 분기는 다음뿐이다 (`artifact_v2`)
  - 계약 선택·실행 조건 검사, 데모 안전장치, 세션 등록, 기록 필드 (아래)
  - 역할의 도구 : scenario-v2 역할은 권한 이름 대신 도구 이름을 쓴다 (015). 고르는 순서는 권한 경로와 같은 어휘 순서
    (`read_file`, `write_file`, `replace_in_file`, `run_tests`) 라 `registered-tools.json`·요청의 도구 목록이 v1 과 같다
- `output-contract-v2` 경로에 걸려 있던 조건 `contract.version == V2` 는 `closed` (= v2 또는 v3, 닫힌 쟁점 어휘 계약) 로 바꿨다.
  scenario-v1 은 v3 를 실행 전에 거절하므로 v1 의 동작은 같다 (A-1-v4 요청 12 건 바이트 동일, 아래)
- **계약 선택 (DM-37)** : 시나리오 필드 `output_contract` (`output-contract-v2` | `output-contract-v3`). 산출물 과제는 **필수**,
  대화 과제는 생략하거나 v3 만. 명령행 `--output-contract` 는 시나리오가 고른 것과 같아야 한다 (D-25 : 암묵값 없음. 다르면 실행 전 오류)
- **산출물 과제의 output-contract-v3** (`dialogue_contract.ArtifactContract`) = v2 필드 + `spec_approved` (bool 또는 null) 만.
  - 이유 : 산출물 과제는 상태 목록·산출물 스키마·라우터가 없어(015 의 artifact 규칙) `status`·`adopted_items`·`deliverable` 을 정의할 수 없다.
    `handoff_to` 는 정의할 수 있지만 고정 순서에서 쓰이지 않는 값을 모델에게 더 요구하게 된다. DM-37 의 "CT 는 v3 (`spec_approved`)" 에 맞춘 최소 형태
  - **PM 확인 필요** (보고 6 절) — v3 의 나머지 필드를 산출물 과제에도 둘지
  - v2 필드는 v2 계약 코드·코드명으로 검사 (`IssueContract(V2)`). `spec_approved` 누락·타입 오류는 형태 오류 (strict 연속 카운터)
  - strict 스키마 이름 `state_report_v3_artifact`, 지시문 = v2 지시문 + `spec_approved` 사실 한 문장 (승인 규칙이 있으면 승인 역할·파일, 없으면 "null")
  - `IssueReport` 는 v2 와 같은 모양에 버전만 v3. `contract_sha256` = 쟁점 목록 해시 + 과제 종류 + 필드 + 승인 규칙
- **안전장치·경로** (대화 과제와 같은 함수 `run_scenario.enforce_demo_track`) : `--phase demo` 필수, `--dataset-run` 거절, DM-34 양방향
  (`runs/demo/` 강제·비데모 금지), 차단 프록시의 비데모 거절(409, DM-32). 프로토콜은 v10 만 (데모 공통 조건 DM-25, 대화 과제와 같음),
  `--closed-list-check` 는 대화 과제 전용
- **세션 등록** : `registration_for(scenario)` 를 `POST /sessions` 로 한 번 보내고, `registered: true` 와 프록시 저장값이 같은지 확인한다
  (대화 과제와 같다). 값은 역할 표시 이름과 고른 지표(산출물 변경·테스트 통과 수·새 쟁점). 대화 과제 전용 값은 빈 목록·null
  (`status_values: []`, `terminal_statuses: []`, `required_adopted_items: null`) — 프록시가 저장할 때 기본값을 채우므로 키를 빼면
  "저장값과 같음" 검사가 어긋난다. v0.2 프록시는 등록을 422 로 거절 → 모델 호출 전 `runner_error`
- **기록** : `conditions.json` 에 `task_kind: artifact`, `turn_order`, `contract_sha256` (v2 는 null), 등록과 해시, 역할별 도구.
  summary 에 `task_kind`, `turn_order`, `output_contract_version`, `registration_sha256`
- **매니페스트 v0.6** 를 산출물 과제에도 쓴다 : `task`, `registration`, `vocabulary_violations` (v0.6 의 공통 부분). 판정은 v0.3 의
  인수 테스트 판정(S-1) 그대로, 대화 과제의 `routing`·`completion_claims` 는 없다. v0.6 를 만든 실제 세션이 없어 v0.6 자리에서 넓혔다
  (지시 : "매니페스트 v0.6 에 산출물 과제 필드를 넣는다")

### DM-37 등가 조건

- fixture `tests/fixtures/scenario-v2-artifact.yaml` = `scenarios/A-1-v4-ambiguous-task-query.yaml` 를 v2 형식으로 옮긴 것.
  내용 차이는 시나리오 ID (`TEST-T2-v2`) 뿐이고, 형식 차이는 v2 필드 표기 (권한 → 도구 이름, `task_kind: artifact`, `turn_order: fixed`,
  `criteria_version: deadlock-v0.3`, `output_contract: output-contract-v2`, v1 전용 `scenario_revision`·`group`·`conversation_collection` 제거),
  승인 절차 없음. 테스트가 A-1-v4 를 같은 규칙으로 옮긴 값과 비교한다
- `tests/v1_request_capture.py` 의 `capture_v2` : `c17-4-v1-requests.json` 을 만든 오프라인 실행과 **같은 가짜 업스트림 응답**,
  v0.3 프록시, `--phase demo`
- 결과 : 업스트림 요청 12 건이 v1 캡처·`c17-4-v1-requests.json` 과 **바이트 동일**. 다른 필드 목록은 **없음** (요청마다 `[]`).
  시나리오 ID 는 요청 본문에 들어가지 않고 헤더(`X-Guardrail-Scenario`, 세션 ID)와 실행 폴더 이름에만 쓰인다

테스트 `tests/test_artifact_v2.py` (하네스 `tests/t2_harness.py`) : fixture 비교, 등가 조건, 등록·기록·관측(v0.3 판정), v3 계약 필드·지시문,
v3 보고의 `spec_approved` 누락 = 형태 오류, 파일 도구가 작업 공간을 바꾸고 관측이 그 값을 봄, 매니페스트 v0.6, 안전장치·계약·프로토콜 거절,
v0.2 프록시의 등록 거절, 차단 프록시.

## 파트 2 — CT 승인 강제 (DM-16)

- 시나리오 필드 `write_gate: {role, requires: spec_approved, set_by, spec_path}` — 설계 문서 6 절의 정의 (`role`·`requires`·`set_by`) 에
  승인 때 해시를 남길 파일 `spec_path` 를 더했다. **기본은 끔** (필드 없음). CT-N·CL 은 끈 채로 등가 조건을 지킨다
  - 검사 : 산출물 과제만, `output_contract: output-contract-v3` 필수 (`spec_approved` 는 v3 필드), `role`·`set_by` 는 서로 다른 시나리오 역할,
    `role` 에 쓰기 도구가 있어야 함, `spec_path` 는 상대 경로이고 감시 파일 (`monitored_paths`)
- 실행 (`experiments/approval_gate.py`, `run_scenario.Workspace`)
  - 승인 전 `role` 의 `write_file`·`replace_in_file` 은 **실행하지 않는다**. 도구 안에서 첫 줄에 막고 예외를 올리면 프레임워크가
    `is_error` 도구 결과로 돌려준다. 파일은 바뀌지 않는다. 다른 역할(기획의 SPEC.md 쓰기 등)은 영향 없음
  - 거절 문구 (사실만) : "Not executed: SPEC.md has not been approved yet (no final report of role reviewer with spec_approved: true).
    No file was changed." — 도구 설명(docstring)은 그대로라 요청의 도구 정의는 바뀌지 않는다
  - v10 최종 보고 요청에 거절 결과와 `is_error` 가 그대로 남는다 (S-31, 테스트)
  - **승인 규칙** (설계 6 절 + 지시) : `set_by` 역할의 **검증된 최종 보고**(`observed_final_report`, 실패 step 의 G0-13 검증 보고 포함 —
    라우터의 DM-44 ③ 과 같은 기준) 에 `spec_approved: true` 가 처음 나온 step 에 승인. 다른 역할의 `true` 는 세지 않는다.
    한 번 난 승인은 유지 (이후 `false` 나 SPEC.md 변경으로 해제하지 않음). 그 step 이 끝난 상태의 `spec_path` sha256 을 기록. 승인은 다음 step 부터 효력
- **연속 중단 카운터·runner_error 와 분리** : 거절은 도구 결과일 뿐 strict 실패가 아니므로 strict 연속 카운터에 들어가지 않고,
  예외가 실행기로 올라가지 않아 `runner_error` 가 되지 않는다. 정체판은 교착(`max_steps` / `guardrail_stop`)으로 끝난다 (테스트)
- step 기록 : 거절된 실행 기록에 `approval_refused: true`. step 은 G0-6 원칙대로 `failed` 로 남기되 사유는 `tool_execution_error` 가 아닌
  `write_refused_before_approval` (다른 도구 오류가 같이 있으면 둘 다). `approval` = `{reported_spec_approved, counted, approved, approved_step,
  refused_writes}` (게이트가 있을 때만)
- **규칙 고지** : 세션 시작 때 모든 역할의 시스템 메시지에 v8 사실 문장 뒤로 **한 문장** — "Approval rule enforced by the harness: write_file and
  replace_in_file calls of role developer are not executed, return an error result and change no file until a final report of role reviewer
  has spec_approved: true (approval of SPEC.md), which then stays in effect for the rest of the session."
  - 반복·지연·거절을 지시하지 않는다 (DM-5, 테스트가 명령형 단어를 검사). 문장 틀은 `approval_gate.NOTICE` 한 곳, 값은 `write_gate` 에서만 오므로
    같은 게이트를 쓰는 정상판·교착판은 같은 문장 (테스트 : 과제 문장이 달라도 같음)
  - 계약 v3 지시문에도 `spec_approved` 의 사실 한 문장 ("Only the spec_approved of role reviewer is read: true from that role approves SPEC.md
    under the approval rule.")
- 기록 : `conditions.write_gate` = 규칙 버전 `write-gate-v1`, 게이트, 고지 문장과 sha256, 거절 문구와 sha256. summary `approval` =
  승인 step (없으면 null), `spec_path`, 승인 때 해시, 거절한 쓰기 수와 step 별 수. 매니페스트 v0.6 `approval` (게이트 없으면 null)

테스트 `tests/test_approval_gate.py` : 스키마 규칙, 고지 문장(모든 역할·한 문장·명령형 없음·같은 게이트면 같은 문장·게이트 없으면 없음),
승인 전 거절·후 실행, 승인 역할만 셈·승인 유지, `replace_in_file` 거절, 최종 요청의 `is_error`, 다른 도구 오류와 구분, 매니페스트.
