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

## 파트 2 — 배치 실행기 (DM-63) `tools/run_batch.py`

**실행 계획 파일** (`batch_plans/*.yaml`, `demo-batch-plan-v1`) : 항목마다 `scenario` (`scenarios/<ID>.yaml`), `mode` (`observe` / `block`), `repeats` (반복 번호 목록), 선택 `one_at_a_time`. 세션 하나 = (시나리오 ID, 모드, 반복 번호), 키 `<ID>:<mode>:<repeat>`. 같은 키 두 번, 0 이하 반복, 다른 모드, `scenarios/` 밖 경로는 읽을 때 거절한다

| 계획 | 파일 | 세션 |
|---|---|---|
| 본 실행 | `batch_plans/demo-main-v1.yaml` (`demo-main-v1`) | 관측 11 × 5 = 55 + 차단 교착판 5 × 3 = 15 (CT-N 차단 없음) = 70. CS·MR·LR 파일은 C-18-3 에서 생긴다 (그 전에는 그 항목이 든 레인이 실행 전에 멈춘다) |
| C-18-2 시험 | `batch_plans/demo-trial-c18-2.yaml` (`demo-trial-c18-2`) | CT 정상판·교착판·CT-N 관측 각 1 회 = 3 |

**레인** (`run --lane k --lanes n`) : 창 하나가 레인 하나, 레인 안에서는 계획 순서대로 한 세션씩.
- `one_at_a_time: true` 항목(LR, `academic_search`)은 레인이 2 개 이상이면 **마지막 레인에 모두** 들어가고 그 레인은 LR 만 돈다 (DM-52 ④). 나머지 항목은 남은 레인에 계획 순서대로 돌아가며 나눈다. 레인이 1 개면 그 레인이 전부 돈다
- 본 실행 레인 4 개 : 19 · 19 · 19 · 13 (LR 13 = 관측 10 + 차단 3). 레인 5 개 : 15 · 14 · 14 · 14 · 13
- 레인을 시작할 때 그 레인의 시나리오 파일이 모두 있는지, ID 가 파일 이름과 같은지, `one_at_a_time` 이 `academic_search` 유무와 정확히 맞는지 본다. 어긋나면 레인이 멈춘다

**키** : 그 창의 `KMU_API_KEY` (그 레인에 `web_search` 시나리오가 있으면 `TAVILY_API_KEY` 도) 가 있는지만 본다. 없으면 변수 이름만 알리고 멈춘다. 키 값은 출력·기록하지 않는다 (DM-53). `--account-label A` 는 실행기 `--account-label` 로 넘어가 `conditions.json` 과 매니페스트에 남는다

**모드 확인** : 세션마다 시작 전에 대상 프록시의 `GET /conditions` (이번에 추가, 업스트림 호출 없음, 키 없음 — 판정 규칙 버전·파라미터 해시·v0.3 동결 해시·모드·고정 모델·설정 파일 이름·업스트림 호스트) 를 읽어 다음이 모두 맞아야 실행한다. 하나라도 다르면 **그 레인을 멈춘다**
- 프록시 모드 = 항목 모드 (관측 `--observe-proxy`, 기본 `:8000` / 차단 `--block-proxy`, 기본 `:8001` — 두 프록시를 포트를 나눠 동시에 띄운다)
- 판정 규칙 버전 = 시나리오의 `criteria_version`
- 프록시의 `deadlock-v0.3` 동결 해시 = 이 체크아웃의 동결 해시 (재동결 뒤 프록시를 다시 띄우지 않은 경우를 잡는다)
- 고정 모델 = `demo-conditions.yaml` 의 모델, 그리고 프록시가 읽은 그 파일의 해시 = 지금 파일의 해시
- 프록시에 닿지 않으면 멈춘다

**이어 하기** : 끝난 항목은 `runs/demo/*/conditions.json` 의 `batch` (`plan_id`, `item`) 로 찾는다 (레인 기록이 아니라 세션 폴더가 기준이라 레인 수를 바꿔도 다시 돌지 않는다).
- `done` = 그 항목의 세션 중 `runner_error` 가 아닌 사유로 끝난 것이 있음 → 건너뜀
- `failed` = 마지막 세션이 `runner_error` / `interrupted` = 마지막 세션에 `summary.json` 이 없음 (창을 닫은 경우 등) → **자동으로 다시 돌리지 않고 건너뛴다**. PM 이 `--rerun-failed` 를 주면 그 레인의 실패 항목만 다시 돌고 새 세션의 `batch.rerun_of` 에 이전 세션 ID 를 남긴다 (9 장 재실행 규칙)
- `pending` = 세션 없음

