# DM-10 · DM-22: `deadlock-v0.3` / `progress-v3` (데모 트랙 판정 규칙)

PM 결정 DM-10 (2026-09-29), DM-22 (C-16 결정 8). 설계 `docs/design/demo-deadlock-v0.3.md`. 구현 C-17-1.
데모 실행 전에 등록·동결하고 데모 중 바꾸지 않는다. 파일럿 주 규칙(v0.2 / v0.3)은 데모 후 PM 결정이다.

## 구성

- `deadlock_policy_v03.py` : v0.2 의 연속 판정 루프 그대로. 숫자는 모두 고정된 파라미터에서 읽는다
- `progress_signal_v3.py` : progress-v2 (역할별 비교, progress-v1 계산 호출) + T1 대화 신호 + T3 산출물 신호
- 디스패치 : 새 `criteria_policy.py` (criteria, v0.3 을 먼저 고르고 나머지는 `deadlock_policy.py` 로 넘김),
  `observation_api.py` (progress-v3 는 고정된 파라미터를 받는다). `session_store.py`·`observation_api.py` 가 이것을 쓴다
- `deadlock_policy.py`, `deadlock_policy_v01.py`, `deadlock_policy_v02.py`, `progress_signal.py`, `progress_signal_v1.py` 는
  바이트 동일 (`tests/fixtures/c17-1-protected-files.json`. `deadlock_policy.py` 는 P0-2 보호 파일이기도 하다).
  그래서 설계 6 절의 "progress_signal 에 progress-v3 분기" 대신 `criteria_policy.py`·`observation_api.py` 에서 나눈다

## 파라미터 — 설정 파일에서만 읽는다

- `guardrail-deadlock-v0.3-kmu.yaml` 의 `criteria_parameters`. 코드에 기본값이 없다. 키가 빠지거나 남으면 프록시 시작 전 오류
- 값 : N 3, grace 2, missing review 3 (v0.2 그대로), **K (`plateau_steps`) 6**, **H (`handoff_record_threshold`) 4 — 기록만**,
  `t3_global_revert: true`, `t1_metrics: [status_advance, adopted_items, new_issue_ids]`, `explanation_version: explain-v1`
- 코드는 형식·범위와 버전 식별자(`progress-v3`, 단위 `global_step` 등)만 검사한다
- 동결 기록 : `docs/criteria/deadlock-v0.3.json` (`criteria_sha256` `a93cc2d6…`). 설정이 이것과 다르면 테스트가 실패한다.
  값을 바꾸려면 새 criteria 버전을 만든다
- v0.1·v0.2 설정에 `criteria_parameters` 를 넣으면 프록시 시작 전 오류 (그 버전들은 코드에 고정)
- v0.2 SPEC 의 `epsilon`, `k` 는 v0.1·v0.2 판정 어디에서도 읽지 않아 v0.3 에 넣지 않았다

## 신호 (설계 2 절)

**T1 대화 신호** — 시나리오가 `t1_metrics` 의 지표를 고를 때만. 세션 전체(모든 역할)와 비교한다.

| 지표 | 진전 | 진전 아님 |
|---|---|---|
| `status_advance` | `status` 가 세션 이전 최고 상태보다 뒤 | 같은 상태 / 직전 측정 상태보다 앞으로 되돌아감 = oscillating |
| `adopted_items` | 세션에서 처음 나온 항목 ID | 재배열, 이미 나온 ID |
| `new_issue_ids` | 세션에서 처음 나온 쟁점 ID | 닫기, 다시 열기 (DM-22) |

- `status` 가 순서 목록 밖(예 : 종료 상태 `escalated`)이면 그 지표는 unmeasured. 에스컬레이션 step 에서 STOP 이 나지 않는 쪽이다 (DM-18)
- `handoff_to` 왕복 : 같은 두 역할 사이 연속 넘김 수 (A→B→A→B = 3). progress 기록의 `handoff` 에만 남기고 판정에 쓰지 않는다
- 역할의 첫 관측은 v2 와 같이 baseline 이다

**T3 산출물 신호** — 산출물 지표에 `files_changed` 가 있을 때 계산. step 의 진전 사건이 `artifact.files_changed` 뿐일 때만 적용한다.

