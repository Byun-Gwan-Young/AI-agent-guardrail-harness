# 모델 실행 조건 · 조건군 · 게이트웨이 probe 후속 (C-17-7)

가이드라인 부록 C 로드맵의 C-17-7 (DM-25 추가분). 근거 결정 : DM-25 (데모·데이터셋 모두 `gpt-oss-120b`), D-32 (상용 모델 교차검증은
주력과 다른 조건군), S-12 (프록시 1 개 = 조건군 1 개), DM-20·DM-40 (닫힌 목록 검사 방식은 조건군 안에서 한 값), D-25 (실행 조건은 명시).
`docs/design/demo-work-plan.md` 의 17-7 행(CT 승인 게이트)은 C-17-5 에서 끝났고, 이 문서의 범위는 가이드라인 로드맵의 C-17-7 이다.

## 파트 1 — 모델을 실행 조건으로 받기 (`model-run-condition-v1`)

**동작** (`experiments/run_scenario.py` `run_model`, 산출물 경로와 대화 과제 경로가 같은 함수를 쓴다)

- `--model <ID>` 가 있으면 그 모델을 보낸다. 없으면 시나리오의 `model` 을 보낸다. 실행기 코드에는 모델 ID 가 없다
- 빈 값, 앞뒤 공백이 있는 값은 실행 전 오류 (오타로 다른 조건군이 생기지 않게)
- `--model` 이 없으면 업스트림 요청은 바이트 그대로다 (C-17-4 scenario-v1 요청 12 건 비교 테스트 유지)
- `--model` 이 있으면 요청 본문의 차이는 `model` 필드뿐이다 (테스트 : A-1-v4 오프라인 실행 12 요청의 JSON 경로 차이 = `.model`)
- `conditions.json` 의 `model` : `{rule, name, source: scenario | run_condition, scenario_model}`. 시나리오 사본(`scenario.model`)은 그대로 남는다
- 시나리오 파일 해시는 바뀌지 않는다. 모델이 다른 실행은 **조건군**으로 구분한다 (아래)

**하지 않은 것** : `--model` 필수화(D-25 처럼), `--dataset-run` 에서 시나리오와 다른 모델 거절, 모델별 단가(`analyze_session.PRICE_PER_M`) 추가.
셋 다 PM 결정 사항으로 보고한다. 단가가 없는 모델의 세션 크레딧은 지금처럼 `unmeasured` 로 나온다.
(DM-54 : `--model` 선택 유지, `--dataset-run` 의 다른 모델 거절은 C-17-8 에서 구현. 단가 추가는 아직 결정 없음)

## 파트 1 — 매니페스트 조건군 (`condition-group-v1`)

`tools/analyze_session.py` `condition_group`. 매니페스트 `condition.group` = `{rule, id, sha256, fields, missing_fields}`.
`id` = `cg-` + `fields` 정규 JSON(키 정렬, 공백 없음)의 SHA-256 앞 12 자리. 같은 조건군의 세션만 함께 센다.

| 필드 | 출처 | 근거 |
|---|---|---|
| `model` | 프록시 세션 meta (실제로 보낸 모델) | D-32 |
| `provider_host`, `proxy_config_file` | 프록시 meta `upstream` | D-27, S-12 (관측·차단 프록시가 다른 조건군) |
| `criteria_version`, `criteria_sha256` | 프록시 meta | DM-33 (재동결하면 다른 조건군) |
| `guardrail_mode` | 프록시 meta | DM-7 |
| `phase` | conditions | DM-2 |
| `runner_protocol`, `collection_policy`, `output_contract_version` | conditions | D-25 |
| `dialogue_flow`, `closed_list_check` | conditions (대화 과제만, 아니면 null) | DM-47, DM-40 |
| `temperature`, `max_tokens`, `max_steps`, `max_llm_calls_per_step`, `context_buffer_messages`, `requested_seed` | conditions·meta·시나리오 | 6 장 실험 조건 |
| `reasoning_effort` (`requested`, `sent_on`) | conditions | D-29. `applied` 는 근거 기록이라 넣지 않는다 |

- 넣지 않은 것 : 시나리오 ID·해시(한 조건군에 여러 시나리오), 실행 회차, 코드 커밋, `dataset_run`
- 매니페스트 `model` 에 `source`·`scenario_model`·`runner_model`·`runner_matches_proxy` 를 더한다
- **제자리 추가** : v0.3 이상 매니페스트(`git_state_status` 를 기록한 실행기의 세션)에 버전 번호 없이 넣었다.
  그런 세션은 아직 0 개다 (`runs/` 의 세 세션은 v7~v9, 실행기 Git 기록 이전). S-31·DM-28·DM-51 과 같은 원칙

