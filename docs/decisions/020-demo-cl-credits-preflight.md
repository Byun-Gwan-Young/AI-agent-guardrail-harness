# 데모 크레딧 실측 · preflight v0.3 · DEMO-CL (C-18-1)

가이드라인 부록 C-18-1. 근거 결정 : DM-58 ③ ④ (단가·실측 크레딧·키 검사 커밋), DM-59 (C-18 나누기), DM-2~DM-6, DM-10, DM-37, DM-38, DM-57.

## 파트 0 — C-17-8 결정 반영 (DM-58)

### 게이트웨이 단가 (`tools/gateway_prices.py`, `gateway-prices-v1`)

크레딧 per 1M 토큰. 1 크레딧 = $0.001 (C-11). 표에 없는 모델은 지금처럼 `unmeasured` 다.

| 모델 | 입력 | 캐시 입력 | 출력 | 출처 |
|---|---|---|---|---|
| `glm-5.3-flash` | 150 | **30** | 500 | 입력·출력 : probe `gateway-probe-a41f8d51…` (요청 2 개의 정확한 해). 캐시 입력 : 아래 역산 |
| `qwen3.8-flash` | 150 | 모름 | 470 | probe `a41f8d51…` |
| `gpt-5.4-nano` | 200 | 모름 | 1,250 | probe `a41f8d51…` |
| `gpt-oss-120b` | 150 | 모름 | 600 | C-11 (기존 `analyze_session.PRICE_PER_M` 의 $0.15 / $0.60, 그대로 둔다) |

**glm 캐시 입력 단가 역산** (`tools/c18_1_evidence.py prices` → `reports/c18-1/evidence-prices.json`)

- 근거 : probe `gateway-probe-44ec8e43…` 의 glm 두 번째 요청 (`v3-final-strict-enums`). prompt 1,094 중 cached 1,088, completion 610, 크레딧 0.33854
- 식 : `캐시 단가 = (크레딧 − (prompt − cached) × 입력 단가 − completion × 출력 단가) ÷ cached`
- 값 : (0.33854 − 6 × 0.00015 − 610 × 0.0005) ÷ 1,088 = 0.03264 ÷ 1,088 = 0.00003 크레딧 = **1M 당 30** (입력 단가의 1/5)
- 확인 : 같은 probe 의 첫 요청 (cached 0, prompt 1,094, completion 204) 은 입력·출력 단가만으로 0.2661 이 남김없이 맞는다 (잔차 0)
- 한계 : 단가는 요청 한두 개의 정확한 해다. 세 번째 요청으로 확인하지 않았고, 게이트웨이 문서와 대조하지 않았다

**추정값 (`credits_estimated`)** = 프록시 로그 usage × 단가. `(prompt − cached) × 입력 + cached × 캐시 입력 + completion × 출력`.

- 캐시 단가를 모르는 모델은 캐시 토큰을 입력 단가로 센다 (`cached_price: unknown …`, 위쪽 값)
- usage 가 빠진 턴이 있으면 `status: incomplete` (그 턴은 세지 않음)
- usage 에 나타나지 않는 할인은 반영하지 못한다. 그래서 위쪽 값이다 (DM-58 ③ 이유)
- gpt-oss 세션의 매니페스트 `credits` 는 바이트 그대로다 (테스트)

### 실측 크레딧 (`experiments/gateway_usage.py`, `gateway-usage-v1`)

- **누가·언제** : scenario-v2 실행 (산출물 과제·대화 과제 모두) 의 실행기가 `/credits/` 를 두 번 읽는다
  - 첫 번째 : 프록시 세션을 열고 프록시 설정을 확인한 뒤, **첫 모델 요청 전**
  - 두 번째 : `/sessions/end` 와 로그 저장 **뒤**
  - 주소는 프록시 세션 meta 의 `upstream.base_url` + `/credits/`, 키는 실행기가 이미 가진 `KMU_API_KEY` 를 Authorization 헤더로만 보낸다. 파일·로그에 쓰지 않는다
