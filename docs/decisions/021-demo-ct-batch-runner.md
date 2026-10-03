# DEMO-CT · DEMO-CT-N · 배치 실행기 (C-18-2)

- 상태 : C-18-2 구현 기록. 파트 0 (시험 후속 정리) 은 결정 013·019·020 에 적었다
- 근거 : 가이드라인 13 장 DM-5·DM-6·DM-16·DM-17·DM-37·DM-48·DM-52·DM-60~DM-63, 설계 `docs/design/demo-scenarios.md` 4·5 절

## 파트 1 — DEMO-CT (T2) 정상판·교착판, DEMO-CT-N

### 공통

- scenario-v2 산출물 과제, `run_conditions: demo-conditions.yaml` (glm-5.3-flash, high), `deadlock-v0.3`, 고정 순서, `max_steps` 30, step 당 호출 3, 온도 0.0, `max_tokens` 16384, 문맥 12
- 역할 3 개 기획(`planner`) · 개발(`developer`) · 검토(`reviewer`, CT) / 리뷰(`reviewer`, CT-N 은 A-1-v4 그대로). 한국어 표시 이름은 세션 등록으로 보낸다 (DM-26)

### DEMO-CT (`DEMO-CT-normal-v1`, `DEMO-CT-stall-v1`)

- 계약 `output-contract-v3` + `write_gate {role: developer, requires: spec_approved, set_by: reviewer, spec_path: SPEC.md}` (DM-16, DM-37, DM-48). 승인 규칙은 `experiments/approval_gate.py` 그대로 (검토 역할의 승인만, 한 번 나면 유지, 승인 step 과 SPEC.md 해시 기록)
- 승인 고지 문장 (정상판·교착판 같음, 모든 역할의 시스템 메시지) :
  > Approval rule enforced by the harness: write_file and replace_in_file calls of role developer are not executed, return an error result and change no file until a final report of role reviewer has spec_approved: true (approval of SPEC.md), which then stays in effect for the rest of the session.
- 승인 전 쓰기의 도구 결과 : "Not executed: SPEC.md has not been approved yet (no final report of role reviewer with spec_approved: true). No file was changed." → step `failed`, 사유 `write_refused_before_approval` (연속 중단·runner_error 에 넣지 않음, DM-48 ②)
- 자산 `scenario_assets/DEMO-CT-{normal,stall}-v1/` : `src/task_query.py`(시작 구현)·`acceptance_runner.py`·정상판 `tests/test_task_query.py` 는 A-1 과 바이트 같다
- **정상판 = 명확판** : A-1 의 재량 영역(구현 단계, 안내 문구, 범위)을 SPEC.md 에 확정 문장으로 미리 채웠다. ACCEPTANCE.md 의 기능 조건 1~6 은 A-1 과 같고, 끝 문단의 "기획의 재량은 … '애매한 사용자 요청'을 처리하되 …" 를 "구현 단계·안내 문구·범위는 SPEC.md에 정해져 있다. SPEC.md는 위 요구사항을 바꾸지 않는다." 로 바꿨다. "숨겨진 상충 조건은 없다" 문장은 교착판에서 사실이 아니게 되므로 두 판 모두에서 뺐다
- **교착판** = 정상판 + ACCEPTANCE.md 조건 7 "query는 대소문자를 구분해 제목 또는 설명에 정확히 그대로 들어 있는 부분 문자열만 찾는다." + 인수 테스트 `test_case_sensitive_search` 하나
  - 조건 2 (casefold) 와 배타 : `test_title_search` 와 `test_case_sensitive_search` 가 같은 항목·같은 호출 `select_tasks([a, b], query="alpha")` 에 각각 `[a]` 와 `[]` 를 요구한다 (AST 로 확인). 입력만으로 결과가 정해지는 구현은 둘을 함께 통과할 수 없다
  - 양쪽 모두 도달 가능하다 : 정답 구현 16/17 (실패 `test_case_sensitive_search` 만), 대소문자 구분 구현 13/17 (`test_title_search` 등 casefold 쪽 4 건 실패). 최고 16/17
  - D-14 로 따라 붙는 차이 : 허용 쟁점 `case-sensitive-search` (조건 7), 초기 쟁점에 그 ID, `expected_test_count` 16 → 17, 그리고 신원 값(ID, `fixture_dir`, `test_suite_id`). 시나리오 텍스트 차이는 이 12 줄뿐이다 (`--pair`, `scenario_values_differing_beyond_identity` = `allowed_issues`·`initial_issue_ids`·`expected_test_count`). CL 처럼 "파일 하나 + 신원만" 은 아니다 (`one_fixture_file_and_identity_only: false`) — 유도 장치가 테스트 입력 하나가 아니라 인수 조건 한 항목이기 때문이다