## 파트 2 — gpt-oss strict 스키마 probe 변형 (DM-20, DM-40)

`tools/probe_gateway.py --with-v3-strict --scenario <scenario-v2 대화 과제>`. PM 이 실행한다 (코딩 에이전트는 오프라인 테스트만).

- 대화 과제의 **최종 보고 요청**을 두 번 보낸다. 실행기가 보낼 수 있는 두 모양이다 (`dialogue_runner.SentContract`)
  - `v3-final-strict-enums` : 닫힌 목록(`status`, `handoff_to`, 산출물 스키마의 enum)을 strict 스키마에 넣는다 = `provider_strict`
  - `v3-final-strict-no-enums` : 같은 스키마에서 enum 만 뺀다 = `after_receipt` (현재 기본값, DM-40)
- 두 요청의 차이는 `response_format` 안의 enum 뿐이다 (테스트). 시스템 문구·스키마·`reasoning_effort`·온도·`max_tokens` 는
  실행기의 실제 최종 요청과 같다 (테스트 : 오프라인 T1 실행의 최종 요청과 필드별 비교). 관측 기록은 과제·초기 쟁점만 넣는다 (v2 최종 변형과 같은 방식)
- 응답은 두 모드 모두 **v3 계약 전체**(닫힌 목록 포함)로 검사한다. 결과 `closed_list_comparison` 에 모드별 HTTP 상태·오류 문구·
  `finish_reason`·계약 통과 여부를 나란히 둔다. 모델을 `--model` 로 주면 모델별로 같은 비교를 낸다
- 지금 있는 대화 과제 시나리오는 합성 fixture `tests/fixtures/scenario-v2-dialogue.yaml` (TEST-T1-v2) 뿐이다. 데모 시나리오(C-18)와
  상태 목록·역할이 다르지만, 확인하려는 것은 게이트웨이가 strict 스키마의 `enum` 키워드를 받는지다
- 판단(“게이트웨이가 strict 스키마를 지원하면 사용”)은 PM 이 한다 (DM-20, DM-40). 한 모드당 요청 1 회라 신뢰성은 확인하지 않는다

**오류 본문 읽기 수정** : 게이트웨이의 오류 본문은 OpenAI 모양(`{"error": {...}}`)이 아니라 `{"detail": {"code", "message"}}` 일 수 있다.
2026-09-29 probe (`gateway-probe-9d2b2053…`) 의 HTTP 400 두 건이 이 모양이어서 `error_message` 가 null 로 남았다. `error_text` 가 두 모양을 모두 읽는다.
기존 결과 파일은 고치지 않는다 (원인 기록은 파트 3).

## 파트 3 — probe `gateway-probe-9d2b2053…` 기록 (DM-25)

값은 `tools/c17_7_evidence.py` → `reports/c17-7/evidence.json` (파일만 읽는다. 네트워크 없음, 모델 reasoning 문장은 읽지 않는다).

**gpt-6 계열 HTTP 400 원인 (재시도 없음)**

| 모델 | 짧은 요청 (도구·`reasoning_effort` 없음) | 도구 요청 (`tools` 4 개, `tool_choice: auto`, `reasoning_effort: high`) |
|---|---|---|
| `gpt-6-sol` | 200 | **400**, `param: reasoning_effort` |
| `gpt-6-luna` | 200 | **400**, `param: reasoning_effort` |

- 오류 문구 (응답 파일 원문, 게이트웨이가 업스트림 오류를 감싼 `detail.message`) : 이 모델은 `/v1/chat/completions` 에서
  함수 도구와 `reasoning_effort` 를 함께 받지 않는다. 도구를 쓰려면 `/v1/responses` 를 쓰거나 `reasoning_effort` 를 `'none'` 으로 하라는 안내
- 즉 **모델이 없거나 키·권한 문제가 아니라, 요청 조합(도구 + 추론 강도)을 이 엔드포인트가 받지 않는 것**이다. 짧은 요청은 두 모델 모두 200
- 실행기는 v9·v10 에서 모든 호출에 `reasoning_effort` 를 보내고 `/chat/completions` 만 쓴다 (D-29, DM-25 조건). 따라서 현재 데모·데이터셋
  조건으로는 gpt-6 계열을 돌릴 수 없다. 안내된 두 길(엔드포인트 변경, 추론 끔)은 모두 조건을 바꾸는 일이라 이번에 하지 않았다 (D-32 때 PM 결정)
- 이 probe 의 `result.json` 은 두 400 의 `error_message` 를 null 로 남겼다 (파트 2 의 오류 본문 모양 문제). 결과 파일은 고치지 않고 위 표가 원인 기록이다

