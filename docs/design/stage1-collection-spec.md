# Stage 1 — 수집 규격 설계안 (C-12)

- 상태 : **Stage 1 결정 반영 (2026-09-22, S-1~S-19, `metrics-v1`)**. 결정은 7장. 1~6장은 C-12 설계안 원문이며, 결정과 다른 부분은 7장이 우선한다. 지표 정의 확정본은 [metrics-v1.md](metrics-v1.md)
- 기준 커밋 : `3bb37ae`
- 근거 세션 : G0-8 `A-1-v2-b51f67df2fb9402ba15fccb35c3db53e` (Groq, v7, `unclassified` D-24), A-1-v3 `A-1-v3-4a0087756b2641f4b8f9b025c0419f73` (게이트웨이, v8, `valid` D-28)
- 수치 출처 : [stage1_values.py](stage1_values.py) (읽기 전용 스크립트) → [stage1-values.json](stage1-values.json). 이 문서의 숫자는 모두 그 출력이다. **추정** 표시가 없는 수치는 측정값이다
- **두 세션은 선택 근거가 아니다.** 둘 다 정상 세션(인수 테스트 16/16 + 완료 선언)이라 실패 세션이 0 개다. 아래 "두 세션 적용값" 은 정의가 로그 필드로 계산 가능한지 확인하는 용도다. 숫자를 이 두 세션에 맞춰 고르지 않았다

---

## 1. 지표 정의 (G0-9, `metrics-v1` 초안)

공통 규칙 : 지표 정의는 `metrics_version` 으로 고정한다. 판정 근거(정상/실패)는 가드레일 신호(progress 상태, criteria 결정, `open_issue_ids`)와 독립이어야 한다 (3-1, D-4).

### 1-1. 정상 세션 (D-4 잔여)

결정됨 : 쟁점 목록 상태는 쓰지 않는다. 남은 것은 인수 테스트 일부 통과, 완료 선언 없음, `max_steps` 도달의 처리다.

| 선택지 | 정의 | 장점 | 단점 |
|---|---|---|---|
| **N1** | 마지막 step 에서 인수 테스트 전부 통과 **그리고** 선언자(reviewer) 완료 선언 = 실행기 `termination_reason: success` | 실행기 종료 규칙과 같아 해석이 단순. "완료했는데 멈추지 못한" 세션을 실패로 잡는다 | 완료 선언은 모델 출력(`completion_declared`)이다. 테스트는 다 통과했는데 선언만 없는 세션은 실패가 되고, 그 세션의 가상 STOP 이후 토큰은 **절감**으로 집계된다 (종료 실패 탐지로 보면 정당하지만 "정상 작업" 과 다름) |
| **N2** | 마지막 step 에서 인수 테스트 전부 통과 (선언 무관, `max_steps` 도달 포함) | 가장 순수한 기계 판정. 모델 발화에 의존하지 않는다 | 선언 없이 30 step 까지 도는 세션도 정상. 그 세션의 가상 STOP 은 오탐으로 집계 → 종료 실패(termination_failure) 판정이 보존율을 깎는다 |
| **N3** | 통과 비율 ≥ 임계값 (예 : 0.9) | 부분 성공을 살린다 | 임계값이 임의. 시나리오마다 테스트 수가 달라 같은 비율의 의미가 다르다. **권하지 않음** (근거 제시만) |

- 보조 규칙 후보 (N1·N2 공통) : 중간 step 에서 전부 통과했다가 마지막에 회귀한 세션 → 마지막 step 기준 (회귀는 실패). 대안 "한 번이라도 전부 통과" 는 회귀를 숨긴다
- **현재 매니페스트의 `judgement.normal_session` 은 N2 로 계산되고 있다** (`machine_success_at_end`). 실행기 `success` 는 N1 이다. D-4 결정 후 한쪽으로 맞춰야 한다
- 두 세션 적용값 : N1·N2·N3 모두 두 세션 정상 (차이 없음)

### 1-2. 보존율 (D-6 ABSTAIN)

`보존율 = 정상 세션 중 첫 가상 STOP 이 없는 세션 수 / 정상 세션 수`

**판정기에는 ABSTAIN 이라는 결정값이 없다.** `deadlock-v0.2` 의 결정값은 `continue` / `deadlock` / `termination_failure` / `unmeasured` 이다 (`deadlock_policy_v02.py`). 가이드라인의 ABSTAIN 은 `unmeasured`(보류)와 `needs_observation_review`(3 step 연속 누락)에 해당한다.

| 선택지 | unmeasured 처리 | 장점 | 단점 |
|---|---|---|---|
| **A1** | STOP 이 아니므로 "STOP 없음" 으로 센다 | 판정기 정의 그대로 | 관측이 계속 빠진 세션이 보존율을 부풀린다 |
| **A2** | `needs_observation_review=true` 가 한 번이라도 있던 정상 세션은 분모에서 빼고 개수를 따로 보고 | 관측 실패와 판정 성능을 분리 | 제외 규칙이 생긴다. 제외 비율을 반드시 같이 보고해야 한다 |
| **A3** | `needs_observation_review` 세션을 "STOP 있음" 으로 센다 (보수) | 보존율을 과대평가하지 않는다 | 관측 실패(하네스 문제)를 판정기 오탐으로 섞는다 |

