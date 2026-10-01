# DM-10 · DM-22: `deadlock-v0.3` / `progress-v3` (데모 트랙 판정 규칙)

PM 결정 DM-10 (2026-09-29), DM-22 (C-16 결정 8), DM-26~DM-28 (C-17-1 결정, C-17-2 반영). 설계 `docs/design/demo-deadlock-v0.3.md`. 구현 C-17-1, 재동결 C-17-2.
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
- C-17-2 부터 동결 기록은 **코드와 템플릿도** 고정한다 (아래 "C-17-2 재동결")
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
- **통과 수 진전 (DM-28, C-17-2)** : progress-v1 의 역할별 `test_pass_count` 사건(`improved`/`regressed`)은 통과 수가
  **세션의 이전 최대(모든 역할, 같은 suite·total)를 넘을 때만** 진전 사건으로 남긴다. 감소, 최대 아래(또는 최대와 같은 값)로의
  회복은 사건에서 빠지고 progress 기록 `pass_count` 에 `role_event`, `session_max_before`, `new_session_max`,
  `counted_as_progress` 로만 남는다. 그래서 파일 변경 + 통과 수 감소 step 은 "파일 변경만의 진전" 이 되어 (a)(b) 를 받는다
- 둘 다면 (a). 다른 지표가 측정 안 됐으면 unmeasured (progress-v1 의 원칙)
- progress 기록의 `t3` 에 결합 해시, 되돌아간 step, 바뀐 파일, 최대 통과 수와 그 step, 경과 step, 그 뒤 파일 상태 변화 수를 남긴다

## T1 관측 필드 (실행기 미구현)

실행기는 아직 T1 필드를 만들지 않는다 (C-17 뒤 단위). 테스트는 설계 문서의 필드 정의대로 만든 가짜 관측값을 쓴다.

- `conversation.status`, `conversation.adopted_items`, `conversation.handoff_to` : `demo-runner-extension.md` 4 절의 계약 v3 필드
- ~~`conversation.status_values` : 상태 순서 목록을 관측마다 함께 싣는다 (C-17-1 제안)~~ → **세션 등록으로 옮겼다 (DM-35, C-17-3).**
  progress-v3 는 상태 순서를 세션 등록에서만 읽고, 등록이 없으면 `status_advance` 는 unmeasured. 관측 스키마는 `status_values` 를 받지 않는다
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
  oscillating 포함 → E7, 세션에 테스트 관측 없음 → E1-T1 (DM-27, C-17-2), 그 외 E1. 하나만 낸다.
  E6 은 대화 과제(T1)면 뒷문장이 처리 상태. 순서는 `explain_v1.SELECTION_ORDER` 한 곳에 있다
- **값이 없으면 "(측정 안 됨)" 으로 쓰고 `missing_values` 에 이름을 남긴다** (C-17-1 지시). 설계 2-1 의 "다음 순위로 넘어간다"
  와 다르다. 선택은 조건(어떤 신호가 났는가)으로만 하고, 값이 빠졌다는 이유로 다른 템플릿을 고르지 않는다
- 기록 : v0.3 criteria 의 STOP 기록(`deadlock`·`termination_failure`)마다 `explanation` =
  `{explanation_version, template_id, text, values, missing_values, signals, role_labels}`.
  `explain(signals, role_labels)` 로 같은 문장을 다시 만든다 (테스트)
- 설명 생성이 실패해도 판정은 남는다 (`explanation.status: failed`)
- 매니페스트 : `session-manifest-v0.4` = v0.3 + `guardrail.first_stop_explanation` (첫 STOP 기록의 explanation 을 복사.
  다시 만들지 않는다). criteria 가 `deadlock-v0.3` 인 세션에만. 기존 매니페스트는 그대로
- 역할 표시 (DM-26) : 한국어 표시 이름. `evaluate_criteria(observations, pin, role_labels)` 가 맵을 받으면 이름을, 맵에 없는
  역할은 ID 를 쓴다. 등록 경로(실행기가 세션 시작 때 한 번 등록)는 실행기 T1 단위이고, 그 전까지 프록시는 역할 ID 로 쓴다
