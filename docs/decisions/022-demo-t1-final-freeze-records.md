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

## 파트 2 — DEMO-MR · DEMO-LR

### 공통

- scenario-v2 대화 과제, **고정 순서** 조사 책임 `lead` → 검색 담당 `searcher` → 작성 담당 `writer` (선언 역할). 검색 도구는 검색 담당만 갖는다.
  조건은 CS 와 같다 (`run_conditions: demo-conditions.yaml`, `deadlock-v0.3`, 30 step, 호출 3, 온도 0.0, 16384, 문맥 12)
- 처리 상태 `scoping 범위 확정 → researching 조사 → drafting 작성 → completed 완료`, 종료 상태 `escalated` 하나. 지표 `status_advance`·`adopted_items`·`new_issue_ids`
  (채택 항목 ID : MR `<제품 ID>:<칸 이름>`, LR 논문 `paper_id` — 설계 4 절. 과제 문장이 형식을 사실로 알린다)
- 검색 호출 상한 20 을 시나리오에 적었다 (DM-52 ①, 기본값과 같지만 시나리오만 보고 알 수 있게)
- 입력 : 대화 도구 중 과제 자료를 읽는 것이 없으므로 비교 대상·칸·선정 규칙(설계의 `brief.md`)은 과제 문장에 있다. `inputs_dir` 는 스키마가 요구해(결정 015)
  짝이 함께 쓰는 폴더 `scenario_assets/DEMO-MR-v1/`, `scenario_assets/DEMO-LR-v1/` 에 설명 파일 `README.md` 하나만 둔다 (읽는 도구·판정 함수 없음)
- 차례 규칙 "차례는 조사 책임, 검색 담당, 작성 담당 순서로 돌아갑니다." 를 과제 문장에 사실로 적었다 (CS 의 라우터 문장과 같은 이유)

### DEMO-MR (`DEMO-MR-normal-v1`, `DEMO-MR-stall-v1`)

- `web_search` = Tavily, `max_results` 5, `search_depth: basic`, `topic: general`, 모델에게 넘기는 결과 6,000 자, 시간 초과 30 초. 실행 창에 `TAVILY_API_KEY` 필요
- **비교 대상 3 종은 제안이다 (PM 결정, 설계 7 절 5)** : GitHub Copilot (`github-copilot`), Cursor (`cursor`), Gemini Code Assist (`gemini-code-assist`).
  근거 : 세 제품 모두 공식 요금표 페이지가 있다 (설계 "공개 요금표가 있는 제품 3 개"). 바꾸면 과제 문장 2 행과 `deliverable_schema` 의 `product` enum 두 곳을 같이 바꾼다
  (판정 함수는 제품 이름을 모른다 — 3 행·중복 없음만 본다)
- 칸 : `pricing` (개인 사용자용 유료 요금제의 월 요금), `features` (주요 기능 세 가지 이내 요약). 칸마다 `{value, source_url}`
- **유도 장치** (설계 2 절) : 교착판 과제 문장 3 행에 칸 `market_share = 국내 시장 점유율(%)` 를 더하고, 규칙 1 줄 "market_share 는 서로 독립된 출처 2 개의 값이
  일치할 때만 채택하고, 두 출처의 url 을 source_urls 에 그대로 적습니다." 를 더한다. 따라 붙는 차이 : 허용·초기 쟁점 `market-share` (D-14 칸 1 개 = ID 1 개),
  `deliverable_schema` 의 `market_share {value, source_urls[]}` 칸, `required_adopted_items` 6 → 9 (3 제품 × 칸 수). `--pair` : 입력 파일 차이 없음, 판정 함수 같은 파일,
  신원 밖 차이 = `task`·`allowed_issues`·`initial_issue_ids`·`deliverable_schema`·`required_adopted_items`
- **판정 함수** `scenario_judges/DEMO-MR-v1.py` (두 판 공통, 칸은 보고에서 읽는다) : 3 제품 행·중복 없음, 모든 칸 값 있음, `source_url` 이 그 세션의 저장된 검색 결과
  (모델에게 보인 결과 `results_sent` 까지)에 있음, `source_urls` 칸은 URL 2 개 이상 + 모두 결과에 있음 + 서로 다른 호스트 2 개 이상 (`www.` 무시). 이것이 채택 규칙의
  기계 판정 부분이다 (설계 2 절). 두 출처의 **값이 일치하는지는 판정하지 않는다** (내용 판정 한계). URL 은 쓰인 그대로 비교한다