- 두 세션 적용값 : `unmeasured` 결정 0 건, `needs_observation_review` 0 건 → 세 선택지 결과 같음
- 참고 (선택 근거 아님) : 두 세션 모두 넣으면 1/2 = 0.5 (G0-8 은 step 6 에서 STOP), D-24 로 G0-8 을 제외하면 1/1

### 1-3. 토큰 절감률 (D-7)

`절감률 = Σ(실패 세션의 첫 가상 STOP 이후 토큰) / Σ(전체 세션 토큰)`

| 선택지 | usage 누락 세션 | 장점 | 단점 |
|---|---|---|---|
| **S1** | 분자·분모 모두에서 제외, 제외 수 보고 | 측정값만 사용 | 누락이 특정 실패 유형(HTTP 400 등)에 몰리면 편향 |
| **S2** | known 소계로 포함, 결과를 "하한" 으로 표기 | 표본 유지 | 분자·분모 모두 과소 → 비율의 방향이 정해지지 않는다 (하한이 아님). **"하한" 표기가 엄밀하지 않다**는 점을 명시해야 함 |
| **S3** | S1 로 주 지표, S2 를 민감도 분석으로 병기 | 둘 다 보인다 | 표 두 개 |

- **손실 지표 병기 (필수 제안)** : 정상 세션의 가상 STOP 이후 토큰은 절감이 아니라 "손실 토큰" 으로 따로 집계한다. G0-8 : known 104,991 토큰 (당시 usage 누락 1 턴 포함 세션)
- 두 세션 적용값 : 실패 세션 0 → 분자 0. 분모 S1 = 87,470 (A-1-v3 만), S2 = 240,824 (known 합)
- 주의 : 실패 세션의 STOP 이후 토큰은 `max_steps` 에 비례한다. 절감률은 `max_steps`(D-31 : 30) 와 묶어서만 보고한다

### 1-4. 탐지 지연 (D-5)

정상 세션에는 교착 시작 시점이 없다. 두 세션 모두 정상이므로 **지연 값은 둘 다 null** 이다.

교착 시작 시점 (사람 라벨 없음) :

| 선택지 | 정의 | 장점 | 단점 |
|---|---|---|---|
| **O1** | 실패 세션에서 인수 테스트 통과 수 또는 산출물 해시가 **마지막으로 바뀐 step + 1** | 가드레일 신호와 독립. 로그 필드(`tests_change_in_step`, `files_changed_in_step`)로 계산됨 | 세션이 끝나야 정해진다(사후 정의라 오프라인 지표로는 문제 없음). 대화만 있는 B 군에는 쓸 수 없다 |
| **O2** | O1 + B 군은 "최종 합의안 구조화 출력의 판정 함수 결과가 마지막으로 바뀐 step + 1" | 군별로 같은 원리 | B 군 판정 함수가 step 마다 돌아야 한다 (현재 없음) |
| **O3** | 보조 LLM 판정자 라벨 (D-34) | 의미 기반 | 주 지표 불가 (6장 D-34 참조) |

- 지연이 음수(STOP 이 시작 시점보다 먼저) → 지연 분포에 넣지 않고 "조기 STOP" 으로 따로 센다 (실패 세션 안의 오탐성 STOP)

**단위 (반드시 먼저 확정)** — 목표 "≤ 2턴" :

| 단위 | 측정값 | R0(`deadlock-v0.2`) 의 구조적 최소 지연 |
|---|---|---|
| step | — | **2 step** (시작 step 부터 stagnant 3 연속이면 시작+2 에서 STOP) |
| 역할 바퀴 (= 역할 수 3 step) | — | 1 바퀴 미만 |
| LLM 호출(턴) | step 당 2.667 (G0-8), 2.556 (A-1-v3) | 약 5 호출 |

- "턴 = LLM 호출" 로 정하면 R0 는 **구조상 목표를 달성할 수 없다**. "턴 = step" 이면 최소값이 목표와 같다. 데이터를 보기 전에 단위를 정해야 하는 이유다

### 1-5. 판정 오버헤드

- 현재 **측정 경로가 없다.** 판정(`calculate_progress` + `evaluate_criteria`)은 LLM 요청 경로가 아니라 `/sessions/observations` 처리 안에서 돈다 (`observation_api.py:45`, `:55`). 시간 기록 없음
- `total_ms - retry_wait_ms` 를 판정 지연으로 쓰면 안 된다 (`docs/S2-experiment-recording.md:42`)
- 설계 선택지
  - **T1** : 관측 레코드에 `judgement_ns` (두 함수 호출 구간, `perf_counter_ns`) 기록. 관측 레코드 필드 추가 → 로그 스키마 버전 변경
  - **T2** : 오프라인 벤치마크 — 수집된 세션 로그를 replay 하며 같은 두 함수를 반복 실행해 분포 산출, 하드웨어·Python 버전 기록
  - T1 은 실제 부하에서의 값, T2 는 재현 가능한 값. 둘 다 둘 수 있다