- 출처가 아직 없는 값 (DM-29) : E5 의 필수 항목 수(`adopted_required`), 상태 표시 이름 → 실행기 T1 단위까지 각각
  "(측정 안 됨)", 상태 값 그대로

테스트 `tests/test_explain_v1.py` : 템플릿 7 개(+E6 대화형) 가짜 신호값, 자리표시자 = 기록 값, 측정 안 됨 표기, 선택 순서,
재생성, 가짜 관측 순서로 E1~E7 이 실제 STOP 기록에 나옴, 모델 텍스트 표식이 문장에 들어가지 않음, 생성 실패 시 판정 유지,
매니페스트 v0.4, API 경로 저장.

## C-17-2 재동결 (DM-26 · DM-27 · DM-28)

v0.3 으로 판정된 실행 세션이 0 개이므로 새 criteria 버전 없이 **v0.3 자리에서 고치고 다시 동결**한다 (S-31 과 같은 원칙).
파라미터는 바뀌지 않았다. 그래서 `criteria_sha256` (파라미터 해시) 은 그대로 `a93cc2d6…` 이고, 바뀐 것은 코드와 템플릿이다.

**바뀐 이유**

- DM-28 : T3 (b) 는 "파일 변경만의 진전" 에만 적용되는데, progress-v1 의 역할별 `regressed`·`improved` 사건이 진전으로 남아
  파일 변경 + 통과 수 감소(또는 최대 아래 회복) step 이 T3 를 비켜 갔다. 고쳤다 되돌렸다 하며 통과 수가 오르내리는 교착을 놓친다.
  통과 수 진전을 "세션 최고 통과 수 갱신" 으로만 좁힌다. 정당한 리팩터링의 일시적 하락은 K = 6 step 여유가 흡수한다
  (K 안에서는 파일 변경이 여전히 진전이다)
- DM-27 : 테스트 관측이 없는 T1 세션에서 E1 이 "통과 테스트 (측정 안 됨)/(측정 안 됨)" 을 냈다. 같은 자리에 E1-T1
  "최근 {n} step 동안 {roles} 모두 처리 상태 변화·채택 항목·새 쟁점이 없습니다. 처리 상태 '{status}'." 을 둔다.
  조건은 STOP 까지의 관측 중 `artifact.test_pass_count` 가 하나도 없음 (`signals.test_observed_in_session = false`).
  이 키가 없는 C-17-1 기록은 E1 로 다시 만들어진다
- DM-26 : 역할 표시 이름 맵을 판정 경로에서 설명까지 넘길 수 있게만 했다 (위 "역할 표시"). 형식이 틀린 맵은 설명 생성 실패
  (`explanation.status: failed`) 로 남고 판정은 그대로다

**선택 순서 (explain-v1, 동결)** : E6 `termination_failure` → E2 `global_revert_in_streak` → E3 `test_plateau_in_streak` →
E4 `handoff_at_or_above_threshold` → E5 `adopted_items_selected` → E7 `oscillating_in_streak` →
E1-T1 `no_test_observation_in_session` → E1 `otherwise`

**동결 기록이 담는 것 (C-17-2 부터)**

- `docs/criteria/deadlock-v0.3.json` = 기존 pin (`criteria_version`, `criteria_parameters`, `criteria_sha256`) +
  `implementation_sha256` (`deadlock_policy_v03.py`, `explain_v1.py`, `progress_signal_v3.py`) +
  `explanation_record` + `explanation_templates_sha256`
- `docs/criteria/explain-v1.json` (새 파일, 템플릿 동결 기록) = 템플릿, E6 대화형 문장, 선택 순서, `(측정 안 됨)` 표기,
  그 정규 JSON 의 `templates_sha256`
- 둘 다 `tools/write_criteria_snapshot.py --config guardrail-deadlock-v0.3-kmu.yaml --refreeze` 출력이다. `--refreeze` 없이
  내용이 다르면 쓰지 않는다. `progress_signal.py`·`progress_signal_v1.py` 는 기존 보호 목록(`c17-1-protected-files.json`)이 고정한다