**D-11 커밋** : 같은 폴더를 `secret_scan` 으로 검사했다 — 파일 25 개, 패턴 4 종 hit 0. 이 환경에는 `KMU_API_KEY` 가 없어 **키 값 자체 검사는 하지 못했다**
(`environment_variables_checked: not set in this environment`). probe 는 키를 헤더로만 보내고 요청 파일은 본문만 저장하며 응답은 `redact` 를 거친다.
PM 이 키 값 검사를 다시 돌리는 명령은 보고서에 있다. 걸리면 이 커밋을 되돌린다.

## 파트 3 — 한 응답의 다중 도구 호출 (확인만, D-32 전까지 변경 없음)

**기록된 세션** (`evidence.json` `multi_tool_calls`) : G0-8·A-1-v3·A-1-v4 의 200 응답에서 도구 호출이 2 개 이상인 응답 **0 건**
(응답별 도구 호출 수 0 또는 1). `parallel_tool_calls` 를 보낸 요청 0 건. 실행기 기록에서 한 모델 호출이 도구를 2 번 이상 실행한 경우 0 건.

**probe 9d2b2053 의 도구 요청** (같은 요청, 모델만 다름) : gpt-oss 1 개, Claude Sonnet 5·Claude Haiku 4.5·gpt-5.5 는 **각각 3 개** (모두 `read_file`).
교차검증 모델에서는 다중 호출이 흔할 수 있다.

**현재 실행기 동작** (코드 읽기 + 특성 테스트 `tests/test_multi_tool_calls.py`)

- autogen `AssistantAgent` 가 한 응답의 호출을 모두 실행한다 (`asyncio.gather`, 동시 실행). `reflect_on_tool_use=False` 라 그 뒤 모델 호출은
  다음 루프에서 일어난다. **도구 호출 수와 무관하게 모델 호출 1 회로 센다** (step 당 3 회 예산은 모델 호출 단위, 테스트 확인)
- `tool_executions` 에 호출마다 한 건, 같은 `llm_call_in_step`. 하나라도 `is_error` 면 그 step 은 G0-6 대로 `tool_execution_error` 실패 (단일 호출과 같음)
- 다음 요청에 결과가 응답의 호출 순서대로 모두 실린다. 프록시 턴 기록 `tool_calls` 는 응답의 호출 수다. `parallel_tool_calls` 는 보내지 않는다
- 미등록 도구는 응답 안의 모든 미등록 이름을 모아 한 번의 교정으로 처리한다 (`perform_step`, 기존 동작)
- **산출물 과제의 파일 도구**(`read_file`·`write_file`·`replace_in_file`)는 동기 함수라 스레드에서 동시에 돈다. 잠금이 없어서
  한 응답이 같은 파일을 두 번 쓰면 순서가 정해지지 않는다. 승인 게이트(DM-16) 검사는 호출마다 한다
- **대화 과제 도구**는 `ToolDispatch` 잠금으로 한 번에 하나씩 돈다. 기록 순번(`seq`)은 잠금을 잡은 순서라 응답의 호출 순서와 다를 수 있다.
  검색 호출 상한·arXiv 간격은 호출마다 적용된다
- gpt-oss 세션에서는 일어난 적이 없으므로 지금 고치지 않는다. D-32 전에 정할 선택지는 보고서 6 절

## C-17-8 파트 1 — C-17-7 결정 반영 (DM-54) · 프록시 모델 고정 (S-12) · 조건군 값

**DM-54 ② `--dataset-run` 의 다른 모델 거절** (`run_model`) — `--dataset-run` 과 시나리오 모델이 아닌 `--model` 을 함께 주면 실행 전 오류
(`--dataset-run sends the scenario model …; --model … differs from it (DM-54)`). 실행 폴더·요청 없음 (테스트). 시나리오 모델을 `--model` 로 다시 적는 것은 허용한다
(출처가 `run_condition` 으로 남는다). scenario-v2 는 원래 `--dataset-run` 을 거절한다 (DM-41).

**DM-54 ④ 한 응답의 파일 도구를 응답 순서대로 하나씩** (`Workspace.ordered_tools`, 산출물 경로)

- autogen 은 한 응답의 호출마다 작업을 만들어 응답 순서대로 `asyncio.gather` 로 함께 시작한다. 실행기가 넘기는 도구는 이제 작업 공간마다 하나인
  `asyncio.Lock` 을 잡은 뒤 실행한다. `asyncio.Lock` 은 기다린 순서대로 깨우므로 호출은 작업이 시작된 순서 = 응답의 호출 순서대로 하나씩 돈다.
  동기 도구(`read_file`·`write_file`·`replace_in_file`)는 잠금 안에서 스레드로, `run_tests` 는 잠금 안에서 그대로 돈다