- observe 모드에서는 판정이 요청 지연에 들어가지 않는다. p99 ≤ 30ms 는 "block 모드로 켰을 때 다음 요청 앞에 붙을 계산 시간" 으로 정의해야 의미가 맞다

---

## 2. 판정 규칙 후보 등록 (D-23 B, D-12)

**파일럿 전에 고정한다. 아래 수치는 구조(역할 수 3, `max_steps`)에서 나온 것이며 두 세션 결과로 고르지 않았다.**

| ID | 규칙 | 파라미터 도출 |
|---|---|---|
| **R0** | `deadlock-v0.2` (주 규칙). 전역 연속 3 step stagnant/oscillating, 같은 역할 비교, grace 2 | 기존 고정값 |
| R1 | 연속 기준 = 역할 1 바퀴 (N = 역할 수 × 1) | 역할 3 개면 N=3 → **R0 와 같다** (엄격한 순환에서). 역할 수가 다른 시나리오(B 군 2 역할 등)에서만 달라진다 |
| **R2** | 연속 기준 = 역할 2 바퀴 (N = 역할 수 × 2 = 6) | "모든 역할이 두 번씩 아무것도 못 바꿈". 30 step = 10 바퀴 중 2 바퀴 |
| **G** | 산출물 지표만 **전역 직전 step** 과 비교, 대화 지표는 같은 역할 비교 유지, N=3 (D-12) | 산출물 변경 1 건이 역할마다 progress 로 잡히는 것 제거 |
| G2 | G + 역할 2 바퀴 | 조합 |

- grace(선언 후 허용)는 모든 후보에서 2 step 그대로. 바꾸면 종료 실패 판정까지 변수가 늘어난다. 바퀴 단위 grace 는 별도 후보로 두지 않는다 (필요하면 PM 이 추가)
- 후보는 **파일럿 전 목록으로 동결**하고, 이후 추가는 "사후 후보" 로 따로 표기한다

### replay 도구 설계

- 입력 : 세션 로그(`logs/<sid>.json` 의 `observations` — 판정 입력이 전부 저장돼 있음), 규칙 레지스트리 파일(`criteria/candidates-v1.json` : ID, 파라미터, 해시)
- 게이트 : 저장된 progress·criteria 를 R0 로 재계산해 **바이트 일치**해야 다른 후보를 계산한다 (기존 `replay_role_progress.py` 의 legacy 게이트와 같은 원칙). 두 세션 모두 일치 확인됨 (`stored_equals_recomputed_v0.2: true`)
- 출력 : 세션 × 후보 → step 별 결정, 첫 STOP step, 레지스트리 해시, 도구 버전. 저장 로그는 수정하지 않는다
- 집계 : 후보별 보존율·절감률 곡선 (metrics-v1 로 계산)

### 두 세션 적용 결과 (참고용, 선택 근거로 쓰지 않는다)

| 후보 | G0-8 첫 STOP | A-1-v3 첫 STOP |
|---|---|---|
| R0 | step 6 | 없음 |
| R1 | step 6 | 없음 |
| R2 | step 9 | 없음 |
| G | step 6 | 없음 |
| G2 | step 9 | 없음 |

- G 는 두 세션에서 progress 상태를 바꾸지 않았다. 산출물 이벤트가 있는 step 은 줄었다 (G0-8 : [14, 15] → [14], A-1-v3 : [5, 6, 7] → [5]). A-1-v3 step 6·7 은 쟁점 종료(대화 지표)로 여전히 progress 다
- G0-8 은 step 4~13 이 10 step 연속 stagnant 라 R2 로도 거짓 교착이 난다

---

## 3. 매니페스트·유효성

### 3-1. 매니페스트 필드 ↔ 실제 로그 필드 (`session-manifest-v0.2`, `tools/analyze_session.py`)

| 매니페스트 | 출처 | 비고 |
|---|---|---|
| `session_id` | 인자, `logs/<sid>.json.session_id` 와 일치 확인 | |
| `scenario.id` / `hash` | `runs/<sid>/scenario.yaml` 의 `scenario_id`, 파일 sha256 | |
| `scenario.version` | 현재 `scenario_id` 를 그대로 씀 | **공백** : YAML `scenario_revision` 을 쓰거나 필드 폐지 |
| `code.git_commit` | 없음 (null) | 3-2 참조 |
| `code.criteria_version` | `log.meta.criteria_version` | |
| `code.progress_version` | `log.meta.criteria_parameters.progress_version` | |
| `code.metrics_version` | 없음 (null) | G0-9 결정 후 |
| `condition.phase` | 인자 (`--phase`) | 실행기가 기록하지 않음 → 사람 입력. **공백** : 실행기 인자로 받아 `conditions.json` 에 기록 |
| `condition.temperature`, `repeat_index` | `conditions.json` `temperature`, `run_index` | |
| `condition.max_steps`, `max_llm_calls_per_step` | `scenario.yaml` `termination` | |
| `condition.max_tokens` | `log.meta.max_tokens` | |
| `condition.context_buffer_messages` | `conditions.json` | |
| `condition.guardrail_mode` | `scenario.yaml` `on_criteria_alert == observe_only` | 프록시 설정 모드와 교차 확인 없음 |
| `condition.runner_protocol`, `reasoning_effort` (v0.2) | `conditions.json` (없으면 요청 본문) | |
| `model.provider` / `upstream` | `log.meta.upstream` | |
| `model.name` | `log.meta.model` | |
| `seed` | `conditions.json` `requested_seed`, `seed_support` | |
| `run.*` | `log.meta.started_at/ended_at`, `summary.json` `termination_reason`, `steps` | |
| `tokens.*` | `log.turns[].prompt_tokens/completion_tokens/tokens` 합산, 누락 턴 수 | 규칙 : 누락 > 0 이면 `total=null` |
| `judgement.before/after` | `summary.json` `tests_passed_before/after`, 마지막 step `acceptance.gate` | |
| `judgement.normal_session` | 마지막 step `gate.machine_success` (= N2) | D-4 결정에 맞춰 변경 필요 |
| `guardrail.virtual_decisions` | `steps.json` `observation.progress.state`, `observation.criteria.decision` | |
| `validity` | 사람 (PM) | |

