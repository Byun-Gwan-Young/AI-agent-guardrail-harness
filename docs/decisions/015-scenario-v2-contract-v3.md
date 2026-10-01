# 시나리오 v2 · 출력 계약 v3 · T1 관측 필드 (C-17-3)

설계 `docs/design/demo-runner-extension.md` 2·4 절, 작업 단위 `demo-work-plan.md` 17-4. 13 장 DM-26·DM-29·DM-30~DM-35 가 우선한다.
이 단위는 **정의와 검증만** 만든다. 실행기의 T1 차례 진행·라우터·도구는 다음 단위다 (실행기는 scenario-v2 를 실행 전 오류로 거절).
→ C-17-4 부터 scenario-v2 **대화 과제**는 실행한다 (등록 전송·계약 v3·어휘 위반·라우터, `docs/decisions/016`). 산출물 과제는 C-17-5 까지 거절.

## scenario-v2 (`scenario_schema.ScenarioV2`)

- `load_scenario` 는 `schema_version` 으로만 고른다. `scenario-v1` 파일은 이전과 똑같이 `Scenario` 로 검증된다 (A-1 네 파일 테스트)
- 공통 : `task_kind` (`artifact` | `dialogue`), 역할별 `tools` (권한 이름 대신 도구 이름), `turn_order` (`fixed` | `router`),
  `criteria_version: deadlock-v0.3` 고정 (T1 신호는 v0.3 에만 있다, DM-10), `expected_outcome: unknown` 고정 (5-1),
  `allowed_issues` 필수 (출력 계약 v2·v3 는 쟁점 목록이 필요), `progress_metric` 은 T1 지표 이름을 받는다, `token_estimate` 선택
- 역할 `role` 은 한국어 표시 이름이다 (DM-26 등록값). 역할 ID 는 `^[a-z][a-z0-9_-]{0,31}$`
- `dialogue` (T1) 규칙
  - `progress_source: conversation`, 인수 테스트·`fixture_dir`·감시 파일 없음
  - 도구는 `lookup_order`, `read_policy`, `web_search`, `academic_search` 만, 쓰기 경로 없음
  - `judge` 는 `scenario_judges/<이름>.py` (에이전트가 읽는 `inputs_dir` 밖. `inputs_dir` 가 `scenario_judges` 를 가리키면 오류)
  - `status_values` (순서 있는 처리 상태, 각 `{id, label}`) 필수, `terminal_statuses` (순서 밖 종료 상태, 예 `escalated`) 선택. ID 는 둘을 합쳐 유일
  - `deliverable_schema` 필수 (아래 부분집합), `inputs_dir` 필수
  - `adopted_items` 지표를 고르면 `required_adopted_items` 필수 (E5 의 `{required}`, DM-29)
  - `turn_order: router` 는 dialogue 에서만 (DM-19 : CS 만 라우터)
- `artifact` (T2·T3) 규칙 : 산출물 출처와 `fixture_dir`, 인수 테스트(`kind: tests`) 필수, 도구는 파일·테스트 4 종, 쓰기 도구가 없는 역할은
  쓰기 경로 없음, T1 지표·상태·산출물 스키마·판정 함수 필드 없음, 차례는 고정
- 데모 시나리오 파일 자체는 C-18 에서 쓴다. 테스트는 합성 fixture `tests/fixtures/scenario-v2-dialogue.yaml` (`TEST-T1-v2`) 와
  A-1-v4 를 v2 artifact 로 옮긴 사전(dict)만 쓴다

### `deliverable_schema` — JSON 스키마 부분집합 (`json_subset.py`)

- 저장소에 JSON 스키마 라이브러리가 없고 설치는 금지다. 그래서 시나리오가 쓸 수 있는 키워드를 **로컬에서 전부 검증할 수 있는 것**으로 제한한다 :
  `type` (object, array, string, integer, number, boolean 중 하나), `properties`, `required`, `additionalProperties`, `items`, `enum`,
  `minItems`, `maxItems`, `minLength`, `maxLength`, `description`, `title`
- object 는 `additionalProperties: false` 이고 `required` 가 모든 속성을 나열해야 한다 (제공자 strict 모드 규칙과 같다)
- null 허용은 시나리오에 쓰지 않는다. 계약 v3 가 `deliverable` 전체를 `anyOf [스키마, null]` 로 감싼다
- 검사는 시나리오를 읽을 때 (`check_schema`), 값 검증은 최종 보고를 받을 때 (`errors`)

## output-contract-v3 (`experiments/dialogue_contract.py`)

