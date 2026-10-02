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