**v0.3 제안 필드** : `code.git_commit` + `git_dirty`, `code.metrics_version`, `credits`(토큰 × 단가 계산값 + 계산 근거), `replay`(후보 규칙별 첫 STOP, 레지스트리 해시), `validity.evidence`(3-3 자동 점검 결과), `run.parallel_group`(D-33).

### 3-2. `git_commit` 기록 방법

| 선택지 | 방법 | 장단점 |
|---|---|---|
| **C1** | 실행기 시작 시 `git rev-parse HEAD` + `git status --porcelain` 로 커밋과 dirty 여부를 `conditions.json` 에 기록. 프록시도 기동 시 자기 커밋을 `meta` 에 기록 | 단순. 실행기와 프록시가 다른 코드일 수 있다는 점까지 잡는다 |
| C2 | C1 + measure 단계에서는 dirty 면 실행 전 오류 | 섞인 코드로 데이터가 생기는 것을 막는다. verify 에서는 경고만 |
| C3 | C1 + dirty 일 때 추적 파일 diff 의 sha256 기록 | dirty 도 식별 가능. diff 자체는 보관 안 함 |

git 이 없거나 저장소 밖에서 돌면 `null` + 사유.

### 3-3. 유효성 분류 (9장) — 로그 근거와 자동화 범위

| 분류 | 자동 판정 가능한 근거 | 자동화 |
|---|---|---|
| `invalid_provider` | `summary.termination_reason == runner_error` 이고 마지막 턴 `status_code` 가 429(재시도 6 회 소진) 또는 5xx 연속 | **자동** 제안 |
| `invalid_runner` | 격리 실패(`isolation.*` false, `conditions_mixed`), 명세 점검기(4장) 실패 상태로 실행, 실행기 예외로 종료(`runner_error` + 제공자 사유 아님), 미등록 도구로 세션 사망 | **자동** 제안 |
| 경계 : 도구 인자 400 `tool_use_failed` | `http_errors[].code`, `failed_generation` 길이·JSON 해석 위치, 같은 턴 요청 `max_tokens` | **반자동** : completion 이 한도에 근접하거나 `failed_generation` 이 중간에서 끊겼으면 `unclassified` 로 올리고, 아니면 모델 행동(데이터) |
| 경계 : 권한 밖 쓰기 | `tool_executions[].error_summary`, 해당 역할 시스템 메시지의 `Files this role can write:` 유무 | **자동** : 사실이 전달됐으면 모델 행동(A-1-v3 step 4), 없었으면 실행기 쪽(G0-8, D-24) |
| 경계 : `finish_reason: length` | `g0_7.finish_reason_counts` | 반자동 → `unclassified` |
| 크레딧 경로 | 사용자가 `/credits/` 전후로 기록 (로그 밖). probe 는 C-11 에서 필드 버그 수정 | 유효성 근거가 아니라 **비용 기록**. 병렬 실행에서는 전후 차이가 섞이므로 토큰 × 단가 계산값을 세션 비용으로 쓴다 (C-11 에서 16.43025 정확 일치, probe 요청도 일치) |
| `valid` | 위 어느 것도 해당 없음 | 자동 **제안**, 확정은 PM |

---

## 4. 명세 점검기 (linter) 설계

입력은 **시나리오 + 실행기 프로토콜 + 출력 계약** 조합이다. 사실 문장은 YAML 이 아니라 프로토콜이 붙이므로 YAML 만 보면 결함 6·7 을 잡을 수 없다. 모델에게 실제로 갈 시스템 메시지를 실행기 코드(`role_system_message`)로 렌더링해서 검사한다.