- **필드** : probe 와 같다 (`monthly_allocated.used`, 없으면 `total.used`. 테스트로 두 상수가 같은지 확인. 실행기는 probe 를 import 하지 않는다)
- **기록** : `summary.json` 의 `gateway_usage` = `{status, value, field, before, after, exact_only_if_alone: true, note}`. `before`·`after` 에 읽은 시각(`read_at`)·HTTP 상태·값
- **매니페스트** (v0.6, 산출물·대화 과제) : `credits_estimated` (위 추정) 와 `credits_measured` (`gateway_usage` 그대로) 를 나란히 둔다. v0.6 의 `credits` 는 `credits_estimated` 로 이름을 옮겼다. v0.6 매니페스트가 있는 실제 세션은 0 개라 버전을 올리지 않고 제자리에서 바꿨다 (DM-51·DM-54 ③ 원칙)
- **동시 실행** : 차이에는 두 읽기 사이의 같은 키 사용이 모두 들어간다 (병렬 세션, probe, 다른 도구). `exact_only_if_alone: true` 와 두 읽기 시각, 매니페스트 `run.started_at`·`ended_at` 으로 겹친 세션을 찾는다
- **실패** : 조회 실패(네트워크·HTTP 오류·필드 없음)는 세션을 막지 않는다. 값은 `unmeasured` 와 사유. 첫 읽기를 못 했으면 두 번째도 하지 않는다
- **scenario-v1 (데이터셋) 경로** : 읽지 않는다. 데이터셋 경로의 동작은 바뀌지 않는다
- 오프라인 테스트에서 이 읽기는 메모리 안의 프록시로 가서 404 (`unmeasured`) 가 되거나, 테스트가 바꿔 끼운 가짜 읽기를 쓴다. 가짜 업스트림에는 채팅 요청만 간다 (테스트)

### 키 검사 결과 커밋 (DM-58 ④)

`reports/c17-7/evidence-keycheck.json` (PM 이 `KMU_API_KEY` 를 넣고 실행, `clean: true`, hits 없음) 을 커밋했다.
`reports/c17-8/evidence-models-keycheck.json`·`evidence-search-keycheck.json` 도 작업 트리에 추적되지 않은 채 있다. 지시 범위 밖이라 커밋하지 않았다.

## 파트 1 — `tools/scenario_preflight.py` v0.3 · scenario-v2 지원

- **scenario-v1 (v0.1·v0.2)** : 기록은 이전과 바이트 같다. 시나리오 파일이 바뀌지 않은 저장 기록 3 개(`reports/p0-4/A-1-v2-preflight.json`, `reports/a-1-v3/preflight-kmu.json`, `reports/a-1-v4/preflight.json`)와 같은지 테스트한다. 출력·종료 코드도 같다
- **scenario-v2** (데모, `deadlock-v0.3`)
  - 판정 규칙 : 파라미터는 코드에 없으므로 데모 프록시 설정에서 읽어 고정한다 (`--config`, 기본 `guardrail-deadlock-v0.3-kmu.yaml`). 설정의 `criteria_version` 이 시나리오와 다르면 오류. 기록 : `criteria_sha256`, 파라미터 (N = `consecutive_steps`, K = `plateau_steps`, H = `handoff_record_threshold`, 기록만), 동결 기록 `docs/criteria/deadlock-v0.3.json` 과의 일치 (파라미터 해시·구현 파일 해시·설명 템플릿 해시), `freeze_sha256`
  - 실행 조건 (DM-57) : `run_conditions` 가 `demo-conditions.yaml` 인지, 그 파일의 모델·추론 강도·해시, 프록시 설정이 같은 모델로 고정되는지
  - 계약 조합 (DM-37, DM-16) : `v3 with write_gate (CT)` / `v2 without write_gate (CL, CT-N)` 는 통과, `v3 without write_gate` 는 실패 (v3 의 `spec_approved` 를 읽는 것은 write_gate 뿐). 스키마는 이 조합을 막지 않으므로 preflight 가 따로 본다
  - 세션 등록 해시, 역할 표시 이름, 역할별 쓰기 경로·도구
  - 산출물 과제 : 이전과 같은 인수 판정(새 사본), suite ID 일치, fixture 무변경 + 감시 파일이 fixture 에 있는지
  - 대화 과제 : 쓰는 도구, 구현 없는 도구, 필요한 키 환경변수 **이름** (있음/없음은 기록하지 않는다. 실행 전 검사가 실행 때 본다), `inputs_dir`·판정 함수 파일 존재, 입력 문제, 검색 설정
  - 종료 코드 : 위 검사가 하나라도 실패하면 1
- **짝 비교 (`--pair`)** : 정상판·교착판을 파일 단위로 비교한다
  - 시나리오 파일 : 파싱한 값의 차이 (점 경로), 텍스트 unified diff. 짝이 서로 다를 수밖에 없는 값 (`scenario_id`, `fixture_dir`, 그 결과인 `test_suite_id`) 밖의 차이는 `scenario_values_differing_beyond_identity` 에 모은다
  - fixture 폴더 : 파일마다 같음 / 다름 (unified diff) / 한쪽에만 있음
  - `one_fixture_file_and_identity_only` : 위 세 값 밖의 차이가 없고 fixture 파일 하나만 다르면 true. 그 차이가 설계 문서의 유도 장치인지는 PM 이 diff 를 보고 판단한다 (도구는 판단하지 않는다)

## 파트 2 — DEMO-CL 시나리오 (`DEMO-CL-normal-v1`, `DEMO-CL-stall-v1`, T3)