- (a) 전역 되돌림 : 감시 파일 결합 해시가 직전 전역 step 과 다르고 세션의 더 이전 step 에 나온 상태 → oscillating
- (b) 통과 수 정체 : 통과 수가 세션 최대를 넘은 마지막 step 으로부터 K step 초과 → stagnant
- 둘 다면 (a). 다른 지표가 측정 안 됐으면 unmeasured (progress-v1 의 원칙)
- progress 기록의 `t3` 에 결합 해시, 되돌아간 step, 바뀐 파일, 최대 통과 수와 그 step, 경과 step, 그 뒤 파일 상태 변화 수를 남긴다

## T1 관측 필드 (실행기 미구현)

실행기는 아직 T1 필드를 만들지 않는다 (C-17 뒤 단위). 테스트는 설계 문서의 필드 정의대로 만든 가짜 관측값을 쓴다.

- `conversation.status`, `conversation.adopted_items`, `conversation.handoff_to` : `demo-runner-extension.md` 4 절의 계약 v3 필드
- **`conversation.status_values`** : 상태 순서 목록을 관측마다 함께 싣는다 (C-17-1 제안. 설계에 위치가 없어 정함)
- 프록시 관측 스키마(`progress_schema.py`)는 아직 이 필드와 T1 지표 이름을 받지 않는다. 바꾸지 않았다 (17-4·17-5 범위)

## 테스트

`tests/test_criteria_v03.py` : 동결 기록 일치, 설정 기본값 없음, 위조 pin 거부, 설계 4 절 표의 경우 1~7, 파라미터를
바꾸면 결과가 따라 바뀜(코드 고정값이 아님), 왕복 수가 판정에 영향 없음, 기존 세 세션의 v0.2 기록 바이트 재현과 v0.3 첫 STOP
(6 / 없음 / 9), API 경로의 `judgement_ns` 기록과 재시작.

## 원인 설명 `explain-v1` (DM-9, C-17-1 파트 2)

`explain_v1.py`. 설계 `docs/design/demo-block-and-explanation.md` 2 절의 템플릿 E1~E7 과 선택 순서 그대로.

- 입력은 판정 신호값뿐 : progress-v3 기록(`t3`, `handoff`, 지표 값)과 criteria 결과(연속 step·상태, 선언 step),
  관측의 통과 수·상태. LLM 호출 없음. narrative·reasoning·`reasons`·`evidence` 는 읽지 않는다
- 선택 : `termination_failure` → E6, 연속 구간에 T3 (a) → E2, (b) → E3, 왕복 ≥ H → E4, 채택 지표 선택 → E5,
  oscillating 포함 → E7, 그 외 E1. 하나만 낸다. E6 은 대화 과제(T1)면 뒷문장이 처리 상태
- **값이 없으면 "(측정 안 됨)" 으로 쓰고 `missing_values` 에 이름을 남긴다** (C-17-1 지시). 설계 2-1 의 "다음 순위로 넘어간다"
  와 다르다. 선택은 조건(어떤 신호가 났는가)으로만 하고, 값이 빠졌다는 이유로 다른 템플릿을 고르지 않는다
- 기록 : v0.3 criteria 의 STOP 기록(`deadlock`·`termination_failure`)마다 `explanation` =
  `{explanation_version, template_id, text, values, missing_values, signals, role_labels}`.
  `explain(signals, role_labels)` 로 같은 문장을 다시 만든다 (테스트)
- 설명 생성이 실패해도 판정은 남는다 (`explanation.status: failed`)
- 매니페스트 : `session-manifest-v0.4` = v0.3 + `guardrail.first_stop_explanation` (첫 STOP 기록의 explanation 을 복사.
  다시 만들지 않는다). criteria 가 `deadlock-v0.3` 인 세션에만. 기존 매니페스트는 그대로
- 역할 표시 : 프록시는 역할 ID(`planner`) 로 쓴다. 한국어 이름(시나리오 `role`)은 `role_labels` 로 줄 수 있으나
  프록시가 시나리오를 모르므로 지금은 쓰지 않는다 (설계 3 절 PM 결정 3 미결)
- 출처가 아직 없는 값 : E5 의 필수 항목 수(`adopted_required`), 상태 표시 이름 → 각각 "(측정 안 됨)", 상태 값 그대로

테스트 `tests/test_explain_v1.py` : 템플릿 7 개(+E6 대화형) 가짜 신호값, 자리표시자 = 기록 값, 측정 안 됨 표기, 선택 순서,
재생성, 가짜 관측 순서로 E1~E7 이 실제 STOP 기록에 나옴, 모델 텍스트 표식이 문장에 들어가지 않음, 생성 실패 시 판정 유지,
매니페스트 v0.4, API 경로 저장.
