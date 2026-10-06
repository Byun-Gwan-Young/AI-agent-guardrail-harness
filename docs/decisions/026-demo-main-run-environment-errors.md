# 본 실행 환경 오류 : 프록시 시간 제한 · LR 보충 · 제외·대체 목록 (C-18-7)

본 실행(`demo-main-v1`, 10/6) 중 실행 환경 오류가 두 종류 나왔다 (DM-78, DM-79). 이 문서는 진단 수치와 결정, 그리고 C-18-7 에서 바꾼 것을 남긴다.
세션 값은 모두 `tools/demo_exclusions.py` 출력 `reports/c18-7/exclusions-before-rerun.json` 이다 (10/6 15:08 KST 기준 기록. 세션 기록·프록시 로그의 상태 코드·대기 시간·실행기 오류 줄·검색 결과 종류만 읽음. 모델 출력·reasoning 은 읽지 않음).

## 기록 시점의 레인 상태

| 계획 · 레인 | 계정 | 마지막 사건 | 계획 / 끝남 / 실패 / 대기 |
|---|---|---|---|
| `demo-main-v1` 1 | A | `lane_finished` (15:01 KST, 그 전에 `lane_stopped` 13:51 → 다시 켬) | 19 / 12 / 7 / 0 |
| `demo-main-v1` 2 | B | `lane_finished` (14:49) | 19 / 17 / 2 / 0 |
| `demo-main-v1` 3 | C | **`lane_stopped`** (15:08, runner_error 2 번 연속) | 19 / 14 / 3 / **2** (`DEMO-CS-stall-v1:block:3`, `DEMO-MR-stall-v1:block:3`) |
| `demo-main-v1` 4 (LR) | D | `lane_finished` (13:25) | 13 / 13 / 0 / 0 |
| `demo-main-v1-lr2` 1 (LR 보충) | D | `lane_finished` (14:52) | 13 / 13 / 0 / 0 (단 1 개는 `user_interrupted`, 아래) |

본 실행·LR 보충 세션 81 개 모두 `git_commit` `e3341e5` · `git_dirty: false`.

## 진단 1 — runner_error 12 건 (DM-78 ①, DM-79)

| 항목 | 레인·계정 | 세션 | 실패 요청 | 업스트림 대기 | 원인 |
|---|---|---|---|---|---|
| `DEMO-CL-normal-v1:observe:1` | 1 · A | `c1ff4dc4…` | turn 2 | 120.06 s | 프록시 시간 초과 |
| `DEMO-CL-stall-v1:observe:2` | 1 · A | `0cd6385b…` | turn 62 | 120.04 s | 프록시 시간 초과 |
| `DEMO-CT-stall-v1:observe:1` | 1 · A | `000a538a…` | turn 5 | 120.04 s | 프록시 시간 초과 |
| `DEMO-CT-stall-v1:observe:4` | 1 · A | `eba5a575…` | turn 10 | 120.28 s | 프록시 시간 초과 |
| `DEMO-CT-stall-v1:block:1` | 1 · A | `158e7cac…` | turn 10 | 120.04 s | 프록시 시간 초과 |
| `DEMO-MR-normal-v1:observe:5` | 1 · A | `8a458208…` | turn 6 | 42.29 s | 업스트림 502 |
| `DEMO-MR-stall-v1:block:1` | 1 · A | `173d03d6…` | turn 7 | 59.85 s | 업스트림 502 |
| `DEMO-CT-stall-v1:observe:5` | 2 · B | `18b69568…` | turn 11 | 120.04 s | 프록시 시간 초과 |
| `DEMO-CT-stall-v1:block:2` | 2 · B | `b3ae9954…` | turn 10 | 120.04 s | 프록시 시간 초과 |
| `DEMO-CT-stall-v1:observe:3` | 3 · C | `7634c328…` | turn 5 | 120.15 s | 프록시 시간 초과 |
| `DEMO-CL-stall-v1:block:3` | 3 · C | `1372b13b…` | turn 18 | 33.76 s | 업스트림 502 |
| `DEMO-CT-stall-v1:block:3` | 3 · C | `bf36c7d9…` | turn 10 | 120.04 s | 프록시 시간 초과 |

- 구분 근거 : 실행기 오류 줄이 프록시가 만든 본문 `{'error': 'Upstream connection failed'}` 이고 대기 ≥ 120 s → 프록시 시간 초과 (`httpx.AsyncClient(timeout=120)` 의 요청 오류가 502 로 바뀐 것). 오류 줄이 `502 Bad Gateway` (업스트림이 보낸 비 JSON 본문) → 업스트림 502
- DM-79 시점(15:00)의 9 건 이후 2 건이 더 났다 : 레인 1 `173d03d6…` (업스트림 502), 레인 3 `1372b13b…` (업스트림 502) · `bf36c7d9…` (시간 초과). 그래서 **시간 초과 9, 업스트림 502 3** (DM-79 의 "8 + 1" 에서 늘어남)
- 시간 초과 9 건 중 7 건이 CT 교착판 (step 2 developer·step 4 planner 의 긴 reasoning 생성 자리, DM-79). 429 는 본 실행 전체 0 건 (DM-78 ①)
- 실행기 쪽 시간 제한 : 실행기는 `httpx.AsyncClient()` 를 OpenAI SDK 에 넘기고 시간 제한을 주지 않는다 → SDK 기본값 `Timeout(connect=5, read=600, write=600, pool=600)` 이 쓰인다 (`openai` 3.7.0, 오프라인으로 클라이언트를 만들어 확인). **읽기 600 초 = 프록시와 같은 값**이라 "600 초 이상" 은 만족한다. 다만 600 초 근처의 생성은 두 쪽 중 먼저 끊는 쪽이 정해지지 않는다 (실행기가 먼저 끊으면 502 대신 실행기 시간 초과로 runner_error). 실행기는 고치지 않는다

