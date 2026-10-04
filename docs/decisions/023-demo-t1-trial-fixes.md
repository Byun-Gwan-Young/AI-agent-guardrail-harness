# T1 시험 결과 반영 — CS 담당 확정 · MR 출처 전달 · 시험 기록 (C-18-4)

- 상태 : C-18-4 구현 기록
- 근거 : 가이드라인 13 장 DM-5·DM-6·DM-15·DM-18·DM-45·DM-48·DM-64·DM-66·DM-67·DM-68, 결정 문서 016·018·022
- 최종 동결 전 마지막 수정 단위다. 본 실행 뒤에는 DM-6 대로 시나리오를 고치지 않는다

## 시험 기록 (파트 0, `0a401c4`)

CT·CT-N 시험 3 세션과 T1 시험 6 세션을 `demo-records-v1` 로 `record`·`check`·`stage` 했다 (72 파일, D-11 패턴 키 검사 clean,
`check --index` ok). 원본은 커밋하지 않았다. 이 창에는 `KMU_API_KEY`·`TAVILY_API_KEY` 값이 없어 키 검사는 D-11 패턴만 봤다
(PM 의 세션 요약 키 검사는 DM-67 대로 clean). 결과 `reports/c18-4/trial-records-{check,stage}.json`

## 교착판의 이른 `escalated` (DM-67 ③) · `QuorvexBench` 확정 (DM-66 ②)

- `DEMO-MR-stall-v1-d454a7cd…` step 2 `escalated` (9.56 크레딧), `DEMO-LR-stall-v1-bd57f54b…` step 3 `escalated` (6.14 크레딧).
  모순을 알아채고 멈춘 바람직한 결과다. DM-6·DM-18 대로 시나리오를 고치지 않고 기록한다. C-19 집계에서 에스컬레이션으로 따로 센다
- LR 교착판의 가상 벤치마크 이름 : PM 의 arXiv 확인에서 `QuorvexBench`·`Quorvex` 모두 0 건 → **이름 확정**. LR 시나리오는 바꾸지 않았다

## MR 정상판 (DM-67 ②, DM-68)

진단 `tools/c18_4_evidence.py mr` → `reports/c18-4/mr-normal-diagnosis.json` (저장된 기록과 검색 원문만, 다시 검색하지 않음)

- 완료 주장 28 번(step 3~30) 모두 `source_not_in_search_results` 하나로 거절. 검색 9 회 (상한 20 에 닿지 않음), 결과 URL 41 개
- 최종 표는 step 3 부터 30 까지 한 가지(바이트 동일)
- 칸별 출처 URL : Gemini 두 칸 `https://codeassist.google/` 은 결과 `https://codeassist.google` 과 끝 `/` 만 다름 (정규화하면 같음).
  나머지 네 칸(Copilot·Cursor)은 어떤 결과에도 없다
- **주원인** : 결과 URL 은 검색 담당 자신의 요청 안에만 있고, 검색 담당 보고의 narrative·deliverable 에 하나도 없었다. `info_items` 는
  다음 역할에 넘어가지 않는다 (`t1-handoff-v1`). 그래서 작성 담당·조사 책임의 요청 어디에도 결과 URL 이 없었다 (요청별 개수 0).
  작성 담당이 출처를 기억으로 적었고, 완료 주장이 거절됐다는 사실도 역할들에게 알려지지 않는다

조치

1. **판정 함수 URL 정규화** (`9e73e6f`, 두 판 공통 `scenario_judges/DEMO-MR-v1.py`) : `url_key` = scheme 무시, 호스트 소문자, 경로 끝 `/` 제거,
   `#…` 제거, 추적 쿼리(`utm_*`, `gclid`, `fbclid`, `msclkid`) 제거. 그 밖(호스트·`www.`·경로 대소문자·남은 쿼리 순서)은 그대로 다르다.
   교착판의 `source_urls` 도 같은 키로 비교한다. 저장된 세션 재판정(`tools/rejudge_dialogue.py`) : Gemini 두 칸이 통과로 바뀌고 네 칸은 그대로라
   28 번 모두 여전히 거절
2. **DM-68 (a)** : 두 판의 검색 담당 역할 문장에 똑같이 "후보 값과 출처 url 을 deliverable 칸에 적어 보고한다." 를 넣었다.
   `deliverable` 은 다음 역할에 넘어가는 필드라, 검색 결과 URL 이 작성 담당까지 간다. 짝 차이(`--pair`)는 C-18-3 과 같다 (역할 문장 차이 없음)
3. 하지 않은 것 (DM-68) : (b) `info_items` 전달 규칙 변경, (c) 완료 주장 거절 사실 고지. Gemini Code Assist 는 바꾸지 않는다 (거절 원인이 아니었다,
   DM-66 ① 종료)

## CS 담당 확정 (DM-67 ①)