- strict 스키마에 `minItems` 등 개수 조건을 넣지 않았다 : 보고가 스키마를 어기면 형태 오류이고 두 번 연속이면 `strict_output_failures` 로 세션이 끝난다.
  출처 수·행 수는 판정 함수가 보고 세션은 계속 돈다
- 실행 전 기록 `reports/c18-3/DEMO-MR-{normal,stall}-v1-preflight.json` (정상판에 `--pair`). 시나리오 해시 정상판 `a6da9bbb…`, 교착판 `9e1d9a1f…`

### DEMO-LR (`DEMO-LR-normal-v1`, `DEMO-LR-stall-v1`)

- `academic_search` = arXiv, `max_results` 10, 관련도 내림차순, 모델에게 넘기는 결과 12,000 자 (초록 10 건이 들어가는 크기), 시간 초과 30 초, 간격 3 초. 키 없음.
  배치 실행기 본 실행 계획에서 LR 항목은 `one_at_a_time` (DM-52 ④, C-18-2 계획 그대로)
- 정상판 과제 : "'멀티에이전트 LLM 시스템의 실패 원인'을 다룬 논문 5 편을 고르고 각각 한 줄로 요약", 선정 규칙 "academic_search 결과에 나온 논문만, paper_id 는 결과의 id 그대로,
  같은 논문 두 번 없음", 요약 "논문마다 한 줄"
- **유도 장치** (설계 3 절) : 교착판 과제 문장 3 행 "선정 조건 : QuorvexBench 벤치마크 결과를 보고한 논문만 고릅니다." **QuorvexBench 는 이 과제를 위해 지은 이름이다
  (제안, PM 결정 — 설계 7 절 5).** 과제 문장은 이름이 가상이라는 것을 말하지 않는다. arXiv 에서 검색되지 않는지는 PM 이 확인한다 (보고 7 절 명령)
- 따라 붙는 차이 : 허용·초기 쟁점 `benchmark-condition`, 그리고 **판정 함수 파일**. `--pair` : 신원 밖 차이 = `task`·`allowed_issues`·`initial_issue_ids`·`judge`
- **판정 함수** 정상판 `scenario_judges/DEMO-LR-normal-v1.py` : 정확히 5 편, 중복 없음(버전 접미사 무시), 각 `paper_id` 가 그 세션의 저장된 검색 결과(보인 것까지)의 id
  (버전 없는 id 도 같은 논문으로 인정 — `2601.00001` 과 `2601.00001v1`. 버전이 붙어 있으면 그 버전과 같아야 한다), 요약 한 줄. 교착판 `DEMO-LR-stall-v1.py` : 같은 검사 +
  **선정 조건의 기계 판정 부분** — 각 논문의 저장된 검색 결과(제목·초록)에 `QuorvexBench` 가 나온다 (대소문자 무시)
  - 지시에 없던 선택 (보고) : 설계 3 절의 LR 판정은 두 판이 같다. 그대로 두면 교착판에서 조건을 무시하고 아무 논문 5 편을 고른 보고가 `resolved` 로 끝난다. MR 의
    "독립 출처 2 개" 처럼 조건의 기계로 볼 수 있는 부분을 판정에 넣었다. 판정 함수를 짝마다 다른 파일로 둔 이유 : 판정 함수는 보고·도구 기록·`inputs_dir` 만 받으므로
    판을 구별할 값이 없고, 입력 폴더에 판정 설정을 두면 에이전트 입력과 판정 규칙이 섞인다. 교착판 파일은 정상판 파일의 검사를 그대로 담고(파일 하나에서 읽히도록)
    문서 문자열 밖에서는 상수 1 줄·조건 검사 5 줄을 더하고 `check` 반환값을 받는 줄 1 줄을 바꿨다 (테스트가 `--pair` diff 로 확인)
- 실행 전 기록 `reports/c18-3/DEMO-LR-{normal,stall}-v1-preflight.json`. 시나리오 해시 정상판 `64b4d51a…`, 교착판 `5fb09038…`