- 도구 본체(`Workspace.tools`)는 그대로다 (기준선 테스트가 동기 함수로 직접 부른다). 넘기는 함수는 `functools.wraps` 라 이름·인자·설명이 같고,
  **도구 스키마가 같다** (테스트 : `FunctionTool` 스키마 비교). 도구 호출이 하나인 응답의 동작과 업스트림 요청은 바뀌지 않는다
  (C-17-4 scenario-v1 요청 12 건 바이트 비교, C-17-5 등가 조건 테스트 통과)
- 테스트 (`tests/test_c17_8_part1.py`) : 첫 쓰기를 0.2 초 늦춘 상태에서 한 응답에 `write(SPEC.md, first)`, `read`, `write(SPEC.md, second)`, `read` →
  읽기 결과 `first`·`second`, 다음 요청의 도구 결과도 그 순서. 같은 늦춤으로 잠금 없이 동시에 돌리면 읽기가 원래 내용을 읽고 파일에 `first` 가 남는 것도
  함께 보여 잠금이 순서를 만든다는 것을 확인한다. C-17-7 의 특성 기록("같은 파일 두 번 쓰기면 결과 불확정")은 이제 "나중 것이 남음" 이다
- `parallel_tool_calls` 는 보내지 않는다 (요청이 바뀐다. D-32 때 정한다). 대화 과제 도구는 원래 `ToolDispatch` 잠금으로 하나씩 돈다 (C-17-6)

**프록시 모델 고정 (S-12 : 프록시 1 개 = 조건군 1 개)** (`experiment_config.pinned_model`, `proxy.py`)

- 프록시가 시작할 때 설정 파일에서 모델 하나를 정한다 (`pinned_model: <ID>`). 코드에는 모델 기본값이 없다. 그 밖의 모델 요청은 업스트림에 보내지 않고,
  세션도 만들지 않고 **409** 로 거절한다 (DM-32 와 같은 방식) : `{"error": {"type": "guardrail_model_not_pinned", "code": "model_differs_from_pinned_model",
  "message": "이 프록시는 모델 … 전용입니다 (S-12, 프록시 1 개 = 조건군 1 개). 요청 모델 : …", "pinned_model", "requested_model"}}`, `x-should-retry: false`
- 고정된 프록시의 세션 meta 에 `pinned_model` (`{name, source}`) 을 남긴다. 고정하지 않은 설정은 지금처럼 모든 모델을 보내고 meta 도 그대로다
- **`deadlock-v0.3` (데모) 설정은 고정이 필수**다 (없으면 프록시 시작 전 오류). 데모 관측·차단 설정 두 개가 같은 모델로 고정된다 (파트 2 에서 `demo-conditions.yaml` 로 옮김)
- 실행기 (`enforce_proxy_model`, 산출물·대화 경로 공통) : 세션 시작 뒤 첫 모델 호출 전에 프록시 meta 를 읽어 **고정 모델이 자기가 보낼 모델과 다르면 실행 전 오류**.
  `--dataset-run` 이나 `--phase demo` 실행은 **고정된 프록시가 필요**하다. 고정 값은 `conditions.json` `proxy_pinned_model` 에 남는다
- **데이터셋 프록시 (보고, PM 결정 필요)** : `guardrail-deadlock-v0.2-kmu.yaml` 은 C-17-1 보호 파일(바이트 고정, `tests/fixtures/c17-1-protected-files.json`)이라
  고정 모델을 넣지 않았다. 데이터셋 모델도 아직 없다 (DM-57 : 파일럿 전에 정함, gpt-oss 는 게이트웨이에서 제거). 그래서 지금은 **`--dataset-run` 이 이 프록시에서
  실행 전 오류**가 난다 (고정 없음). C-20 에서 데이터셋 모델을 정할 때 고정 모델이 있는 데이터셋 설정을 만든다 — 새 설정 파일로 할지, 보호 해시를 갱신할지는 PM 결정.
  Groq 시대 설정 `guardrail.yaml`·`guardrail-deadlock-v0.2.yaml` 도 고정하지 않았다 (G0-8 재현용, 데이터셋·데모 실행에 쓰지 않음)

**조건군 값 확인 (`condition-group-v1`, 제자리 추가 — 실제 세션 0 개, DM-54 ③)**

