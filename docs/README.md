# docs — 문서

| 폴더 | 무엇인지 |
|---|---|
| [`criteria/`](criteria/) | 판정 기준 · 동결 기록. **바꾸지 않는다** (새 기준은 새 버전 파일) |
| [`decisions/`](decisions/) | 결정 문서 (번호 순). PM 결정(D-·S-·DM-)을 구현에서 어떻게 지켰는지 |
| [`design/`](design/) | 설계 문서와 그 숫자를 만든 읽기 전용 스크립트 |
| [`findings/`](findings/) | 실험에서 발견한 것 (초기 A-1 4 차 실행 분석 등) |
| [`assets/`](assets/) | 로고 |
| `handoff/` | PM 이 관리하는 인계 문서 (가이드라인·README 초안). `.gitignore` 로 저장소에 넣지 않는다 (S-21) |

## criteria — 판정 기준 · 동결 기록

| 파일 | 무엇인지 |
|---|---|
| [`deadlock-v0.1.json`](criteria/deadlock-v0.1.json) | 첫 판정 기준 (설명 `deadlock_criteria.md`) |
| [`deadlock-v0.2.json`](criteria/deadlock-v0.2.json) | v0.2 : 역할별 진전도 비교·전역 연속 (P0-1, D-2). A-1-v2~v4 가 씀 |
| [`deadlock-v0.3.json`](criteria/deadlock-v0.3.json) | v0.3 : v0.2 + T1 대화 신호 + T3 산출물 신호, 구현·템플릿 해시까지 고정 (DM-10, DM-22, DM-33). 데모가 씀 |
| [`explain-v1.json`](criteria/explain-v1.json) | STOP 원인 설명 템플릿 E1~E7 과 고르는 순서 (DM-9) |
| [`demo-final-freeze.json`](criteria/demo-final-freeze.json) | 데모 최종 동결 : 62 파일 · 11 시나리오의 sha256, 내용 해시 `6a7bf8dc…` (DM-75). `tools/final_freeze.py check` 로 확인 |

## decisions — 결정 문서

| 문서 | 내용 |
|---|---|
| [`002`](decisions/002-session-lifecycle.md) | 세션 시작·종료 API 와 재시작 복원 |
| [`003`](decisions/003-progress-observations.md) | 관측 API, 대화·산출물 두 소스 진전도 |
| [`004`](decisions/004-role-scoped-progress.md) | 역할별 진전도 비교 (P0-1) |
| [`005`](decisions/005-independent-observation-collection.md) | 대화·산출물 관측 독립 보존 (P0-2) |
| [`006`](decisions/006-closed-issue-vocabulary.md) | 닫힌 쟁점 어휘 (P0-3) |
| [`007`](decisions/007-info-items-recorded-only.md) | `info_items` 는 기록만 (P0-4, 선택지 C) |
| [`008`](decisions/008-tool-execution-errors.md) | 도구 실행 오류를 step 기록에 반영 (G0-6) |
| [`009`](decisions/009-verified-narrative-sharing.md) | 검증된 최종 보고를 다른 역할에 전달 (G0-13) |
| [`010`](decisions/010-harness-facts-v8.md) | 호출 예산·쓰기 가능 파일을 사실로 고지 (G0-14, 프로토콜 v8) |
| [`011`](decisions/011-provider-switch-gateway.md) | 업스트림 설정 선택, 프로토콜 매번 명시 (D-27, D-25) |
| [`012`](decisions/012-final-report-allowlist-v10.md) | 최종 보고 요청은 허용 필드만 (프로토콜 v10, S-25·S-31) |
| [`013`](decisions/013-deadlock-v0.3.md) | `deadlock-v0.3` / `progress-v3` 와 재동결 기록 (DM-10, DM-22) |
| [`014`](decisions/014-demo-block-mode.md) | 데모 차단 모드 (DM-7, DM-23) |
| [`015`](decisions/015-scenario-v2-contract-v3.md) | 시나리오 v2 · 출력 계약 v3 · T1 관측 필드 (C-17-3) |
| [`016`](decisions/016-dialogue-runner-t1.md) | 실행기 T1 대화 흐름 (C-17-4) |
| [`017`](decisions/017-artifact-runner-v2.md) | 실행기 v2 산출물 과제 경로 (C-17-5) |
| [`018`](decisions/018-dialogue-tools.md) | T1 도구 4 종 · 검색 결과 원문 저장 (C-17-6) |
| [`019`](decisions/019-model-run-condition.md) | 모델 실행 조건 · 조건군 (C-17-7) |
| [`020`](decisions/020-demo-cl-credits-preflight.md) | 크레딧 실측 · preflight v0.3 · DEMO-CL (C-18-1) |
| [`021`](decisions/021-demo-ct-batch-runner.md) | DEMO-CT · CT-N · 배치 실행기 (C-18-2) |
| [`022`](decisions/022-demo-t1-final-freeze-records.md) | 데모 기록 커밋 규칙 · T1 시나리오 · 최종 동결 도구 (C-18-3) |
| [`023`](decisions/023-demo-t1-trial-fixes.md) | T1 시험 결과 반영 (C-18-4) |
| [`024`](decisions/024-demo-aggregate-replay.md) | 집계 도구 · 세션 재생 페이지 (C-19-1) |
| [`025`](decisions/025-demo-mr-retest-final-freeze.md) | MR 재시험 · 동결 범위 62 파일 · 최종 동결 (C-18-6) |
| [`026`](decisions/026-demo-main-run-environment-errors.md) | 본 실행 환경 오류 : 프록시 시간 제한 · LR 보충 · 제외 목록 (C-18-7) |
| [`027`](decisions/027-demo-main-run-operator-errors.md) | 본 실행 운영 실수 : 검색 키 오타 · 두 번째 실패 · 계정 이름표 (C-18-8) |

