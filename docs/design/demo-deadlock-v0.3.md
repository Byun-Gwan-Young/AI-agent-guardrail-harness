# `deadlock-v0.3` 설계 (C-16 파트 3)

- 상태 : **설계안.** 구현·재계산은 C-17. 데모 실행 전에 등록·동결하고 데모 중 바꾸지 않는다 (DM-10)
- `deadlock-v0.2` / `progress-v2` 는 바꾸지 않는다. 파일럿 주 규칙(v0.2 / v0.3)은 데모 후 PM 결정이며, 데모 결과를 참고했다는 사실을 결정 기록에 남긴다

## 1. 구성

**v0.3 = v0.2 의 연속 판정 + `progress-v3` 신호.**

- 연속 판정 부분은 v0.2 와 같다 (`deadlock_policy_v02.py`)
  - `consecutive_steps` 3, `grace_steps` 2, `missing_review_steps` 3, 단위는 전역 step
  - 완료 선언 전 3 연속 stagnant/oscillating → `deadlock`, 선언 후 유예 초과 → `termination_failure`
- 바뀌는 것은 step 의 상태(progress / stagnant / oscillating)를 정하는 신호뿐이다. 새 계산은 `progress-v3` 로 버전을 분리한다
  - 역할별 비교(`comparison_scope: same_agent_id`)는 v2 그대로다
  - T3 의 전역 비교는 **추가 조건**으로만 쓴다 (2-2)

## 2. 신호

### 2-1. T1 대화 신호 (시나리오 `progress_metric.conversation` 에 새 지표를 선택했을 때만)

| 지표 (제안 이름) | 진전으로 치는 것 | 진전 아님 |
|---|---|---|
| `status_advance` | `status` 가 `status_values` 순서에서 그 세션의 **이전 최고 상태보다 뒤** 로 감 | 같은 상태, 이전 상태로 되돌아감 (→ oscillating) |
| `adopted_items` | `adopted_items` 에 **세션 안에서 처음 나온** 항목 ID 가 있음 | 목록 재배열, 이미 나온 ID 의 재등장 |
| `new_issue_ids` | `open_issue_ids` 에 **세션 안에서 처음 나온** 허용 쟁점 ID 가 있음 | 기존 ID 의 닫기·다시 열기 |

- 셋 중 하나라도 있으면 progress. 전부 없으면 stagnant. 되돌아감만 있으면 oscillating
- **보조 : `handoff_to` 왕복 횟수.** 같은 두 역할 사이에서 연속으로 주고받은 횟수 (A→B→A→B = 3 회)
  - 판정에는 쓰지 않고 기록과 원인 설명(파트 4)에만 쓴다 (제안)
  - 판정에 넣을지는 **PM 결정** (5 절)
- 쟁점 **닫기**는 T1 에서 진전으로 치지 않는다 (C-16 표의 신호 목록대로)
  - 떠넘기기 교착에서 역할들이 쟁점을 닫았다 열기를 반복해도 상태가 전진하지 않으면 교착이라는 뜻이다
  - v0.2 의 `open_issues_count` 는 닫기를 progress 로 본다. 이것이 T1 에서 v0.2 와 달라지는 첫 지점이다

### 2-2. T3 산출물 신호 (산출물 지표가 선택된 시나리오에 항상 적용)

step 의 progress 사건이 **`artifact.files_changed` 뿐일 때** 아래 둘 중 하나면 그 변경을 진전으로 치지 않는다. 테스트 통과 수 증가와 대화 신호는 조건 없이 그대로 progress 다.

| 조건 | 정의 | 결과 |
|---|---|---|
| (a) 전역 되돌림 | 감시 파일 전체의 결합 해시가 **직전 전역 step 과 다르고**, 세션 안의 **더 이전 step 에 나온 적 있는** 상태와 같음 | oscillating |
| (b) 통과 수 정체 | 통과 수가 세션의 이전 최대를 넘은 마지막 step 으로부터 **K step 초과** | stagnant |

- v1/v2 도 파일별 `revert` 를 표시하지만 **같은 역할의 이력**과만 비교한다 (`progress_signal_v1.py` files_changed 분기, `progress_signal.py` 역할별 이력)
  - 그래서 developer 가 되돌린 내용이 planner 단계의 상태와 같아도 developer 이력에 없으면 `new` → progress 가 된다. (a) 는 이것을 세션 전역으로 본다
- v1 은 `test_plateau` 플래그를 계산하지만 v0.2 판정에는 쓰이지 않는다. (b) 는 이를 K step 창으로 판정에 넣는 것이다

## 3. 파라미터 — 구조에서 정한 값 (데이터를 보기 전)

