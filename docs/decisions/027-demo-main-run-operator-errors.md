# 본 실행 운영 실수 정리 : 검색 키 오타 · 두 번째 실패 · 계정 이름표 (C-18-8)

재실행(10/6 22:25~10/7 00:04 KST)과 MR 보충(`demo-main-v1-mr2`, 10/7 00:19~00:29 KST) 뒤에 확인된 운영 실수 세 가지(DM-81)의 진단 수치와, C-18-8 에서 바꾼 것을 남긴다. 026 (C-18-7) 을 잇는다.
세션 값은 모두 `tools/demo_exclusions.py` (`demo-exclusions-v2`) 를 세 계획(`demo-main-v1`, `demo-main-v1-lr2`, `demo-main-v1-mr2`)에 돌린 출력이다 (세션 기록·프록시 로그의 상태 코드·대기 시간·검색 기록의 결과 종류와 HTTP 상태만 읽음. 모델 출력·reasoning 은 읽지 않음). PM 이 C-18-8 명령서 1 절에서 같은 명령으로 `reports/c18-8/exclusions.json` 을 만든다.

## 레인 상태 (C-18-8 시작 시)

`demo-main-v1` 레인 1~4, `demo-main-v1-lr2`, `demo-main-v1-mr2` 의 마지막 실행이 모두 `lane_finished`. 세션 98 개 = 본 실행 82 (재실행 포함) + LR 보충 13 + MR 보충 3. `git_commit` 은 `e3341e5` 81 개 (본 실행·LR 보충), `163b723` 17 개 (재실행 14 + MR 보충 3), `git_dirty` 는 모두 false.

## 진단 1 — 검색 키 오타 (DM-81 ①)

창 2 에서 들어간 Tavily 키가 잘못된 문자열이었다. 검색 기록(`search/records.jsonl`)의 HTTP 상태로 본다.

| 항목 | 레인 · 이름표 | 세션 | 검색 호출 | 종료 |
|---|---|---|---|---|
| `DEMO-MR-normal-v1:observe:3` | 2 · B | `0382a780…` | 4 회 모두 401 | `escalated` 4 step |
| `DEMO-MR-stall-v1:observe:4` | 2 · B | `0c6719c3…` | 5 회 모두 401 | `escalated` 3 step |
| `DEMO-MR-stall-v1:block:3` | 3 재실행 · C | `82564d3c…` | 5 회 모두 401 | `escalated` 4 step |
| `DEMO-MR-stall-v1:observe:1` | 2 · B | `5a05895c…` | 검색 기록 없음 | `escalated` 1 step → **유효** |
| `DEMO-MR-stall-v1:block:2` | 2 · B | `60b59c82…` | 검색 기록 없음 | `escalated` 1 step → **유효** |

401·403 이 있는 세션은 이 3 개뿐이다 (98 세션 전체). 401 응답 본문은 "Unauthorized: missing or invalid API key." 다.

## 진단 2 — 두 번째 실패 (DM-81 ③)

| 항목 | 첫 실패 | 재실행 | 재실행의 실패 요청 | 업스트림 대기 |
|---|---|---|---|---|
| `DEMO-CL-stall-v1:observe:2` | `0cd6385b…` 프록시 120 초 시간 초과 (21 step) | `d4ba1c9f…` 28 step | turn 76, **504** | 300.48 s |
| `DEMO-CT-stall-v1:block:3` | `bf36c7d9…` 프록시 120 초 시간 초과 (4 step) | `b12151a1…` 2 step | turn 5, **504** | 300.15 s |

프록시가 만든 502 (600 초 제한) 가 아니라 **업스트림 게이트웨이가 약 300 초에서 끊고 돌려준 504** 다. DM-79 ③ 대로 세 번째는 돌리지 않는다 → 두 항목은 "실행 환경 사유 미완료". 데이터셋 트랙 전에 게이트웨이의 약 300 초 제한을 조건으로 적는다 (프록시 600 초는 그보다 길어 실제 상한은 게이트웨이다).

## 결정 1 — 제외 규칙 추가 (`demo-exclusions-v2`)