| 지시 목록 | 조건군 필드 | 출처 | C-17-8 |
|---|---|---|---|
| 모델 | `model` | 프록시 세션 meta (실제로 보낸 모델) | 있었음 |
| 모델 출처 | `model_source` (`scenario` / `run_condition`) | `conditions.json` `model.source` | **추가** |
| 추론 강도 | `reasoning_effort` (`requested`, `sent_on`) | `conditions.json` | 있었음 |
| 판정 규칙 버전 | `criteria_version` | 프록시 meta | 있었음 |
| 판정 파라미터 해시 | `criteria_sha256` | 프록시 meta | 있었음 |
| 동결 해시 (코드·템플릿) | `criteria_freeze_sha256` | 프록시 meta `criteria_freeze.sha256` (v0.3 만, 아니면 null) | **추가** — 재동결은 `criteria_sha256` 을 바꾸지 않으므로(DM-33) 따로 둔다 |
| 프로토콜 | `runner_protocol` | `conditions.json` | 있었음 |
| 출력 계약 | `output_contract_version` | `conditions.json` | 있었음 |
| strict 방식 | `closed_list_check` | `conditions.json` (대화 과제만) | 있었음 |
| 차례 전달 규칙 | `recent_messages_rule` (`t1-handoff-v1`), `dialogue_flow` | `conditions.json` (대화 과제만) | `recent_messages_rule` **추가** |
| phase | `phase` | `conditions.json` | 있었음 |
| 모드 | `guardrail_mode` | 프록시 meta | 있었음 |
| 검색 설정 | `search_settings_sha256` (`tool_settings` 정규 JSON 의 SHA-256, 없으면 null) | `conditions.json` | **추가** |
| (그 밖) | `provider_host`, `proxy_config_file`, `collection_policy`, `temperature`, `max_tokens`, `max_steps`, `max_llm_calls_per_step`, `context_buffer_messages`, `requested_seed` | | 있었음 |

- 동결 기록 : 프록시가 시작할 때 `criteria_freeze.freeze` 로 v0.3 판정 파일 3 개의 SHA-256 과 템플릿 해시를 계산해 세션 meta `criteria_freeze` 에 남긴다.
  `tools/write_criteria_snapshot.py` 가 같은 함수를 쓴다 (동결 파일 출력 바이트 동일 확인). 테스트 : meta 값 = `docs/criteria/deadlock-v0.3.json` 의 값
- 테스트 : 목록의 각 값이 조건군에 있음, 새 값 넷이 바뀌면 조건군 ID 가 바뀜, 대화 과제 매니페스트의 실제 값

## C-17-8 파트 2 — 모델 교체 (DM-57) · DM-20 확정 (DM-55)

**근거 probe 다시 읽기** (`tools/c17_8_evidence.py models` → `reports/c17-8/evidence-models.json`, 파일만 읽음) — **DM-57 의 값과 모두 같다** (`all_same_as_dm57: true`)

| 확인 | probe 값 | DM-57 |
|---|---|---|
| ① 도구 + 추론 high (`a41f8d51`, A-1-v4) | 셋 다 200, `tool_calls` 반환 (glm 3, qwen 4, nano 3 개) | 통과, 3~4 개 |
| ① v3 strict `enum` 없음 (`44ec8e43`, TEST-T1-v2) | 셋 다 200, 계약 유효 | 통과 |
| v3 strict `enum` 포함 | 셋 다 200, 계약 유효 | 통과 (DM-55 (가)) |
| 단가 (크레딧 per 1M, 입력/출력) | glm 150/500, qwen 150/470, nano 200/1,250 (`a41f8d51` 두 요청으로 푼 값. nano 단독 `e38debde` 도 200/1,250) | 같음 |
| A-1-v4 30 step 환산 (입력 444,636 · 출력 106,866) | glm 120.13, qwen 116.92, nano 222.51 | 약 120 / 117 / 222 (1 크레딧 이내) |
| strict 최종 보고 1 회 출력 (`enum` 없음) | qwen 5,239, glm 204, nano 376 | 같음 |
| strict 두 번째 요청 cached | glm 1,088, qwen 1,024, nano 0 | 1,024~1,088 (nano 는 캐시 없음, DM-57 에 따로 적혀 있지 않음) |
| gpt-oss (`8f022e0a` strict 2 건, `2992b509` 일반 2 건) | 4 건 모두 404 `Model 'accounts/fireworks/models/gpt-oss-120b' not found` | 같음 |

- strict probe(`44ec8e43`)의 `model_summary.token_rates` (glm 210/178, qwen 3/500) 는 **단가가 아니다**. 두 번째 요청에 캐시된 입력이 있어 두 식을 푼 값이 틀어진다.
  단가는 캐시가 없는 도구 probe 의 값이다
- 모델 목록에서 빠진 것(`accounts/fireworks/models/gpt-oss-120b`, `meta-llama/Llama-4-Maverick…`)은 probe 파일에 없다 (PM 이 `/models/` 로 확인). DM-57 기록으로만 남긴다
- 선정 근거 (DM-57) : 세 후보 모두 ① 통과. 30 step 환산은 qwen 이 3 % 싸지만 같은 strict 요청의 출력이 glm 의 약 26 배(5,239 대 204)라 실제 비용·시간이 커질 것이므로 glm.
  환산은 모델별 출력 길이 차이를 반영하지 못한다