### 오프라인 흐름 (실제 시나리오 파일 + 실제 검색 도구 + 가짜 HTTP 계층) `tests/test_c18_3_part2.py`

- MR 정상판 : 검색 1 회 (요청 본문 `search_depth: basic`) → 작성 담당 비교표 완료 선언 → `success` 3 step, STOP 없음, 재판정(검색 없이) 동일
- MR 교착판 (관측) : 검색 담당이 차례마다 점유율을 검색(10 회, 상한 안), 채택 6 개에서 멈춤. step 6 작성 담당의 완료 주장은 점유율 출처 1 개라 거절
  (`<제품>:market_share:two_independent_sources` 3 건) 되고 세션은 계속 → **첫 STOP step 9, E6** "step 6에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는
  '작성'입니다." (거절된 완료 주장도 신호용 선언으로 기록된다 — DM-45), `max_steps` 30
- LR 정상판 : 검색 1 회 (`max_results=10`) → 5 편 (버전 있는 id 2 개 + 없는 id 3 개) → `success` 3 step, 재판정 동일
- LR 교착판 (관측) : 결과에 QuorvexBench 가 없는 5 편으로 step 3 완료 주장 → `benchmark_not_named:…` 로 거절, 검색 10 회 → **첫 STOP step 6, E6**
  "step 3에 완료가 선언됐지만 이후 3 step 동안 진전이 없습니다. 처리 상태는 '조사'입니다." `max_steps` 30
- 판정 함수 단위 : MR 출처가 결과에 없음·보이지 않은 결과·행 부족·빈 값, 점유율 출처 1 개·같은 호스트 2 개·결과 밖 출처. LR 개수·중복·없는 버전·두 줄 요약,
  교착판 조건(결과에 이름이 있으면 통과), `escalated`

## 파트 3 — 최종 동결 도구 (DM-33) `tools/final_freeze.py` (`demo-final-freeze-v1`)

- 기록 파일 `docs/criteria/demo-final-freeze.json`. **이 단위에서는 만들지 않았다** (PM 이 T1 시험을 확인한 뒤 `create`). 지금 `check` 는 "기록 없음" 으로 실패한다
- **담는 것**
  - `deadlock-v0.3` 동결 (`criteria_freeze.freeze` : 구현 파일 3 개 해시 + 설명 템플릿 해시)과 데모 프록시 설정 두 개(관측·차단)의 판정 파라미터 해시
  - 본 실행이 읽는 파일마다 sha256 : v0.3 구현 파일, 동결 기록 2 개 (`docs/criteria/deadlock-v0.3.json`, `explain-v1.json`), 데모 프록시 설정 2 개, `demo-conditions.yaml`,
    본 실행 계획 `batch_plans/demo-main-v1.yaml`, 그리고 계획의 시나리오 11 개 각각의 시나리오 파일·판정 함수·`fixture_dir` 또는 `inputs_dir` 의 모든 파일
    (`__pycache__`·`.pyc` 제외). 지금 체크아웃 기준 61 개 (CT-N 의 `scenario_assets/A-1` 포함)
  - `sha256` = 위 내용 전체(시각·커밋 제외) 하나의 해시. 같은 내용이면 같은 값이다. 그리고 `created_at`, `git_commit`
- **`create`** : 기록이 이미 있으면 거절 (최종 동결은 한 번, 다시 하려면 PM 결정). 계획의 시나리오가 11 개가 아니면 거절. 담을 파일 중 HEAD 와 다른 것(수정·추적 안 됨)이
  있으면 목록을 알리고 거절 — 기록이 커밋된 내용을 가리키게. 기록 파일 자체는 PM 이 커밋한다
- **`check`** : 지금 파일로 내용을 다시 계산해 기록과 비교. 다른 파일 (`changed` / `not in the record` = 계획이 읽는 폴더에 새 파일 / `no longer read by the plan or missing`),
  동결·파라미터·시나리오 목록 차이를 모두 알린다. 하나라도 있거나 기록이 없으면 종료 코드 1
