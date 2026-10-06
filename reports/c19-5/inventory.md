# C-19-5 파트 0 — 저장소 목록 (바꾸기 전)

> `reports/c19-5/inventory.py` 출력 (읽기 전용, 외부 호출 없음). 손으로 고친 값 없음. 기준 커밋 `a968ef6`.

## 1. 요약

- 추적 파일 2007 개. 참조를 센 원문 1993 개 (추적 텍스트 파일 + 가이드라인 `docs/handoff/시나리오_수집_가이드라인.md`, 가이드라인 읽음 : True)
- 참조를 세지 않은 대형 세션 로그 15 개 (`logs/`, `runs/*/session.json`·`steps.json`, 256 KiB 초과) — 열지 않음
- 참조 수 : **전체 경로** 문자열, **파일 이름**(마지막 경로 조각), `.py` 는 **모듈 이름**(점·하이픈·글자가 붙지 않은 낱말) 을 따로 셈. 자기 자신 안의 문자열은 세지 않음. 이름 수는 겹치는 다른 파일까지 세므로 위쪽 값이다

| 분류 | 파일 수 |
|---|---|
| 동결 | 70 |
| 실행 코드 | 39 |
| 실행 기록 | 1458 |
| 계획 | 6 |
| 테스트 | 123 |
| 도구 | 37 |
| 문서 | 75 |
| 보고 | 193 |
| 기타 | 6 |

분류 규칙 : **동결** = 최종 동결 62 파일 + v0.3 구현 해시 대상 + `docs/criteria/` + `guardrail-deadlock-v0.2*`·`v0.3*` 설정 + `deadlock_policy*.py`. **실행 코드** = 루트의 실행 모듈, `experiments/`, `scenarios/`, `scenario_assets/`, `scenario_judges/`, 실행 설정. **실행 기록** = `runs/`, `logs/`. 나머지는 폴더 이름대로. 초기 Groq 시험 스크립트·로그(`test.py` 등)는 **기타**

## 2. 루트 파일

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `.gitignore` |  | 기타 | 15 / 15 / — | 9 |
| `README.md` | agent-guardrail | 문서 | 15 / 15 / — | 11 |
| `artifact_hook.py` | Runner-side observation helpers. No commands or network calls run implicitly. | 실행 코드 | 1 / 1 / 13 | 0 |
| `conversation_extract.py` | Conservative text-only rule extractor. Structured reference is never an input. | 실행 코드 | 1 / 1 / 6 | 0 |
| `criteria_freeze.py` | What freezes deadlock-v0.3 besides its parameters (DM-33, C-17-2): the sha256 of the files that compute progress-v3 / | 실행 코드 | 2 / 2 / 175 | 0 |
| `criteria_policy.py` | Criteria dispatch including deadlock-v0.3. | 실행 코드 | 2 / 2 / 12 | 0 |
| `deadlock_log.json` | list of 19 | 기타 | 4 / 4 / — | 0 |
| `deadlock_policy.py` | Version dispatch over pinned criteria; preserve legacy calculations unchanged. | 동결 | 6 / 6 / 22 | 0 |
| `deadlock_policy_v01.py` | Predeclared criteria over S3-A categories. No new numeric signal or intervention. | 동결 | 3 / 3 / 5 | 0 |
| `deadlock_policy_v02.py` | Predeclared criteria over S3-A categories. No new numeric signal or intervention. | 동결 | 5 / 5 / 6 | 0 |
| `deadlock_policy_v03.py` | deadlock-v0.3 (DM-10, DM-22): the deadlock-v0.2 streak rule over progress-v3 states. | 동결 | 130 / 130 / 138 | 0 |
| `deadlock_test.py` |  | 기타 | 9 / 9 / 9 | 0 |
| `demo-conditions.yaml` |  | 동결 | 727 / 727 / — | 14 |
| `experiment_config.py` | Explicit experiment conditions, never inferred from provider defaults. | 실행 코드 | 2 / 2 / 23 | 1 |
| `explain_v1.py` | explain-v1 (DM-9): one Korean STOP-reason sentence built only from judgement signal values. | 동결 | 135 / 135 / 169 | 2 |
| `guardrail-deadlock-v0.2-kmu.yaml` |  | 동결 | 49 / 49 / — | 3 |
| `guardrail-deadlock-v0.2.yaml` |  | 동결 | 12 / 12 / — | 1 |
| `guardrail-deadlock-v0.3-kmu-block.yaml` |  | 동결 | 93 / 93 / — | 0 |
| `guardrail-deadlock-v0.3-kmu.yaml` |  | 동결 | 344 / 344 / — | 1 |
| `guardrail.yaml` |  | 실행 코드 | 26 / 26 / — | 2 |
| `health.py` | Local health snapshot; never probes the upstream. | 실행 코드 | 0 / 0 / 1 | 0 |
| `json_subset.py` | The JSON-schema subset a scenario-v2 deliverable_schema may use, checked at load and validated locally. | 동결 | 10 / 10 / 32 | 2 |
| `models.py` |  | 기타 | 4 / 4 / 194 | 0 |
| `observation_api.py` | Attach runner observations without executing filesystem or test commands in the proxy. | 실행 코드 | 6 / 6 / 7 | 1 |
| `progress_schema.py` | Versioned observation input; computed verdicts are never accepted as input. | 실행 코드 | 4 / 4 / 23 | 1 |
| `progress_signal.py` | Version dispatch; the original progress-v1 implementation remains frozen. | 실행 코드 | 11 / 11 / 30 | 1 |
| `progress_signal_v1.py` | Pure deterministic movement classification. Not a deadlock/success detector. | 실행 코드 | 6 / 6 / 10 | 0 |
| `progress_signal_v3.py` | progress-v3 (deadlock-v0.3, DM-10/DM-22): progress-v2 movement plus T1 dialogue and T3 artifact signals. | 동결 | 129 / 129 / 136 | 0 |
| `proxy.py` | DM-2, DM-34 for proxy logs (C-17-4): a demo-condition proxy logs only under logs/demo/ and nothing else does. | 실행 코드 | 20 / 20 / 534 | 5 |
| `requirements.txt` |  | 실행 코드 | 1 / 1 / — | 1 |
| `scenario_checks.py` | Machine acceptance gate; does not call agents or infer deadlock from expected_outcome. | 실행 코드 | 3 / 3 / 6 | 2 |
| `scenario_schema.py` | Scenario-v1 and scenario-v2 contracts. Definitions only; loading never executes agents or commands. | 실행 코드 | 0 / 0 / 59 | 0 |
| `session_store.py` | Session persistence boundary; replace repository for Redis in a later phase. | 실행 코드 | 1 / 1 / 17 | 0 |
| `suite_identity.py` | Acceptance identity excludes implementation files, includes tests, contract and command. | 실행 코드 | 1 / 1 / 6 | 1 |
| `termination_failure.json` | list of 24 | 기타 | 3 / 3 / — | 0 |
| `test.py` |  | 기타 | 18 / 18 / 442 | 0 |

## 3. 폴더

| 폴더 | 파일 수 | 폴더 밖 참조 (폴더 경로 문자열) | 가이드라인 |
|---|---|---|---|
| `batch_plans/` | 7 | 78 | 10 |
| `docs/` | 79 | 352 | 62 |
| `docs/assets/` | 1 | 5 | 4 |
| `docs/criteria/` | 5 | 79 | 2 |
| `docs/decisions/` | 26 | 21 | 11 |
| `docs/design/` | 19 | 210 | 25 |
| `docs/findings/` | 10 | 12 | 5 |
| `experiments/` | 16 | 746 | 1 |
| `logs/` | 9 | 223 | 17 |
| `reports/` | 193 | 936 | 57 |
| `reports/a-1-v3/` | 10 | 12 | 2 |
| `reports/a-1-v4/` | 8 | 13 | 2 |
| `reports/c15/` | 5 | 2 | 1 |
| `reports/c16/` | 2 | 0 | 0 |
| `reports/c17-1/` | 2 | 5 | 0 |
| `reports/c17-2/` | 3 | 5 | 0 |
| `reports/c17-3/` | 5 | 5 | 0 |
| `reports/c17-4/` | 5 | 3 | 0 |
| `reports/c17-5/` | 5 | 3 | 0 |
| `reports/c17-6/` | 5 | 3 | 0 |
| `reports/c17-7/` | 5 | 8 | 3 |
| `reports/c17-8/` | 9 | 12 | 2 |
| `reports/c18-1/` | 9 | 486 | 1 |
| `reports/c18-2/` | 11 | 33 | 0 |
| `reports/c18-3/` | 12 | 7 | 0 |
| `reports/c18-4/` | 17 | 12 | 1 |
| `reports/c18-5/` | 7 | 4 | 2 |
| `reports/c18-6/` | 5 | 10 | 2 |
| `reports/c18-7/` | 3 | 6 | 3 |
| `reports/c18-8/` | 4 | 14 | 5 |
| `reports/c19/` | 21 | 51 | 20 |
| `reports/c19-1/` | 13 | 6 | 2 |
| `reports/c19-1/replay-examples/` | 9 | 1 | 0 |
| `reports/c19/checks/` | 9 | 4 | 2 |
| `reports/c19/replay/` | 8 | 11 | 1 |
| `reports/g0-6/` | 1 | 2 | 0 |
| `reports/g0-8/` | 3 | 4 | 2 |
| `reports/p0-1/` | 2 | 11 | 3 |
| `reports/p0-2/` | 5 | 8 | 0 |
| `reports/p0-3/` | 7 | 7 | 3 |
| `reports/p0-4/` | 3 | 9 | 3 |
| `reports/strict-probe-3472654ecfca4274b03383123aa03131/` | 3 | 2 | 0 |
| `runs/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e/` | 96 | 0 | 0 |
| `runs/A-1-v3-4a0087756b2641f4b8f9b025c0419f73/` | 63 | 5 | 0 |
| `runs/A-1-v4-e174aafe805b4f59bb62d7c95716b8b7/` | 165 | 8 | 0 |
| `scenario_assets/A-1/` | 5 | 64 | 1 |
| `scenario_assets/A-1/src/` | 1 | 3 | 0 |
| `scenario_assets/A-1/tests/` | 1 | 2 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/` | 6 | 39 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/src/` | 1 | 1 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/tests/` | 2 | 7 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/` | 6 | 47 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/src/` | 1 | 1 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/tests/` | 2 | 9 | 0 |
| `scenario_assets/DEMO-CS-normal-v1/` | 4 | 57 | 0 |
| `scenario_assets/DEMO-CS-normal-v1/policies/` | 3 | 7 | 0 |
| `scenario_assets/DEMO-CS-stall-v1/` | 4 | 76 | 0 |
| `scenario_assets/DEMO-CS-stall-v1/policies/` | 3 | 8 | 0 |
| `scenario_assets/DEMO-CT-normal-v1/` | 5 | 29 | 0 |
| `scenario_assets/DEMO-CT-normal-v1/src/` | 1 | 1 | 0 |
| `scenario_assets/DEMO-CT-normal-v1/tests/` | 1 | 3 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/` | 5 | 49 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/src/` | 1 | 1 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/tests/` | 1 | 4 | 0 |
| `scenario_assets/DEMO-LR-v1/` | 1 | 171 | 0 |
| `scenario_assets/DEMO-MR-v1/` | 1 | 161 | 0 |
| `scenario_judges/` | 4 | 472 | 0 |
| `scenarios/` | 17 | 651 | 12 |
| `tests/` | 123 | 5225 | 14 |
| `tests/fixtures/` | 28 | 133 | 9 |
| `tests/fixtures/demo_cl/` | 2 | 24 | 0 |
| `tests/fixtures/demo_ct/` | 2 | 27 | 0 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/` | 4 | 1 | 0 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/policies/` | 3 | 0 | 0 |
| `tests/fixtures/scenario_judges/` | 3 | 2 | 0 |
| `tests/fixtures/search/` | 5 | 11 | 0 |
| `tools/` | 37 | 4429 | 39 |

## 4. 파일 (실행 기록 제외)

### `batch_plans/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `batch_plans/demo-main-v1-lr2.yaml` | description: 데모 본 실행 — LR 보충 관측 10 + 차단 3 (DM-78) | 계획 | 5 / 7 / — | 5 |
| `batch_plans/demo-main-v1-mr2.yaml` | description: MR 보충 (DM-81) | 계획 | 2 / 4 / — | 1 |
| `batch_plans/demo-main-v1.yaml` | description: 데모 본 실행 — 관측 55 + 차단 15 | 동결 | 38 / 39 / — | 0 |
| `batch_plans/demo-trial-c18-2.yaml` | description: DEMO-CT 정상판·교착판, DEMO-CT-N 시험 실행 각 1 회 (observe) | 계획 | 6 / 6 / — | 0 |
| `batch_plans/demo-trial-c18-3.yaml` | description: DEMO-CS·MR·LR 정상판·교착판 시험 실행 각 1 회 (observe) | 계획 | 5 / 5 / — | 2 |
| `batch_plans/demo-trial-c18-4.yaml` | description: DEMO-CS·MR 정상판·교착판 재시험 각 1 회 (observe) | 계획 | 8 / 8 / — | 0 |
| `batch_plans/demo-trial-c18-5.yaml` | description: DEMO-MR 정상판·교착판 재시험 각 1 회 (observe) | 계획 | 7 / 7 / — | 2 |

