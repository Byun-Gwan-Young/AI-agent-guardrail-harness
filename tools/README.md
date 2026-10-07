# tools — 실행 · 집계 · 기록 · 분석 도구

모든 명령은 저장소 루트에서 `venv/bin/python -B tools/<도구>.py …` 로 실행합니다.
**외부 호출**이라고 적힌 도구만 네트워크를 씁니다 (키가 필요하면 실행 창에서만 `export`, 길이만 확인 — DM-53). 나머지는 저장된 파일만 읽습니다.

## 실행

| 도구 | 하는 일 | 대표 명령 |
|---|---|---|
| [`run_batch.py`](run_batch.py) | 배치 계획의 한 레인을 이 창에서 차례로 실행 (세션마다 `experiments/run_scenario.py` 를 띄움). 끝난 항목은 건너뜀. **외부 호출** (프록시를 거쳐 모델·검색) | `venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 1 --lanes 4 --account-label A` |
| | 계획 대비 진행 상황 | `venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-main-v1.yaml --lanes 4` |
| [`scenario_preflight.py`](scenario_preflight.py) | 시나리오 실행 전 기록 (파일 해시, 쟁점 어휘, 실행 전 인수 판정). `--pair` 로 정상판·교착판 차이 | `venv/bin/python -B tools/scenario_preflight.py scenarios/DEMO-CL-stall-v1.yaml --pair scenarios/DEMO-CL-normal-v1.yaml` |
| [`final_freeze.py`](final_freeze.py) | 데모 최종 동결 기록(62 파일) 만들기·확인 | `venv/bin/python -B tools/final_freeze.py check` |
| [`run_offline_tests.py`](run_offline_tests.py) | 전체 오프라인 테스트, 기준선·신규 구분, 모듈별 시간 제한 | `venv/bin/python -B tools/run_offline_tests.py --baseline tests/fixtures/p0-3-mechanism-test-ids.json --output /tmp/tests.json` |

## 데모 기록 · 집계 · 재생

| 도구 | 하는 일 | 대표 명령 |
|---|---|---|
| [`demo_records.py`](demo_records.py) | 데모 세션에서 커밋할 작은 파일(`record/`)을 만들고 검사·stage, 원본 압축 백업 (DM-64 ⑤) | `venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index` |
| [`demo_exclusions.py`](demo_exclusions.py) | 본 실행의 제외·대체 목록 (실행 환경 사유, DM-78·DM-81) | `venv/bin/python -B tools/demo_exclusions.py --plan demo-main-v1 --plan demo-main-v1-lr2 --plan demo-main-v1-mr2 --output /tmp/exclusions.json` |
| [`demo_account_corrections.py`](demo_account_corrections.py) | 재실행 창이 바뀐 세션의 계정 이름표 보정 파일 (DM-81 ②) | `reports/c18-8/pm-commands.md` 참고 |
| [`aggregate_demo.py`](aggregate_demo.py) | 계획별 세션을 시나리오·유형·전체로 집계 (JSON + 마크다운) | `reports/c18-8/pm-commands.md` 5 절 (`--plan` 3 개 + `--exclusions` + `--account-corrections`) |
| [`replay_demo.py`](replay_demo.py) | 세션 재생 기록(`replay.json`)과 정적 재생 페이지·목록 | `venv/bin/python -B tools/replay_demo.py pages reports/c19/aggregate-main.json --output-dir reports/c19/replay` |
| [`demo_ui.py`](demo_ui.py) | 데모 화면 (정적 HTML 하나 : 대시보드·세션·비교·통계·시스템 구조·사용 가이드·실시간 모니터) | `venv/bin/python -B tools/demo_ui.py build --aggregate reports/c19/aggregate-main.json --output reports/c19-3/demo.html` |
| [`demo_live.py`](demo_live.py) | 실시간 모니터 : 진행 중 데모 세션의 기록 파일을 읽기만 하는 로컬 서버 (127.0.0.1:8010, 구조화 값만) | `venv/bin/python -B tools/demo_live.py serve` |
| [`summarize_demo_session.py`](summarize_demo_session.py) | 데모 세션 폴더 하나의 짧은 요약 (PM 이 붙여 넣는 용도) | `venv/bin/python -B tools/summarize_demo_session.py runs/demo/<세션 ID>` |
| [`rejudge_dialogue.py`](rejudge_dialogue.py) | 대화 과제(T1) 세션의 판정 함수 결과를 저장된 기록으로 다시 계산 | `venv/bin/python -B tools/rejudge_dialogue.py runs/demo/<세션 ID>` |
| [`recompute_v03.py`](recompute_v03.py) | 기존 세션을 `deadlock-v0.3` + `explain-v1` 로 다시 판정 | `venv/bin/python -B tools/recompute_v03.py --output /tmp/v03.json` |
| [`gateway_prices.py`](gateway_prices.py) | 게이트웨이 단가표와 토큰 × 단가 크레딧 추정 (모듈) | 다른 도구가 가져다 씀 |