- 이번 달 사용량 : 마지막 probe 요청 뒤 `monthly_allocated.used` 6.8413 (probe 파일 값)
- D-11 : 다섯 폴더(파일 41 개)를 `secret_scan` 으로 검사, 걸린 것 없음. 이 환경에 `KMU_API_KEY` 가 없어 **키 값 자체 검사는 하지 못했다** (PM 명령은 C-17-8 보고서). 커밋 `966a9b3`

**`gpt-oss-120b` 가 기본값·고정값으로 들어 있던 곳** (C-17-8 기준 커밋 `4d425e5`, `git grep`, 스크립트 분류)

| 분류 | 위치 | 처리 |
|---|---|---|
| **교체 대상 (데모 실행에 쓰임)** | `guardrail-deadlock-v0.3-kmu.yaml`:1, `guardrail-deadlock-v0.3-kmu-block.yaml`:1 (머리 주석. 모델 키는 없었다) | 주석을 고치고 `run_conditions: demo-conditions.yaml` 로 고정 (아래) |
| | `docs/design/demo-scenarios.md`:20 (C-18 이 따르는 공통 조건 줄) | 모델·추론 강도에 줄을 긋고 `run_conditions` 안내를 붙였다 |
| **데이터셋 시나리오 (새 버전 필요, C-20)** | `scenarios/A-1-ambiguous-task-query.yaml`:8, `A-1-v2`:13, `A-1-v3`:7·12, `A-1-v4`:12 | 그대로. 데이터셋 모델은 파일럿 전에 정하고 새 시나리오 버전을 만든다 (DM-54 ②) |
| | `guardrail-deadlock-v0.2-kmu.yaml`:1 (머리 주석) | 그대로. C-17-1 보호 파일 (파트 1 "데이터셋 프록시") |
| **기록이라 그대로** | `logs/` 9 파일, `runs/` 35 파일, `reports/` 12 파일 (기존 세션·probe·분석), `docs/decisions/011`·`019`, `docs/design/demo-model-probe.md`, `docs/findings/error-evidence.json`, `docs/A1-*.md` | 그대로 |
| | `tests/fixtures/scenario-v2-dialogue.yaml`:8 (TEST-T1-v2), `tests/fixtures/scenario-v2-artifact.yaml`:9 (DM-37 의 A-1-v4 사본), 테스트 상수 (`test_harness_facts`·`test_model_run_condition`·`test_multi_tool_calls`·`test_probe_models`·`test_probe_v3_strict`) | 그대로 (C-17-4 기준값·C-17-5 등가 조건). 테스트는 fixture 모델로 고정한 설정 사본으로 돈다 (`tests/pinned_configs.py`) |
| | `tools/analyze_session.py`:387 (`PRICE_PER_M`, 기록된 세션의 단가) | 그대로. glm 단가 추가는 PM 결정 (C-17-7 보고) |
| | `experiments/probe_strict_output.py`:14, `test.py`:5, `deadlock_test.py`:10 (Groq 시대) | 그대로. 데모 트랙 뒤 Groq 잔재 정리 |

C-17-8 뒤 데모 실행 경로(코드·데모 설정)에는 `gpt-oss` 가 없다 (`evidence-models.json` `now_tracked.demo` 는 `demo-scenarios.md` 의 줄 그은 기록뿐).

**데모 모델을 한 곳에서 (`demo-conditions.yaml`, `demo-run-conditions-v1`)**

```yaml
conditions_version: demo-run-conditions-v1
model: glm-5.3-flash
reasoning_effort: high                                    # C-18-2 (DM-60). C-17-8 에서는 medium
reasoning_effort_evidence: reports/c18-1/trial-summary.json  # C-18-2. C-17-8 에서는 null
```

- 이 파일만 데모 모델·추론 강도를 정한다. 코드·설정 YAML 에는 모델 ID 가 없다 (테스트 : 루트·`experiments/` 의 Python 과 `guardrail*.yaml` 에 `glm-5.3-flash` 없음)
- **실행기** : scenario-v2 에 `run_conditions: demo-conditions.yaml` 을 두면 그 시나리오는 `model`·`reasoning_effort`·`reasoning_effort_evidence` 를 쓰지 않고
  (둘 다 쓰거나 둘 다 없으면 스키마 오류) 실행할 때 파일 값으로 채운다 (`scenario_schema.resolve_run_conditions`). C-18 데모 시나리오 11 개가 이 방식을 쓴다.
  `conditions.json` `run_conditions` 에 파일 경로·SHA-256·값을 남긴다. 모델 출처는 `scenario` (시나리오가 가리킨 파일), `--model` 을 주면 `run_condition`