| 사유 코드 | 규칙 | 이번 세션 수 |
|---|---|---|
| `env_search_unavailable` | `demo-main-v1` 의 DEMO-LR 세션 전체 (DM-78 ③, 그대로) | 13 |
| **`env_search_key_invalid`** | 검색 호출 중 HTTP 401·403 이 하나라도 있음 (종료 분류와 무관) | 3 |
| **`incomplete_after_retry`** | runner_error 이고 그 세션 자체가 재실행 (`batch.rerun_of` 있음). 원인은 `evidence.cause` 에 502·504 규칙으로 (504 = `env_upstream_504`) | 2 |
| `env_upstream_timeout` | runner_error + 프록시가 만든 502 + 대기 120 초 이상 (그대로) | 9 |
| `env_upstream_502` | runner_error + 업스트림이 보낸 502 (그대로) | 3 |
| `run_interrupted` | `user_interrupted` (그대로) | 1 |

- 규칙은 위 순서대로 첫 번째로 맞는 것 하나. 첫 실패가 504 이면 정할 규칙이 없으므로 `unresolved` 로 올리고 도구가 끝 코드 1 을 낸다 (이번에는 0 건)
- **보충 세션으로 대체** : 재실행으로 대체되지 않은 제외 세션은, 보충 계획(`demo-main-v1-<x>`)에 같은 항목 세션이 있으면 그것으로 `replaced_by`. 같은 항목에 다른 후보(재실행, 유효 세션, 두 번째 보충 세션)가 있거나 바꿀 제외 세션이 없으면 대체하지 않고 `unresolved` (이번에는 0 건)
- 출력에 항목별 최종 상태 `items` 를 더했다 (유효 세션, 없으면 마지막으로 시도한 세션의 사유)
- 집계(`aggregate_demo.py`)는 v1·v2 목록을 모두 받는다. v2 목록이면 머리 줄이 "재실행·보충 세션으로 대체" 로 바뀐다

**결과** : 세션 98, 제외 31, 대체 28 (재실행 12 + LR 보충 13 + MR 보충 3), `unresolved` 0, `unfinished` 0. 계획 항목 70 개 중 **유효 67**, 유효 세션 없음 3.

## 항목별 최종 상태

제외 세션이 없는 42 항목은 세션 하나가 그대로 유효하다. 아래는 제외 세션이 있는 28 항목 (세션 ID 앞 8 자, `⇒` = `replaced_by`).

| 항목 | 경과 | 최종 |
|---|---|---|
| CL-normal 관측 #1 | `c1ff4dc4` runner_error → env_upstream_timeout ⇒ `51aef935` success | 유효 |
| CL-stall 관측 #2 | `0cd6385b` runner_error → env_upstream_timeout ⇒ `d4ba1c9f` runner_error → incomplete_after_retry (504, 300.5 s) | **미완료** |
| CL-stall 차단 #3 | `1372b13b` runner_error → env_upstream_502 ⇒ `3f94b297` guardrail_stop | 유효 |
| CT-stall 관측 #1 | `000a538a` → env_upstream_timeout ⇒ `df08a5f8` max_steps | 유효 |
| CT-stall 관측 #3 | `7634c328` → env_upstream_timeout ⇒ `1b7bd963` max_steps | 유효 |
| CT-stall 관측 #4 | `eba5a575` → env_upstream_timeout ⇒ `79fdaab1` max_steps | 유효 |
| CT-stall 관측 #5 | `18b69568` → env_upstream_timeout ⇒ `0d834a82` max_steps | 유효 |
| CT-stall 차단 #1 | `158e7cac` → env_upstream_timeout ⇒ `34b05804` guardrail_stop | 유효 |
| CT-stall 차단 #2 | `b3ae9954` → env_upstream_timeout ⇒ `46ea7790` guardrail_stop | 유효 |
| CT-stall 차단 #3 | `bf36c7d9` → env_upstream_timeout ⇒ `b12151a1` runner_error → incomplete_after_retry (504, 300.1 s) | **미완료** |
| MR-normal 관측 #3 | `0382a780` escalated → env_search_key_invalid ⇒ `d69416ae` (MR 보충) success | 유효 |
| MR-normal 관측 #5 | `8a458208` runner_error → env_upstream_502 ⇒ `c0daa4d6` success | 유효 |
| MR-stall 관측 #4 | `0c6719c3` escalated → env_search_key_invalid ⇒ `7cee4bcb` (MR 보충) escalated | 유효 |
| MR-stall 차단 #1 | `173d03d6` runner_error → env_upstream_502 ⇒ `54ca8a07` escalated | 유효 |
| MR-stall 차단 #3 | `82564d3c` escalated → env_search_key_invalid ⇒ `abb47045` (MR 보충) escalated | 유효 |
| LR-normal 관측 #1~#5 | 본 실행 5 개 → env_search_unavailable ⇒ LR 보충 5 개 모두 success | 유효 5 |
| LR-stall 관측 #1~#5 | 본 실행 5 개 → env_search_unavailable ⇒ LR 보충 5 개 모두 escalated | 유효 5 |
| LR-stall 차단 #1·#2 | 본 실행 → env_search_unavailable ⇒ LR 보충 escalated | 유효 2 |
| LR-stall 차단 #3 | `07bae846` → env_search_unavailable ⇒ `445ab1ba` (LR 보충) user_interrupted 0 step → run_interrupted | **미완료** (DM-80 ②) |

