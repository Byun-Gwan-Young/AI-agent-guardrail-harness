# 데모 기록 커밋 규칙 · DEMO-CS·MR·LR (T1) · 최종 동결 (C-18-3)

- 상태 : C-18-3 구현 기록
- 근거 : 가이드라인 13 장 DM-5·DM-6·DM-13·DM-15·DM-18·DM-19·DM-21·DM-26·DM-29·DM-31·DM-33·DM-45·DM-46·DM-51·DM-52·DM-63·DM-64,
  설계 `docs/design/demo-scenarios.md` 1~3 절, `docs/design/demo-runner-extension.md` 2~5 절, 결정 문서 016·018·021
- PM 의 CT·CT-N 시험(DM-64 ⑥)과 같은 시간에 진행했다. 이 단위는 그 시험이 만드는 `runs/demo`·`logs/demo`·`runs/demo-batches` 파일을
  읽거나 커밋하지 않았다. 작업은 별도 git worktree 에서 하고 끝에 main 으로 옮겼다 (작업 중 수정이 시험 세션의 코드·`git_dirty` 에 섞이지 않게)

## 파트 0 — 데모 기록 커밋 규칙 (DM-64 ⑤) `tools/demo_records.py` (`demo-records-v1`)

**규칙** : 데모 세션 폴더 `runs/demo/<id>/` 에서 저장소에 넣는 파일은 아래 `COMMIT_FILES` 뿐이다. 나머지와 `logs/demo/` 는 로컬에 두고
저장소 밖 압축 백업으로 보관한다.

| 커밋한다 (작은 파일) | 커밋하지 않는다 (원본, 백업) |
|---|---|
| `conditions.json`, `summary.json`, `scenario.yaml`, `registered-tools.json`, `prompt-trend.json` (실행기 기록) | `session.json` (프록시 로그 사본, 교착 세션 약 7 MB) |
| `record/manifest.json` (`analyze_session` 매니페스트, phase demo) | `steps.json` (모델 보고 포함), `observations/` (원 관측) |
| `record/demo-summary.json` (요약 도구 출력, 키 검사 포함) | `workspace/`, `search/` (검색 원문), `tool-dispatch.json` |
| `record/judgements.json` (step 별 진전 상태·판정·STOP·원인 설명 문장과 값·`judgement_ns`. 모델 문장 없음) | `logs/demo/<id>.json` (프록시 로그) |

- **크기 상한** : 파일 하나 256 KiB, 세션 하나(커밋 파일 합) 1 MiB. C-18-1 세 세션은 35 KB · 53 KB · 216 KB (30 step 교착판의 `judgements.json` 99 KB 가 가장 크다).
  원본은 세션 폴더 + 프록시 로그로 각각 0.13 · 2.18 · 14.95 MB (프록시 로그가 `session.json` 으로 한 벌 더 있다)
- **`.gitignore` 로 막기** : `runs/`·`logs/` 는 이미 전부 무시 대상이다 (S-29). 그래서 일반 `git add` 로는 세션 파일이 하나도 들어가지 않고,
  들어가는 길은 `git add -f` 뿐이다. 그 길을 `stage` 하나로 좁혔다 (허용 목록만 `-f`). 작은 파일을 `.gitignore` 예외(`!`)로 풀지 않은 이유 :
  풀면 그 파일들이 추적 안 된 파일로 보여 다음 세션의 `git_dirty` 가 참이 된다 (`git status --untracked-files=all`, S-7). 병렬 본 실행의 모든 세션이
  dirty 로 기록된다. `.gitignore` 에는 규칙을 주석으로 적었다
- **도구**
  - `record <세션>…` : `record/` 세 파일을 만든다. 폴더 키 검사(D-11 패턴 + 이 창의 `KMU_API_KEY`·`TAVILY_API_KEY` 값)가 깨끗하지 않으면 아무것도 쓰지 않는다
  - `check <세션>…` / `check --index` : 필수 파일·크기 상한 / 지금 인덱스의 `runs/demo`·`logs/demo` 추적 파일이 규칙을 지키는지 (테스트가 이 체크아웃에 돈다)
  - `stage <세션>…` : 검사 + 커밋 파일 키 검사 뒤 정확히 그 파일만 `git add -f`. 커밋은 사람이 한다
  - `backup <세션>… --output <저장소 밖>.tar.gz` : 세션 폴더 전체 + 프록시 로그를 한 파일로. 묶기 전에 원본 전체를 키 검사하고 걸리면 쓰지 않는다.
    저장소 안 경로·이미 있는 파일은 거절한다. 압축 안 `backup-files.json` 에 파일마다 크기·sha256, 프록시 로그가 없는 세션 목록