- **데모 프록시** : 관측·차단 설정 둘 다 `run_conditions: demo-conditions.yaml` 로 그 파일의 모델에 고정된다 (meta `pinned_model.source: run_conditions`, 파일 해시 포함)
- **probe** : `tools/probe_gateway.py --scenario <데모 시나리오>` 도 같은 값을 쓴다 (테스트 : dry run 요청이 glm·high. C-17-8 에서는 medium)
- ~~추론 강도 `medium` 의 실제 적용 여부는 probe 로 확인하지 않았다 → `reasoning_effort.applied: unverified`~~ → **C-18-2 (DM-60)** : `medium` 은 glm 이 400 으로 거절했다 (시험 세션 `c3a4c019…`). `high` 로 바꾸고 시험 세션 두 개의 reasoning 토큰을 근거 파일로 둔다 → `applied: probe_indicated`, `evidence: reports/c18-1/trial-summary.json` (아래 C-18-2 절)
- `run_conditions` 가 없는 scenario-v2(C-17 fixture)와 scenario-v1(A-1 계열)은 지금처럼 시나리오의 모델을 보낸다. **scenario-v1 기본 실행의 업스트림 요청은 바이트 그대로**다
  (C-17-4 요청 12 건 비교 통과). 데모 경로의 요청은 지시의 예외대로 바뀐다 : 모델 `glm-5.3-flash`, `reasoning_effort: medium` (C-18-2 부터 `high`), 최종 보고 strict 스키마에 `enum` 포함

**DM-55 — 대화 과제의 기본 strict 방식 = `enum` 포함 (`provider_strict`)**

- `dialogue_runner.DEFAULT_CLOSED_LIST_CHECK = 'provider_strict'`. `--closed-list-check after_receipt` 를 주면 DM-40 방식(enum 없이 보내기). 받은 뒤 검사(어휘 위반 기록)는 두 방식 모두 그대로
- `conditions.closed_list_check` : `{mode, decision: DM-20, enums_sent_to_provider, basis}`. 기본이면 `basis` 가 `default (DM-55: enum strict probe gateway-probe-44ec8e43 passed for the demo model)`,
  명시하면 `run condition`. 조건군 필드 `closed_list_check` 에 방식이 들어간다 (테스트 : `after_receipt` 로 바꾸면 조건군 ID 가 바뀐다)
- probe 근거는 glm 이다. 다른 모델로 데모를 돌리면(`--model`) 그 모델의 strict probe 를 다시 보고 정한다 (DM-55 규칙). C-19 본 실행은 한 방식으로 고정 (DM-40)

**한 응답의 다중 도구 호출** — 후보 셋 모두 3~4 개. 테스트가 있다 : 산출물 경로 응답 순서 실행 `tests/test_c17_8_part1.py` (`InOrderRunTests`, 4 호출),
도구 호출 수와 무관하게 모델 호출 1 회 `tests/test_multi_tool_calls.py`, 대화 경로 직렬 실행·검색 상한 `tests/test_dialogue_tool_flows.py`·`tests/test_c17_8_part0.py`.
검색 상한 20 에 일찍 닿는지는 C-18 시험 실행에서 본다

**비용 재추정 (추정)** (`docs/design/demo_budget.py --prompt-rate 150 --completion-rate 500 --model-label glm-5.3-flash --used-this-month 6.8413` → `reports/c17-8/demo-budget-glm.json`)

- 스크립트가 단가를 인자로 받게 고쳤다 (`--prompt-rate`, `--completion-rate`, `--output`, `--model-label`, `--used-this-month`). 기본값(150/600)으로 돌리면 C-16 출력과 기존 키가 모두 같다
- 세션 기준값 (gpt-oss 세션의 토큰을 glm 단가로) : 정상(A-1-v3 같은) 15.69, 교착(A-1-v4 같은) 120.13, 차단(A-1-v4 첫 STOP 까지) 36.53
- 데모 70 세션 혼합 추정 **4,544.17**. C-18 시험 11 세션 범위 172.64~1,321.41 을 더하면 **4,716.81~5,865.58** → 위쪽이 월 할당 5,000 을 넘는다
- 관측 반복 수(DM-6)별 (차단 3 회·시험 11 세션 유지) : 5 회 70 세션 4,544 (+시험 4,717~5,866) / 4 회 59 세션 3,745 (3,918~5,066) / 3 회 48 세션 2,946 (3,118~4,267)
- 한계 : 토큰 수는 gpt-oss(추론 high) 세션이다. glm 의 출력 길이·`medium` 효과·캐시 할인은 반영하지 않았다 (위쪽 추정). 실측은 C-18 시험 실행으로 갱신