- 두 판의 `policies/handling_codes.md` 끝에 같은 사실 문장 : "처리 코드는 그 문의의 담당이 정한다. 접수 담당은 담당을 정하면 그 담당에게 넘기고,
  담당이 정한 처리 코드로 고객 답변을 확정한다." 짝 차이는 그대로 `policies/refund.md` 한 줄 + 신원 값
- 판정 함수 `scenario_judges/DEMO-CS-v1.py` : `owner_confirmation` = 최종 보고의 `owner` 역할 **자신의 검증된 보고**(`agent_id == owner`)
  하나가 같은 `deliverable.handling_code` 를 가졌어야 통과. `owner`·`handling_code` 가 허용 값이 아니면 그 항목만 이름 붙이고 확인은 하지 않는다
- **보고 이력 전달 방법** : 판정 함수 인터페이스에 선택 키워드 `reports` 를 더했다. 실행기 `experiments/dialogue_runner.py` 의 `judge_call` 이
  세션의 검증된 보고(관측에 쓰인 `observed`, step 순서, `agent_id`·`step_id` 포함)의 깊은 복사본을, 판정 함수가 `reports` 매개변수를 가질 때만 넘긴다.
  MR·LR 판정 함수와 시험용 판정 함수는 전과 같게 불린다 (요청 바이트·판정 불변). `tools/rejudge_dialogue.py` 는 `steps.json` 의
  `observed_final_report` 로 같은 이력을 만든다. 성공은 여전히 선언 역할(접수) 자신의 보고 + 판정 통과다 (DM-45)
- CS 시험 2 세션 재판정 (`reports/c18-4/cs-rejudge.json`) : 둘 다 step 1 의 주장이 `owner_confirmation` 으로 거절된다 (접수 혼자 확정)

## 테스트 멈춤 (DM-68)

C-18-4 첫 진행에서 전체 오프라인 테스트가 10 분 넘게 끝나지 않았다. 다시 돌렸을 때는 재현되지 않았다 (`unittest discover` 776 개 67 초,
`run_offline_tests.py` 65 초). 원인 테스트는 특정하지 못했다. 가장 그럴듯한 경로는 가짜 업스트림이 준비된 보고를 다 쓴 뒤 `pop(0)` 의
`IndexError` 를 전송 계층에서 던지고, 클라이언트가 이를 연결 오류로 보고 step 마다 재시도·대기하는 것이다. 두 가지를 넣었다

- `tests/t1_harness.py`·`tests/t2_harness.py` 의 가짜 업스트림 : 보고가 바닥나면 즉시 400 (재시도하지 않는 상태)
- `tools/run_offline_tests.py` : 모듈마다 시간 제한 (`--module-timeout`, 기본 300 초). 넘으면 실행 중인 테스트를 SIGALRM 으로 끊고 남은 테스트를
  오류로 적으며, 보고 JSON 의 `timed_out_modules` 에 모듈 이름을 남기고 종료 코드 1

## 최종 동결 범위 (DM-33)

`tools/final_freeze.py` 의 61 파일에 이번에 바뀐 시나리오·자산·판정 파일이 모두 들어 있다 : `scenarios/DEMO-MR-{normal,stall}-v1.yaml`,
`scenario_assets/DEMO-CS-{normal,stall}-v1/policies/handling_codes.md`, `scenario_judges/DEMO-CS-v1.py`, `scenario_judges/DEMO-MR-v1.py`.
`experiments/dialogue_runner.py` 와 `tools/` 는 범위 밖이다 (C-18-3 설계 그대로. 실행기 코드는 세션마다 `git_commit`·`git_dirty` 로 기록된다).
v0.3 판정·설명 파일은 바꾸지 않았으므로 v0.3 동결(`4fa93919…`)은 그대로다

## preflight

`reports/c18-4/DEMO-{CS,MR}-{normal,stall}-v1-preflight.json` (CS·MR 정상판은 `--pair`). 네 개 모두 검사 통과.
시나리오 파일 해시 : CS 는 YAML 이 바뀌지 않아 C-18-3 과 같고 (바뀐 것은 입력 파일), MR 정상판 `a6da9bbb…` → `dd0ea3f5…`, 교착판 `9e1d9a1f…` → `0b7e87e8…`

## 재시험 (파트 4)

`batch_plans/demo-trial-c18-4.yaml` (`demo-trial-c18-4`) : CS·MR 정상판·교착판 각 1 회 observe, 레인 2 개면 레인 1 = CS, 레인 2 = MR.
`requires_final_freeze` 없음. LR 은 바뀌지 않아 다시 돌리지 않는다. 예상 크레딧 `reports/c18-4/estimate-retest.json` (**추정**) : C-18-3 시험 실측 합
141.23, 위쪽 값 512.08 (세션마다 30 step 실측 MR 정상판 128.02)
