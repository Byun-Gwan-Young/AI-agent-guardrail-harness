# DM-7 · DM-23: 데모 차단 모드 (block)

PM 결정 DM-7 (2026-09-29), DM-23 (C-16 결정 9), DM-32·DM-34 (C-17-2 결정, C-17-3 반영). 설계 `docs/design/demo-block-and-explanation.md` 1 절.
구현 C-17-2 파트 1, 개정 C-17-3 파트 0.
데모에서만 쓴다. 데이터셋 수집은 계속 observe 만 한다 (14 장). 복구 개입(INJECT 등)은 범위 밖 (DM-8).

## 켜는 방법

- 설정 키 `guardrail_mode: observe | block`. **키가 없으면 observe** — 기존 설정 파일 4 개(`guardrail.yaml`, v0.2 두 개,
  `guardrail-deadlock-v0.3-kmu.yaml`)는 바꾸지 않았다. 다른 값은 프록시 시작 전 오류
- 차단 전용 설정 `guardrail-deadlock-v0.3-kmu-block.yaml` = 관측 설정 + `guardrail_mode: block` 한 줄 (테스트로 확인)
- **block 은 `criteria_version: deadlock-v0.3` 에서만 프록시가 시작된다** (설계에 없던 추가 안전장치). 데이터셋 판정 버전(v0.1·v0.2)과
  함께 쓸 수 없고, 차단 오류 본문의 원인 설명(explain-v1)도 v0.3 에만 있다
- 프록시는 세션 시작 때 모드를 세션 메타 `guardrail_mode` 에 고정한다. 재시작 뒤 다른 설정으로 떠도 그 세션의 모드는 바뀌지 않는다
  (이 키가 없는 이전 세션은 observe)

## 안전장치 두 개 (DM-23)

1. **phase 헤더 — block 프록시는 demo phase 전용 (DM-32, C-17-3)** : `X-Guardrail-Phase` 가 `demo` 가 아닌 요청은 **409** 로
   거절한다. 본문 `{"error": {"type": "guardrail_block_requires_demo_phase", "code": "block_mode_requires_demo_phase",
   "message": "차단 프록시는 demo phase 전용입니다 (X-Guardrail-Phase: demo)", "phase": <받은 값>}}`, 헤더 `x-should-retry: false`
   - `POST /sessions` 와 `/v1/chat/completions` 둘 다. 판단은 그 세션 메타의 모드(없는 세션이면 이 프록시의 모드)로 한다
   - 업스트림으로 아무것도 보내지 않고, 턴으로 남기지 않으며, 세션이 없으면 세션 파일도 만들지 않는다
   - 실행기는 세션 시작 응답이 오류면 프록시 사유를 붙여 `runner_error` 로 끝낸다 (`Proxy refused the session (409): …`). 모델 호출 0 회
   - **C-17-2 와 다른 점** : C-17-2 는 지시대로 비데모 요청을 관측처럼 통과시켰다. 조용히 통과시키면 잘못된 조건군(v0.3·block)의
     세션이 섞이므로 DM-32 로 바꿨다 (S-12 : 프록시 1 개 = 조건군 1 개). 설계 1-1 의 409 제안과 같아졌다
   - 실행기는 `--phase demo` 일 때만 이 헤더를 보낸다. phase 는 프록시가 기록하는 실행 조건(`request_params.phase`, 메타 `phase`)이
     되어 세션 안에서 바뀌면 `conditions_mixed` 로 잡힌다. 값은 짧은 소문자 토큰만 받는다 (그 밖은 400)
2. **`--dataset-run` 배제** (실행기, 모델 호출 전)
   - `--dataset-run` + `--phase demo` → 실행 폴더를 만들기 전에 오류
   - `--dataset-run` 은 demo phase 를 가질 수 없으므로 block 프록시에서는 세션 시작부터 409 로 거절된다 (DM-32).
     세션을 연 직후 메타가 `guardrail_mode: block` 이면 실행기가 한 번 더 거부하는 검사(`enforce_observe_proxy`)는 두 번째
     안전장치로 남겨 두었다

## 데모 출력 경로 (DM-34, C-17-3)

- `--phase demo` 실행의 실행 폴더는 `runs/demo/` 아래만 허용한다. `--output-root` 를 주지 않으면 `runs/demo/`, 다른 경로를 주면
  실행 폴더를 만들기 전에 오류
- 반대로 demo 가 아닌 실행이 `runs/demo/` 아래에 쓰려 하면 같은 시점에 오류 (DM-2 : 데이터셋과 섞지 않는다. 지시에 없던 반대 방향 검사)
- `--output-root` 기본값은 phase 로 정한다 (`runs/` 또는 `runs/demo/`). 기존 비데모 실행의 실효 기본값 `runs/` 는 그대로
- `tools/analyze_session.py` 는 실행 폴더를 `runs/<id>` 에 없으면 `runs/demo/<id>` 에서, 프록시 로그를 `logs/<id>.json` 에 없으면
  `logs/demo/<id>.json` 에서 찾는다

## 차단 시점과 응답

- 판정은 step 끝 관측 뒤에 나온다. 세션의 관측 중 판정이 `deadlock`/`termination_failure` 인 첫 기록이 있으면, 그 뒤의
  demo phase 요청은 업스트림으로 보내지 않는다. 그래서 막히는 것은 **STOP step 다음 step 의 첫 LLM 요청**이다
- 판정 계산은 관측 모드와 같다 (`/sessions/observations` 그대로, `judgement_ns` 도 그대로 기록). 차단 여부만 다르다
- 응답 **403**, 헤더 `x-should-retry: false`, `X-Guardrail-Turn`. 본문 (OpenAI 오류 형식) :