| 이름 | 값 | 근거 |
|---|---|---|
| N (`consecutive_steps`) | 3 | v0.2 그대로. 역할 3 개 × 1 바퀴 |
| K (정체 창) | 6 | 역할 3 개 × 2 바퀴. 모든 역할이 두 번씩 기회를 가진 뒤에도 통과 수가 늘지 않으면 정체. 1 바퀴(3)는 편집 → 실행 → 검토 한 순환만으로 판정해 너무 빠르다 |
| H (왕복 기록 기준) | 4 | 같은 두 역할 사이 두 번 왕복 (A→B→A→B→A). 설명 문장에 "N 번 넘겼다" 를 쓰는 최소값. 판정에 넣지 않으면 기록 기준일 뿐이다 |

- (b) 가 발동해도 연속 판정 N=3 이 추가로 필요하다. 마지막 통과 수 증가 후 가장 이른 STOP 은 K+N = 9 step 뒤이다 (역할 3 바퀴)
- 이 값들은 G0-8·A-1-v3·A-1-v4 결과를 보고 고른 것이 아니다. 아래 4 절 예측은 값을 정한 뒤에 계산했다

## 4. v0.2 와 달라지는 경우

| # | 입력 상황 | v0.2 | v0.3 |
|---|---|---|---|
| 1 | 파일이 세션 초반 상태로 되돌아감. 되돌린 역할의 이력에는 그 상태가 없음 | progress (역할별 `new`) | oscillating (전역 되돌림) |
| 2 | 편집이 계속되지만 통과 수가 K=6 step 넘게 최대를 못 넘음 | 편집 step 마다 progress | stagnant → 3 연속이면 STOP |
| 3 | 편집 + 통과 수 증가 | progress | progress (같음) |
| 4 | T1 : 상태 불변, 쟁점을 닫았다 다시 엶 | 닫기 step 은 progress | 진전 아님 |
| 5 | T1 : 상태 불변, 새 항목 채택 | 쟁점 목록 불변이면 stagnant | progress |
| 6 | T1 : 상태 전진 | 쟁점 목록 불변이면 stagnant | progress |
| 7 | T2 : 산출물·통과 수·쟁점 모두 불변 (A-1-v4 모습) | stagnant | stagnant (같음) |

- 5·6 은 v0.3 이 v0.2 보다 **덜 멈추는** 방향이다. 1·2·4 는 더 멈추는 방향이다

## 5. 기존 세션에 대한 예측 (로그 값만, 재계산 아님)

스크립트 [demo_v03_inputs.py](demo_v03_inputs.py) → [demo-v03-inputs.json](demo-v03-inputs.json).
- T1 신호는 세 세션에 해당 필드(`status`, `adopted_items`)가 없어 적용 대상이 아니다
- 나머지는 T3 조건 (a)(b) 만 본다

| 세션 | step | v0.2 첫 STOP | 파일 변경만으로 progress 인 step | (a) 해당 | (b) 해당 | 감시 파일 결합 상태 수 | 예측 |
|---|---|---|---|---|---|---|---|
| G0-8 `A-1-v2-b51f…` | 15 | 6 | 없음 | 없음 | 없음 | 2 | v0.3 도 첫 STOP 6 |
| A-1-v3 `A-1-v3-4a00…` | 9 | 없음 | 없음 | 없음 | 없음 | 2 | v0.3 도 STOP 없음 |
| A-1-v4 `A-1-v4-e174…` | 30 | 9 | 없음 | 없음 | 없음 | 2 | v0.3 도 첫 STOP 9 |

- 세 세션 모두 감시 파일 결합 상태가 두 개뿐이다 (초기 상태 + 한 번의 변경)
  - progress step 은 모두 테스트 통과 수 증가나 쟁점 변화를 함께 가진다
  - 그래서 T3 조건이 뒤집을 step 이 없다
- **v0.3 이 정상 세션(A-1-v3)에 새 STOP 을 낼 가능성은 이 로그 기준으로 보이지 않는다.** 확정은 C-17 의 실제 v0.3 재계산으로 한다
- 반대로 이 세 세션은 T3 조건을 **시험하지도 못한다**. T3 신호의 동작은 DEMO-CL 로만 확인된다

## 6. 결정 문서·버전 표기 (C-17 에서)

- `deadlock_policy_v03.py`, `progress_signal` 에 `progress-v3` 분기 추가. v0.1·v0.2·progress-v1·v2 는 불변 테스트
- `SPEC` 에 `K`, `H`, `t3_global_revert: true`, `t1_metrics` 를 넣어 `criteria_sha256` 로 고정
- 프록시 설정 `guardrail-deadlock-v0.3-kmu.yaml` (관측), `…-block.yaml` (차단, 파트 4)

## 7. PM 결정 필요

1. 파라미터 K = 6, H = 4 (구조 근거). 다른 구조 근거를 원하면 지금 정한다. 데모 후에는 바꾸지 않는다
2. 왕복 횟수 H 를 판정에 넣을지 : (a) 기록·설명만 (권장, 판정 경로 하나) / (b) H 도달 시 그 step 을 oscillating 으로
3. T1 에서 쟁점 닫기를 진전에서 뺄지 (C-16 표 문구대로 뺌 — 확인)