| # | 검사 | A-1-v2 × v7 (G0-8 조건) | A-1-v2 × v8 | A-1-v3 × v7 | A-1-v3 × v8 (재검증 조건) |
|---|---|---|---|---|---|
| L1 | 역할마다 호출 예산 문장 | **3 역할 모두 없음 (결함 7)** | 있음 | 없음 | 있음 |
| L2 | 역할마다 쓰기 가능 파일 명시 (없으면 "none") | **3 역할 모두 없음 (결함 6)** | 있음 | 없음 | 있음 |
| L3 | 지시문이 계약에 없는 필드를 요구 (snake_case 토큰 중 계약 필드·도구·경로가 아닌 것) | 없음 | 없음 | 없음 | 없음 |
| L3b | "null 과 이유" 처럼 계약에 없는 이유 필드 요구 | 없음 (C-6 에서 수정됨) | 없음 | 없음 | 없음 |
| L4 | `initial_issue_ids ⊂ allowed_issues`, 모든 허용 ID 에 정의 | 통과 | 통과 | 통과 | 통과 |
| L5 | 모델·criteria·`max_tokens`·온도 명시, `expected_outcome: unknown` | 통과 | 통과 | 통과 | 통과 |

추가 후보 : L6 `max_steps`·호출 수와 예산 문장의 숫자 일치, L7 (v9) `reasoning_effort` 값이 시나리오/조건에서 오는지, L8 프록시 설정 `criteria_version` = 시나리오 `criteria_version`, L9 쓰기 가능 경로가 `monitored_paths` 안에 있는지.

**경계 (검사하지도 제안하지도 않는 것)** : "먼저 편집하라", "다시 읽지 마라", "빨리 합의하라" 같은 전략·행동 문장. 점검기 출력은 누락·모순 목록뿐이고 문장을 생성하지 않는다. 점검기가 실패하면 실행 전 오류 또는 `invalid_runner` 근거가 된다.

위치 : `scenario_checks.py` 는 인수 판정 게이트(15 행)라 목적이 다르다. 새 모듈 `tools/lint_scenario.py` 로 두고 `role_system_message`·`issue_contract` 를 재사용하는 안을 제안한다.

---

## 5. 파일럿 준비

### 5-1. B-6 · C-9 필요 항목 (작성하지 않음)

**공통 공백** : 현재 실행기는 3 역할(planner/developer/reviewer) + 테스트 픽스처가 있는 산출물 시나리오만 받는다 (`run_scenario.py` : "This runner currently supports the approved three-role artifact scenario"). B 군은 **실행기 확장이 먼저**다.

B-6 (대화형, 모순 조건 유지)
- 역할 구성 (2~3), 서버 사양 협상 과제, **의도된 모순 조건 1 개** (B-7 과의 유일한 차이)
- 판정 : 최종 합의안을 구조화 출력(새 계약 필드, 예 : `proposal_values`)으로 받고 **판정 함수**가 조건 충족을 검사. 모순이 있으므로 정상 도달 불가가 설계 의도지만, 라벨은 여전히 사후 판정 함수 결과로 정한다
- 진전 지표 선택 : 산출물 없음 → `progress_source: conversation`. 후보 `open_issues_count`(D-14 : 협상 조건 1 개 = 쟁점 ID 1 개, 과정 쟁점 2 개는 B 군 의미로 재정의 필요), `proposal_value_delta`(progress-v1 에 계산은 있으나 v2 계약에 필드 없음 → 계약 버전 변경)
- 교착 시작 시점 O2 를 쓰려면 판정 함수가 step 마다 돌아야 한다
- 5-5 완료 기준 중 "정답 경로 검증" 은 B-6 에 적용 불가 (모순) → B-7 에서 정답 합의안이 판정 함수를 통과하는지 확인

C-9 (정상 완주, 정당한 반복 검증)
- 반복이 과제상 필요한 이유를 문서화 (예 : 수정마다 테스트 재실행이 필요한 구조)
- 3 역할 산출물형이면 현 실행기로 가능
- 정답 경로 검증, 인수 테스트, D-14 허용 쟁점, `writable_paths`, 5-5 전 항목
- 보존율 측정용이므로 **반복하는 정상 작업이 R0 에서 STOP 을 내는지**가 관찰 대상 — 그러나 시나리오를 STOP 이 안 나게 조정하지 않는다

### 5-2. 크레딧 (파일럿)

측정 : A-1-v3 = 16.43025 크레딧 / 9 step / 23 호출 = step 당 평균 1.826, 최대 3.003 (step 4), 1k 토큰당 0.1878. 판별 probe(`2a31f5fe…`) 요청당 : low 0.172~0.206, high 0.920~0.946.

**추정 (측정 아님)** — A-1-v3 의 step 당 크레딧(평균~최대)을 step 수에 곱함. v9 는 probe 의 high−low 차이(요청당 0.715~0.773)를 매 호출에 더함. probe 는 짧은 계산 문제라 실제 과제의 추론 증가량은 모른다. 문맥 증가는 버퍼 12 메시지로 포화된다고 가정.

| 조건 | 18 step 세션 | 30 step 세션 |
|---|---|---|
| v8 (low, 최종 호출만) | 32.9 ~ 54.1 | 54.8 ~ 90.1 |
| v9 (high, 모든 호출) | 65.7 ~ 95.8 | 109.6 ~ 159.7 |

### 5-3. D-29 전후 파일럿 조건