```json
{"error": {"type": "guardrail_stop", "code": "guardrail_stop", "message": "<STOP 기록의 explain-v1 문장>",
           "stop_step": 6, "decision": "deadlock", "criteria_version": "deadlock-v0.3", "criteria_sha256": "a93cc2d6…",
           "explanation_version": "explain-v1", "template_id": "E1", "session_id": "<세션 ID>"}}
```

- `message` 는 STOP 기록의 `explanation.text` 를 그대로 복사한다 (DM-9, 다시 만들지 않는다). 설명 생성이 실패한 STOP 이면 문장을
  지어내지 않고 `"guardrail_stop"` 과 `template_id: null` 을 낸다
- 같은 세션의 이후 demo 요청도 모두 같은 403 이다

## 기록

- 프록시 턴 : 거절한 요청도 턴으로 남긴다 — `forwarded: false`, `blocked: true`, `status_code: 403`,
  `upstream_ms: 0`, `upstream_request_body: null`, 토큰 `0/0/0` (업스트림으로 보내지 않았으므로 제공자 소비가 없다는 측정값),
  `response_body` 는 위 오류 본문. 실행기는 이 턴 번호로 step 과 턴을 잇는다
- 프록시 메타 `guardrail_block` (첫 거절 때 생성) : `stop_step`, `decision`, `criteria_version`, `criteria_sha256`,
  `explanation` (STOP 기록의 것을 복사), `blocked_at_step` (= 그때까지 관측 수 + 1), `first_blocked_turn`, `refused_requests`
- 실행기 : `perform_step` 이 403 + `code: guardrail_stop` 을 `blocked` 로 돌려준다. 재시도·도구 실패 복구·`abort` 로 가지 않는다.
  그 step 은 `step_status: blocked`, `acceptance: null`, 관측을 보내지 않고, 세션은 종료 사유 **`guardrail_stop`** 으로 정상 종료한다
  (`/sessions/end` 평소대로, 종료 코드 0). 그 밖의 403 은 이전과 같이 `abort` 다
  - 이전 경로 : `step_execution.py` 예외 분기 → `abort` → `run_scenario.py` 에서 `runner_error`
  - `summary.json` 의 `guardrail_stop` = 오류 본문 값 + `blocked_step`. `conditions.json` 에 `phase`, `guardrail_mode`
  - 거절 턴도 토큰이 있으므로 (`0`) 세션 `total_tokens` 는 측정값으로 남는다
- 매니페스트 **`session-manifest-v0.5`** = v0.4 + `condition.phase`, `condition.guardrail_mode` (프록시 메타 기준. v0.4 까지는
  시나리오 `on_criteria_alert` 에서 읽었다), `guardrail.mode`, `guardrail.block` (위 메타 값 + 거절 턴 번호, 업스트림으로 보낸
  턴 수, 원인 문장, 첫 STOP 기록 문장과 같은지, 실제 사용 토큰), `guardrail.savings_vs_observe`. v0.3 판정 세션 중 프록시가
  `guardrail_mode` 를 기록한 세션(C-17-2 이후)에만 쓴다. 기존 매니페스트는 다시 쓰지 않는다

## 절감 보고 (DM-23)

- "차단으로 이 세션에서 N 토큰을 아꼈다" 는 측정할 수 없다 (같은 세션이 차단 없이 어떻게 흘렀을지는 관측되지 않는다)
- `guardrail.savings_vs_observe` 는 **필드만** 마련했다 : `status: unmeasured`, `value: null`, 기준 문장, 이 세션 총 토큰.
  같은 시나리오 관측 세션(중앙값·범위)과의 차이는 데모 집계(C-19)가 채운다. 이 세션 하나로는 계산하지 않는다
- 관측 세션의 사후 절감(첫 가상 STOP 이후 토큰, `counterfactual_stop`)과 이름·위치를 분리한다

## 테스트

`tests/test_block_mode.py` : 가짜 업스트림 + 메모리 프록시. STOP 다음 요청 403·업스트림 미전달·본문 문장 = STOP 기록 문장·
거절 턴 기록·메타 `guardrail_block`·`judgement_ns`, phase 없음/다른 phase 는 통과, 관측 설정은 demo phase 여도 통과,
설명 실패 시 문장 지어내지 않음, phase 헤더 형식, block 프록시의 비데모 요청 409 (세션 시작·대화·데모 세션의 phase 없는 요청),
설정 차이·v0.3 전용·모드 값 검사, 안전장치 두 개, `guardrail_stop` 판별, 데모 출력 경로 규칙,
`perform_step` 의 blocked 결과와 다른 403 의 abort 유지, 실제 실행기 오프라인 실행 (step 6 STOP → step 7 거절 → `guardrail_stop`,
매니페스트 v0.5, 실행 폴더 `runs/demo/`), demo phase 없는 실행은 block 프록시에서 세션 시작 409·관측 프록시에서는 차단 없음,
`--dataset-run` 두 경로.

## 알려진 한계

- `tools/analyze_c14.py`, `tools/compare_sessions.py` 는 모든 step 에 `acceptance` 가 있다고 가정한다 (C-11·C-14 세션 전용 도구).
  차단 세션에 쓰려면 고쳐야 한다. `tools/analyze_session.py` 는 고쳤다
- 프록시 로그 경로(`GUARDRAIL_LOG_DIR=logs/demo`)는 프록시가 실행 phase 를 시작 전에 알 수 없어 실행 명령으로 정한다.
  코드가 강제하는 것은 실행 폴더(`runs/demo/`, DM-34)뿐이다
