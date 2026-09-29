# 차단 모드 + 원인 설명 설계 (C-16 파트 4)

- 상태 : **설계안.** 구현은 C-17
- 범위 : 데모에서만 쓴다 (DM-7, DM-9). 데이터셋 수집은 계속 observe 만 한다 (14 장). 복구 개입(INJECT 등)은 범위 밖 (DM-8)

## 1. 차단 모드 (DM-7)

### 1-1. 켜는 방법과 안전장치

- **현재 코드에는 모드 설정이 없다.** 프록시는 판정을 기록만 하고 요청을 언제나 전달한다. 그래서 observe 는 "차단 코드가 없음" 으로 보장된다
- 새 키 `guardrail_mode: observe | block` 을 설정 파일에 둔다. **없으면 observe.** 기존 설정 파일 3 개는 바꾸지 않는다
- 데모 차단 전용 설정 `guardrail-deadlock-v0.3-kmu-block.yaml` 에만 `block` 을 쓴다
- 이중 안전장치 (제안)
  - 프록시가 `block` 이면 세션 시작 시 실행기의 `X-Guardrail-Phase` 헤더가 `demo` 인지 확인하고, 아니면 첫 요청을 거부한다 (409, `block_mode_requires_demo_phase`)
  - 실행기의 `--dataset-run` 과 `--phase demo` 는 함께 줄 수 없다 (실행 전 오류)
  - 모드는 세션 메타·`conditions.json`·매니페스트에 기록한다 (`guardrail_mode`)

### 1-2. 차단 조건과 시점

- `/sessions/observations` 가 기록한 판정의 `decision` 이 `deadlock` 또는 `termination_failure` 가 **처음** 된 순간, 세션에 차단 표시를 남긴다
  - 남기는 값 : `blocked = {stop_step, decision, criteria_version, reason, explanation, signals}`
- 판정은 step 끝 관측 뒤에 나온다. 따라서 차단되는 것은 **STOP 이 난 step 의 다음 step 의 첫 LLM 요청**이다 (C-16 표 "다음 LLM 요청")
- 관측 모드와 같은 판정 계산을 쓴다. 차단 여부만 다르다

### 1-3. 프록시 응답

- 상태 코드 **403** (제안)
  - 5xx·429·408·409 는 OpenAI SDK 의 기본 재시도 대상이라 쓰지 않는다
  - 실행기는 `max_retries=0` 이지만 (`run_scenario.py:394`), 다른 클라이언트로도 재시도되지 않게 한다
  - 헤더 `x-should-retry: false`
- 본문 (OpenAI 오류 형식) :

```json
{"error": {"type": "guardrail_stop", "code": "guardrail_stop",
           "message": "<원인 설명 문장 (2 절)>",
           "stop_step": 9, "decision": "deadlock", "criteria_version": "deadlock-v0.3",
           "session_id": "<세션 ID>"}}
```

- 업스트림으로 아무것도 보내지 않는다. 프록시 로그 턴 기록 : `forwarded: false`, `blocked: true`, `status_code: 403`, 토큰 0, `upstream_ms: 0`
- 같은 세션의 이후 요청도 모두 같은 403 (실행기는 첫 403 에서 멈추므로 보통 1 건)

### 1-4. 실행기 처리

- `step_execution.perform_step` 의 예외 분기에서 `status_code == 403` 이고 `error.code == 'guardrail_stop'` 이면 `outcome = {'blocked': True, ...}` 로 돌려준다
  - 현재는 이런 오류가 `abort` → `runner_error` 가 된다 (`step_execution.py:290`, `run_scenario.py:553`)
- 세션 종료 사유 **`guardrail_stop`**. 차단된 step 은 `step_status: blocked` 로 남기고, 관측은 보내지 않는다 (모델 출력이 없다)
- `/sessions/end` 는 평소대로 호출한다

### 1-5. 기록

- 매니페스트 `guardrail` 절 : `mode: block`, `first_stop_step`, `blocked_request_step`, `explanation`, `signals`
- 대시보드·차단 오류 본문·매니페스트의 설명 문장은 **같은 문자열** (DM-9). 프록시가 한 번 만들고 나머지는 복사한다

### 1-6. 절감 토큰 계산 — 관측 세션의 사후 계산과 구분

| 이름 | 무엇 | 어디서 |
|---|---|---|
| 관측 세션 사후 절감 (기존) | 관측 세션에서 첫 가상 STOP 이후 소비된 토큰 | 같은 세션 로그 (반사실) |
| **차단 세션 실제 소비** | 차단 세션이 실제로 쓴 토큰. 차단 뒤는 0 | 차단 세션 로그 (측정) |
| **관측 대비 차이** | 같은 시나리오 관측 5 회의 총 토큰 (중앙값·범위) − 차단 세션 총 토큰 | 두 집단 비교 |