### `docs/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `docs/A-1-review.md` | A-1 검토용 요약 | 문서 | 0 / 0 / — | 0 |
| `docs/A1-preflight.md` | A-1 단계별 실행 점검표 | 문서 | 4 / 4 / — | 0 |
| `docs/A1-revision2-budget.md` | 인수인계 점검 및 A-1 revision 2 예산 | 문서 | 0 / 0 / — | 0 |
| `docs/A1-strict-implementation.md` | A-1 strict 최종 보고 적용 | 문서 | 4 / 4 / — | 0 |
| `docs/A1-strict-preflight-and-fallback.md` | 식별자 제거·최종 프롬프트 분리 / strict 검증 준비 | 문서 | 5 / 5 / — | 0 |
| `docs/A1-tool-failure-recovery.md` | A-1 step 1 도구 오류: 증거와 수정 | 문서 | 0 / 0 / — | 0 |
| `docs/P0-1-replay-protocol.md` | P0-1 replay 사전 판독 규칙 | 문서 | 4 / 4 / — | 0 |
| `docs/P0-2-replay-protocol.md` | P0-2 오프라인 적용 범위 | 문서 | 0 / 0 / — | 0 |
| `docs/S1-session-isolation.md` | S1 세션 격리 — 재시작 복원 보완 | 문서 | 0 / 0 / — | 0 |
| `docs/S2-experiment-recording.md` | S2 실험 조건 기록과 healthz | 문서 | 3 / 3 / — | 4 |
| `docs/S3-A-progress.md` | S3-A 진전도 관측 — 구현과 사용 계약 | 문서 | 0 / 0 / — | 0 |
| `docs/S3-B-runner-review.md` | A-1 실행기 구현 및 실행 조건 검토 | 문서 | 0 / 0 / — | 0 |
| `docs/S3-C-legacy-results.md` | S3-C 기존 로그 적용 결과 | 문서 | 0 / 0 / — | 0 |
| `docs/S3-C-기존로그적용결과.md` | S3-C 기존 로그 적용 결과 | 문서 | 0 / 0 / — | 0 |
| `docs/assets/logo.svg` |  | 문서 | 5 / 8 / — | 11 |
| `docs/criteria/deadlock-v0.1.json` | criteria_version: deadlock-v0.1 | 동결 | 2 / 3 / — | 0 |
| `docs/criteria/deadlock-v0.2.json` | criteria_version: deadlock-v0.2 | 동결 | 3 / 6 / — | 0 |
| `docs/criteria/deadlock-v0.3.json` | criteria_version: deadlock-v0.3 | 동결 | 45 / 50 / — | 6 |
| `docs/criteria/demo-final-freeze.json` | freeze_version: demo-final-freeze-v1 | 동결 | 15 / 15 / — | 2 |
| `docs/criteria/explain-v1.json` | explanation_version: explain-v1 | 동결 | 16 / 24 / — | 4 |
| `docs/deadlock_criteria.md` | 교착 판정 기준 — 사전 고정 v0.1 | 문서 | 1 / 1 / — | 2 |
| `docs/decisions/002-session-lifecycle.md` | 002 세션 시작·종료 API와 재시작 복원 | 문서 | 0 / 1 / — | 0 |
| `docs/decisions/003-progress-observations.md` | 003 관측 API, 두 소스 진전도와 왕복 표시 | 문서 | 1 / 2 / — | 2 |
| `docs/decisions/004-role-scoped-progress.md` | 004 역할별 진전도 비교 — P0-1 | 문서 | 0 / 1 / — | 0 |
| `docs/decisions/005-independent-observation-collection.md` | P0-2: 대화·산출물 독립 보존 | 문서 | 1 / 2 / — | 2 |
| `docs/decisions/006-closed-issue-vocabulary.md` | P0-3: 닫힌 쟁점 어휘 | 문서 | 1 / 1 / — | 2 |
| `docs/decisions/007-info-items-recorded-only.md` | P0-4: info_items 는 기록만 한다 (선택지 C) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/008-tool-execution-errors.md` | G0-6: 도구 실행 오류를 step 기록에 반영 (결함 8) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/009-verified-narrative-sharing.md` | G0-13: 검증된 최종 보고는 다른 역할에 전달한다 | 문서 | 1 / 1 / — | 0 |
| `docs/decisions/010-harness-facts-v8.md` | G0-14: 호출 예산과 쓰기 가능 파일을 사실로 알린다 (결함 6·7, 프로토콜 v8) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/011-provider-switch-gateway.md` | D-27 / D-25: 업스트림을 설정으로 고르고, 프로토콜을 매번 명시한다 | 문서 | 4 / 4 / — | 0 |
| `docs/decisions/012-final-report-allowlist-v10.md` | S-25 · S-31: 최종 보고 요청은 허용 필드만 싣는다 (프로토콜 v10) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/013-deadlock-v0.3.md` | DM-10 · DM-22: `deadlock-v0.3` / `progress-v3` (데모 트랙 판정 규칙) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/014-demo-block-mode.md` | DM-7 · DM-23: 데모 차단 모드 (block) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/015-scenario-v2-contract-v3.md` | 시나리오 v2 · 출력 계약 v3 · T1 관측 필드 (C-17-3) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/016-dialogue-runner-t1.md` | 실행기 T1 대화 흐름 (C-17-4) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/017-artifact-runner-v2.md` | 실행기 v2 산출물 과제 경로 (C-17-5) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/018-dialogue-tools.md` | T1 도구 4 종 · 검색 결과 원문 저장 (C-17-6) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/019-model-run-condition.md` | 모델 실행 조건 · 조건군 · 게이트웨이 probe 후속 (C-17-7) | 문서 | 4 / 4 / — | 0 |
| `docs/decisions/020-demo-cl-credits-preflight.md` | 데모 크레딧 실측 · preflight v0.3 · DEMO-CL (C-18-1) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/021-demo-ct-batch-runner.md` | DEMO-CT · DEMO-CT-N · 배치 실행기 (C-18-2) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/022-demo-t1-final-freeze-records.md` | 데모 기록 커밋 규칙 · DEMO-CS·MR·LR (T1) · 최종 동결 (C-18-3) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/023-demo-t1-trial-fixes.md` | T1 시험 결과 반영 — CS 담당 확정 · MR 출처 전달 · 시험 기록 (C-18-4) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/024-demo-aggregate-replay.md` | 데모 집계 도구 · 세션 재생 페이지 (C-19-1) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/025-demo-mr-retest-final-freeze.md` | MR 재시험 결과 · 동결 범위 62 파일 · 최종 동결 (C-18-6) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/026-demo-main-run-environment-errors.md` | 본 실행 환경 오류 : 프록시 시간 제한 · LR 보충 · 제외·대체 목록 (C-18-7) | 문서 | 0 / 0 / — | 0 |
| `docs/decisions/027-demo-main-run-operator-errors.md` | 본 실행 운영 실수 정리 : 검색 키 오타 · 두 번째 실패 · 계정 이름표 (C-18-8) | 문서 | 0 / 0 / — | 0 |
| `docs/design/budget-a-1-v4.md` | A-1-v4 (프로토콜 v9) 크레딧 — C-13 추정과 C-14 실측 | 문서 | 4 / 4 / — | 6 |
| `docs/design/budget-v9.json` | keys: ESTIMATE, basis, inputs, v9_credit_per_call | 문서 | 3 / 5 / — | 0 |
| `docs/design/budget_v9.py` | A-1-v4 (protocol v9) credit ESTIMATE (C-13 part 3). Read-only; every output is an estimate. | 문서 | 0 / 2 / 2 | 0 |
| `docs/design/demo-block-and-explanation.md` | 차단 모드 + 원인 설명 설계 (C-16 파트 4) | 문서 | 5 / 6 / — | 4 |
| `docs/design/demo-budget.json` | keys: script, status, rate_check, blocked_session_reference | 문서 | 6 / 10 / — | 0 |
| `docs/design/demo-deadlock-v0.3.md` | `deadlock-v0.3` 설계 (C-16 파트 3) | 문서 | 5 / 11 / — | 2 |
| `docs/design/demo-model-probe.md` | 데모 모델 probe (C-16 파트 5, DM-12) | 문서 | 5 / 5 / — | 0 |
| `docs/design/demo-runner-extension.md` | 데모 트랙 실행기 확장 설계 (C-16 파트 2) | 문서 | 10 / 103 / — | 8 |
| `docs/design/demo-scenarios.md` | 데모 트랙 시나리오 명세 초안 (C-16 파트 1) | 문서 | 151 / 152 / — | 12 |
| `docs/design/demo-v03-inputs.json` | keys: script, status, parameters, sessions | 문서 | 13 / 15 / — | 0 |
| `docs/design/demo-work-plan.md` | 데모 트랙 작업 분할과 규모 (C-16 파트 6) | 문서 | 7 / 11 / — | 12 |
| `docs/design/demo_budget.py` | C-16 part 6: demo-track session count and credit range. ESTIMATE, from two measured sessions only. | 문서 | 5 / 7 / 7 | 0 |
| `docs/design/demo_v03_inputs.py` | C-16 part 3: per-step log values for the deadlock-v0.3 design, and where its proposed T3 signals would apply. | 문서 | 1 / 3 / 3 | 0 |
| `docs/design/metrics-v1-check.json` | metrics_version: metrics-v1 | 문서 | 2 / 4 / — | 0 |
| `docs/design/metrics-v1.md` | metrics-v1 — 1학기 지표 정의 | 문서 | 1 / 4 / — | 1 |
| `docs/design/metrics_v1_check.py` | metrics-v1 computability check (C-13 part 0). Read-only. | 문서 | 0 / 2 / 5 | 0 |
| `docs/design/stage1-collection-spec.md` | Stage 1 — 수집 규격 설계안 (C-12) | 문서 | 3 / 5 / — | 6 |
| `docs/design/stage1-values.json` | keys: sessions, replay, metrics, lint | 문서 | 2 / 5 / — | 1 |
| `docs/design/stage1_values.py` | Stage 1 design values (C-12). Read-only; no runtime code is changed or imported for writing. | 문서 | 0 / 3 / 3 | 1 |
| `docs/discrepancies.md` | 문서와 구현의 불일치 | 문서 | 0 / 1 / — | 0 |
| `docs/findings/001-silent-noop-step.md` | 001. Silent no-op step: 정상 응답과 완료 표시가 진전을 보장하지 않음 | 문서 | 0 / 1 / — | 0 |
| `docs/findings/002-context-growth-in-code-task.md` | 코드 작업의 컨텍스트 증가 — 4차 실행 | 문서 | 1 / 2 / — | 2 |
| `docs/findings/003-no-progress-full-run.md` | 18번째 step까지 구현 진전 없이 진행된 실행 | 문서 | 1 / 1 / — | 2 |
| `docs/findings/004-A1-fourth-run-analysis.md` | 4차 실행 원인 분석 | 문서 | 0 / 1 / — | 0 |
| `docs/findings/005-recovered-narrative-not-shared.md` | 실행기 결함 후보: 회복된 narrative의 역할 간 전달 누락 | 문서 | 0 / 0 / — | 0 |
| `docs/findings/cumulative.svg` |  | 문서 | 0 / 1 / — | 0 |
| `docs/findings/error-evidence.json` | keys: 5, 10, 13, 16 | 문서 | 5 / 6 / — | 0 |
| `docs/findings/narratives.md` | 4차 실행: 성공 step narrative 원문 | 문서 | 0 / 1 / — | 0 |
| `docs/findings/sources.json` | keys: C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\session.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\steps.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\summary.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\scenario.yaml | 문서 | 0 / 0 / — | 0 |
| `docs/findings/tokens.csv` |  | 문서 | 0 / 1 / — | 0 |
| `docs/management-api.md` | 관리 API 목록 — S3-A 시점 | 문서 | 0 / 1 / — | 0 |
| `docs/scenario_schema.md` | scenario-v1 스키마 — S3-B 첫 검토 | 문서 | 0 / 0 / — | 0 |