## 데이터셋 세션 분석 (A-1 계열)

| 도구 | 하는 일 | 대표 명령 |
|---|---|---|
| [`analyze_session.py`](analyze_session.py) | 세션 하나의 사후 분석 (가이드라인 7-3, 매니페스트) | `venv/bin/python -B tools/analyze_session.py <세션 ID> --phase verify` |
| [`compare_sessions.py`](compare_sessions.py) | 분석된 두 세션 나란히 비교 | `venv/bin/python -B tools/compare_sessions.py <기준 세션 ID> <비교 세션 ID> --output /tmp/compare.json` |
| [`check_harness_facts.py`](check_harness_facts.py) | 호출 예산·쓰기 가능 파일이 모델에 고지됐는지 로그로 확인 (결함 6·7) | `venv/bin/python -B tools/check_harness_facts.py <세션 ID>` |
| [`analyze_c14.py`](analyze_c14.py) | A-1-v4 재검증 근거 (C-14). 추론은 크기만 셈 | `reports/a-1-v4/c14-report.md` 참고 |
| [`estimate_v10_context.py`](estimate_v10_context.py) | 프로토콜 v10 최종 보고 입력 크기 추정 | `venv/bin/python -B tools/estimate_v10_context.py <세션 ID>` |
| [`audit_tool_execution_errors.py`](audit_tool_execution_errors.py) | 도구 오류 step 감사 (G0-6) | `venv/bin/python -B tools/audit_tool_execution_errors.py --output /tmp/audit.json` |
| [`evaluate_legacy_criteria.py`](evaluate_legacy_criteria.py) | 초기 대화형 로그에 v0.1 기준 적용 (S3-C) | `venv/bin/python -B tools/evaluate_legacy_criteria.py --deadlock deadlock_log.json --termination termination_failure.json --termination-declaration-turn <턴> --output /tmp/legacy.json` |
| [`replay_role_progress.py`](replay_role_progress.py) | P0-1 역할별 진전도 replay | `reports/p0-1/comparison.md` 참고 |
| [`replay_preserved_observations.py`](replay_preserved_observations.py) | P0-2 보존 관측 3 단계 replay | `reports/p0-2/comparison.md` 참고 |
| [`p0_4_info_items_options.py`](p0_4_info_items_options.py) | P0-4 `info_items` 선택지 비교 | `venv/bin/python -B tools/p0_4_info_items_options.py --output /tmp/p0-4.json` |
| [`write_criteria_snapshot.py`](write_criteria_snapshot.py) | 판정 기준 동결 기록(`docs/criteria/`) 쓰기. 이전 버전은 덮어쓰지 않음. 동결 파일을 쓰므로 PM 지시 없이 돌리지 않는다 | `venv/bin/python -B tools/write_criteria_snapshot.py --config guardrail-deadlock-v0.3-kmu.yaml` |

## probe (사용자가 실행, 외부 호출)

| 도구 | 하는 일 |
|---|---|
| [`probe_gateway.py`](probe_gateway.py) | 계명대 게이트웨이 모델의 도구·추론·strict 지원 확인 (요청 1 회씩) |
| [`probe_gateway_support.py`](probe_gateway_support.py) | probe 공통 함수 (모듈) |
| [`probe_groq_strict.py`](probe_groq_strict.py) | Groq strict 스키마 probe (초기 제공자, G0-3) |
| [`probe_search.py`](probe_search.py) | Tavily·arXiv 검색 확인 (고정 질의 1 회씩, LLM 호출 없음) |

## 작업 단위별 근거·견적 스크립트

그 단위 보고서의 숫자를 만든 스크립트입니다. 다시 돌리면 같은 값이 나와야 합니다.

| 도구 | 단위 | 출력 |
|---|---|---|
| [`c17_7_evidence.py`](c17_7_evidence.py) | C-17-7 | `reports/c17-7/` |
| [`c17_8_evidence.py`](c17_8_evidence.py) | C-17-8 | `reports/c17-8/` |
| [`c18_1_evidence.py`](c18_1_evidence.py) | C-18-1 | `reports/c18-1/` |
| [`c18_2_evidence.py`](c18_2_evidence.py) | C-18-2 | `reports/c18-2/` |
| [`c18_3_evidence.py`](c18_3_evidence.py) | C-18-3 (T1 시험 견적) | `reports/c18-3/estimate-trial.json` |
| [`c18_4_evidence.py`](c18_4_evidence.py) | C-18-4 | `reports/c18-4/` |
| [`c18_5_estimate.py`](c18_5_estimate.py) | C-18-5 (MR 재시험 견적) | `reports/c18-5/estimate-retest.json` |
| [`c18_6_estimate.py`](c18_6_estimate.py) | C-18-6 (본 실행 견적) | `reports/c18-6/estimate-main.json` |
| [`c18_6_evidence.py`](c18_6_evidence.py) | C-18-6 (MR 재시험 근거) | `reports/c18-6/mr-retest-evidence.json` |
