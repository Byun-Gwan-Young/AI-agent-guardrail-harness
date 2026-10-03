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