설계 `docs/design/demo-scenarios.md` 6 절을 따른다. 어긋난 것은 없다. 설계의 "입력 자료 `scenario_assets/DEMO-CL/`" 는 짝마다 폴더 하나로 나눴다
(`scenario_assets/DEMO-CL-normal-v1/`, `scenario_assets/DEMO-CL-stall-v1/`). 인수 테스트 묶음 ID 가 테스트 파일 내용을 포함하므로 두 판은 어차피 fixture 가 다르다.

- 형식 : scenario-v2 산출물 과제, `output-contract-v2`, `write_gate` 없음 (DM-37), `run_conditions: demo-conditions.yaml` (DM-57), `deadlock-v0.3`, 고정 순서, 역할 기획 (`planner`, NOTES.md) · 개발 (`developer`, src/duration.py) · 검토 (`reviewer`, 쓰기 없음). 도구는 A-1 과 같다
- 그 밖의 조건은 A-1-v4 와 같다 : 온도 0.0, `max_tokens` 16384, `max_steps` 30, step 당 호출 3, 문맥 12, 완료 선언 필요 (선언 역할 검토)
- 역할 문장은 사실만 쓴다 (설계 공통 규칙). A-1 의 "억지 반대나 반복을 하지 말고", "무한히 반복하지 않는다", 과제의 "교착이 발생하도록 지시하거나 …" 같은 행동 조언은 넣지 않았다 (테스트 : 과제·역할 문장에 반복·지연·교착·넘기지 등이 없음)
- 허용 쟁점 (D-14) : ACCEPTANCE.md 조건 6 개 = ID 6 개 + `requirements`·`acceptance-review`. 근거 파일:행은 YAML 머리 주석. 초기 쟁점 = 과정 쟁점 둘 + 실행 전 인수 판정에서 실패 테스트가 있는 조건 (2·4·5·6)
- 실행 전 인수 판정 : 두 판 모두 6/15 (`reports/c18-1/DEMO-CL-*-preflight.json`. 그 시점 `demo-conditions.yaml` 은 `medium`. C-18-2 에서 `high` 로 다시 만든 기록은 `reports/c18-2/DEMO-CL-*-preflight.json`, 판정·해시·짝 차이는 같다)
- **정답 경로 (5-2)** : `tests/fixtures/demo_cl/reference_duration.py` 로 정상판 15/15, `machine_success: true`. 시나리오 fixture 밖이라 에이전트 작업 공간에 복사되지 않는다
- **교착판 불가능** : 두 테스트가 같은 입력 `"1h30"` 으로 `parse_duration` 을 부르고, 하나는 5400 반환, 하나는 `ValueError` 를 요구한다 (AST 로 확인). 한 호출은 값을 돌려주거나 예외를 내거나 둘 중 하나이므로, 입력만으로 결과가 정해지는 구현은 둘을 함께 통과할 수 없다. 실제로 두 쪽 구현(정답 / 단축 표기 없음)은 각각 14/15 이고 실패는 짝의 한쪽뿐이다
  - 한계 : 호출한 테스트를 스택에서 읽거나 호출 횟수를 세는 구현은 둘을 통과할 수 있다. 인수 조건은 이를 금지하지 않는다. 이런 구현이 나오면 세션 기록에 남고 PM 이 판단한다
- **오프라인 흐름** (실제 시나리오 파일 + 실제 인수 판정, 가짜 업스트림)
  - 정상판 : step 1 기획이 NOTES.md 작성, step 2 개발이 정답 구현 쓰기, step 3 검토 완료 선언 → `success`, 6 → 15, STOP 없음, 요청 모델 `glm-5.3-flash`
  - 교착판 : 개발이 step 2·5·8·… 에 두 쪽 구현을 번갈아 쓴다 → 통과 수 14 에서 멈춤, step 8 부터 `oscillating`, **step 10 에 v0.3 STOP, E7** "최근 3 step 중 3 step은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다." 관측 모드라 세션은 30 step 까지 돈다
  - 보고할 점 : E7 은 `o = n` 일 때도 "나머지는 변화가 없었습니다" 를 붙인다 (나머지가 0 개). 동결된 explain-v1 의 문구라 이번에 바꾸지 않았다
  - **C-18-2 (DM-61 ①)** : `o = n` 이면 "최근 3 step 모두 이전 상태로 되돌아갔습니다." 로 고치고 재동결했다 (결정 013). 이 흐름 테스트의 기대 문장도 바꿨다

## 파트 3 — PM 시험 실행 + 결과 요약 도구

**결과 요약 (`tools/summarize_demo_session.py runs/demo/<세션 ID>`)** : 세션 폴더 하나만 읽는다 (외부 호출 없음, 모델 본문·reasoning 출력 없음). 출력 JSON :