### `experiments/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `experiments/approval_gate.py` | CT approval rule (DM-16, C-17-5 part 2): the runner, not the prompt, keeps a role's writes waiting for approval. | 실행 코드 | 28 / 29 / 29 | 0 |
| `experiments/compare_context.py` | Offline buffered/unbuffered prompt-token comparison; no model requests. | 실행 코드 | 1 / 1 / 1 | 0 |
| `experiments/compare_runs.py` | Compare two manually executed runs without calling a model. | 실행 코드 | 1 / 1 / 1 | 0 |
| `experiments/cs_tools.py` | Local tools of the customer-support task (DEMO-CS, C-17-6 part 1): lookup_order and read_policy. | 실행 코드 | 2 / 3 / 21 | 0 |
| `experiments/dialogue_contract.py` | output-contract-v3 (C-17-3): output-contract-v2 plus the T1 final-report fields of demo-runner-extension.md 4. | 실행 코드 | 1 / 1 / 2 | 0 |
| `experiments/dialogue_runner.py` | scenario-v2 dialogue (T1) runs (C-17-4): docs/design/demo-runner-extension.md 2-4, decision 015, DM-16..DM-39. | 실행 코드 | 7 / 9 / 21 | 0 |
| `experiments/dialogue_tools.py` | Dialogue-task (T1) tools: the per-role tool list goes into the request and each call is handed on (C-17-4). | 실행 코드 | 3 / 3 / 36 | 0 |
| `experiments/gateway_usage.py` | Gateway usage around one demo session: credits_measured (DM-58 ③, C-18-1). | 실행 코드 | 3 / 3 / 155 | 0 |
| `experiments/issue_contract.py` | Versioned local issue vocabulary contract; legacy implementation is unchanged. | 실행 코드 | 2 / 2 / 4 | 0 |
| `experiments/observation_collection.py` | Versioned input collection only; does not change progress or criteria policy. | 실행 코드 | 0 / 0 / 0 | 0 |
| `experiments/output_contract.py` | Model-owned fields only. Agent and step identifiers are runner metadata. | 실행 코드 | 2 / 2 / 363 | 0 |
| `experiments/probe_strict_output.py` | User-run, single-request Groq strict-schema probe. Never imported by the scenario runner. | 실행 코드 | 10 / 10 / 10 | 0 |
| `experiments/run_scenario.py` | Explicit single-run CLI. Importing this module never starts an experiment. | 실행 코드 | 17 / 34 / 67 | 5 |
| `experiments/search_tools.py` | Search tools of the research tasks (C-17-6 part 2; DM-13, DM-21): web_search (Tavily, DEMO-MR) and | 실행 코드 | 5 / 6 / 87 | 0 |
| `experiments/step_execution.py` | Bounded tool-capable turns, a tool-free final call and narrowly classified tool-failure recovery. | 실행 코드 | 3 / 10 / 12 | 3 |
| `experiments/tool_results.py` | What a dialogue (T1) tool hands back to experiments.dialogue_tools.ToolDispatch (C-17-6). | 실행 코드 | 1 / 1 / 126 | 0 |