시나리오·모드별 유효 수 : CL-stall 관측 **4 / 5**, CT-stall 차단 **2 / 3**, LR-stall 차단 **2 / 3**, 나머지 13 묶음은 계획 수 그대로 (관측 5 / 5, 차단 3 / 3).

## 결정 2 — 계정 이름표 보정 (DM-81 ②)

재실행을 원래 레인 창이 아닌 창에서 돌렸다. 기록의 `account_label` 은 레인의 원래 값이다. **키는 어떤 기록에도 없으므로 실제 계정은 PM 진술(DM-81 ②, 10/7)이 근거다.** 적용 대상은 규칙으로 고른다 : 계획 `demo-main-v1` + `git_commit` `163b723` (재실행 커밋) + 레인 1~3. 보정 파일 `reports/c18-8/account-corrections.json` (`tools/demo_account_corrections.py`).

| 레인 | 이름표 | 실제 계정 | 세션 (앞 8 자, 항목) |
|---|---|---|---|
| 1 | A | **C** | `51aef935` CL-normal 관측 #1 · `d4ba1c9f` CL-stall 관측 #2 · `df08a5f8` CT-stall 관측 #1 · `79fdaab1` CT-stall 관측 #4 · `c0daa4d6` MR-normal 관측 #5 · `34b05804` CT-stall 차단 #1 · `54ca8a07` MR-stall 차단 #1 |
| 2 | B | **A** | `0d834a82` CT-stall 관측 #5 · `46ea7790` CT-stall 차단 #2 |
| 3 | C | **B** | `1b7bd963` CT-stall 관측 #3 · `3f94b297` CL-stall 차단 #3 · `b12151a1` CT-stall 차단 #3 · `0246cb21` CS-stall 차단 #3 · `82564d3c` MR-stall 차단 #3 |

- 14 세션. 레인 3 의 `0246cb21`·`82564d3c` 는 재실행이 아니라 처음 돈 항목이지만 같은 실행(같은 창)에서 돌았으므로 같이 보정한다
- 결과(종료 분류·판정)에는 영향이 없다. 집계는 계정별 크레딧 합계를 **이름표 그대로(`accounts`)** 와 **보정 적용(`accounts_corrected`)** 둘 다 낸다 (`aggregate_demo.py --account-corrections`). 보정 파일 없이 돌리면 출력은 이전과 같다
- 집계의 계정 합계는 집계에 든(제외되지 않은) 세션만 센다 (C-19-1 부터 같은 규칙). 제외 세션이 쓴 크레딧은 계정 합계에 들지 않는다
- MR 보충 3 세션의 이름표는 B 다. PM 진술에 이 실행의 계정이 없어 보정하지 않았다

## 결정 3 — MR 보충 계획 커밋

`~/demo-mr2/demo-main-v1-mr2.yaml` 을 같은 바이트로 `batch_plans/demo-main-v1-mr2.yaml` 에 넣는다 (C-18-8 파트 3). sha256 은 레인 기록의 `plan_sha256` 과 같아야 한다.