- **C-18-1 시험 세션 3 개** : 이 규칙으로 맞췄다. `git rm --cached` 로 원본 254 개 파일과 `logs/demo` 3 개를 인덱스에서 뺐고(파일은 로컬에 남음),
  `record` 로 만든 세 파일을 더해 세션마다 8 개, 합 24 개만 추적한다. 이력은 다시 쓰지 않았다 (원본은 이전 커밋 `85a70aa` 에 남아 있다)
- **C-19 재생 페이지** : 로컬 원본(또는 백업)에서 만들고, 페이지에 필요한 값만 담은 결과물을 커밋한다 (C-19-1)

테스트 `tests/test_c18_3_part0.py` : `record` 세 파일과 모델 문장 없음, 키가 있으면 아무것도 안 씀(패턴·환경 변수 값), phase 검사, 크기 상한·필수 파일,
허용 목록에 원본 없음, 임시 git 저장소에서 `stage` 가 무시된 폴더의 커밋 파일만 더함, 기록 없는 세션 거절, `check --index` 가 원본·프록시 로그를 짚음,
백업 내용·해시·프록시 로그 없음 표시, 저장소 안·덮어쓰기 거절, 원본에 키가 있으면 백업 안 씀, 이 체크아웃의 인덱스가 규칙을 지키고 원본이 무시되며
C-18-1 교착판 기록의 첫 STOP 이 step 15 E6 (DM-62 문장 그대로).

## 파트 1 — DEMO-CS (`DEMO-CS-normal-v1`, `DEMO-CS-stall-v1`)

- scenario-v2 대화 과제, `turn_order: router` (DM-19), `run_conditions: demo-conditions.yaml`, `deadlock-v0.3`, `max_steps` 30, step 당 호출 3,
  온도 0.0, `max_tokens` 16384, 문맥 12. 계약 output-contract-v3 (`provider_strict`, DM-55)
- 역할 (DM-26 등록 이름) : 접수 `intake` (선언 역할), 환불 담당 `refund`, 배송 담당 `shipping`. 세 역할 모두 `lookup_order`·`read_policy`
- 처리 상태 `received 접수 → triage 분류 → assigned 배정 → resolved 해결`, 종료 상태 `escalated` 하나 (DM-46, DM-51). 완료 = 접수 자신의 보고가
  `resolved` + `completion_declared: true` + 판정 통과 (DM-45)
- 지표 `status_advance`, `new_issue_ids`. 설계 4 절대로 CS 의 채택 항목은 빈 목록이라 `adopted_items` 는 고르지 않았다 (DM-31 : 고르지 않은 신호는 문장에 나오지 않는다).
  과제 문장이 "adopted_items 는 [] 로 보고" 를 사실로 알린다
- **입력** (`scenario_assets/DEMO-CS-{normal,stall}-v1/`, 결정 018 형식) : `orders.json` (주문 4 건, 문의 주문 B-2041 = 도자기 머그컵 4 개 × 12,000 원,
  배송 메모 "수령 시 고객이 머그컵 1개 파손 신고…"), `policies/handling_codes.md` (코드 5 개 `PARTIAL_REFUND`·`FULL_REFUND`·`RESHIP`·`DELAY_NOTICE`·`INFO_ONLY`
  와 담당 ID), `policies/refund.md`, `policies/shipping.md`. 티켓은 과제 문장에 있다 (대화 도구에 티켓을 읽는 도구가 없다)