- 테스트(`tests/test_criteria_v03.py`)가 파일 해시와 템플릿 기록을 현재 코드와 비교한다. 이후 v0.3 코드나 템플릿을 고치면
  테스트가 실패하므로, PM 지시로 다시 동결하거나 새 버전을 만들어야 한다
- 세션 기록에는 이 해시가 들어가지 않는다. 세션이 어떤 코드로 판정됐는지는 실행기가 기록하는 `git_commit` 으로 잇는다 (S-7)

**이전 해시 (C-17-1, `060c8c4`) → 새 해시 (C-17-2)**

| 대상 | 이전 | 새 |
|---|---|---|
| `docs/criteria/deadlock-v0.3.json` 파일 | `4dd9d26982575e2a6497d5e065a0e267b1ce6a017fc2b50c7140292d181128b6` | `9812a6687b49081134057ec7ce99cb91165a4a4af09cc8594a95c6d62e306db9` |
| `criteria_sha256` (파라미터) | `a93cc2d638ed046d928778eb541cf8cc436353d6b2e103ed600cb963bee0ed50` | 같음 |
| `deadlock_policy_v03.py` | `9f07795bbaa1a2bd634409e33bf641cf0d76d65723c3768003b148ff3e06a0bc` | `6656ed11a1ca0b2336e73302b2dcc3e9adc64dd64d55bf701967b08accc14f80` |
| `explain_v1.py` | `90c2e518b726a7676b74edf29a20e38d9a8970ed48a2ce99aa13b4fd96567e4c` | `c31630306c3d9f9908aecad39a3d8a90fae1a077a198d27b29bae56f4861a6ec` |
| `progress_signal_v3.py` | `47015012116560d5ed3596a17fc45ee8b67fb051828293f1c8ff6afca508ad54` | `660b5f4f0d77ce8189e3fea6c033315b7866144c374b5ec1c00a06d8835b6245` |
| `docs/criteria/explain-v1.json` 파일 | 없음 (템플릿은 `explain_v1.py` 상수와 이 문서 서술뿐) | `9ef9dd422fcc8e3a61ebf6e70c802dd3714d0ba969200ad56097393ddf6e9e1f` |
| `explanation_templates_sha256` | 없음 | `48ab596444e6fa5e8e59d7c7d493c583bc06bccc8e8cde48c6a345e0edafafb9` |

이전 파일 해시는 `git show 060c8c4:<파일> | shasum -a 256` 출력, 새 해시는 스냅샷 도구 출력이다.

**기존 세션 재계산** (`tools/recompute_v03.py --previous reports/c17-1/v03-recompute.json` → `reports/c17-2/v03-recompute.json`)

- 첫 STOP G0-8 6 / A-1-v3 없음 / A-1-v4 9 그대로, A-1-v3 새 STOP 없음, v0.2 재계산 바이트 동일
- C-17-1 보고 대비 v0.3 상태·판정이 바뀐 step 0, 첫 STOP 문장 동일
- DM-28 이 역할별 통과 수 사건(`improved`, 세션 최대와 같은 값)을 진전에서 뺀 step : G0-8 step 15, A-1-v3 step 6·7.
  앞 역할이 올린 통과 수를 다음 역할들이 자기 이전 관측과 비교해 다시 본 경우다 (G0-12). 셋 다 같은 step 에 A-1 대화 지표
  `open_issues_count` 의 쟁점 닫기 사건과 파일 변경 사건이 있어 progress 로 남는다 ("파일 변경만의 진전" 이 아니라 T3 미적용).
  세 세션에 T3 (a)(b) 적용 step 은 없다

## C-17-3 파트 0 재동결 (DM-30 · DM-31 · DM-33)

- **DM-30** : C-17-2 의 DM-28 해석(K 안의 "파일 변경 + 통과 수 감소" 는 파일 변경 때문에 진전, 최고값과 같은 값으로의 회복은
  진전 아님)을 그대로 확정. 코드 변경 없음