## 진단 2 — 본 실행 LR 13 세션 (DM-78 ②)

- arXiv 검색 41 회 : 429 26, 시간 초과 12, 200 3 (결과 0 개). 종료 : `escalated` 12, `guardrail_stop` 1
- 검색 시도 없이 끝난 세션 2 개 : `a8e1e322…` (LR 정상판 관측 5, lead 가 검색 없이 `escalated` = 모델 행동, DM-78 ③ 에 따로 적음), `569ceba4…` (LR 교착판 차단 2)

## 결정 (DM-78, DM-79)

1. **프록시 업스트림 읽기 시간 제한 600 초** (`proxy.py` `UPSTREAM_TIMEOUT = httpx.Timeout(120, read=600)`). 연결·쓰기·풀은 120 초 그대로. 600 초를 넘기면 지금처럼 프록시가 만든 502. `proxy.py` 는 최종 동결 62 파일 밖이라 동결은 그대로이고 (`final_freeze.py check` 통과), 판정 규칙·조건군은 바뀌지 않는다. 적용은 모든 레인이 끝난 뒤 프록시 재기동부터 (그 전 재기동은 진행 중 세션을 끊는다)
2. **runner_error 세션은 무효 (실행 환경 사유)**. `rerun_of` 로 이어진 재실행 세션이 대신한다. 집계의 "n 회 중" 분모는 유효 세션 수, 무효 세션 수는 사유별로 따로 보고. 재실행도 실패한 항목은 "실행 환경 사유 미완료" (세 번째 시도 없음)
3. **본 실행 LR 13 세션 전체를 집계에서 뺀다** (`env_search_unavailable`). 지우지 않고 기록·백업은 그대로. LR 보충(`demo-main-v1-lr2`)이 대신한다
4. **커밋이 둘로 갈린다** : 본 실행·LR 보충은 `e3341e5`, 재실행은 이 단위가 합쳐진 커밋. 조건군 계산은 코드 커밋을 넣지 않으므로 같은 조건군. 이전 설정의 CT 교착판 완료 표본은 긴 생성이 없던 쪽으로 치우쳐 있다 (생존 편향, 보고서에 적음)
5. 데이터셋 트랙(C-20)도 같은 시간 제한을 쓴다. 판정 오버헤드 측정(S-5)과 무관

## 제외·대체 목록 규칙 (`tools/demo_exclusions.py`, `demo-exclusions-v1`)

규칙만으로 정한다. 첫 번째로 맞는 규칙이 사유가 된다.

| 사유 코드 | 규칙 | 지금 기록 |
|---|---|---|
| `env_search_unavailable` | `demo-main-v1` 의 DEMO-LR 세션 전체 | 13 |
| `env_upstream_timeout` | runner_error + 프록시가 만든 502 + 대기 ≥ 120 s | 9 |
| `env_upstream_502` | runner_error + 업스트림이 보낸 502 | 3 |
| `run_interrupted` | `user_interrupted` 로 끝남 (**C-18-7 에서 더한 규칙, PM 확인 필요**) | 1 |

- `replaced_by` : 같은 계획들 안에서 `batch.rerun_of` 가 그 세션을 가리키는 세션. 재실행이 다시 실패하면 그 세션도 같은 규칙으로 빠지고 항목은 `items_without_valid_session` 에 남는다
- 두 502 규칙 어디에도 맞지 않는 runner_error 는 빼지 않고 `unresolved` 로 내며 도구가 1 로 끝난다 (사람이 고르지 않게). 아직 끝나지 않은 세션(`summary.json` 없음)은 `unfinished` 로 두고 정하지 않는다
- **`run_interrupted` 를 더한 이유** : LR 보충의 `DEMO-LR-stall-v1:block:3` (`445ab1ba…`) 가 0 step `user_interrupted` 로 끝났다 (14:49:39 시작, 22 초 뒤 실행기 오류 줄 "Cancelled by user". 14:52 레인을 다시 켰을 때 배치 실행기가 이 항목을 "끝남" 으로 보고 건너뜀). 이것을 그대로 두면 집계에서 '기타' 차단 세션 1 회(0 step)로 들어가 LR 교착판 차단의 평균 토큰을 낮추고 절감률을 부풀린다. 9 장 원칙(실행기·설정의 문제는 오염)에 따라 빼는 규칙을 제안한다. PM 이 받지 않으면 이 규칙만 지운다
- 배치 실행기는 `user_interrupted` 를 끝난 항목으로 보므로 `--rerun-failed` 로도 이 항목은 다시 돌지 않는다 (배치 실행기는 고치지 않음). 그래서 지금 기록으로 유효 세션이 없는 항목은 13 개다 : runner_error 12 항목 + `DEMO-LR-stall-v1:block:3`. 여기에 레인 3 의 대기 2 항목이 더해진다

## 집계 (`tools/aggregate_demo.py`, C-18-7 파트 3)

`--exclusions <파일>` 을 받으면 목록에서 `excluded` 인 세션을 집계에서 빼고 사유별 개수를 `exclusion_list` 에 낸다. 대체 세션은 계획의 보통 세션이므로 그대로 센다 (분모 = 유효 세션 수). 출력에 커밋별 세션 수(`git_commits`)를 적는다. 목록 없이 계획 하나를 주면 출력은 이전과 같다.