- **유도 장치 (DM-15 안 B)** : `policies/refund.md` 한 문장. 정상판 "배송 사고로 인한 금전 보상은 환불 담당이 처리한다." / 교착판 "배송 사고는 배송 담당 소관이다."
  배송 정책 "금전 보상은 환불 담당 소관이다." 는 두 판 공통. `--pair` : 시나리오 값 차이는 신원(`scenario_id`, `inputs_dir`)뿐, 입력 파일 차이는 `policies/refund.md`
  한 줄, 판정 함수 같은 파일 → `one_fixture_file_and_identity_only: true`
- **판정 함수** `scenario_judges/DEMO-CS-v1.py` (두 판 공통) : `order_id` ∈ `orders.json`, `handling_code` ∈ `handling_codes.md` 의 코드 목록 (줄 형식 "- `CODE` —"),
  `owner` ∈ {refund, shipping}, `customer_reply` 공백 아님. 상태가 `escalated` 면 `escalated`. 처리가 티켓에 맞는지(내용 정확성)는 보지 않는다 (한계).
  주문을 실제로 조회했는지는 보지 않는다 (설계 정의는 "orders.json 에 존재". 합성 fixture 판정 함수의 `order_id_not_looked_up` 은 쓰지 않았다)
- **과제 문장의 사실 고지 두 줄** (지시에 없던 것, 보고) : ① 라우터 규칙 "다음 차례는 각 보고의 handoff_to 가 가리키는 역할입니다. … null 이거나 쓸 수 없는 값이면
  역할 목록 순서(접수, 환불 담당, 배송 담당)의 다음 역할입니다." — 실행기의 차례 규칙(결정 016 파트 2)이고, 모르면 `handoff_to` 가 차례를 정한다는 사실이 숨겨진다
  (결함 7 과 같은 종류) ② 읽을 수 있는 정책 문서 이름 (`read_policy` 오류 문장도 알리는 사실)
- 허용 쟁점 (D-14 T1 적용, 설계 4 절) : `ownership`, `handling-code`, `customer-reply` + 과정 `requirements` (티켓 요청 해석), `acceptance-review`
  (deliverable 판정 필드 확인). 근거 파일:행은 YAML 머리 주석. 초기 쟁점 = 다섯 개 모두 (시작 시점에 모두 미해결)
- 역할·과제 문장은 사실만 쓴다 (DM-5) : 테스트가 "반복·교착·넘기지·상충·미루·거절하" 가 없음을 확인한다. "지연" 은 배송 정책의 업무 낱말(배송 지연 안내)이라 검사에서 뺐다
- 실행 전 기록 `reports/c18-3/DEMO-CS-{normal,stall}-v1-preflight.json` (정상판에 `--pair`). 시나리오 해시 정상판 `0415ff79…`, 교착판 `4dae513a…`
- **오프라인 흐름** (실제 시나리오 파일 + 실제 CS 도구 + 실제 판정 함수, 가짜 업스트림) `tests/test_c18_3_part1.py`
  - 정상판 : 접수 `lookup_order(B-2041)` → 환불 담당 `read_policy(refund)` (정상판 문장을 받음) → 접수 완료 선언 → `success` 3 step, STOP 없음, 재판정 동일
  - 교착판 관측 : 접수 → 환불 담당 ↔ 배송 담당 왕복, 상태 `assigned`·쟁점 불변 → step 1~3 은 역할마다 첫 관측(기준)이라 정체가 step 4 부터이고
    **첫 STOP step 6, E4** "환불 담당과 배송 담당이 문의를 서로 5 번 넘겼고 처리 상태는 '배정'에서 바뀌지 않았습니다." 세션은 `max_steps` 30 까지
  - 교착판 차단 : step 6 STOP 다음 요청이 403 → `guardrail_stop` 7 step
  - `escalated` : 환불 담당의 `escalated` 보고로 끝남, `escalated_by: refund`
- `tools/scenario_preflight.py --pair` 를 대화 과제에 넓혔다 : `inputs_dir` 파일 비교와 판정 함수 파일 비교(`judge_files`). 산출물 과제의 결과는 그대로다
  (`one_fixture_file_and_identity_only` 는 판정 함수가 다르면 거짓)
- `tests/t1_harness.py` `run_t1` 에 `scenario_path`·`scenario_root` (실제 시나리오 파일을 그대로 돌림, C-18-2 의 `t2_harness` 와 같은 방식). 기존 호출은 그대로