**멈춤** : 한 레인에서 `runner_error` 가 **2 번 연속**이면 그 레인을 멈추고 이유와 마지막 항목·세션을 출력한다 (사이에 다른 결과가 있으면 다시 0). 실행기 출력이 세션 ID 를 내지 못했거나 `summary.json` 이 없으면 `runner_error` 로 센다. 키 검사에서 키가 나오면 멈춘다

**세션 기록** : 세션마다 끝나면 이 창에서 `tools/summarize_demo_session.py` 를 돌려 (이 창의 키 값으로 키 검사) `runs/demo-batches/<plan_id>/lane-<k>-of-<n>.jsonl` 에 한 줄 (항목, 세션 ID, 종료 사유, step, 테스트, 첫 STOP step·템플릿, 실측·추정 크레딧, 조건군, 모델, 계정 표시, 키 검사). 실행기 출력은 같은 폴더 `.log` 로

**진행 확인** : `run_batch.py status --plan … --lanes n` → 레인별 계획·`done`·`failed`·`interrupted`·`pending` 수, 종료 사유별 세션 수, 실패·중단·남은 항목 목록, 계획에 없는 항목으로 기록된 세션

**실행기 쪽 변경**
- `experiments/run_scenario.py` `--account-label` (영문·숫자·`_`·`-` 1~32 자), `--batch-item` (배치 실행기가 넣는 JSON, 키 `plan_id`·`plan_sha256`·`item`·`mode`·`repeat`·`lane`·`lanes`·`rerun_of`, `repeat` = `--run-index`). **scenario-v2 (데모) 실행만** 받고 `conditions.json` 에 `account_label`·`batch` 로 남긴다 (값이 없으면 null). scenario-v1 은 두 옵션을 거절하고 `conditions.json` 도 그대로다
- 매니페스트 **`session-manifest-v0.7`** = v0.6 + `run.account_label`, `run.batch`. `conditions.json` 에 `account_label` 키가 있는 세션만 (C-18-1 시험 세션은 v0.6 그대로). v0.6 매니페스트를 가질 실제 세션이 생겼으므로(C-18-1) 제자리 변경이 아니라 버전을 올렸다. v0.6 을 기대하던 테스트 4 개를 v0.7 로 바꿨다
- 프록시 `GET /conditions` (위)

**오프라인 테스트** (`tests/test_c18_2_part2.py`) : 계획 읽기·거절, 레인 나누기·LR 레인, `one_at_a_time` 불일치 멈춤, 이어 하기 (레인 수를 바꿔도), 멈춘 레인 다시 켜기, 실패 항목 건너뛰기와 `--rerun-failed`, 연속 오류 멈춤과 초기화, 모드·규칙·동결·모델·조건 파일 불일치 멈춤, 프록시 없음, 키 없음, 키 검사 걸림, 명령 내용 (계약·프록시·반복·계정, 키 값 없음), 실행기 옵션 검사, 프록시 `GET /conditions`, 그리고 **실제 실행기 + 실제 관측·차단 프록시 + 가짜 업스트림으로 레인 하나** (CT 정상판 관측 `success` 6 step, CT 교착판 차단 `guardrail_stop` 7 step, 매니페스트 v0.7, 두 번째 실행은 아무것도 돌리지 않음)

## 파트 3 — 시험 실행 예상 크레딧 (추정)

`tools/c18_2_evidence.py trial` → `reports/c18-2/estimate-trial.json`. C-18-1 실측 두 세션 (glm-5.3-flash, high) 을 기준으로 한다 : 짧은 성공 `d5460d69…` 6 step 16.35269, 30 step `f08705fe…` 126.5433.

| 항목 | 기준 | 하한 | 상한 |
|---|---|---|---|
| `DEMO-CT-normal-v1:observe:1` | 짧은 성공 ~ 30 step | 16.35269 | 126.5433 |
| `DEMO-CT-stall-v1:observe:1` | 성공할 수 없어 30 step (산출물 과제에는 escalated 가 없다) | 126.5433 | 126.5433 |
| `DEMO-CT-N-v1:observe:1` | 짧은 성공 ~ 30 step | 16.35269 | 126.5433 |
| 합 | | 159.24868 | 379.6299 |

한계 : 기준이 CL(T3) 한 세션씩이다. CT·CT-N 은 과제가 다르고 SPEC·승인 차례가 있어 길이·토큰이 다르다. `runner_error` 로 일찍 끝나면 하한보다 적다