## C-18-2 파트 0 — 추론 강도 high (DM-60) · 산출물 과제의 조건군 값

**DM-60** : `demo-conditions.yaml` 을 `reasoning_effort: high` 로 커밋한다 (PM 이 C-18-1 시험 실행 중 바꾼 값).

- 원인 : 첫 시험 세션 `DEMO-CL-normal-v1-c3a4c019…` 이 step 1 에서 400 (`code 1210` "This model always engages in thinking and cannot be disabled; please use low, high, or max"). 0 크레딧
- 근거 파일 `reports/c18-1/trial-summary.json` (`tools/c18_2_evidence.py`, 세션 폴더만 읽음) 의 `reasoning_effort_evidence` :
  `DEMO-CL-normal-v1-d5460d69…` high · 18 턴 · reasoning 9,800 / `DEMO-CL-stall-v1-f08705fe…` high · 76 턴 · reasoning 25,527 / `c3a4c019…` medium · 400
- `reasoning_effort_evidence` 는 경로만 받는다 (`experiment_config.load_run_conditions`, 실행기는 파일이 없으면 실행 전 오류). 세션 ID 와 토큰 수는 YAML 머리 주석과 근거 파일에 적었다
- 그 결과 `conditions.reasoning_effort.applied` 가 `unverified` → `probe_indicated` 가 된다. 이름은 v9 부터 쓰던 값 그대로이고(데이터셋 경로 코드 불변), 여기서는 "근거 파일이 적용을 보여 준다" 는 뜻이다 (근거는 probe 가 아니라 시험 세션의 reasoning 토큰). `low`·`max` 는 시험하지 않았다
- 조건군 필드는 `requested`·`sent_on` 만 쓰므로 근거 파일 변경은 조건군 ID 를 바꾸지 않는다. `medium` → `high` 는 조건군을 바꾼다 (실제로 `c3a4c019…` `cg-1cf34b825a1d`, 나머지 두 세션 `cg-9bfd9889d4f8`)
- `medium` 을 가정한 곳 : 테스트 (`tests/test_c17_8_part2.py` 6 곳, `tests/test_c18_1_part3.py` 1 곳) 를 `high` 로, preflight 는 `reports/c18-2/DEMO-CL-*-preflight.json` 로 새로 만들었다 (C-18-1 기록은 그 시점 값 medium 으로 남긴다. 차이는 `run_conditions_sha256`·`reasoning_effort`·`freeze_sha256` 뿐이고 시나리오 해시·짝 차이·실행 전 판정 6/15 는 같다)
- 그대로 둔 기록 : `reports/c17-8/demo-budget-glm.json`, `reports/c18-1/estimate-trial.json` 의 "reasoning medium 미반영" 메모 (그 시점 추정의 한계 문장. 실측 DM-62 가 대체), `docs/design/demo-scenarios.md` 21 행의 C-17-8 기록

**조건군 빈 필드 (C-18-2 요약 도구 보완)** : 시험 세션 셋의 `condition_group_missing_fields` 5 개를 나눴다 (`tools/summarize_demo_session.py` `condition_group_missing_by_class`)

| 필드 | 분류 | 처리 |
|---|---|---|
| `dialogue_flow`, `recent_messages_rule` | 산출물 과제에 해당 없음 (대화 과제 전달 규칙, DM-47) | 그대로 |
| `search_settings_sha256` | 검색 도구가 없는 과제에 해당 없음 | 그대로 |
| `requested_seed` | 기록된 null (seed 를 요청하지 않음. `conditions.json` 에 키가 있다) | 그대로 |
| `closed_list_check` | **정말 빠짐** — 산출물 과제가 닫힌 목록(쟁점 ID) 검사 방식을 남기지 않았다 | **채움** |

- 채운 값 (`experiments/run_scenario.ARTIFACT_CLOSED_LIST_CHECK`, scenario-v2 산출물 과제만) : `{mode: after_receipt, decision: D-13, enums_sent_to_provider: false, basis: …}`. 산출물 과제의 strict 스키마는 v2·v3 모두 `enum` 을 보내지 않는다 (`issue_contract.response_format`). 요청 바이트는 바뀌지 않는다
- 영향 : 산출물 과제 세션의 조건군 ID 가 C-18-1 시험 세션(`cg-9bfd9889d4f8`)과 달라진다. 시험 세션끼리만 해당하고 본 실행은 최종 동결 뒤 한 조건군이다. scenario-v1(데이터셋) 경로의 `conditions.json` 은 바뀌지 않는다