| | D-29 이전 (A-1-v3 조건) | D-29 이후 (결정됨, C-13) |
|---|---|---|
| 프로토콜 | v8 | v9 (`reasoning_effort` 모든 호출) |
| `reasoning_effort` | low, 도구 없는 최종 호출만 | high, 모든 호출. 적용 근거 = probe (`applied: probe_indicated`) |
| `max_tokens` | 2400 | 16384 |
| `max_steps` | 18 | 30 (D-31) |
| 시나리오 | A-1-v3 | A-1-v4 (B-6·C-9 도 v9 조건으로 작성) |
| 조건군 | A-1-v3 세션은 **다른 조건군** — 파일럿·본 수집과 섞지 않음 | |

---

## 5-4. 규모 설계 (D-30 ~ D-34)

### D-30 반복 수 계산 규칙 (파일럿 전 등록 제안)

필요 정상 세션 수 (정확 이항 단측 95% 상한 ≤ 5%) :

| 정상 세션 오탐 수 | 필요한 정상 세션 수 |
|---|---|
| 0 | 59 (3의 규칙 근사 60) |
| 1 | 93 |
| 2 | 124 |
| 3 | 153 |

규칙 후보 (모두 **정상/실패 기계 판정만** 입력으로 쓴다. 가상 STOP·criteria 결과는 입력에 넣지 않는다) :

- **P1 비례 배분** : 시나리오 s 의 파일럿 정상 비율 p̂ₛ (라플라스 보정 (정상+1)/(n+2)) 로, Σ rₛ·p̂ₛ ≥ 60 과 Σ rₛ·(1−p̂ₛ) ≥ 30 을 만족하는 최소 반복 rₛ 를 시나리오 균등 반복에서 시작해 늘린다. 시나리오당 최소 3 회, 상한 설정
- **P2 단계형** : 1 차로 시나리오당 고정 반복(예 : 5) → 정상/실패 수를 세고 → 부족분만 해당 군 시나리오에 추가. 판정기 결과는 보지 않는다
- 주의 : 파일럿은 온도 0.0(검증 조건)이라 온도 0.3 측정 조건의 정상 비율과 다를 수 있다. P1 의 p̂ 를 측정 조건 첫 회차로 갱신할지 PM 결정
- 금지 : 판정기 성능(오탐 수)을 보고 표본을 늘리거나 멈추는 규칙. 위 표는 "목표 달성에 필요한 크기" 를 보이는 것이지 중간 확인 규칙이 아니다. 오탐이 나와서 늘리는 것을 허용하려면 **사전에** 순차 검정 규칙으로 등록해야 한다

### D-31 `max_steps` 30

- **추정** : 30 step 세션 v9 기준 109.6 ~ 159.7 크레딧 (5-2 표). 호출 상한 30 × 3 = 90 호출
- `grace_steps`(2)·연속 기준(3)은 step 단위라 `max_steps` 와 직접 얽히지 않는다. 호출 예산 문장은 `max_llm_calls_per_step` 만 쓰므로 영향 없음 (C-13 에서 재확인)

### D-32 교차검증 모델 — probe 확인 항목

후보 : 게이트웨이의 Claude Sonnet 5. 사실 확인 전 가정하지 않는다. probe 항목 :
1. `/models/` 의 정확한 모델 id
2. `temperature` 0.0·0.3 수용 여부, 추론 설정과 온도의 동시 사용 가능 여부
3. `reasoning_effort` 수용·변환 여부 (게이트웨이가 다른 파라미터로 바꾸는지), 추론 토큰 보고 필드
4. strict `response_format`(json_schema) 수용과 계약 통과
5. `tools` + `tool_choice: auto` 동작, 도구와 추론 설정 동시 전송
6. `max_tokens` 상한, `finish_reason` 값 체계
7. usage 필드 형태(캐시 토큰 포함)와 토큰당 크레딧 단가 (1 요청 전후 `/credits/`)
8. seed 지원 여부 (지원 표시 없으면 unverified 유지)
9. 속도 제한·지연 (병렬 설계용)

결과로 그 모델에서 가능한 조건을 고정하고, 주력과 **다른 조건군**으로 기록한다.

### D-33 병렬 실행

- 격리 : 세션 키는 `X-Guardrail-Session` 헤더, 작업 폴더는 `runs/<sid>/workspace` (세션별 복사). 한 프록시 프로세스가 여러 세션을 처리하는 구조는 이미 있다. 단, **`GUARDRAIL_CONFIG` 는 프로세스 단위**라 같은 프록시에서 도는 세션은 같은 조건군이어야 한다
- 동시 실행 수 : 게이트웨이 60 초 120 건. A-1-v3 는 23 호출 / 87 초 (low). 병렬 수 k 는 "파일럿에서 잰 세션당 분당 호출 수" 로 120 을 나눈 값보다 작게, 여유분을 두고 사전 등록. 추정으로 정하지 않고 파일럿 실측으로 계산
- 429 : 프록시가 최초 요청 외 최대 6 회 재시도(지수 + jitter). 재시도로 회복되면 세션 유효(`retry_count` 기록), 소진되면 `invalid_provider` → 같은 조건 새 세션 ID 로 재실행(`rerun_of`)
- 재시도 대기는 교착이 아니다. 판정 입력은 step 단위라 대기 시간이 판정에 들어가지 않는다
- 크레딧 : 병렬이면 `/credits/` 전후 차이를 세션에 나눌 수 없다 → 세션 비용 = 토큰 × 단가 계산값(C-11 에서 정확 일치 확인). 배치 전후 `/credits/` 스냅샷으로 합계만 대조
- 같은 시나리오·조건의 세션을 동시에 돌리면 제공자 캐시·부하가 세션 간 독립성에 영향을 줄 수 있다 (캐시 토큰은 A-1-v3 에서 할인 없음 확인). 매니페스트에 `parallel_group` 기록 제안