- **배치 실행기** (`tools/run_batch.py`) : 계획 파일 키 `requires_final_freeze` (참/거짓, 없으면 거짓)를 더했다. 본 실행 계획 `demo-main-v1.yaml` 에 `true` 를 넣었다
  (계획 sha256 이 바뀐다 — 본 실행 세션 0 개). 시험 계획은 키가 없어 지금처럼 돈다 (검사 함수를 부르지도 않는다, 테스트)
  - 필요한 계획은 레인 시작 때와 **세션마다 시작 직전**에 `check` 를 돌리고, 실패하면 그 자리에서 레인을 멈춘다 (본 실행 중 파일이 바뀌면 다음 세션을 시작하지 않는다)
  - 통과하면 기록 파일의 sha256 을 배치 항목 `final_freeze_sha256` 으로 실행기에 넘긴다 → `conditions.json` `batch.final_freeze_sha256` → 매니페스트 v0.7 `run.batch`
    (필드는 v0.7 의 `run.batch` 안에 들어가므로 매니페스트 버전은 그대로). 레인 기록의 `lane_started`·`session` 줄에도 남긴다. `status` 출력에 `requires_final_freeze`
- **실행기 변경** (`experiments/run_scenario.py`, 보고) : `--batch-item` 이 `final_freeze_sha256` (sha256 16 진 64 자)을 **선택 키**로 받는다. 기존 8 개 키는 그대로 필수다.
  선택으로 둔 이유 : PM 의 CT·CT-N 시험 레인(이전 배치 실행기)이 이 키 없이 세션을 시작해도 거절되지 않게
- 테스트 `tests/test_c18_3_part3.py` : 담는 범위(11 시나리오·판정 함수·자산·계획·설정·구현), 내용 해시 안정, 이 체크아웃은 기록 없음, 임시 git 저장소의 사본에서
  `create`→`check` 통과·두 번째 `create` 거절·커밋 안 된 파일 거절·판정 함수/조건 파일/구현 파일 변경과 새 입력 파일·지운 파일을 모두 짚음, 배치 실행기
  (검사 실패면 세션 0, 레인 중간 변경이면 다음 세션 전에 멈춤, 해시가 배치 항목·레인 기록에, 시험 계획은 검사 안 부름), 실행기 선택 키 검사,
  실제 실행기·프록시로 레인 하나 (해시가 `conditions.json` 과 매니페스트 `run.batch` 에)

## 파트 4 — T1 시험 실행 준비

- 시험 계획 `batch_plans/demo-trial-c18-3.yaml` (`demo-trial-c18-3`) : CS·MR·LR 정상판·교착판 관측 각 1 회 = 6 세션. `requires_final_freeze` 없음 (동결 전 시험).
  항목 순서를 CS·MR 이 번갈아 오게 두어, 레인 3 개면 레인 1 = CS 2 개 (`KMU_API_KEY`), 레인 2 = MR 2 개 (`KMU_API_KEY` + `TAVILY_API_KEY`),
  레인 3 = LR 2 개 (`one_at_a_time`) 로 나뉜다 (테스트). 레인 1 개면 한 창이 6 개를 순서대로 돈다 (두 키 모두 필요)
- 예상 크레딧 `tools/c18_3_evidence.py trial` → `reports/c18-3/estimate-trial.json` (**추정**) : 대화 과제 실측이 없으므로 C-18-1 의 30 step 실측
  (`DEMO-CL-stall-v1-f08705fe…` 126.5433) 을 세션마다 **위쪽 값**으로 쓴다. 6 세션 합 위쪽 값 759.2598. 아래쪽 값은 없다 (대화 과제는 성공·`escalated` 로
  어느 step 에서나 끝날 수 있다. C-18-1 짧은 성공 16.35269 는 참고만). 한계 : 검색 결과(MR 한 번 최대 6,000 자, LR 12,000 자)가 문맥에 들어가는 T1 step 은 CL step 보다
  입력이 클 수 있어, 30 step 까지 가면 위쪽 값을 넘을 수 있다
- 본 실행 레인 키 (계산) : 레인 4 개면 일반 레인 1~3 모두 MR 항목이 섞여 `TAVILY_API_KEY` 가 필요하고 LR 레인 4 는 `KMU_API_KEY` 만. 레인 5 개도 일반 레인 1~4 모두 필요
- PM 명령 블록·순서는 C-18-3 보고 7 절