- v2 (`experiments/issue_contract.py`) 와 v1 은 바이트 동일 (`tests/fixtures/c17-3-protected-files.json`). v3 는 별도 모듈에서 v2 계약을
  그대로 불러 v2 필드를 v2 규칙·코드로 검사하고, 아래 필드를 더한다. 실행기 CLI 의 `--output-contract` 선택지는 아직 v1·v2 뿐
- 추가 필드 (모두 required, strict) : `status` (enum = `status_values` 순서 + `terminal_statuses`, 제공자에 보낸다),
  `handoff_to` (역할 ID enum 또는 null), `adopted_items` (문자열 목록 또는 null, **전체 목록**), `deliverable` (부분집합 스키마 또는 null),
  `spec_approved` (bool 또는 null, CT 승인 규칙용)
- 위반 분류 : 형식이 맞는데 닫힌 목록 밖의 값 → `status_not_allowed`, `handoff_to_not_allowed` (D-17 처럼 어휘 위반.
  `VOCABULARY_VIOLATIONS_V3` 에 v2 의 두 코드와 함께 있다. strict 연속 중단에서 빼는 적용은 실행기 T1 단위). 타입·누락·중복·산출물 스키마 불일치는
  일반 계약 위반 (`ValueError`)
- 지시문은 v2 지시문 + 사실만 (상태 목록과 순서, 종료 상태, 역할 ID, 전체 목록이라는 뜻, 산출물 스키마). 전략 조언 단어 검사 테스트
- `report()` 는 v2 와 같은 모양 (`IssueReport` 가 `output-contract-v3` 를 받도록 넓혔다). `contract_sha256` 은 쟁점 목록 해시·상태·역할·산출물 스키마를 묶은 값

## T1 관측 필드 (`progress_schema.py`)

- `Conversation` 에 `status`, `adopted_items` (유일한 비어 있지 않은 한 줄 ID), `handoff_to`. **None 이면 직렬화에서 빠진다** — 이전 관측의
  저장 모양이 그대로다 (테스트)
- `conversation.status_values` 는 관측에 싣지 않는다 (DM-35, 세션 등록 — 파트 2). 관측에 넣으면 스키마 오류
- 관측의 지표 선택은 `ObservedMetrics` (v1 이름 + `status_advance`, `adopted_items`, `new_issue_ids`, 이름 중복 금지). scenario-v1 의
  `Metrics` 는 v1 이름만 받는다 (그대로)
- 관측 API : T1 지표나 T1 필드가 있는 관측은 그 세션의 판정이 progress-v3 (deadlock-v0.3) 일 때만 받는다. 아니면 422 —
  이전에도 스키마 오류 422 였으므로 v0.1·v0.2 세션의 동작은 같다

## 세션 등록 (DM-26 · DM-29 · DM-35, C-17-3 파트 2)

- 세션 시작 때 한 번 : `POST /sessions` 본문 `{"registration": {...}}`. 본문이 없으면 이전과 같다 (응답도 `{"session_id"}` 그대로).
  등록이 있으면 응답에 `"registered": true`, 프록시 세션 메타 `registration` 에 저장하고 바꾸지 않는다
- 형식 `session-registration-v1` (`progress_schema.SessionRegistration`) : `role_labels` (역할 ID → 표시 이름), `status_values`
  (순서 있는 `{id, label}`), `terminal_statuses`, `required_adopted_items` (E5), `progress_source`, `progress_metric` (고른 지표).
  `status_advance` 를 고르면 상태 순서 필수
- **deadlock-v0.3 프록시에서만** 받는다. v0.1·v0.2 프록시는 422 (데이터셋 경로는 그대로)
- 시나리오에서 만드는 함수 `scenario_schema.registration_for(scenario_v2)` — 역할 `role`, 상태·종료 상태 이름, `required_adopted_items`,
  지표 선택을 옮긴다. 실행기가 이것을 보내는 것은 실행기 T1 단위 (실행기는 아직 scenario-v2 를 실행하지 않는다)
- 관측 API : 등록된 세션의 관측은 `progress_source`·`progress_metric` 이 등록과 같아야 한다 (아니면 422). 설명 문장이 고른 지표를
  나열하므로(DM-31) 판정에 쓰인 지표와 등록 지표가 어긋나지 않게 한다
- 판정·설명이 등록을 읽는 방식은 `docs/decisions/013` "C-17-3 파트 2 재동결" 절
- 테스트 `tests/test_session_registration.py` : 등록 모델·시나리오 변환, 잘못된 등록, API 저장·v0.3 전용·본문 형식, 등록과 다른 지표 선택 거절,
  등록된 상태 순서로 `status_advance` 판정, 가짜 T1 관측으로 E1-T1·E5·E6 문장이 등록된 한국어 이름으로 나옴, 등록 없을 때 ID·"(측정 안 됨)"