### D-34 보조 LLM 라벨

| 선택지 | 내용 | 장점 | 단점 |
|---|---|---|---|
| L-0 | 채택 안 함 | 단순, 순환 위험 없음 | 기계 정의(O1)의 타당성 점검 수단이 없다 |
| L-1 | 주력과 다른 모델이 세션 기록(가드레일 결정 **제외**)을 읽고 교착 시작 step 표시. 기계 정의와의 일치도만 보고 | 사람 라벨 대체, 규모 확장 가능 | 판정자 프롬프트가 또 하나의 가정. 판정자 모델의 편향 |
| L-2 | L-1 + 일부 세션 사람 2 인 라벨로 판정자 자체 검증 | 판정자 신뢰도 측정 가능 | 사람 비용 |

공통 조건 : 판정자 입력에서 progress 상태·criteria 결정을 빼야 독립성이 유지된다. 판정자 프롬프트·모델·버전을 수집 전에 고정.

### 시나리오 수 vs 반복 수

| 선택지 | 내용 | 장단점 |
|---|---|---|
| K1 | 11 개 유지, 반복으로 표본 달성 | 작성·검증 노력 최소. 결과가 소수 과제에 좌우될 수 있다 (세션들이 시나리오 안에서 상관) |
| K2 | 시나리오 추가 (예 : A 군 확장), 시나리오당 반복 축소 | 일반화에 유리. 시나리오마다 정답 경로 검증·명세 점검 필요 |
| K3 | 11 개로 파일럿 후, 정상/실패 비율이 한쪽으로 쏠린 군만 시나리오 추가 | 노력 대비 효율. 추가 기준을 사전 등록해야 함 (판정기 결과로 정하지 않는다) |

통계 메모 : 한 시나리오의 반복 세션은 독립이 아니다. 보존율 신뢰구간을 시나리오 단위 클러스터로 보고하는 방식을 metrics-v1 에 넣을지 PM 결정.

---

## 6. Stage 2 도구 목록

| 필요 기능 | 기존 도구 | 공백 |
|---|---|---|
| 7-3 사후 분석, 매니페스트 | `tools/analyze_session.py` | `git_commit` null, `normal_session` 정의가 D-4 와 연결 안 됨, 유효성 자동 제안 없음, `prompt_checks` 휴리스틱이 v8 문장을 못 잡음 |
| 세션 비교 | `tools/compare_sessions.py` | 2 세션 비교만. 데이터셋 집계 없음 |
| 사실 문장 사후 확인 | `tools/check_harness_facts.py` | 실행 **전** 점검기 없음 → `tools/lint_scenario.py` (4장) |
| 실행 전 기록 | `tools/scenario_preflight.py` | 점검기 호출 추가 |
| 제공자 probe | `tools/probe_gateway.py` | D-32 용 모델 중립 변형 |
| replay | `tools/replay_role_progress.py`, `replay_preserved_observations.py` (legacy 게이트 포함) | 다중 규칙 replay + 규칙 레지스트리 (2장) |
| 지표 계산 | 없음 | `tools/compute_metrics.py` (metrics-v1, 후보 규칙별) |
| 반복 수 계획 | 없음 | D-30 규칙 계산기 |
| 병렬 실행 | 없음 | 실행 관리자 (D-33) |
| 판정 시간 | 없음 | T1/T2 (1-5) |
| B 군 | 없음 | 실행기 확장, 판정 함수, 계약 필드 |
| 보조 라벨 | 없음 | D-34 채택 시 |

**`prompt_checks` 처리 방안** — (a) `check_harness_facts.py` 의 문장 표지로 바꾸고 분석 출력에 `analysis_version` 을 추가, 새 버전 결과는 새 파일로 저장(G0-8·A-1-v3 보고서는 덮어쓰지 않고, 재현 테스트는 버전을 고정해 비교) (b) 필드를 제거하고 `check_harness_facts` 결과를 분석에 포함. 둘 다 기존 보고서 재현 테스트의 기대값 처리가 필요하다.

---

## 7. PM 결정 (Stage 1 결정 S-1~S-19, 2026-09-22)

결정 문장은 가이드라인 13장 "Stage 1 결정" 표에 있다. 아래는 각 문장에 해당하는 이 문서의 선택지 기호다. **문장이 기호보다 우선한다.** 문장과 기호가 어긋나거나 문장이 정하지 않은 부분은 "차이·미결정" 열에 적었다.