## design — 설계

| 파일 | 내용 |
|---|---|
| [`stage1-collection-spec.md`](design/stage1-collection-spec.md) | Stage 1 수집 규격 설계 (C-12). 숫자 : `stage1_values.py` → `stage1-values.json` |
| [`metrics-v1.md`](design/metrics-v1.md) | 1 학기 지표 정의 `metrics-v1`. 계산 가능성 점검 : `metrics_v1_check.py` → `metrics-v1-check.json` |
| [`budget-a-1-v4.md`](design/budget-a-1-v4.md) | A-1-v4 크레딧 추정과 실측. 숫자 : `budget_v9.py` → `budget-v9.json` |
| [`demo-scenarios.md`](design/demo-scenarios.md) | 데모 시나리오 명세 (C-16 파트 1) |
| [`demo-runner-extension.md`](design/demo-runner-extension.md) | 데모 실행기 확장 설계 (C-16 파트 2) |
| [`demo-deadlock-v0.3.md`](design/demo-deadlock-v0.3.md) | `deadlock-v0.3` 설계 (C-16 파트 3). 입력 : `demo_v03_inputs.py` → `demo-v03-inputs.json` |
| [`demo-block-and-explanation.md`](design/demo-block-and-explanation.md) | 차단 모드 + 원인 설명 설계 (C-16 파트 4) |
| [`demo-model-probe.md`](design/demo-model-probe.md) | 데모 모델 probe (C-16 파트 5) |
| [`demo-work-plan.md`](design/demo-work-plan.md) | 데모 작업 분할과 규모 (C-16 파트 6). 예산 : `demo_budget.py` → `demo-budget.json` |

## findings — 발견

| 파일 | 내용 |
|---|---|
| [`001-silent-noop-step.md`](findings/001-silent-noop-step.md) | 정상 응답과 완료 표시가 진전을 보장하지 않음 |
| [`002-context-growth-in-code-task.md`](findings/002-context-growth-in-code-task.md) | 코드 작업의 컨텍스트 증가 (4 차 실행) |
| [`003-no-progress-full-run.md`](findings/003-no-progress-full-run.md) | 18 step 까지 구현 진전 없이 진행된 실행 |
| [`004-A1-fourth-run-analysis.md`](findings/004-A1-fourth-run-analysis.md) | 4 차 실행 원인 분석 |
| [`005-recovered-narrative-not-shared.md`](findings/005-recovered-narrative-not-shared.md) | 회복된 narrative 의 역할 간 전달 누락 (G0-13) |
| `cumulative.svg`, `tokens.csv`, `narratives.md`, `error-evidence.json`, `sources.json` | 위 분석의 그림·표·원문 근거 |

## 이 폴더 바로 아래의 문서 (2026-09 초기 작업)

인수인계(2026-09-15) 무렵의 단계별 메모입니다. 이번에는 옮기지 않았습니다 : 일부는 다른 파일이 경로로 가리키고 (DM-84 ①), 참조가 0 건인 8 개는 옮기는 명령이 보류됐습니다 (`reports/c19-5/moves.md`). 정리는 발표 뒤 재배치 때 합니다 (DM-84 ⑦).

| 문서 | 내용 |
|---|---|
| [`deadlock_criteria.md`](deadlock_criteria.md) | 교착 판정 기준 사전 고정 v0.1 |
| [`S1-session-isolation.md`](S1-session-isolation.md) | S1 세션 격리 — 재시작 복원 |
| [`S2-experiment-recording.md`](S2-experiment-recording.md) | S2 실험 조건 기록과 healthz |
| [`S3-A-progress.md`](S3-A-progress.md) | S3-A 진전도 관측 — 구현과 사용 계약 |
| [`S3-B-runner-review.md`](S3-B-runner-review.md) | S3-B A-1 실행기 구현 검토 |
| [`S3-C-legacy-results.md`](S3-C-legacy-results.md) | S3-C 기존 로그에 v0.1 적용 결과 |
| `S3-C-기존로그적용결과.md` | 위 `S3-C-legacy-results.md` 와 바이트가 같은 사본 (한글 이름) |
| [`scenario_schema.md`](scenario_schema.md) | scenario-v1 스키마 첫 검토 |
| [`A-1-review.md`](A-1-review.md) | A-1 검토용 요약 |
| [`A1-preflight.md`](A1-preflight.md) | A-1 단계별 실행 점검표 |
| [`A1-revision2-budget.md`](A1-revision2-budget.md) | 인수인계 점검과 A-1 revision 2 예산 |
| [`A1-strict-preflight-and-fallback.md`](A1-strict-preflight-and-fallback.md) | strict 검증 준비 |
| [`A1-strict-implementation.md`](A1-strict-implementation.md) | A-1 strict 최종 보고 적용 |
| [`A1-tool-failure-recovery.md`](A1-tool-failure-recovery.md) | A-1 step 1 도구 오류 증거와 수정 |
| [`P0-1-replay-protocol.md`](P0-1-replay-protocol.md) | P0-1 replay 사전 판독 규칙 |
| [`P0-2-replay-protocol.md`](P0-2-replay-protocol.md) | P0-2 오프라인 적용 범위 |
| [`management-api.md`](management-api.md) | 관리 API 목록 (S3-A 시점) |
| [`discrepancies.md`](discrepancies.md) | 문서와 구현의 불일치 기록 |