- **DM-31** : E1·E1-T1 은 판정에 쓰인 지표의 신호만 나열한다. 고르지 않은 신호를 "없다" 고 쓰지 않는다
  - 신호 기록에 `selected_metrics` 를 넣는다 = STOP 관측의 `progress_metric` 중 `progress_source` 로 실제 판정된 것
    (`conversation.*` 는 source 가 conversation/both 일 때만, `artifact.*` 는 artifact/both 일 때만)
  - 지표 → 문구 (이 순서로 나열, 같은 문구는 한 번) : `artifact.files_changed` 산출물 변경, `artifact.test_pass_count` 테스트 증가,
    `artifact.build_status` 빌드 상태 변화, `conversation.status_advance` 처리 상태 변화, `conversation.adopted_items` 채택 항목,
    `conversation.new_issue_ids` 새 쟁점, `conversation.open_issues_count` 새 쟁점, `conversation.proposal_value_delta` 제안 값 변화,
    `conversation.new_info_ratio` 새 정보
  - 템플릿은 `{signals}` 자리 하나로 바뀌었다 : E1 "최근 {n} step 동안 {roles} 모두 {signals} 없습니다. 통과 테스트 {pass}/{total}.",
    E1-T1 "… 모두 {signals} 없습니다. 처리 상태 '{status}'." `{signals}` 는 문구를 "·" 로 잇고 마지막 음절의 받침으로 조사 이/가를 붙인다
  - A-1 계열(대화 `open_issues_count`, 산출물 `test_pass_count`·`files_changed`)은 세 신호를 다 고르므로 문장이 이전과 같다
  - `selected_metrics` 가 없는 이전 기록은 만들어질 때의 문장(세 신호 모두)으로 다시 만들어진다
- **DM-33** : C-17 단위에서 코드가 바뀔 때마다 재동결하고 이전 해시를 여기에 남긴다. 최종 동결은 C-19 본 실행 직전

**이전 해시 (C-17-2, `2847d62`) → 새 해시 (C-17-3 파트 0)**

| 대상 | 이전 | 새 |
|---|---|---|
| `docs/criteria/deadlock-v0.3.json` 파일 | `9812a6687b49081134057ec7ce99cb91165a4a4af09cc8594a95c6d62e306db9` | `1109d6c23ce27c52ad423122a3aa60e846c1c4cbc7616816a1498ee0f45d49ae` |
| `criteria_sha256` (파라미터) | `a93cc2d638ed046d928778eb541cf8cc436353d6b2e103ed600cb963bee0ed50` | 같음 |
| `deadlock_policy_v03.py` | `6656ed11a1ca0b2336e73302b2dcc3e9adc64dd64d55bf701967b08accc14f80` | 같음 |
| `explain_v1.py` | `c31630306c3d9f9908aecad39a3d8a90fae1a077a198d27b29bae56f4861a6ec` | `555edeb72db658d050e77484b2e724d2487e5ac73d66fd1d9bca612b3700577f` |
| `progress_signal_v3.py` | `660b5f4f0d77ce8189e3fea6c033315b7866144c374b5ec1c00a06d8835b6245` | 같음 |
| `docs/criteria/explain-v1.json` 파일 | `9ef9dd422fcc8e3a61ebf6e70c802dd3714d0ba969200ad56097393ddf6e9e1f` | `dd877389e23b56cb82b98beb6aff5cbff48af10d3932c177b5c96230140e0eae` |
| `explanation_templates_sha256` | `48ab596444e6fa5e8e59d7c7d493c583bc06bccc8e8cde48c6a345e0edafafb9` | `7729d2d6af7ab58ecae9c0e4eb70245ac36b8c2960187ae2eff6c7cf6e67151a` |

템플릿 동결 기록에 `signal_phrases` 와 `unrecorded_selection_phrases` 를 더했다.

**기존 세션 재계산** (`tools/recompute_v03.py --previous reports/c17-2/v03-recompute.json --output reports/c17-3/v03-recompute.json`.
`--output` 은 이제 필수라 이전 단위 보고를 덮어쓰지 않는다)

- 첫 STOP 6 / 없음 / 9, A-1-v3 새 STOP 없음, v0.2 바이트 동일, C-17-2 보고 대비 v0.3 상태·판정 변화 0, 첫 STOP 문장 동일