- "차단으로 이 세션에서 N 토큰을 아꼈다" 는 측정할 수 없다. 같은 세션이 차단 없이 어떻게 흘렀을지는 관측되지 않기 때문이다
- 발표에는 **"관측 5 회 대비 차이 (데모 세션 기준)"** 로만 쓴다
- 첫 STOP step 이 관측 세션과 다를 수 있다 (온도 0.0 이라도 재현성 미검증, seed unverified). 차단 세션마다 첫 STOP step 을 함께 보고한다

## 2. 원인 설명 (DM-9)

### 2-1. 원칙

- **판정 신호값만으로 만든 템플릿 문장.** LLM 생성 금지, 모델 reasoning·narrative 사용 금지
- 한국어 한두 문장. 값은 모두 관측·판정 기록의 필드에서 가져온다. 값이 없으면 그 템플릿을 쓰지 않고 다음 순위로 넘어간다
- 템플릿 목록과 선택 순서는 `deadlock-v0.3` 과 함께 동결한다 (`explanation_version: explain-v1`)

### 2-2. 템플릿

| ID | 조건 | 문장 | 들어가는 값 (출처) |
|---|---|---|---|
| E1 | T2 : 최근 N step 이 stagnant, 산출물·통과 수·쟁점 불변 | "최근 {n} step 동안 {roles} 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 {pass}/{total}." | n = `consecutive_steps`, roles = 그 step 들의 `agent_id` (역할 이름), pass/total = 마지막 관측 `artifact.test_pass_count`/`test_total_count` |
| E2 | T3 (a) 전역 되돌림 | "{path} 가 step {k} 의 내용으로 되돌아갔고, 통과 테스트는 {m} step 동안 {pass}/{total} 입니다." | path = 바뀐 감시 파일, k = 같은 결합 해시가 처음 나온 step, m = 통과 수 최대 갱신 이후 step 수 |
| E3 | T3 (b) 통과 수 정체 | "step {a} 이후 {m} step 동안 파일이 {c} 번 바뀌었지만 통과 테스트는 {pass}/{total} 에서 늘지 않았습니다." | a = 마지막 최대 갱신 step, c = 그 뒤 `files_changed` 사건 수 |
| E4 | T1 왕복 (라우터, 왕복 ≥ H) | "{role_a} 과 {role_b} 가 문의를 서로 {h} 번 넘겼고 처리 상태는 '{status}' 에서 바뀌지 않았습니다." | role_a/b, h = `handoff_to` 왕복 횟수, status = 현재 `status` 의 표시 이름 |
| E5 | T1 채택 정체 | "최근 {n} step 동안 채택 항목이 {adopted}/{required} 에서 늘지 않았고 처리 상태는 '{status}' 입니다." | adopted = 세션 안 처음 나온 채택 ID 수, required = 시나리오 필수 항목 수 |
| E6 | 완료 선언 후 유예 초과 (`termination_failure`) | "step {d} 에 완료가 선언됐지만 이후 {n} step 동안 진전이 없습니다. 통과 테스트 {pass}/{total}." | d = `declared_step`. T1 은 뒷문장을 "처리 상태는 '{status}' 입니다." 로 |
| E7 | oscillating 이 섞인 연속 | "최근 {n} step 중 {o} step 은 이전 상태로 되돌아갔고, 나머지는 변화가 없었습니다." | o = 연속 구간의 oscillating 수 (`consecutive_states`) |

- 예 : A-1-v4 의 첫 STOP (step 9) 에 E1 을 적용하면
  - 템플릿 : "최근 3 step 동안 기획·개발·리뷰 모두 산출물 변경·테스트 증가·새 쟁점이 없습니다. 통과 테스트 7/16."
  - 값은 로그의 `consecutive_steps` 3, step 7~9 의 역할, 통과 수 7/16
  - 이 문장은 설계 예시이며, 실제 문자열은 C-17 구현이 로그에서 만든다

### 2-3. 선택 순서 (두 개 이상 해당할 때)

`termination_failure` 면 E6 → 연속 구간에 T3 (a) step 이 있으면 E2 → (b) 면 E3 → T1 왕복 기록이 H 이상이면 E4 → T1 채택 지표가 선택된 시나리오면 E5 → oscillating 이 있으면 E7 → 그 외 E1. 한 개만 낸다.

## 3. PM 결정 필요

1. 차단 응답 상태 코드 : 403 (제안) / 다른 코드
2. 이중 안전장치 (phase 헤더 확인 + `--dataset-run` 배타) 채택 여부
3. 설명 문장의 역할 표시 : 역할 ID (`planner`) / 한국어 역할 이름 (`기획`, 시나리오 `role` 필드). 제안 : 한국어 이름
4. 차단 세션의 절감 보고 방식 : "관측 5 회 대비 차이" 만 (권장)