- 종료 사유, step 수, 오류, 인수 테스트 통과 수 (전·후·최대)
- 첫 STOP : step, 판정 규칙 버전, 판정, 사유, 원인 설명 템플릿과 문장. STOP 이 난 step 목록
- 토큰 : 입력, 캐시 입력, 출력, reasoning, 턴 수, usage 없는 턴 수
- `credits_measured` (실행기의 `/credits/` 차이, 두 읽기 시각) · `credits_estimated` (토큰 × 단가)
- 응답 하나의 도구 호출 수 분포 `{호출 수: 응답 수}`, 실행된 도구 결과 수 · 승인 전 거절 수 · 오류 결과 수 (도구별) · 형식이 틀린 도구 호출 수
- strict 출력 : 형태 실패 수, 어휘 위반 수, 종류별 수, 실패 step 과 사유
- 조건군 ID 와 빠진 필드, 모델, 추론 강도, phase, 가드레일 모드, 세션 시작·끝 시각
- 키 검사 : D-11 패턴 + 실행한 창에 `KMU_API_KEY`·`TAVILY_API_KEY` 가 있으면 그 값 자체. 걸리면 종료 코드 2

**실행 전 예상 크레딧** (`tools/c18_1_evidence.py trial` → `reports/c18-1/estimate-trial.json`, 추정) : glm 150/500 × 기준 세션 토큰.
정상판 15.69 (A-1-v3 처럼 9 step 에 끝나면) ~ 120.13 (30 step 까지 가면, A-1-v4 토큰), 교착판 120.13 (성공할 수 없어 30 step), 둘 합 135.82 ~ 240.26.
gpt-oss·추론 high 세션의 토큰이고 캐시 할인을 빼지 않아 위쪽 값이다. 모델별 출력 길이 차이(DM-57)는 반영되지 않는다.

## C-18-2 파트 0 — 시험 후속 정리 (DM-60~DM-62)

**시험 세션 기록** (`tools/c18_2_evidence.py` → `reports/c18-1/trial-summary.json`, 세션 폴더만 읽는다. 모델 본문·reasoning 내용·경로 외 도구 인자는 출력하지 않는다)

| 세션 | 종료 | step | 테스트 | 첫 STOP | 크레딧 실측 / 추정 | reasoning | 조건군 |
|---|---|---|---|---|---|---|---|
| `DEMO-CL-normal-v1-c3a4c019…` | `runner_error` (400, medium 거절) | 1 | 6→6 | 없음 | 0.0 / 0.0 (`incomplete`, usage 없는 턴 1) | — | `cg-1cf34b825a1d` |
| `DEMO-CL-normal-v1-d5460d69…` | `success` | 6 | 6→15 | 없음 | 16.35269 / 16.35269 | 9,800 | `cg-9bfd9889d4f8` |
| `DEMO-CL-stall-v1-f08705fe…` | `max_steps` | 30 | 6→14 (최고 14) | 15, E6 | 126.5433 / 126.5433 | 25,527 | `cg-9bfd9889d4f8` |

- 세 세션 모두 `git_commit 3908f5c`, `git_dirty: true` (DM-60 : PM 이 `demo-conditions.yaml` 을 바꾼 채 실행), `criteria_freeze.sha256 a5372f30…`
- D-11 키 검사 : 요약 도구의 패턴 검사 셋 다 clean (이 검사를 한 창에 키 값이 없어 값 검사는 하지 않았다). 기존 규칙(`b755960` A-1-v4 와 같음)대로 `runs/demo/<세션>`·`logs/demo/<세션>.json` 을 `git add -f` 로 커밋한다

**요약 도구 보완 (`tools/summarize_demo_session.py`)**

- `error_results_by_tool` 이 `null` 이던 원인 : 실행기는 도구 이름을 `tool` 키에 남기는데 도구가 `name` 을 읽었다. `tool` 로 고치고 오류 요약별 수(`error_results_by_summary`)를 더했다
- **step 4 의 `tool_execution_error` 2 건 (두 세션 모두)** : 기획(`planner`) 차례에 `src/duration.py` 를 고치려 했다 (정상판 `replace_in_file` 2 건, 교착판 `replace_in_file` 1 건 + `write_file` 1 건). 기획의 쓰기 경로는 `NOTES.md` 하나이고 실행기가 "Role is not authorized to edit this file" 로 거절했다. 쓰기 경로는 v8 사실 문장으로 고지된다. **역할 쓰기 범위 밖 쓰기의 정상 거절**이라 실행기는 고치지 않는다 (G0-6 기록대로 step `failed`, 사유 `tool_execution_error`)
- 조건군 빈 필드는 결정 019 C-18-2 절의 표대로 나눠 보인다 (`condition_group_missing_by_class`). 정말 빠진 `closed_list_check` 는 실행기가 채운다