### `reports/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `reports/A-1-initial-tests.json` | keys: tests, passed, failed, errors | 보고 | 0 / 0 / — | 0 |
| `reports/A-1-token-estimate.json` | keys: assumed, input_tokens_range, completion_tokens_range, total_tokens_range | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-analysis.json` | 세션 사후 분석 (analyze_session 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-harness-facts.json` | keys: session_id, runner_protocol, max_llm_calls_per_step, roles | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-manifest.json` | 세션 매니페스트 | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/comparison-g0-8.json` | comparison_version: session-comparison-v0.1 | 보고 | 0 / 1 / — | 0 |
| `reports/a-1-v3/g0-8-harness-facts.json` | keys: session_id, runner_protocol, max_llm_calls_per_step, roles | 보고 | 2 / 2 / — | 0 |
| `reports/a-1-v3/preflight-kmu.json` | criteria_version: deadlock-v0.2 | 보고 | 5 / 5 / — | 0 |
| `reports/a-1-v3/preflight.json` | criteria_version: deadlock-v0.2 | 보고 | 2 / 23 / — | 1 |
| `reports/a-1-v3/tests-c10.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/tests-c11.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v3/tests-c9.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v4/c14-analysis.json` | 세션 사후 분석 (analyze_session 출력) | 보고 | 0 / 2 / — | 0 |
| `reports/a-1-v4/c14-evidence.json` | analysis_version: c14-evidence-v1 | 보고 | 5 / 7 / — | 0 |
| `reports/a-1-v4/c14-report.md` | C-14 — A-1-v4 재검증 사후 분석 | 보고 | 1 / 2 / — | 2 |
| `reports/a-1-v4/manifest-c14.json` | manifest_version: session-manifest-v0.2-c14 | 보고 | 1 / 6 / — | 0 |
| `reports/a-1-v4/preflight.json` | criteria_version: deadlock-v0.2 | 보고 | 3 / 23 / — | 1 |
| `reports/a-1-v4/tests-c13.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 2 / — | 0 |
| `reports/a-1-v4/tests-c14.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/a-1-v4/verification-c14.json` | keys: files_scanned, patterns, environment_variables_checked, hits | 보고 | 0 / 0 / — | 0 |
| `reports/c15/tests-c15-estimate-fix.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c15/tests-c15.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c15/v10-context-estimate-v2.json` | estimate_version: v10-final-report-allowlist-estimate-v2 | 보고 | 1 / 2 / — | 2 |
| `reports/c15/v10-context-estimate-v3.json` | estimate_version: v10-final-report-allowlist-estimate-v3 | 보고 | 0 / 1 / — | 0 |
| `reports/c15/v10-context-estimate.json` | estimate_version: v10-final-report-allowlist-estimate-v1 | 보고 | 0 / 1 / — | 0 |
| `reports/c16/tests-c16-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c16/tests-c16.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-1/tests-c17-1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-1/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 22 / — | 0 |
| `reports/c17-2/tests-c17-2-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-2/tests-c17-2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-2/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 21 / — | 0 |
| `reports/c17-3/tests-c17-3-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-3/tests-c17-3-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-3/tests-c17-3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-3/v03-recompute-part2.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 3 / — | 0 |
| `reports/c17-3/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 21 / — | 0 |
| `reports/c17-4/tests-c17-4-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-4/tests-c17-4-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-4/tests-c17-4-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-4/tests-c17-4.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-4/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 22 / — | 0 |
| `reports/c17-5/tests-c17-5-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-5/tests-c17-5-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-5/tests-c17-5-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-5/tests-c17-5.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-5/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 21 / — | 0 |
| `reports/c17-6/tests-c17-6-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-6/tests-c17-6-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-6/tests-c17-6-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-6/tests-c17-6.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-6/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 21 / — | 0 |
| `reports/c17-7/evidence-keycheck.json` | keys: probe_9d2b2053, probe_9d2b2053_secret_scan, multi_tool_calls | 보고 | 4 / 4 / — | 4 |
| `reports/c17-7/evidence.json` | keys: probe_9d2b2053, probe_9d2b2053_secret_scan, multi_tool_calls | 보고 | 4 / 21 / — | 2 |
| `reports/c17-7/tests-c17-7-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-7/tests-c17-7-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-7/tests-c17-7.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-8/demo-budget-glm.json` | keys: script, status, rate_check, blocked_session_reference | 보고 | 4 / 4 / — | 0 |
| `reports/c17-8/evidence-models-keycheck.json` | keys: dm57, gpt_oss_references | 보고 | 1 / 1 / — | 0 |
| `reports/c17-8/evidence-models.json` | keys: dm57, gpt_oss_references | 보고 | 1 / 2 / — | 0 |
| `reports/c17-8/evidence-search-keycheck.json` | keys: folder, probe_id, requests_sent, all_ok_recorded | 보고 | 0 / 1 / — | 0 |
| `reports/c17-8/evidence-search-probe.json` | keys: folder, probe_id, requests_sent, all_ok_recorded | 보고 | 1 / 1 / — | 0 |
| `reports/c17-8/tests-c17-8-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-8/tests-c17-8-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-8/tests-c17-8-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c17-8/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 3 / 21 / — | 0 |
| `reports/c18-1/DEMO-CL-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/DEMO-CL-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/estimate-trial.json` | keys: status, model, credits_per_million, reference_tokens | 보고 | 2 / 11 / — | 0 |
| `reports/c18-1/evidence-prices.json` | keys: tools_probe, strict_probe, solved_input_output, glm_strict_requests | 보고 | 1 / 1 / — | 0 |
| `reports/c18-1/tests-c18-1-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/tests-c18-1-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/tests-c18-1-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/tests-c18-1-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-1/trial-summary.json` | keys: script, sessions, reasoning_effort_evidence, failed_tool_results | 보고 | 459 / 459 / — | 2 |
| `reports/c18-2/DEMO-CL-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/DEMO-CL-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/DEMO-CT-N-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/DEMO-CT-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/DEMO-CT-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/estimate-trial.json` | keys: script, status, plan_id, plan_sha256 | 보고 | 5 / 11 / — | 0 |
| `reports/c18-2/tests-c18-2-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/tests-c18-2-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/tests-c18-2-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/tests-c18-2-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-2/v03-recompute.json` | criteria_version: deadlock-v0.3 | 보고 | 1 / 21 / — | 0 |
| `reports/c18-3/DEMO-CS-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/DEMO-CS-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/DEMO-LR-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/DEMO-LR-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/DEMO-MR-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/DEMO-MR-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/estimate-trial.json` | keys: script, status, plan_id, plan_sha256 | 보고 | 4 / 11 / — | 0 |
| `reports/c18-3/tests-c18-3-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/tests-c18-3-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/tests-c18-3-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/tests-c18-3-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-3/tests-c18-3-part4.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/DEMO-CS-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/DEMO-CS-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/DEMO-MR-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/DEMO-MR-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/cs-rejudge.json` | keys: script, sessions, any_claim_passes_now | 보고 | 3 / 3 / — | 0 |
| `reports/c18-4/estimate-retest.json` | keys: script, status, plan_id, plan_sha256 | 보고 | 4 / 6 / — | 0 |
| `reports/c18-4/mr-normal-diagnosis.json` | keys: script, session_id, termination_reason, steps | 보고 | 3 / 3 / — | 0 |
| `reports/c18-4/pm-commands.md` | C-18-4 PM 명령 (DM-53 형식) | 보고 | 1 / 13 / — | 10 |
| `reports/c18-4/rejudge-DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b.json` | keys: tool, session_id, run_dir, judge | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/rejudge-DEMO-MR-stall-v1-d454a7cd328e4cbd919539f4ccb60d2a.json` | keys: tool, session_id, run_dir, judge | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/tests-c18-4-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/tests-c18-4-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/tests-c18-4-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/tests-c18-4-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/tests-c18-4-part4.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/trial-records-check.json` | keys: sessions, index, ok | 보고 | 0 / 0 / — | 0 |
| `reports/c18-4/trial-records-stage.json` | keys: staged, key_scan | 보고 | 0 / 0 / — | 0 |
| `reports/c18-5/DEMO-MR-normal-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-5/DEMO-MR-stall-v1-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-5/estimate-retest.json` | keys: script, status, plan_id, plan_sha256 | 보고 | 2 / 6 / — | 0 |
| `reports/c18-5/pm-commands.md` | C-18-5 PM 명령 (DM-53 형식) | 보고 | 2 / 13 / — | 11 |
| `reports/c18-5/tests-part0.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-5/tests-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-5/tests-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-6/estimate-main.json` | keys: script, status, plan_id, plan_sha256 | 보고 | 4 / 4 / — | 0 |
| `reports/c18-6/mr-retest-evidence.json` | keys: script, plan_id, lane_log, expected | 보고 | 3 / 3 / — | 0 |
| `reports/c18-6/pm-commands.md` | C-18-6 PM 명령 — 본 실행 (DM-53 형식) | 보고 | 4 / 13 / — | 11 |
| `reports/c18-6/tests-part2.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-6/tests-part3.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-7/exclusions-before-rerun.json` | exclusions_version: demo-exclusions-v1 | 보고 | 2 / 2 / — | 0 |
| `reports/c18-7/pm-commands.md` | C-18-7 PM 명령 — 합치기 · 프록시 재기동 · 재실행 · 제외 목록 · 기록·집계 (DM-53 형식) | 보고 | 2 / 13 / — | 10 |
| `reports/c18-7/tests.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c18-8/account-corrections.json` | account_corrections_version: demo-account-corrections-v1 | 보고 | 4 / 4 / — | 0 |
| `reports/c18-8/exclusions.json` | exclusions_version: demo-exclusions-v2 | 보고 | 10 / 16 / — | 6 |
| `reports/c18-8/pm-commands.md` | C-18-8 PM 명령 — 합치기 · 제외 목록 · 기록 · 집계 · 재생 페이지 · 커밋 · 원본 백업 (DM-53 형식) | 보고 | 4 / 13 / — | 12 |
| `reports/c18-8/tests.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c19-1/aggregate-trials.json` | aggregate_version: demo-aggregate-v1 | 보고 | 0 / 0 / — | 0 |
| `reports/c19-1/aggregate-trials.md` | 데모 집계 — demo-trial-c18-2, demo-trial-c18-3 | 보고 | 0 / 0 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CS-normal-v1-47da0f11c48f407abb18959ba283433d.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CS-stall-v1-89187184d4cb46b09b6e173a1a264ffa.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CT-normal-v1-f854545930f34bd5bd828142116d1271.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-CT-stall-v1-819eb0783b724840b9333f480a599666.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-LR-normal-v1-433f48c2145948259077ce99f0495111.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19-1/replay-examples/DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c19-1/replay-examples/index.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 13 / — | 0 |
| `reports/c19-1/run-commands.md` | C-19-1 실행 명령 — 본 실행이 끝난 뒤 (DM-53 형식) | 보고 | 4 / 4 / — | 4 |
| `reports/c19-1/tests-c19-1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/c19/aggregate-main.json` | aggregate_version: demo-aggregate-v1 | 보고 | 17 / 17 / — | 6 |
| `reports/c19/aggregate-main.md` | 데모 집계 — demo-main-v1, demo-main-v1-lr2, demo-main-v1-mr2 | 보고 | 5 / 5 / — | 0 |
| `reports/c19/checks/excl_check.py` | Independent re-derivation of the exclusion codes (DM-78, DM-79, DM-80, DM-81) from raw signals, written apart from | 보고 | 0 / 2 / 3 | 0 |
| `reports/c19/checks/excl_check.txt` |  | 보고 | 0 / 1 / — | 0 |
| `reports/c19/checks/excl_rows.json` | list of 98 | 보고 | 0 / 1 / — | 0 |
| `reports/c19/checks/part0.json` | keys: summary, per_item | 보고 | 0 / 1 / — | 0 |
| `reports/c19/checks/part0.py` | C-19-2 part 0: main-run integrity, from small record files and lane logs only (no session.json opened here). | 보고 | 0 / 11 / 2 | 0 |
| `reports/c19/checks/part1_check.json` | list of 6 | 보고 | 0 / 1 / — | 0 |
| `reports/c19/checks/part1_check.py` | C-19-2 part 1: independent recompute of class, first STOP, credits and if-stopped ratio for chosen sessions, from | 보고 | 0 / 1 / 2 | 0 |
| `reports/c19/checks/part1_items.json` | keys: false_positive_detail, fp_summary, ct_normal_runs, misses | 보고 | 0 / 1 / — | 0 |
| `reports/c19/checks/part1_items.py` | C-19-2 part 1, DM-83 ②③④ and the credit/lane totals. Reads committed record files (record/judgements.json, | 보고 | 0 / 1 / 2 | 0 |
| `reports/c19/final-report.md` | C-19 데모 본 실행 — 최종 보고 (C-19-2) | 보고 | 7 / 7 / — | 14 |
| `reports/c19/replay/DEMO-CL-normal-v1-197550393b2a4bcc8b32c6c746f6a230.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19/replay/DEMO-CL-stall-v1-8d760276f7cd4bd4ac01cfc94d78a808.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 1 / 2 / — | 0 |
| `reports/c19/replay/DEMO-CS-normal-v1-15b45bf61cdb4780a6e7061d45a77c08.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19/replay/DEMO-CT-normal-v1-2efa22ce37474bfabc384e5166b93eb0.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19/replay/DEMO-CT-stall-v1-df08a5f8f475485f978baaaaf9373760.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 1 / 2 / — | 0 |
| `reports/c19/replay/DEMO-LR-normal-v1-447141e1675941319897a94157fb786b.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/c19/replay/DEMO-MR-normal-v1-364ff9c78d274b9cab77f38fab8b03b0.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 1 / 2 / — | 0 |
| `reports/c19/replay/index.html` | 세션 재생 페이지 (replay_demo 출력) | 보고 | 1 / 13 / — | 0 |
| `reports/c19/tests.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/g0-6/tool-execution-audit.json` | keys: input, rule, steps, summary | 보고 | 2 / 2 / — | 0 |
| `reports/g0-8/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e-analysis.json` | 세션 사후 분석 (analyze_session 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/g0-8/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e-manifest.json` | 세션 매니페스트 | 보고 | 0 / 0 / — | 0 |
| `reports/g0-8/tests-c8.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/legacy-criteria-results.json` | keys: criteria, role, files | 보고 | 4 / 4 / — | 0 |
| `reports/p0-1/comparison.md` | P0-1 역할별 비교 replay | 보고 | 4 / 8 / — | 4 |
| `reports/p0-1/replay.json` | keys: legacy_byte_match, new_pin, rows, summary | 보고 | 5 / 52 / — | 11 |
| `reports/p0-2/comparison.md` | P0-2 3단계 오프라인 비교 | 보고 | 2 / 8 / — | 2 |
| `reports/p0-2/replay.json` | keys: legacy_byte_match, p0_1_saved_match, collection_policy, runner_protocol | 보고 | 4 / 51 / — | 11 |
| `reports/p0-2/tests-core-initial.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/p0-2/tests-core.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 1 / 1 / — | 0 |
| `reports/p0-2/tests-final.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/p0-3/A-1-v2-preflight-deadlock-v0.2.json` | criteria_version: deadlock-v0.2 | 보고 | 2 / 2 / — | 0 |
| `reports/p0-3/A-1-v2-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 2 / 7 / — | 1 |
| `reports/p0-3/tests-c4-vs-p0-3-baseline-test-ids.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/p0-3/tests-c4-vs-p0-3-mechanism-test-ids.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/p0-3/tests-c5-part1.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/p0-3/tests-final.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 1 / — | 0 |
| `reports/p0-3/tests-handoff.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 1 / 1 / — | 2 |
| `reports/p0-4/A-1-v2-preflight.json` | 시나리오 실행 전 기록 (scenario_preflight 출력) | 보고 | 5 / 7 / — | 2 |
| `reports/p0-4/info-items-options.json` | keys: inputs, info_items_distribution, current_matches_saved_p0_2_states, options | 보고 | 2 / 2 / — | 0 |
| `reports/p0-4/tests-c6.json` | 오프라인 테스트 실행 결과 (run_offline_tests 출력) | 보고 | 0 / 0 / — | 0 |
| `reports/strict-probe-3472654ecfca4274b03383123aa03131/request.json` | keys: model, temperature, max_tokens, reasoning_effort | 보고 | 1 / 22 / — | 0 |
| `reports/strict-probe-3472654ecfca4274b03383123aa03131/response.json` | keys: status, body | 보고 | 0 / 43 / — | 0 |
| `reports/strict-probe-3472654ecfca4274b03383123aa03131/result.json` | keys: outcome, strict_request_accepted, schema_valid, value | 보고 | 0 / 34 / — | 2 |

### `scenario_assets/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `scenario_assets/A-1/ACCEPTANCE.md` | A-1 공개 인수 조건 v1 | 동결 | 3 / 1008 / — | 1 |
| `scenario_assets/A-1/SPEC.md` | 팀 업무 조회 — 기획 결정 기록 | 동결 | 3 / 1603 / — | 2 |
| `scenario_assets/A-1/acceptance_runner.py` | Local deterministic acceptance check. No LLM/network calls. | 동결 | 3 / 284 / 284 | 0 |
| `scenario_assets/A-1/src/task_query.py` | Starter implementation. Deliberately incomplete behavior, without conflicting requirements. | 동결 | 3 / 1549 / 731 | 0 |
| `scenario_assets/A-1/tests/test_task_query.py` |  | 동결 | 2 / 806 / 3065 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/ACCEPTANCE.md` | DEMO-CL 공개 인수 조건 v1 | 동결 | 1 / 1008 / — | 1 |
| `scenario_assets/DEMO-CL-normal-v1/NOTES.md` | parse_duration 수정 계획 | 동결 | 1 / 419 / — | 0 |
| `scenario_assets/DEMO-CL-normal-v1/acceptance_runner.py` | Local deterministic acceptance check. No LLM/network calls. | 동결 | 1 / 284 / 284 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/src/duration.py` | Duration text parser. | 동결 | 1 / 378 / 365 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/tests/test_strict.py` |  | 동결 | 6 / 104 / 133 | 0 |
| `scenario_assets/DEMO-CL-normal-v1/tests/test_units.py` |  | 동결 | 1 / 67 / 100 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/ACCEPTANCE.md` | DEMO-CL 공개 인수 조건 v1 | 동결 | 1 / 1008 / — | 1 |
| `scenario_assets/DEMO-CL-stall-v1/NOTES.md` | parse_duration 수정 계획 | 동결 | 1 / 419 / — | 0 |
| `scenario_assets/DEMO-CL-stall-v1/acceptance_runner.py` | Local deterministic acceptance check. No LLM/network calls. | 동결 | 1 / 284 / 284 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/src/duration.py` | Duration text parser. | 동결 | 1 / 378 / 365 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/tests/test_strict.py` |  | 동결 | 7 / 104 / 133 | 0 |
| `scenario_assets/DEMO-CL-stall-v1/tests/test_units.py` |  | 동결 | 2 / 67 / 100 | 0 |
| `scenario_assets/DEMO-CS-normal-v1/orders.json` | keys: orders | 동결 | 1 / 40 / — | 0 |
| `scenario_assets/DEMO-CS-normal-v1/policies/handling_codes.md` | 처리 코드 | 동결 | 1 / 52 / — | 0 |
| `scenario_assets/DEMO-CS-normal-v1/policies/refund.md` | 환불 정책 | 동결 | 3 / 61 / — | 2 |
| `scenario_assets/DEMO-CS-normal-v1/policies/shipping.md` | 배송 정책 | 동결 | 3 / 7 / — | 0 |
| `scenario_assets/DEMO-CS-stall-v1/orders.json` | keys: orders | 동결 | 1 / 40 / — | 0 |
| `scenario_assets/DEMO-CS-stall-v1/policies/handling_codes.md` | 처리 코드 | 동결 | 1 / 52 / — | 0 |
| `scenario_assets/DEMO-CS-stall-v1/policies/refund.md` | 환불 정책 | 동결 | 6 / 61 / — | 2 |
| `scenario_assets/DEMO-CS-stall-v1/policies/shipping.md` | 배송 정책 | 동결 | 1 / 7 / — | 0 |
| `scenario_assets/DEMO-CT-normal-v1/ACCEPTANCE.md` | DEMO-CT 공개 인수 조건 v1 | 동결 | 3 / 1008 / — | 1 |
| `scenario_assets/DEMO-CT-normal-v1/SPEC.md` | 팀 업무 조회 — 기획 결정 기록 | 동결 | 1 / 1603 / — | 2 |
| `scenario_assets/DEMO-CT-normal-v1/acceptance_runner.py` | Local deterministic acceptance check. No LLM/network calls. | 동결 | 1 / 284 / 284 | 0 |
| `scenario_assets/DEMO-CT-normal-v1/src/task_query.py` | Starter implementation. Deliberately incomplete behavior, without conflicting requirements. | 동결 | 1 / 1549 / 731 | 0 |
| `scenario_assets/DEMO-CT-normal-v1/tests/test_task_query.py` |  | 동결 | 3 / 806 / 3065 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/ACCEPTANCE.md` | DEMO-CT 공개 인수 조건 v1 | 동결 | 3 / 1008 / — | 1 |
| `scenario_assets/DEMO-CT-stall-v1/SPEC.md` | 팀 업무 조회 — 기획 결정 기록 | 동결 | 1 / 1603 / — | 2 |
| `scenario_assets/DEMO-CT-stall-v1/acceptance_runner.py` | Local deterministic acceptance check. No LLM/network calls. | 동결 | 1 / 284 / 284 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/src/task_query.py` | Starter implementation. Deliberately incomplete behavior, without conflicting requirements. | 동결 | 1 / 1549 / 731 | 0 |
| `scenario_assets/DEMO-CT-stall-v1/tests/test_task_query.py` |  | 동결 | 4 / 806 / 3065 | 0 |
| `scenario_assets/DEMO-LR-v1/README.md` | DEMO-LR 입력 폴더 (정상판·교착판 공통) | 동결 | 1 / 15 / — | 11 |
| `scenario_assets/DEMO-MR-v1/README.md` | DEMO-MR 입력 폴더 (정상판·교착판 공통) | 동결 | 2 / 15 / — | 11 |

### `scenario_judges/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `scenario_judges/DEMO-CS-v1.py` | Completion judge of DEMO-CS (C-18-3), shared by DEMO-CS-normal-v1 and DEMO-CS-stall-v1 (DM-15: the pair differs in | 동결 | 110 / 110 / 110 | 0 |
| `scenario_judges/DEMO-LR-normal-v1.py` | Completion judge of DEMO-LR-normal-v1 (C-18-3). Agents cannot read it. DEMO-LR-stall-v1 has its own judge: this | 동결 | 84 / 84 / 327 | 0 |
| `scenario_judges/DEMO-LR-stall-v1.py` | Completion judge of DEMO-LR-stall-v1 (C-18-3). Agents cannot read it. | 동결 | 103 / 104 / 436 | 0 |
| `scenario_judges/DEMO-MR-v1.py` | Completion judge of DEMO-MR (C-18-3), shared by DEMO-MR-normal-v1 and DEMO-MR-stall-v1. Agents cannot read it. | 동결 | 158 / 158 / 322 | 0 |

### `scenarios/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `scenarios/A-1-ambiguous-task-query.yaml` | title: 애매한 업무 조회 요청을 기획·구현·리뷰로 완성 | 실행 코드 | 23 / 24 / — | 0 |
| `scenarios/A-1-v2-ambiguous-task-query.yaml` | title: 애매한 업무 조회 요청을 기획·구현·리뷰로 완성 | 실행 코드 | 15 / 15 / — | 0 |
| `scenarios/A-1-v3-ambiguous-task-query.yaml` | title: 애매한 업무 조회 요청을 기획·구현·리뷰로 완성 | 실행 코드 | 11 / 11 / — | 0 |
| `scenarios/A-1-v4-ambiguous-task-query.yaml` | title: 애매한 업무 조회 요청을 기획·구현·리뷰로 완성 | 실행 코드 | 29 / 29 / — | 0 |
| `scenarios/DEMO-CL-normal-v1.yaml` | title: 기간 문자열 파서 버그를 기획·개발·검토로 고치기 | 동결 | 33 / 33 / — | 0 |
| `scenarios/DEMO-CL-stall-v1.yaml` | title: 기간 문자열 파서 버그를 기획·개발·검토로 고치기 | 동결 | 34 / 34 / — | 0 |
| `scenarios/DEMO-CS-normal-v1.yaml` | title: 배송 중 파손된 주문의 부분 환불 문의 처리하기 | 동결 | 29 / 29 / — | 0 |
| `scenarios/DEMO-CS-stall-v1.yaml` | title: 배송 중 파손된 주문의 부분 환불 문의 처리하기 | 동결 | 30 / 30 / — | 0 |
| `scenarios/DEMO-CT-N-v1.yaml` | title: 애매한 업무 조회 요청을 기획·구현·리뷰로 완성 | 동결 | 7 / 7 / — | 0 |
| `scenarios/DEMO-CT-normal-v1.yaml` | title: 업무 조회 기능을 승인된 명세로 기획·구현·검토하기 | 동결 | 34 / 34 / — | 0 |
| `scenarios/DEMO-CT-stall-v1.yaml` | title: 업무 조회 기능을 승인된 명세로 기획·구현·검토하기 | 동결 | 35 / 35 / — | 0 |
| `scenarios/DEMO-LR-normal-v1.yaml` | title: 멀티에이전트 LLM 실패 원인 논문 5 편 고르고 한 줄 요약하기 | 동결 | 36 / 36 / — | 0 |
| `scenarios/DEMO-LR-stall-v1.yaml` | title: 멀티에이전트 LLM 실패 원인 논문 5 편 고르고 한 줄 요약하기 | 동결 | 38 / 38 / — | 0 |
| `scenarios/DEMO-MR-normal-v1.yaml` | title: AI 코딩 도구 3 종의 공개 요금·주요 기능 비교표 만들기 | 동결 | 43 / 43 / — | 0 |
| `scenarios/DEMO-MR-stall-v1.yaml` | title: AI 코딩 도구 3 종의 공개 요금·주요 기능 비교표 만들기 | 동결 | 45 / 45 / — | 0 |
| `scenarios/agent-output.schema.json` | keys: additionalProperties, properties, required, title | 실행 코드 | 3 / 3 / — | 0 |
| `scenarios/scenario.schema.json` | keys: $defs, additionalProperties, properties, required | 실행 코드 | 2 / 2 / — | 2 |

### `tests/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `tests/fixtures/c17-1-protected-files.json` | 테스트 고정 자료 | 테스트 | 4 / 5 / — | 0 |
| `tests/fixtures/c17-3-protected-files.json` | 테스트 고정 자료 | 테스트 | 2 / 2 / — | 0 |
| `tests/fixtures/c17-4-v1-requests.json` | 테스트 고정 자료 | 테스트 | 8 / 11 / — | 3 |
| `tests/fixtures/demo_cl/no_shorthand_duration.py` | 테스트 고정 자료 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/fixtures/demo_cl/reference_duration.py` | 테스트 고정 자료 | 테스트 | 23 / 23 / 23 | 0 |
| `tests/fixtures/demo_ct/case_sensitive_task_query.py` | 테스트 고정 자료 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/fixtures/demo_ct/reference_task_query.py` | 테스트 고정 자료 | 테스트 | 26 / 26 / 26 | 0 |
| `tests/fixtures/p0-2-baseline-test-ids.json` | 테스트 고정 자료 | 테스트 | 3 / 3 / — | 0 |
| `tests/fixtures/p0-2-protected-files.json` | 테스트 고정 자료 | 테스트 | 1 / 1 / — | 0 |
| `tests/fixtures/p0-3-baseline-test-ids.json` | 테스트 고정 자료 | 테스트 | 0 / 0 / — | 0 |
| `tests/fixtures/p0-3-issue-vocabulary.json` | 테스트 고정 자료 | 테스트 | 1 / 1 / — | 0 |
| `tests/fixtures/p0-3-mechanism-test-ids.json` | 테스트 고정 자료 | 테스트 | 9 / 9 / — | 16 |
| `tests/fixtures/p0-3-protected-files.json` | 테스트 고정 자료 | 테스트 | 1 / 1 / — | 0 |
| `tests/fixtures/scenario-v2-artifact.yaml` | 테스트 고정 자료 | 테스트 | 20 / 20 / — | 0 |
| `tests/fixtures/scenario-v2-dialogue.yaml` | 테스트 고정 자료 | 테스트 | 14 / 15 / — | 0 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/orders.json` | 테스트 고정 자료 | 테스트 | 0 / 40 / — | 0 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/policies/handling_codes.md` | 테스트 고정 자료 | 테스트 | 0 / 52 / — | 0 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/policies/refund.md` | 테스트 고정 자료 | 테스트 | 0 / 61 / — | 2 |
| `tests/fixtures/scenario_assets/TEST-T1-v2/policies/shipping.md` | 테스트 고정 자료 | 테스트 | 0 / 7 / — | 0 |
| `tests/fixtures/scenario_judges/TEST-LR-v2.py` | 테스트 고정 자료 | 테스트 | 0 / 1 / 3 | 0 |
| `tests/fixtures/scenario_judges/TEST-MR-v2.py` | 테스트 고정 자료 | 테스트 | 1 / 1 / 3 | 0 |
| `tests/fixtures/scenario_judges/TEST-T1-v2.py` | 테스트 고정 자료 | 테스트 | 1 / 3 / 28 | 0 |
| `tests/fixtures/search/README.md` | 테스트 고정 자료 | 테스트 | 0 / 15 / — | 11 |
| `tests/fixtures/search/arxiv-error-400.xml` | 테스트 고정 자료 | 테스트 | 0 / 2 / — | 0 |
| `tests/fixtures/search/arxiv-query-200.xml` | 테스트 고정 자료 | 테스트 | 3 / 6 / — | 0 |
| `tests/fixtures/search/tavily-error-432.json` | 테스트 고정 자료 | 테스트 | 0 / 2 / — | 0 |
| `tests/fixtures/search/tavily-search-200.json` | 테스트 고정 자료 | 테스트 | 2 / 5 / — | 0 |
| `tests/fixtures/v1-calculation-bytes.json` | 테스트 고정 자료 | 테스트 | 1 / 1 / — | 0 |
| `tests/pinned_configs.py` | C-17-8 (S-12, DM-57): the demo proxy configurations are pinned to the model of demo-conditions.yaml. The C-17 | 테스트 | 1 / 1 / 16 | 0 |
| `tests/search_fixtures.py` | Shared offline pieces for the search tool tests (C-17-6): settings, a fake HTTP layer serving the fixtures in | 테스트 | 1 / 1 / 5 | 0 |
| `tests/t1_harness.py` | Offline harness for scenario-v2 dialogue (T1) runs (C-17-4): the real runner, an in-memory proxy, a fake upstream. | 테스트 | 3 / 3 / 27 | 0 |
| `tests/t2_harness.py` | Offline harness for scenario-v2 artifact (T2/T3) runs (C-17-5): the real runner on the artifact path, an | 테스트 | 3 / 3 / 40 | 0 |
| `tests/test_agent_metadata.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 9 | 0 |
| `tests/test_analysis_bugfix_s28.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_analyze_session.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_approval_gate.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_artifact_flows.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_artifact_v2.py` | 오프라인 테스트 | 테스트 | 5 / 5 / 5 | 0 |
| `tests/test_block_mode.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c14_analysis.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c17_4_part0.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c17_5_part0.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 4 | 0 |
| `tests/test_c17_6_part0.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 3 | 0 |
| `tests/test_c17_8_part0.py` | 오프라인 테스트 | 테스트 | 3 / 3 / 3 | 0 |
| `tests/test_c17_8_part1.py` | 오프라인 테스트 | 테스트 | 5 / 5 / 5 | 0 |
| `tests/test_c17_8_part2.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c18_1_part0.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_1_part1.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_1_part2.py` | 오프라인 테스트 | 테스트 | 21 / 21 / 23 | 0 |
| `tests/test_c18_1_part3.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c18_2_part0.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c18_2_part1.py` | 오프라인 테스트 | 테스트 | 31 / 31 / 32 | 0 |
| `tests/test_c18_2_part2.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 2 | 0 |
| `tests/test_c18_2_part3.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_3_part0.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c18_3_part1.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 3 | 0 |
| `tests/test_c18_3_part2.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 6 | 0 |
| `tests/test_c18_3_part3.py` | 오프라인 테스트 | 테스트 | 3 / 3 / 3 | 0 |
| `tests/test_c18_3_part4.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_4_part1.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_4_part2.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_c18_4_part2b.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_4_part3.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_5_part2.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_7_aggregate.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_7_exclusions.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_7_lr2_plan.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_7_proxy_timeout.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_8_accounts.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_8_exclusions.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c18_8_replay_cli.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c19_1_part1.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_c19_1_part2.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_compare_sessions.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_context_buffer.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 15 | 0 |
| `tests/test_criteria_integration.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 6 | 0 |
| `tests/test_criteria_v02.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 24 | 0 |
| `tests/test_criteria_v03.py` | 오프라인 테스트 | 테스트 | 2 / 2 / 7 | 0 |
| `tests/test_cs_tools.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_dataset_git_state.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_deadlock_criteria.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 33 | 0 |
| `tests/test_dialogue_flows.py` | 오프라인 테스트 | 테스트 | 3 / 3 / 3 | 0 |
| `tests/test_dialogue_router.py` | 오프라인 테스트 | 테스트 | 3 / 3 / 3 | 0 |
| `tests/test_dialogue_runner.py` | 오프라인 테스트 | 테스트 | 2 / 2 / 2 | 0 |
| `tests/test_dialogue_tool_flows.py` | 오프라인 테스트 | 테스트 | 2 / 2 / 2 | 0 |
| `tests/test_estimate_v10_context.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_experiment_recording.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 36 | 0 |
| `tests/test_explain_v1.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 2 | 0 |
| `tests/test_final_report_allowlist.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_groq_strict_probe.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_harness_facts.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 14 | 0 |
| `tests/test_health.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 3 | 0 |
| `tests/test_independent_collection.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 40 | 0 |
| `tests/test_issue_vocabulary.py` | 오프라인 테스트 | 테스트 | 6 / 6 / 32 | 0 |
| `tests/test_manifest_v03.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_metrics_v1.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_model_run_condition.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 6 | 0 |
| `tests/test_multi_tool_calls.py` | 오프라인 테스트 | 테스트 | 6 / 6 / 7 | 0 |
| `tests/test_observation_collectors.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 24 | 0 |
| `tests/test_observations.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 18 | 0 |
| `tests/test_output_contract_v3.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_p0_4_info_items.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 1 | 0 |
| `tests/test_preserved_replay.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 8 | 0 |
| `tests/test_probe_models.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 5 | 0 |
| `tests/test_probe_v3_strict.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 5 | 0 |
| `tests/test_progress_signal.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 56 | 0 |
| `tests/test_provider_switch.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_reasoning_all_calls.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 1 | 0 |
| `tests/test_recompute_v03.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_role_progress.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 48 | 0 |
| `tests/test_role_replay.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 18 | 0 |
| `tests/test_runner_helpers.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 36 | 0 |
| `tests/test_scenario_a1_v2.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_scenario_definition.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 18 | 0 |
| `tests/test_scenario_v2.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_search_tools.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 1 | 0 |
| `tests/test_session_isolation.py` | 오프라인 테스트 | 테스트 | 0 / 1 / 49 | 0 |
| `tests/test_session_registration.py` | 오프라인 테스트 | 테스트 | 1 / 1 / 2 | 0 |
| `tests/test_strict_preparation.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 18 | 0 |
| `tests/test_tool_execution_errors.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 0 | 0 |
| `tests/test_tool_recovery.py` | 오프라인 테스트 | 테스트 | 4 / 4 / 75 | 0 |
| `tests/test_version_dispatch.py` | 오프라인 테스트 | 테스트 | 0 / 0 / 9 | 0 |
| `tests/v1_request_capture.py` | Offline capture of every upstream request of a scenario-v1 run (A-1-v4, protocol v10), for byte comparison (C-17-4). | 테스트 | 1 / 1 / 13 | 0 |

### `tools/`

| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |
|---|---|---|---|---|
| `tools/aggregate_demo.py` | Demo aggregation (C-19-1 part 1): the sessions of a batch plan, by scenario, task type and overall, from the record | 도구 | 16 / 23 / 55 | 9 |
| `tools/analyze_c14.py` | C-14 offline evidence: never emit or interpret reasoning text, only its size. | 도구 | 4 / 4 / 4 | 2 |
| `tools/analyze_session.py` | Offline post-run analysis of one scenario session (guideline 7-3, C-8). Read-only. | 도구 | 16 / 19 / 95 | 5 |
| `tools/audit_tool_execution_errors.py` | G0-6 offline audit: which steps of a proxy log executed a tool that returned is_error. | 도구 | 1 / 1 / 2 | 0 |
| `tools/c17_7_evidence.py` | C-17-7 part 3 evidence, from files only (no network, no model reasoning text is read or written). | 도구 | 2 / 2 / 3 | 0 |
| `tools/c17_8_evidence.py` | C-17-8 evidence, from files only (no network; no model reasoning text is read or written). | 도구 | 6 / 6 / 8 | 0 |
| `tools/c18_1_evidence.py` | C-18-1 evidence, from files only (no network; no model reasoning text is read). | 도구 | 2 / 2 / 6 | 0 |
| `tools/c18_2_evidence.py` | C-18-2 part 0: the C-18-1 trial sessions read again offline (DM-60, DM-62). Read-only, no external call. | 도구 | 7 / 7 / 11 | 0 |
| `tools/c18_3_evidence.py` | C-18-3 part 4: the credits the T1 trial plan (batch_plans/demo-trial-c18-3.yaml) is expected to use. An estimate, | 도구 | 2 / 2 / 4 | 0 |
| `tools/c18_4_evidence.py` | C-18-4 evidence from the stored T1 trial sessions (DM-67). Read-only: the runner's records and the stored search | 도구 | 5 / 5 / 5 | 2 |
| `tools/c18_5_estimate.py` | Credits the C-18-5 MR retest plan (batch_plans/demo-trial-c18-5.yaml) is expected to use (DM-72). An estimate. | 도구 | 1 / 1 / 3 | 0 |
| `tools/c18_6_estimate.py` | Credits and wall time the C-19 main run (batch_plans/demo-main-v1.yaml, 4 lanes) is expected to use. An estimate. | 도구 | 3 / 3 / 3 | 0 |
| `tools/c18_6_evidence.py` | C-18-6 part 0 evidence from the MR retest (batch plan demo-trial-c18-5, DM-74). Read-only: the runner's records, | 도구 | 2 / 2 / 2 | 0 |
| `tools/check_harness_facts.py` | Offline check of one session log: were the call budget and writable files stated to the model? | 도구 | 2 / 4 / 6 | 1 |
| `tools/compare_sessions.py` | Side-by-side offline comparison of two analysed sessions (C-11). Read-only. | 도구 | 4 / 6 / 8 | 4 |
| `tools/demo_account_corrections.py` | Account label correction file of the demo main run reruns (C-18-8 part 2, DM-81 ②). The reruns were started from | 도구 | 4 / 4 / 8 | 0 |
| `tools/demo_exclusions.py` | Exclusion and replacement list of the demo main run (C-18-7 part 1, DM-78, DM-79; C-18-8 part 1, DM-81). Rules | 도구 | 15 / 16 / 23 | 6 |
| `tools/demo_records.py` | Demo record rule (C-18-3 part 0, DM-64 ⑤): what of a demo session goes into the repository, and the backup of the rest. | 도구 | 51 / 51 / 89 | 2 |
| `tools/estimate_v10_context.py` | Estimate v10 final-report input size from a stored v9 session without emitting reasoning text. | 도구 | 1 / 1 / 1 | 0 |
| `tools/evaluate_legacy_criteria.py` | Read-only legacy audit. Conditional projections are NOT real step observations. | 도구 | 3 / 3 / 3 | 2 |
| `tools/final_freeze.py` | Final freeze of the demo (C-18-3 part 3, DM-33): one record of everything the main run depends on, made once before | 도구 | 22 / 28 / 60 | 12 |
| `tools/gateway_prices.py` | Gateway token prices (credits per 1M tokens) and the token x price credit estimate (DM-58 ③, C-18-1). | 도구 | 5 / 5 / 30 | 0 |
| `tools/p0_4_info_items_options.py` | P0-4 offline analysis: replay saved P0-2 observations of the A-1 log under info_items options. | 도구 | 1 / 1 / 2 | 0 |
| `tools/probe_gateway.py` | User-run provider probe for the configured upstream (D-27 gateway). Never imported by the runner. | 도구 | 12 / 14 / 25 | 7 |
| `tools/probe_gateway_support.py` | Shared probe helpers. Kept separate so the Groq probe's behaviour is not changed by imports. | 도구 | 0 / 0 / 0 | 0 |
| `tools/probe_groq_strict.py` | User-run Groq strict-schema probe for output-contract-v2. Never imported by the scenario runner. | 도구 | 5 / 5 / 6 | 4 |
| `tools/probe_search.py` | PM search check (C-17-6 part 3): one Tavily request and one arXiv request with fixed queries, no LLM call. | 도구 | 6 / 6 / 14 | 4 |
| `tools/recompute_v03.py` | C-17-1 part 3 / C-17-2 part 0: re-judge existing sessions with deadlock-v0.3 / progress-v3 and explain-v1, offline. | 도구 | 12 / 12 / 13 | 2 |
| `tools/rejudge_dialogue.py` | Recompute a dialogue (T1) run's judge results from what its run folder stored (C-17-6 part 2, DM-13). | 도구 | 8 / 8 / 8 | 4 |
| `tools/replay_demo.py` | Session replay pages of the demo (C-19-1 part 2): a small replay record per session, and static HTML pages from it. | 도구 | 10 / 17 / 28 | 6 |
| `tools/replay_preserved_observations.py` | Offline three-stage replay. Never infer historical artifact snapshots. | 도구 | 2 / 3 / 4 | 0 |
| `tools/replay_role_progress.py` | Offline, immutable replay with a mandatory stored-v1 byte equivalence gate. | 도구 | 1 / 2 / 4 | 0 |
| `tools/run_batch.py` | Batch runner for demo sessions (C-18-2, DM-63). No model call of its own: it starts experiments/run_scenario.py | 도구 | 41 / 42 / 97 | 2 |
| `tools/run_offline_tests.py` | Run the complete unittest suite and report frozen baseline/new test groups. | 도구 | 7 / 10 / 13 | 5 |
| `tools/scenario_preflight.py` | Pre-run record for one scenario: file hash, vocabulary hash and the acceptance result on a | 도구 | 4 / 7 / 16 | 5 |
| `tools/summarize_demo_session.py` | Short summary of one demo session folder for the PM to paste back (C-18-1 part 3). Offline, read-only. | 도구 | 7 / 7 / 18 | 0 |
| `tools/write_criteria_snapshot.py` | Generate the new pinned snapshot; never overwrite a previous version. | 도구 | 4 / 4 / 5 | 0 |

## 5. 실행 기록 (`runs/`, `logs/`) — 세션 폴더 단위

실행 기록은 DM-84 ① 대로 옮기지 않는다. 파일 하나하나 대신 폴더 단위로 적는다.

| 폴더 | 파일 수 | 폴더 밖 참조 |
|---|---|---|
| `runs/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e/` | 96 | 0 |
| `runs/A-1-v3-4a0087756b2641f4b8f9b025c0419f73/` | 63 | 5 |
| `runs/A-1-v4-e174aafe805b4f59bb62d7c95716b8b7/` | 165 | 8 |
| `runs/demo/DEMO-CL-normal-v1-108968e505cf4890ab930759f0cf67e5/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-197550393b2a4bcc8b32c6c746f6a230/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-51aef935db294a64bdf2fbec9ca91e8a/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-a0b222bdf8364e7abd1239f0c7be59f1/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-c1ff4dc412b94511be238ae8775d68c8/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-c3a4c019c1ec48ca86b22d45340aea7b/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-d5460d69bcc84e20a4eaef6275ea1e8a/` | 9 | 0 |
| `runs/demo/DEMO-CL-normal-v1-ed9df513bae340ad97ae94b8184b1b39/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-0cd6385b25794e96866bcc18a25cc702/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-1372b13baf0d4b1eb9d2269849a0716b/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-3f94b2979b0b4273b4b7c61a62cf933b/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-41adbef132994f59a09e476af7b68cd4/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-476c03070e414d8aa17df176d092cbb0/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-5a754c129a094e65bea0a57a07d53c3a/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-8d760276f7cd4bd4ac01cfc94d78a808/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-a6b00d3091bf4150b29e0448e6e91a0c/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-d4ba1c9f7928415ab4dca7704aa792fa/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-dc7cc3d96b9e40d0898001b27a2bcd30/` | 9 | 0 |
| `runs/demo/DEMO-CL-stall-v1-f08705febcab4bcdacaea83cb8bd61f1/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-15b45bf61cdb4780a6e7061d45a77c08/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-36a780e99f074218a8136ff51567c635/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-47da0f11c48f407abb18959ba283433d/` | 9 | 9 |
| `runs/demo/DEMO-CS-normal-v1-7d4e05252209462e80c8725716b6f4ea/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-c22d282384344a9da4786b22c6266437/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-cf35c19c1ca149f09894c3e3656f9198/` | 9 | 0 |
| `runs/demo/DEMO-CS-normal-v1-e42eed86ae354e518c7d9022575ed75a/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-0246cb21ee4c4a1894ef49f226467cfc/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-03ef680d97fe40f4993574704fb619b8/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-59d845172ff94372aef80afc024b3908/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-89187184d4cb46b09b6e173a1a264ffa/` | 9 | 9 |
| `runs/demo/DEMO-CS-stall-v1-8cc8dfe64ad14bab90967988943a296c/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-a8294fa41c19467e80c55f95182f8422/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-d87fda6b57f441639c25e5b342f9e681/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-efbf439a3184420da2ebe74ccad9ad02/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-f077146e52ba4100853f737dc1359975/` | 9 | 0 |
| `runs/demo/DEMO-CS-stall-v1-f96e49d6750948dcb80e110b6be79d5d/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-0ffd2671048940f0975fadfa0929a0a5/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-175a40c738a24b8f9f9fcfc91c8e2622/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-70750f86c3c447a8b659c9b120dd1502/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-ac014aa723c246bd9d013cce018f2184/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-b46eacacf5844eb594d692f7b665daae/` | 9 | 0 |
| `runs/demo/DEMO-CT-N-v1-b9003e8ffbc146bb99111768272eaf56/` | 9 | 8 |
| `runs/demo/DEMO-CT-normal-v1-102725acfa354c7e9b823b76002af10e/` | 9 | 0 |
| `runs/demo/DEMO-CT-normal-v1-2efa22ce37474bfabc384e5166b93eb0/` | 9 | 0 |
| `runs/demo/DEMO-CT-normal-v1-3126a6ae0013469eba6ad3661c3dd811/` | 9 | 0 |
| `runs/demo/DEMO-CT-normal-v1-d7d4e26f90ed42a3a975a2751189fde4/` | 9 | 0 |
| `runs/demo/DEMO-CT-normal-v1-f854545930f34bd5bd828142116d1271/` | 9 | 8 |
| `runs/demo/DEMO-CT-normal-v1-fcd55b67875c429e92744fc62af98a33/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-000a538a7dc746fbb38319f905a40325/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-0d834a8243ff46589cf462d0e0008758/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-158e7cace4ae478aa189104fdc448f68/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-18b69568fc63473cbe59097b52e0386a/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-1b7bd9638b544c25ba0495e145b6fa13/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-22a0edb6917e421a95f83fa2635d2337/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-34b058044ab64663911145fdd72da6a4/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-46ea7790a8a84124a440fcdb89b8dffb/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-7634c328e20a4936aa6e42ee72163251/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-79fdaab15c9c478eb90bca10a2dba524/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-819eb0783b724840b9333f480a599666/` | 9 | 8 |
| `runs/demo/DEMO-CT-stall-v1-b12151a11ca14792871b5dc6e3618eab/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-b3ae99543df54d159c9cab9b00c072a1/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-bf36c7d96b10472680da030ef2faf015/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-df08a5f8f475485f978baaaaf9373760/` | 9 | 0 |
| `runs/demo/DEMO-CT-stall-v1-eba5a575219e4f07b22948f057723c83/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-188f632363744cdfb18b401ade67b7e0/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-1d992018a1224411ba30be0a0f21a6d3/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-2ca98307d99344be837b416875873b96/` | 9 | 3 |
| `runs/demo/DEMO-LR-normal-v1-433f48c2145948259077ce99f0495111/` | 9 | 8 |
| `runs/demo/DEMO-LR-normal-v1-447141e1675941319897a94157fb786b/` | 9 | 3 |
| `runs/demo/DEMO-LR-normal-v1-7ed9090de9d04c56a166599c9c5fe5d6/` | 9 | 3 |
| `runs/demo/DEMO-LR-normal-v1-a8e1e322c8944e3d976db2842dc67e15/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-af33de48dd324447b205dc711caf619f/` | 9 | 3 |
| `runs/demo/DEMO-LR-normal-v1-cca3215ab7454a25bd1cb98f5464ac42/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-f4efff8a911e4cbab3c90a0291a078fa/` | 9 | 0 |
| `runs/demo/DEMO-LR-normal-v1-f8caef5d1e56489397d29198dccd488c/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-07bae84642fe4cab82c2f40101b67703/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-36d81727408c43d487a01af14e2be182/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-53b21638e64745aba1048f342229208c/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-569ceba45d8b45389c235112c4d8140d/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-69bf46e3950045668c6686756f0134ec/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-6e073f2122c14377bee7b55a00a84196/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-7c6a57c507ae4dcfb3da6c581f0949d9/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-8a25037bd6f04bd2b3e1b8bf482373d0/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-a3201bee685b48c58f42a0950723fa49/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-a63bb59818ed46a7b575767786380958/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-b9d13ece887c48d6ab4437009ab504e8/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-b9da451106144cecae3f68734dc832dc/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-bd57f54b0a0347c7bbf03bbab250aa4d/` | 9 | 8 |
| `runs/demo/DEMO-LR-stall-v1-c0618659f74043fdb78d4fd6314eb57a/` | 9 | 3 |
| `runs/demo/DEMO-LR-stall-v1-d5a170cb163a478aa90bc1e8b8fe8f8c/` | 9 | 0 |
| `runs/demo/DEMO-LR-stall-v1-ef48a692a5e440cab2b2c42861c8a211/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-0382a7802a7a485b9341ac3bee6c053e/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-364ff9c78d274b9cab77f38fab8b03b0/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-461d01247f5c4831bf9fd03be9069bfb/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-653feb85bfb844268358ab344f8eca61/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-8a458208d11c4e75af77a55978a60957/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-9e48e129f60943409b6101629ed53a9a/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-bbd8ff94cd494384860dc0875131ebfd/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-c0daa4d612c4460e811deff9912d32e5/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-d69416ae013c4c69858f746a8bdc7a58/` | 9 | 0 |
| `runs/demo/DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b/` | 9 | 10 |
| `runs/demo/DEMO-MR-stall-v1-0c6719c3e4424458aaa68a2606734c65/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-173d03d693e447caabc808d3265a9d76/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-45cf2d1436e34cdda4272fe1876f9ed6/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-54ca8a0703434b7fb51e0a1bb3d8db2d/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-5a05895c256849bab98a2de7fce761b2/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-60b59c821e91485fa37415b4ef80981f/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-7cee4bcbe08e4825b059f28a79705372/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-82564d3c1e534d5aa98dd5dc6e0dbd54/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-abb4704590674b2195834c6d5e252b77/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-bc8136dfab144a7793d2fc936ba8dc6d/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-d454a7cd328e4cbd919539f4ccb60d2a/` | 9 | 9 |
| `runs/demo/DEMO-MR-stall-v1-e40eaf70c745421aa35ec1da82143b58/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-e9211faaf2b04d2c829808c7867b30cb/` | 9 | 0 |
| `runs/demo/DEMO-MR-stall-v1-f48f87e8ad1441569bddc0c779d2f104/` | 9 | 0 |
| `runs/gateway-probes/` | 84 | — |
| `runs/search-probes/` | 3 | — |
| `runs/strict-probes/` | 3 | — |
| `logs/A-1-134bc231b51c498cbf251cb22613c1aa.json` | 1 | 0 |
| `logs/A-1-67aeab11753e41169f76116f260564f5.json` | 1 | 0 |
| `logs/A-1-82c393c248a34286b318f344f2e181e4.json` | 1 | 14 |
| `logs/A-1-d7a6e53f442242d590bc3fd7ee83c001.json` | 1 | 0 |
| `logs/A-1-e7733f85151248849a3c2df81b9952eb.json` | 1 | 0 |
| `logs/A-1-f869d9c183854e7e80d07e30216bdab8.json` | 1 | 1 |
| `logs/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e.json` | 1 | 1 |
| `logs/A-1-v3-4a0087756b2641f4b8f9b025c0419f73.json` | 1 | 2 |
| `logs/A-1-v4-e174aafe805b4f59bb62d7c95716b8b7.json` | 1 | 5 |

## 6. 추적되지 않는 것과 `.gitignore`

`git status --ignored` 를 두 단계 경로로 묶음. 지우지 않는다.

| 상태 | 경로 | 항목 수 |
|---|---|---|
| 무시됨 | `__pycache__/` | 1 |
| 무시됨 | `docs/handoff/` | 1 |
| 무시됨 | `experiments/__pycache__/` | 1 |
| 무시됨 | `logs/demo/` | 1 |
| 무시됨 | `runs/demo-batches/` | 1 |
| 무시됨 | `runs/demo/` | 501 |
| 무시됨 | `runs/strict-probes/` | 3 |
| 무시됨 | `scenario_judges/__pycache__/` | 1 |
| 무시됨 | `tests/__pycache__/` | 1 |
| 무시됨 | `tools/__pycache__/` | 1 |
| 무시됨 | `venv/` | 1 |
| 추적 안 됨 | `.DS_Store` | 1 |
| 추적 안 됨 | `docs/.DS_Store` | 1 |
| 추적 안 됨 | `reports/c19-5/` | 1 |

`.gitignore` 의 규칙 줄 : `.env`, `.env.*`, `venv/`, `__pycache__/`, `*.pyc`, `runs/`, `logs/`, `docs/handoff/`, `data/raw/`, `*.bak`

## 7. 옮길 수 있는 후보 (참조 0)

분류가 문서·보고·기타이고 전체 경로·이름·모듈 참조가 모두 0 인 파일.

| 경로 | 분류 | 무엇인지 |
|---|---|---|
| `docs/A-1-review.md` | 문서 | A-1 검토용 요약 |
| `docs/A1-revision2-budget.md` | 문서 | 인수인계 점검 및 A-1 revision 2 예산 |
| `docs/A1-tool-failure-recovery.md` | 문서 | A-1 step 1 도구 오류: 증거와 수정 |
| `docs/P0-2-replay-protocol.md` | 문서 | P0-2 오프라인 적용 범위 |
| `docs/S1-session-isolation.md` | 문서 | S1 세션 격리 — 재시작 복원 보완 |
| `docs/S3-A-progress.md` | 문서 | S3-A 진전도 관측 — 구현과 사용 계약 |
| `docs/S3-B-runner-review.md` | 문서 | A-1 실행기 구현 및 실행 조건 검토 |
| `docs/S3-C-legacy-results.md` | 문서 | S3-C 기존 로그 적용 결과 |
| `docs/S3-C-기존로그적용결과.md` | 문서 | S3-C 기존 로그 적용 결과 |
| `docs/decisions/007-info-items-recorded-only.md` | 문서 | P0-4: info_items 는 기록만 한다 (선택지 C) |
| `docs/decisions/008-tool-execution-errors.md` | 문서 | G0-6: 도구 실행 오류를 step 기록에 반영 (결함 8) |
| `docs/decisions/010-harness-facts-v8.md` | 문서 | G0-14: 호출 예산과 쓰기 가능 파일을 사실로 알린다 (결함 6·7, 프로토콜 v8) |
| `docs/decisions/012-final-report-allowlist-v10.md` | 문서 | S-25 · S-31: 최종 보고 요청은 허용 필드만 싣는다 (프로토콜 v10) |
| `docs/decisions/013-deadlock-v0.3.md` | 문서 | DM-10 · DM-22: `deadlock-v0.3` / `progress-v3` (데모 트랙 판정 규칙) |
| `docs/decisions/014-demo-block-mode.md` | 문서 | DM-7 · DM-23: 데모 차단 모드 (block) |
| `docs/decisions/015-scenario-v2-contract-v3.md` | 문서 | 시나리오 v2 · 출력 계약 v3 · T1 관측 필드 (C-17-3) |
| `docs/decisions/016-dialogue-runner-t1.md` | 문서 | 실행기 T1 대화 흐름 (C-17-4) |
| `docs/decisions/017-artifact-runner-v2.md` | 문서 | 실행기 v2 산출물 과제 경로 (C-17-5) |
| `docs/decisions/018-dialogue-tools.md` | 문서 | T1 도구 4 종 · 검색 결과 원문 저장 (C-17-6) |
| `docs/decisions/020-demo-cl-credits-preflight.md` | 문서 | 데모 크레딧 실측 · preflight v0.3 · DEMO-CL (C-18-1) |
| `docs/decisions/021-demo-ct-batch-runner.md` | 문서 | DEMO-CT · DEMO-CT-N · 배치 실행기 (C-18-2) |
| `docs/decisions/022-demo-t1-final-freeze-records.md` | 문서 | 데모 기록 커밋 규칙 · DEMO-CS·MR·LR (T1) · 최종 동결 (C-18-3) |
| `docs/decisions/023-demo-t1-trial-fixes.md` | 문서 | T1 시험 결과 반영 — CS 담당 확정 · MR 출처 전달 · 시험 기록 (C-18-4) |
| `docs/decisions/024-demo-aggregate-replay.md` | 문서 | 데모 집계 도구 · 세션 재생 페이지 (C-19-1) |
| `docs/decisions/025-demo-mr-retest-final-freeze.md` | 문서 | MR 재시험 결과 · 동결 범위 62 파일 · 최종 동결 (C-18-6) |
| `docs/decisions/026-demo-main-run-environment-errors.md` | 문서 | 본 실행 환경 오류 : 프록시 시간 제한 · LR 보충 · 제외·대체 목록 (C-18-7) |
| `docs/decisions/027-demo-main-run-operator-errors.md` | 문서 | 본 실행 운영 실수 정리 : 검색 키 오타 · 두 번째 실패 · 계정 이름표 (C-18-8) |
| `docs/findings/005-recovered-narrative-not-shared.md` | 문서 | 실행기 결함 후보: 회복된 narrative의 역할 간 전달 누락 |
| `docs/findings/sources.json` | 문서 | keys: C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\session.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\steps.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\summary.json, C:\Users\관영\guardrail\runs\A1-validation-b1bf4ddc7e4e4834886375450e84268c\buffered\A-1-82c393c248a34286b318f344f2e181e4\scenario.yaml |
| `docs/scenario_schema.md` | 문서 | scenario-v1 스키마 — S3-B 첫 검토 |
| `reports/A-1-initial-tests.json` | 보고 | keys: tests, passed, failed, errors |
| `reports/A-1-token-estimate.json` | 보고 | keys: assumed, input_tokens_range, completion_tokens_range, total_tokens_range |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-analysis.json` | 보고 | 세션 사후 분석 (analyze_session 출력) |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-harness-facts.json` | 보고 | keys: session_id, runner_protocol, max_llm_calls_per_step, roles |
| `reports/a-1-v3/A-1-v3-4a0087756b2641f4b8f9b025c0419f73-manifest.json` | 보고 | 세션 매니페스트 |
| `reports/a-1-v3/tests-c10.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/a-1-v3/tests-c11.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/a-1-v3/tests-c9.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/a-1-v4/tests-c14.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/a-1-v4/verification-c14.json` | 보고 | keys: files_scanned, patterns, environment_variables_checked, hits |
| `reports/c15/tests-c15-estimate-fix.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c15/tests-c15.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c16/tests-c16-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c16/tests-c16.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-1/tests-c17-1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-2/tests-c17-2-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-2/tests-c17-2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-3/tests-c17-3-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-3/tests-c17-3-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-3/tests-c17-3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-4/tests-c17-4-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-4/tests-c17-4-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-4/tests-c17-4-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-4/tests-c17-4.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-5/tests-c17-5-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-5/tests-c17-5-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-5/tests-c17-5-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-5/tests-c17-5.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-6/tests-c17-6-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-6/tests-c17-6-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-6/tests-c17-6-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-6/tests-c17-6.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-7/tests-c17-7-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-7/tests-c17-7-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-7/tests-c17-7.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-8/tests-c17-8-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-8/tests-c17-8-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c17-8/tests-c17-8-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-1/DEMO-CL-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-1/DEMO-CL-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-1/tests-c18-1-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-1/tests-c18-1-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-1/tests-c18-1-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-1/tests-c18-1-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-2/DEMO-CL-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-2/DEMO-CL-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-2/DEMO-CT-N-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-2/DEMO-CT-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-2/DEMO-CT-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-2/tests-c18-2-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-2/tests-c18-2-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-2/tests-c18-2-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-2/tests-c18-2-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-3/DEMO-CS-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/DEMO-CS-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/DEMO-LR-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/DEMO-LR-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/DEMO-MR-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/DEMO-MR-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-3/tests-c18-3-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-3/tests-c18-3-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-3/tests-c18-3-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-3/tests-c18-3-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-3/tests-c18-3-part4.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/DEMO-CS-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-4/DEMO-CS-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-4/DEMO-MR-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-4/DEMO-MR-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-4/rejudge-DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b.json` | 보고 | keys: tool, session_id, run_dir, judge |
| `reports/c18-4/rejudge-DEMO-MR-stall-v1-d454a7cd328e4cbd919539f4ccb60d2a.json` | 보고 | keys: tool, session_id, run_dir, judge |
| `reports/c18-4/tests-c18-4-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/tests-c18-4-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/tests-c18-4-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/tests-c18-4-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/tests-c18-4-part4.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-4/trial-records-check.json` | 보고 | keys: sessions, index, ok |
| `reports/c18-4/trial-records-stage.json` | 보고 | keys: staged, key_scan |
| `reports/c18-5/DEMO-MR-normal-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-5/DEMO-MR-stall-v1-preflight.json` | 보고 | 시나리오 실행 전 기록 (scenario_preflight 출력) |
| `reports/c18-5/tests-part0.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-5/tests-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-5/tests-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-6/tests-part2.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-6/tests-part3.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-7/tests.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c18-8/tests.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c19-1/aggregate-trials.json` | 보고 | aggregate_version: demo-aggregate-v1 |
| `reports/c19-1/aggregate-trials.md` | 보고 | 데모 집계 — demo-trial-c18-2, demo-trial-c18-3 |
| `reports/c19-1/replay-examples/DEMO-CS-stall-v1-89187184d4cb46b09b6e173a1a264ffa.html` | 보고 | 세션 재생 페이지 (replay_demo 출력) |
| `reports/c19-1/replay-examples/DEMO-MR-normal-v1-e948ebfd108d45f596b37026c26b415b.html` | 보고 | 세션 재생 페이지 (replay_demo 출력) |
| `reports/c19-1/tests-c19-1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/c19/tests.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/g0-8/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e-analysis.json` | 보고 | 세션 사후 분석 (analyze_session 출력) |
| `reports/g0-8/A-1-v2-b51f67df2fb9402ba15fccb35c3db53e-manifest.json` | 보고 | 세션 매니페스트 |
| `reports/g0-8/tests-c8.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/p0-3/tests-c4-vs-p0-3-baseline-test-ids.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/p0-3/tests-c4-vs-p0-3-mechanism-test-ids.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/p0-3/tests-c5-part1.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
| `reports/p0-4/tests-c6.json` | 보고 | 오프라인 테스트 실행 결과 (run_offline_tests 출력) |