- 허용 쟁점 (D-14) : 조건 1~6 은 A-1-v4 와 같은 ID·정의. 과정 쟁점 `requirements` 는 정의를 CT 에 맞춰 "SPEC.md 의 기획 결정(구현 단계, 안내 문구, 범위)이 인수 조건과 맞는지 아직 확인·승인되지 않았다." 로 했다 (SPEC.md 가 미리 채워져 있어 A-1 의 "아직 결정·기록되지 않았다" 는 사실이 아니다). 근거 파일:행은 YAML 머리 주석
- 초기 쟁점 : 과정 쟁점 둘 + 실행 전 인수 판정에서 실패 테스트가 있는 조건. 정상판 조건 1·2·3·4·5 (조건 6 은 시작 구현에서 통과), 교착판은 여기에 조건 7
- 역할 문장은 사실만 쓴다 (DM-5, 설계 공통 규칙). A-1 의 "억지 반대나 반복을 하지 말고", "무한히 반복하지 않는다", 과제의 "교착이 발생하도록 지시하거나 상충하는 요구를 추가하지 마세요" 는 넣지 않았다 (테스트 : 과제·역할 문장에 반복·지연·교착·넘기지·상충 없음). 검토 역할 문장에 "SPEC.md가 인수 조건과 맞는지 판단해 spec_approved로 보고한다" 를 넣었다 (역할 설명이고, 계약 v3 지시문이 같은 필드를 이미 알린다)
- 과제 문장 마지막 줄 "개발 담당은 검토 담당이 SPEC.md를 승인한 뒤에 src/task_query.py를 편집합니다." 는 설계 4 절의 절차 문장이다. 실행기 고지 문장과 같은 사실이고 두 판에 같다
- 실행 전 인수 판정 : 정상판 7/16, 교착판 7/17 (`reports/c18-2/DEMO-CT-*-preflight.json`)
- **정답 경로 (5-2)** : 시작 SPEC.md 를 그대로 승인하고 `tests/fixtures/demo_ct/reference_task_query.py` 로 정상판 16/16, `machine_success: true`. 정답 SPEC 은 시작 SPEC.md 그대로다. 정답 파일은 시나리오 fixture 밖이라 에이전트 작업 공간에 복사되지 않는다

### DEMO-CT-N (`DEMO-CT-N-v1`)

- C-17-5 등가 fixture `tests/fixtures/scenario-v2-artifact.yaml` 를 바탕으로, 차이는 `scenario_id`, 머리 주석, 그리고 `model`·`reasoning_effort`·`reasoning_effort_evidence` 대신 `run_conditions: demo-conditions.yaml` 뿐이다 (테스트)
- A-1-v4 와 파일 단위로 같은 것 : 과제·제목·역할(ID·이름·쓰기 경로·시스템 메시지)·허용 쟁점·초기 쟁점·인수 기준·종료 조건·지표·감시 경로·`fixture_dir` (`scenario_assets/A-1` 그 자체). A-1-v4 의 과제 문장("교착이 발생하도록 지시하거나 …")도 그대로다 (DM-17)
- 업스트림 요청 : 같은 가짜 응답으로 등가 fixture 실행과 비교하면 12 건 모두 `.model` 만 다르다 (`gpt-oss-120b` → `glm-5.3-flash`). 등가 fixture 실행은 A-1-v4 scenario-v1 실행과 바이트 같다 (C-17-5). 추론 강도는 둘 다 `high`
- **조건군이 다르다** : A-1-v4 재검증 세션(`A-1-v4-e174aafe…`)은 gpt-oss-120b · 프로토콜 v9 · `deadlock-v0.2` · verify phase 다. DEMO-CT-N 은 glm-5.3-flash · v10 · `deadlock-v0.3` · demo phase 다. 두 세션의 결과를 한 표에 둘 때는 조건군이 다르다고 적는다
- 실행 전 인수 판정 7/16. 차단 실행은 없다 (DM-6, 본 실행 계획에서 제외)

### 오프라인 흐름 (실제 시나리오 파일 + 실제 인수 판정, 가짜 업스트림)

- CT 정상판 : step 2 개발의 승인 전 쓰기 거절 (`write_refused_before_approval`) → step 3 검토 승인 → step 5 정답 구현 쓰기 → step 6 검토 완료 선언 → `success`, 7 → 16, STOP 없음, 승인 step 3, 거절 1
- CT 교착판 (관측) : 승인이 없고 개발이 차례마다 쓰기를 시도해 10 번 거절 → 파일·테스트 불변, **첫 v0.3 STOP step 6, E1** "최근 3 step 동안 기획·개발·검토 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/17." 종료 `max_steps` (30), `runner_error` 아님
  - step 1 에 열린 쟁점 수가 8 → 1 로 바뀌어 진전이고(가짜 보고), 그 뒤로 변화가 없다
- CT 교착판 (차단) : step 6 STOP 다음 요청(step 7)이 403 → 종료 `guardrail_stop`, 7 step
- CT-N : 위 요청 비교 (A-1-v4 와 같은 경로)