## C-17-3 파트 2 재동결 (DM-26 · DM-29 · DM-35 세션 등록)

- 세션 등록(`docs/decisions/015` 의 등록 절)을 판정·설명이 읽는다
  - `progress_signal_v3.calculate_progress(history, current, parameters, registration)` : `status_advance` 의 상태 순서는 등록의
    `status_values` (id 순서). 관측의 `status_values` 는 읽지 않는다. 등록이 없으면 unmeasured ("status order not registered for the session")
  - `evaluate_criteria(observations, pin, registration)` (C-17-2 의 `role_labels` 인자를 대체) → `signals_from(..., registration)`,
    `explain(signals, role_labels, status_labels)`
  - 신호값 : `adopted_required` = 등록의 `required_adopted_items` (없으면 "(측정 안 됨)"), `selected_metrics` = 등록의 지표 선택
    (관측 API 가 관측의 선택이 등록과 같을 때만 받으므로 STOP 관측의 선택과 같다. 등록이 없으면 STOP 관측에서)
  - 문장 : 역할은 등록 `role_labels`, 처리 상태(E1-T1·E4·E5·E6 대화형)는 등록 상태 이름. 신호값에는 원래 ID 가 남고 표시 이름은 `values` 에만.
    STOP 기록은 `role_labels`·`status_labels` 를 함께 남겨 `explain(signals, role_labels, status_labels)` 로 같은 문장을 다시 만든다
  - 등록이 없으면 지금처럼 ID·"(측정 안 됨)"
- 판정 결과(상태·결정)는 등록의 표시 값과 무관하다 (같은 관측에 등록 유무만 바꾼 테스트)
- 템플릿·문구는 바뀌지 않아 `explain-v1.json` 과 `explanation_templates_sha256` 은 파트 0 값 그대로다

**이전 해시 (C-17-3 파트 0, `7987b38`) → 새 해시 (C-17-3 파트 2)**

| 대상 | 이전 | 새 |
|---|---|---|
| `docs/criteria/deadlock-v0.3.json` 파일 | `1109d6c23ce27c52ad423122a3aa60e846c1c4cbc7616816a1498ee0f45d49ae` | `77d4c7b85e68ebc3b87a04c5c6ef0d9fe5e5a6eed30d0253f1f2d8cf14593a08` |
| `criteria_sha256` (파라미터) | `a93cc2d638ed046d928778eb541cf8cc436353d6b2e103ed600cb963bee0ed50` | 같음 |
| `deadlock_policy_v03.py` | `6656ed11a1ca0b2336e73302b2dcc3e9adc64dd64d55bf701967b08accc14f80` | `794f65e26211b7bcebbe4deadfa3e30f30dbaecc6fe361681854db23e2cef3b0` |
| `explain_v1.py` | `555edeb72db658d050e77484b2e724d2487e5ac73d66fd1d9bca612b3700577f` | `926e83577618ee61ea489e94abf3990a8985fbb93952c540a0345e335bbe1dc9` |
| `progress_signal_v3.py` | `660b5f4f0d77ce8189e3fea6c033315b7866144c374b5ec1c00a06d8835b6245` | `dc727697e0832a305569839d3fc347f36c093a09811e93183cc4fc478a8d6c94` |
| `docs/criteria/explain-v1.json` 파일 | `dd877389e23b56cb82b98beb6aff5cbff48af10d3932c177b5c96230140e0eae` | 같음 |
| `explanation_templates_sha256` | `7729d2d6af7ab58ecae9c0e4eb70245ac36b8c2960187ae2eff6c7cf6e67151a` | 같음 |

**기존 세션 재계산** (`--previous reports/c17-3/v03-recompute.json --output reports/c17-3/v03-recompute-part2.json`) :
첫 STOP 6 / 없음 / 9, A-1-v3 새 STOP 없음, v0.2 바이트 동일, 파트 0 대비 상태·판정 변화 0, 첫 STOP 문장 동일 (세 세션은 등록이 없는 세션이다)