| # | C-12 질문 | 결정 | 선택 기호 | 차이·미결정 |
|---|---|---|---|---|
| 1 | 정상 세션 (D-4) | S-1 | **N1** | 없음. 매니페스트 `normal_session` 을 N2 → N1 로 바꾸는 작업은 C-14 (S-8) |
| 2 | ABSTAIN·unmeasured (D-6) | S-2 | **A1** + unmeasured·검토 필요 step 비율 상시 보고 | 없음 |
| 3 | usage 누락 (D-7) | S-3 | **S3 (주·보조 순서 반대)** | 이 문서의 S3 는 "S1 주, S2 민감도" 였다. 결정 문장은 **known 토큰 계산(S2 방식, 누락 턴 수 병기)이 주, 누락 세션 제외(S1)가 민감도**다. 문장대로 따른다. "하한" 표기는 쓰지 않는다. 정상 세션 손실 토큰 병기 채택 |
| 4 | 탐지 지연 (D-5) | S-4, S-19 | **O1 (A·C 군) / O2 (B 군)**, 단위 **step**, 역할 바퀴 병기 | "세션 끝까지 회복 없이 이어진 무진전 구간의 첫 step" 은 O1 의 "마지막 변화 step + 1" 과 같은 정의로 해석했다. 무진전 여부는 인수 테스트 통과 수·산출물 해시(B 군은 판정 함수 결과)로만 보고 progress 상태는 쓰지 않는다 (자기 채점 방지). **미결정 : "조기 STOP"(시작 시점보다 먼저 난 STOP) 을 별도로 셀지** — metrics-v1 은 중앙값에서 빼고 개수를 따로 보고하는 것으로 적었다 (PM 확인 필요). S-19 로 목표치 없음 |
| 5 | 판정 오버헤드 | S-5 | **T1** | T2(오프라인 벤치마크)는 채택 안 됨 |
| 6 | 판정 규칙 후보 | S-6 | **R0·R1·R2·G·G2 동결** | 없음 |
| 7 | `git_commit` | S-7 | **C2** | **미결정 : "데이터셋 세션" 의 범위.** 파일럿(Stage 4, 검증 조건 0.0)의 정상/실패 비율이 S-11 반복 수 계산에 쓰이므로 파일럿 세션이 dirty 차단 대상인지 확인 필요 |
| 8 | 매니페스트 v0.3 | S-8 | 3-1 **v0.3 제안 필드 전부** | **미결정 : `scenario.version` 처리** (`scenario_revision` 사용 / 폐지) |
| 9 | 유효성 자동 제안 | S-9 | 3-3 표 **전체** | 없음 |
| 10 | 명세 점검기 | S-10 | **L1~L9 전부**, 데이터셋 세션은 실패 시 실행 전 오류 | 7번과 같은 "데이터셋 세션" 범위 문제. 검증·디버그 세션은 경고로 해석 |
| 11 | 반복 수 규칙 (D-30) | S-11 | **P1** + 시나리오당 상한 20 + 오탐 시 정상 목표 93 / 124 | 문장이 정하지 않은 것 : P1 의 라플라스 보정·시나리오당 최소 3 회 유지 여부, 파일럿(0.0) 비율을 측정 조건(0.3) 첫 회차로 갱신할지, 시나리오 클러스터 보고 여부. 또 오탐 0 건 목표는 D-30 의 3의 규칙 60, 정확 이항은 59 (5-4 표) |
| 12 | 병렬 실행 (D-33) | S-12 | 프록시 1 개 = 조건군 1 개, **동시 3 으로 시작 후 단계적 증가**, 크레딧 = 토큰 × 단가 | 증가 폭·판단 구간(몇 세션 동안 429 없음)은 C-14 에서 등록 필요 |
| 13 | 보조 LLM 라벨 (D-34) | S-13 | **L-0** | 파일럿 후 재검토 |
| 14 | 시나리오 수 | S-14 | **K1** | 없음 |
| 15 | B 군 실행기 확장 | S-15 | **파일럿 범위에 포함** | 계약 필드(`proposal_values` 등) 추가 여부는 C-15 설계에서 |
| 16 | `prompt_checks` | S-16 | **(a) 와 (b) 어느 쪽도 아님 — 버전 분기** | 결정 문장 : v8 이후 세션은 harness-facts 기반 검사, v7 이하는 기존 휴리스틱 유지 (G0-8 재현). (a) 의 "표지 교체" 를 v8+ 에만 적용하는 형태로 해석 |

**C-12 이후 추가 결정 (7장 질문 밖)**

| 결정 | 내용 | 이 문서와의 관계 |
|---|---|---|
| S-17 | 1학기 목표치 4 개 : ① 판정 오버헤드 p99 ≤ 30ms ② 정상 보존율 ≥ 95% ③ 토큰 절감률 ≥ 20% ④ **탐지율 ≥ 80%** | ④ 탐지율(실패 세션 중 가상 STOP 을 낸 비율)은 이 문서 1장에 없던 지표다. metrics-v1 에 추가 |
| S-18 | 절감률 **주 지표는 실패 세션 기준 분모**, 전체 세션 기준은 병기 | 1-3 과 가이드라인 3-4 의 식(전체 세션 분모)은 병기 지표가 됨 |
| S-19 | 탐지 지연은 목표치 없이 step 단위 중앙값 보고 | 1-4 의 단위 논의와 같은 방향 |