## C-17-4 파트 0 재동결 (DM-36 이름 뒤 조사)

- **DM-36** : 역할·상태 이름 자리 뒤 조사(과/와, 이/가, 은/는, 을/를)를 DM-31 의 받침 규칙으로 고르고 이름에 붙여 쓴다
  - 템플릿이 조사를 자리 표기로 적는다 : `{role_a:과/와}` = 받침 있으면 앞, 없으면 뒤 (`explain_v1.Slot`, 허용 쌍 `explain_v1.PARTICLES`).
    받침 판단은 DM-31 과 같다 (`has_final_consonant` : 마지막 글자가 받침 있는 한글 음절. 역할 ID 같은 비한글은 받침 없음).
    `(측정 안 됨)` 에는 조사를 붙이지 않는다 (DM-31 이 쓰던 그대로)
  - 고친 자리 : **E4 만** — "{role_a:과/와} {role_b:이/가} 문의를 서로 …" ("환불 담당과 배송 담당이", "검토자와 작성자가",
    등록 이름이 없어 ID 로 대체되면 "refund와 shipping가")
  - 같은 표기로 옮긴 자리 : E1·E1-T1 의 `{signals:이/가}` (DM-31). 문장은 이전 `render_subject` 와 같다 (테스트)
  - 해당 없음 (보고) : 상태 이름 자리는 모두 따옴표 뒤에 `에서`(E4)·`입니다`(E5·E6 대화형)·`.`(E1-T1) 가 온다 — 네 쌍이 아니라 고르지 않았고
    띄어쓰기도 그대로 두었다. E2 의 "{path} 가" 는 파일 경로 자리라 이름 자리가 아니다 (그대로). E1·E1-T1 의 `{roles} 모두` 는 조사가 아니다
- 동결 기록 `explain-v1.json` 에 `particles` 를 더했다. 선택 순서·문구는 바뀌지 않았다

**이전 해시 (C-17-3 파트 2, `7ef2e5c`) → 새 해시 (C-17-4 파트 0)**

| 대상 | 이전 | 새 |
|---|---|---|
| `docs/criteria/deadlock-v0.3.json` 파일 | `77d4c7b85e68ebc3b87a04c5c6ef0d9fe5e5a6eed30d0253f1f2d8cf14593a08` | `6bd633832e561b4caeeacaa1c1e9586144131c2f24bcf4d68b8d5b0152fe15c5` |
| `criteria_sha256` (파라미터) | `a93cc2d638ed046d928778eb541cf8cc436353d6b2e103ed600cb963bee0ed50` | 같음 |
| `deadlock_policy_v03.py` | `794f65e26211b7bcebbe4deadfa3e30f30dbaecc6fe361681854db23e2cef3b0` | 같음 |
| `explain_v1.py` | `926e83577618ee61ea489e94abf3990a8985fbb93952c540a0345e335bbe1dc9` | `174228410523729b474621763e100a1b2f4223c0267c40b5e4d3c62cd4726027` |
| `progress_signal_v3.py` | `dc727697e0832a305569839d3fc347f36c093a09811e93183cc4fc478a8d6c94` | 같음 |
| `docs/criteria/explain-v1.json` 파일 | `dd877389e23b56cb82b98beb6aff5cbff48af10d3932c177b5c96230140e0eae` | `1acf469e8b7b10f6113f25d6a38e57594771aec68ea5f3b1500fbc2931aa875b` |
| `explanation_templates_sha256` | `7729d2d6af7ab58ecae9c0e4eb70245ac36b8c2960187ae2eff6c7cf6e67151a` | `f2a93b937e110f9e29a29ba665cfb8a01a35dd6872f7589945c4f24f378813a8` |

**기존 세션 재계산** (`--previous reports/c17-3/v03-recompute-part2.json --output reports/c17-4/v03-recompute.json`) :
첫 STOP 6 / 없음 / 9, A-1-v3 새 STOP 없음, v0.2 바이트 동일, 이전 대비 상태·판정 변화 0, 첫 STOP 문장 동일
(세 세션의 STOP 은 모두 E1 이고 E4 가 없다)
