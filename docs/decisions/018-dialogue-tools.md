# T1 도구 4 종 · 검색 결과 원문 저장 (C-17-6)

작업 단위 `demo-work-plan.md` 17-6 (도구). 설계 `docs/design/demo-runner-extension.md` 5 절(도구 인터페이스·검색 결과 저장),
`docs/design/demo-scenarios.md` 1~3 절(CS·MR·LR), 결정 문서 016·017. 13 장 DM-13·DM-21·DM-48~DM-51 이 설계 문서보다 우선한다.
실제 데모 시나리오와 입력 자료는 C-18 이다. 이 문서의 파일 형식을 C-18 이 따른다.

## 파트 1 — 로컬 도구 2 종 (CS, `experiments/cs_tools.py`)

두 도구 모두 시나리오의 `inputs_dir` 만 읽는다. 쓰지 않고, `inputs_dir` 밖은 읽지 않는다 (테스트 : 호출 전후 입력 파일 바이트 동일).

**`lookup_order(order_id)`**

- 입력 : `inputs_dir/orders.json` — 아래 형식. 호출마다 읽는다 (캐시 없음)
- 반환 : `order_id` 가 **정확히 같은** 주문 한 건의 JSON 객체 그대로 (대소문자·공백을 고치지 않는다)
- 없는 ID → 사실 문장 오류 결과 : `No order with order_id "<값>" in the order data.` (빈 값이면 `lookup_order needs order_id as a non-empty string.`)
- 호출 기록에 `source = {file: "orders.json", sha256}` — 어떤 입력으로 답했는지 다시 확인할 수 있게

**`read_policy(name)`**

- 입력 : `inputs_dir/policies/<이름>.md`
- 이름으로 받는 형태 셋 : `refund`, `refund.md`, `policies/refund.md`. 그 밖의 경로(`..`, 절대 경로, 하위 폴더, 다른 파일)는 문서를 가리키지 않는다.
  경로를 이어 붙여 파일을 여는 것이 아니라 `policies/` 의 문서 목록에서 이름을 찾으므로 경로 탈출이 생기지 않는다.
  `inputs_dir` 밖으로 풀리는 링크 파일은 문서 목록에 넣지 않는다 (테스트)
- 반환 : 문서 본문 (UTF-8 텍스트) 그대로. 호출 기록에 `source = {file: "policies/<이름>.md", sha256}`
- 없는 이름·경로 → 사실 문장 오류 결과 : `No policy document named "<값>". read_policy reads only the policy documents of the task: <이름 목록>.`
- **목록 보기** : 설계 문서 5 절에 목록 기능이 없어 따로 만들지 않았다. 대신 없는 이름의 오류 결과가 문서 이름을 사실로 알린다
  (산출물 경로의 "등록된 도구만 사용하라: …" 교정과 같은 종류의 사실). 이름을 알릴 방법이 없으면 모델이 이름을 추측하다 호출 예산을 쓰고,
  그것은 하네스가 만든 정체다 (G0-8 교훈). **PM 확인 필요** (보고 6 절) — 오류 결과에서 이름을 뺄지

**파일 형식 (C-18 이 따른다)**

| 파일 | 형식 |
|---|---|
| `orders.json` | UTF-8 JSON 객체. 키는 정확히 `"orders"` 하나, 값은 목록. 각 주문은 JSON 객체이고 `"order_id"` 는 비어 있지 않은 문자열, 파일 안에서 유일. 나머지 필드는 자유 (도구가 그대로 돌려준다) |
| `policies/<이름>.md` | UTF-8 텍스트 (마크다운). 이름 = 파일 이름에서 `.md` 를 뺀 것 : 소문자 영문·숫자·`_`·`-`, 첫 글자는 영문 소문자나 숫자, 64 자 이하. 이 규칙 밖의 `.md` 파일은 문서가 아니며 실행 전 검사(파트 3)에서 오류다 |

- 형식 검사 함수 `cs_tools.input_problems(tool, inputs_dir)` (파트 3 의 실행 전 검사가 쓴다) : 파일 없음, JSON 아님, 최상위 형태, `order_id` 누락·타입·중복,
  `policies/` 없음·문서 없음·이름 규칙 밖 파일
- 시험 입력 : `tests/fixtures/scenario_assets/TEST-T1-v2/` (합성 주문 3 건, 정책 문서 3 개). 실제 CS 입력 자료는 C-18

**실행기 쪽 (`experiments/dialogue_tools.py`)**

- `IMPLEMENTATIONS` 에 두 도구를 넣었다. 도구 결과 형식 `experiments/tool_results.py` : 값을 그대로 돌려주거나, 호출 기록에 더할 필드가 있으면
  `Result(value, record)`. 값이 없는 호출은 `ToolFactError(사실 문장, record)` — AutoGen 이 예외 문장을 `is_error` 도구 결과로 모델에게 준다
- 오류 결과는 G0-6 원칙대로 step 을 `failed` (`tool_execution_error`) 로 남기지만 세션은 계속 돈다. 연속 중단 카운터와 무관하다 (테스트)
- **호출 직렬화** : AutoGen 은 한 응답의 도구 호출 여러 개를 동시에 실행한다 (동기 함수는 스레드). 호출 기록 순서가 섞이지 않고 검색 제공자가
  한 번에 연결 하나만 보게(arXiv 이용 약관, 파트 2) `ToolDispatch` 가 호출을 하나씩 받는다
- 도구 설명(docstring)을 실제 동작에 맞췄다 : `lookup_order` 의 "or \"not found\"" → 없는 ID 는 오류 결과. 대화 과제 실행 세션이 0 개라 요청 본문이 바뀌어도 비교할 기존 기록이 없다
- 실행 전 거절 문구 "Tools not implemented until C-17-6" → "Tools without an implementation"

테스트 `tests/test_cs_tools.py` : 한 건 반환·출처 기록, 없는 ID·빈 값, 읽기 전용, 이름 세 형태, 경로·없는 이름 거절(문서 이름 고지), 밖으로 풀리는 링크,
입력 형식 검사, 실제 실행기 경로에서 오류 결과가 모델 요청의 도구 결과로 들어가고 step 은 `failed`·세션은 계속.

## 파트 2 — 검색 도구 2 종 + 원문 저장 (`experiments/search_tools.py`, DM-13 · DM-21)

**제공자** (DM-21) — 문서 확인 2026-10-02, 실제 호출 없음

| 도구 | 제공자 | 요청 | 인증 | 근거 |
|---|---|---|---|---|
| `web_search` (MR) | Tavily | `POST https://api.tavily.com/search`, JSON 본문 | `Authorization: Bearer <TAVILY_API_KEY>` | Tavily Search API reference |
| `academic_search` (LR) | arXiv API | `GET https://export.arxiv.org/api/query?search_query=…&start=0&max_results=…&sortBy=…&sortOrder=…`, Atom 응답 | 없음 | arXiv API User's Manual (문서의 기본 주소는 `http://`, 같은 호스트의 https 를 쓴다) |

**arXiv 호출 간격 (확인 결과)** — 3 초가 맞다. 이용 약관(https://info.arxiv.org/help/api/tou.html) : "make no more than one request every three
seconds, and limit requests to a single connection at a time". 사용 설명서도 연속 호출에 3 초 지연을 권한다.
- 구현 : 앞 arXiv 요청이 **끝난** 시각부터 `min_interval_seconds` 가 지나야 다음 요청을 보낸다 (시작 기준보다 보수적). 기다린 시간은 기록 `waited_seconds`
- 스키마가 `min_interval_seconds ≥ 3` 을 강제한다. "연결 하나" 는 호출 직렬화(파트 1)로 지킨다
- **한계 (보고)** : 간격은 **실행기 프로세스 하나 안에서만** 지킨다. LR 세션 여러 개를 수동 병렬(DM-24, 창 3 개)로 돌리면 프로세스끼리는 간격을 모른다.
  LR 세션은 한 번에 하나만 돌리는 것을 제안한다 (보고 6 절)

**설정** — 시나리오 `tool_settings` 에서만 읽는다. 코드에 기본값이 없다. 역할이 쓰는 검색 도구마다 설정이 정확히 있어야 하고(없으면 스키마 오류),
쓰지 않는 도구의 설정도 오류. 산출물 과제는 `tool_settings` 를 가질 수 없다. 설정과 그 해시는 `conditions.json` (`tool_settings`, `search`),
검색 기록 한 줄마다, 매니페스트 v0.6 `task.tool_settings`·`task.search` 에 남는다.

| 필드 | `web_search` (Tavily) | `academic_search` (arXiv) |
|---|---|---|
| `provider` | `tavily` | `arxiv` |
| `max_results` | 1~20 (Tavily 범위) | 1~50 |
| 검색 방식 | `search_depth` : `basic` / `advanced`, `topic` : `general` / `news` | `sort_by` : `relevance` / `lastUpdatedDate` / `submittedDate`, `sort_order` |
| `max_result_chars` | 모델에게 넘기는 한 번의 결과 글자 수 상한 (≥ 200) | 같음 |
| `max_calls_per_session` | 세션당 실제로 보낸 요청 수 상한 (≥ 1) | 같음 |
| `timeout_seconds` | 0 초과 120 이하 | 같음 |
| `min_interval_seconds` | — | ≥ 3 (위) |

- **도구가 고정하는 Tavily 값** : `include_answer: false`, `include_raw_content: false`, `include_images: false`. 모델은 검색 결과만 받고 Tavily 가 생성한 답·
  페이지 전문·이미지는 받지 않는다. 설정이 아니라 도구 정의라 코드 상수이고, 요청 기록과 `conditions.search.*.fixed_parameters` 에 남는다
- **세션당 호출 상한의 기본값 제안** (정하지 않음, 보고 6 절) : **20**. 근거는 구조다 — MR·LR 은 고정 순서 3 역할이고 `max_steps` 30 이면 검색 담당 차례는 10 번,
  차례마다 도구를 쓸 수 있는 호출은 3 − 1 = 2 번 (마지막 호출은 도구 없음, v8 사실 문장) → 10 × 2 = 20. 한 응답에 도구 호출을 여러 개 담으면 이보다 많아질 수 있고,
  그때 상한이 비용을 막는다. 상한에 닿은 호출은 요청을 보내지 않고 사실 문장 오류 결과
  (`web_search was not run: the limit of 20 web_search calls for this session is reached.`)

**모델 인터페이스 (설계 5 절과 다름, 보고)**

- `web_search(query)`, `academic_search(query)` — 설계 표의 `max_results: int = 5` 인자를 **뺐다**. 지시가 결과 수를 설정값(하드코딩 금지)으로 정했고,
  인자로 두면 기본값 5 가 요청의 도구 스키마에 하드코딩되며, 같은 시나리오 세션끼리 결과 수(비용·결과)가 모델 선택에 따라 달라진다. 결과 수는 `max_results` 설정이다.
  **PM 확인 필요** — 모델이 설정 이하에서 고르게 되돌릴지
- `academic_search` 의 질의는 **그대로** arXiv `search_query` 로 보낸다 (도구 설명이 이 사실과 `all:`·`ti:`·`abs:`·`AND`/`OR`/`ANDNOT` 이 있다는 것을 알린다).
  자유 문장을 `all:` 로 바꾸는 규칙을 만들지 않았다 — 어떤 규칙이든 결과를 바꾸는 하네스 선택이 되고, 그대로 보내면 기록된 질의가 곧 보낸 질의다.
  자유 문장이 arXiv 에서 어떻게 해석되는지는 PM 검색 확인 도구(파트 3)와 C-18 시험 실행에서 본다
- 도구 설명(docstring) 은 사실만 쓴다 (제공자, 돌려주는 필드, 결과 수는 과제가 정함)

**원문 저장** — 세션 폴더 `runs/demo/<세션>/search/`

- `search/responses/<sha256>.json|.xml` : 200 응답 본문을 **받은 바이트 그대로** 저장 (같은 내용은 파일 하나). 설계 5 절의 `search-cache.jsonl` 안
  `response_raw` 대신 파일로 둔 이유 : JSON 한 줄에 다시 담으면 재직렬화라 "원문 그대로" 가 아니고, XML(arXiv)은 JSON 값이 아니다
- `search/records.jsonl` : 검색 호출 1 건 = 1 줄 (상한·인자 오류로 보내지 않은 호출 포함)

| 필드 | 뜻 |
|---|---|
| `seq`, `dispatch_seq`, `step_id`, `agent_id`, `tool`, `provider`, `query`, `requested_at` | 어느 호출인가 (`dispatch_seq` = `tool-dispatch.json` 의 호출 번호) |
| `settings`, `settings_sha256` | 그 호출에 쓴 설정 |
| `request` | 보낸 그대로의 method·URL·파라미터·본문·헤더. **키 없음** (`auth` 에 "값은 기록하지 않음" 문장만) |
| `outcome` | `ok` / `invalid_arguments` / `limit_reached` / `missing_key` / `timeout` / `network_error` / `http_error` / `parse_error` / `provider_error` |
| `http_status`, `elapsed_ms`, `waited_seconds` | 응답 상태, 걸린 시간, arXiv 간격 대기 |
| `response` | 저장한 응답 `{sha256, bytes, path, content_type, redacted, received_sha256}` 또는 null |
| `error` | 실패 기록 `{type, message}` (키 가림, 300 자) 또는 null |
| `normalizer`, `results`, `total_results` | 원문에서 만든 정규화 결과 (`tavily-results-v1` : rank·title·url·excerpt / `arxiv-atom-v1` : rank·id·title·authors·year·excerpt, arXiv 전체 건수) |
| `truncation` | 자르기 규칙·상한·원래 길이·보낸 길이·자른 길이·보낸 결과 수 |
| `model_text`, `model_text_sha256` | 모델에게 넘긴 내용 그대로 (오류면 그 사실 문장) |

- **로그에서는 해시로 참조** : 호출 기록(`tool-dispatch.json`)의 `search` = `{record_seq, provider, outcome, response_sha256, results, results_sent, total_results}`.
  `results` 는 판정 함수 입력이다 (아래)
- 요약 `summary.search` (매니페스트 v0.6 `search`) : 보낸 요청 수, 기록 수, 결과별 수, 저장 응답 수, `records.jsonl` 의 sha256

**모델에게 넘기는 내용과 자르기** (`uniform-excerpt-cut-v1`)

- JSON 텍스트 `{result_count, results, excerpts_cut_to_chars, results_left_out, (arXiv) total_results}`. 결과 항목은 Tavily `title·url·excerpt`,
  arXiv `id·title·authors·year·excerpt`. 질의는 다시 싣지 않는다
- 전체가 `max_result_chars` 보다 길면 모든 발췌(excerpt)를 **같은 길이**로 자른다 — 들어가는 가장 긴 길이(이분 탐색), 자른 발췌 끝에 "…".
  발췌를 비워도 안 들어가면 뒤에서부터 결과를 뺀다. 결과는 항상 유효한 JSON 이고 같은 입력이면 같은 출력이다. 자른 길이·뺀 수는 텍스트 안에도 사실로 들어간다

**실패 처리** — 자동 재시도 없음 (요청 1 번 = 기록 1 줄, 테스트)

| 경우 | 모델이 받는 오류 결과 (사실 문장) | 저장 |
|---|---|---|
| 시간 초과 / 네트워크 오류 | `<tool> failed: no response from <제공자> (timed out \| network error). No results.` | 오류 기록 (원문 없음) |
| HTTP 오류 (200 아님) | `<tool> failed: HTTP <상태> from <제공자>. [제공자 오류 문장] No results.` — 제공자 문장은 Tavily `detail.error`, arXiv 오류 피드 `summary`, 200 자 | 오류 기록 (본문 300 자 발췌, 원문 파일 없음) |
| 200 인데 읽을 수 없음 | `<tool> failed: the <제공자> response could not be read. No results.` | 원문 저장 + 오류 기록 |
| arXiv 200 오류 피드 | `academic_search failed: arXiv returned an error: <summary> No results.` | 원문 저장 + 오류 기록 |
| 빈 질의 / 키 없음 / 상한 | 각각 사실 문장, 요청 안 보냄 | 기록만 |

**키** (`TAVILY_API_KEY`, KMU 키와 같은 규칙)

- 환경 변수에서 호출 때만 읽는다. 요청 기록·오류 기록·모델 텍스트에 넣지 않는다. 제공자가 응답이나 오류 본문에 키를 되돌려 보내면 저장 전에
  `[REDACTED]` 로 바꾸고 `redacted: true`·받은 원문 해시를 남긴다 (테스트 : 세션 폴더 어느 파일에도 키 바이트 없음)
- D-11 검사 (`tools/analyze_session.py secret_scan`) : 검색 도구 설정이 있는 세션만 `tvly-` 패턴과 `TAVILY_API_KEY` 값 자체를 더 찾는다.
  검색 도구가 없는 세션은 검사 항목이 이전과 같아 기존 저장 분석(G0-8·A-1 계열)이 그대로 재현된다

**replay — 다시 검색하지 않는다**

- `search_tools.load_records(run_dir)` : 기록마다 저장 원문 파일의 sha256 을 확인하고, 원문에서 정규화를 다시 해 기록된 결과와 같은지, 자르기를 다시 해
  모델 텍스트·자르기 기록이 같은지 확인한다. 다르면 `ReplayMismatch`
- `search_tools.replay_tool_records(run_dir)` : `tool-dispatch.json` 의 검색 참조를 위 원문에서 다시 만든 값으로 바꿔 돌려준다 (판정 함수 입력)
- `tools/rejudge_dialogue.py <run_dir>` : 판정 재계산. step 마다 그때까지의 최신 검증 보고와 그때까지의 도구 기록(위)으로 판정 함수를 다시 부르고,
  완료 주장(DM-45)도 다시 판정해 기록과 비교한다. 판정 함수 파일 해시도 `conditions.judge` 와 비교. 검색·모델·프록시 호출 없음
- 세션 재생 화면(C-19)도 같은 저장 원문을 읽으면 된다
- 설계 5 절의 `--search-replay <cache>` (저장 결과로 **세션을 다시 실행**) 는 만들지 않았다. C-17-6 지시의 replay 는 재계산·재생·판정이고,
  다시 실행하면 모델 호출이 생기는 새 세션이다

**판정 함수 연결** — `judge(report, *, tool_records, inputs_dir)` 의 `tool_records` 가 위 호출 기록이다. 검색 호출이면 `search.results` 와
`search.results_sent` (모델이 실제로 본 결과 수) 로 "보고의 출처 URL·논문 ID 가 그 세션의 저장된 검색 결과에 있었는가" 를 검사한다.
시험용 판정 함수 `tests/fixtures/scenario_judges/TEST-MR-v2.py` (URL), `TEST-LR-v2.py` (arXiv ID 2 개).

**기록 위치**

- `conditions.json` : `tool_settings`, `search` (도구별 제공자·주소·키 환경 변수 이름·고정 파라미터·정규화기·자르기 규칙·설정과 해시·간격 범위·재시도 없음)
- 매니페스트 **v0.6 자리에서 넓혔다** : `task.tool_settings`, `task.search`, 대화 과제의 `search` (요약). v0.6 을 만든 실제 세션이 아직 없다 (DM-51 원칙)

테스트 `tests/test_search_tools.py` (가짜 HTTP 계층 `tests/search_fixtures.py`, 응답 fixture `tests/fixtures/search/` — 모양의 출처는 그 폴더 README) :
Tavily 요청·원문 바이트 저장·정규화·모델 텍스트·호출 참조, 되돌아온 키 가림, arXiv 요청 파라미터·정규화(옛 형식 ID 포함)·간격, 상한, 실패 7 경우(재시도 없음),
빈 질의·키 없음, 자르기(균일 자르기·결과 빼기·결정적), replay(원문만, 전송 없음, 판정 동일, 변조 거부), 설정 스키마, 도구 인자.

## 파트 3 — 실행 전 검사 · PM 검색 확인 도구 · 통합 테스트

**실행 전 검사** (`dialogue_runner.tool_preflight`, 검사 이름 `dialogue-tool-preflight-v1`)

- 위치 : 대화 과제 실행의 인자 검사 바로 뒤. **모델·검색·프록시 호출 전, 세션 ID 와 실행 폴더를 만들기 전**이다 (테스트 : 세션 ID 생성에 닿으면 실패)
- 검사 : ① 시나리오 역할들이 쓰는 도구마다 구현이 있는가 ② 쓰는 도구가 요구하는 키 환경 변수가 있는가 (지금은 `web_search` → `TAVILY_API_KEY`.
  값은 읽어 보이지 않고 `present`/`missing` 만) ③ `inputs_dir` 가 있는가, 쓰는 로컬 도구의 입력이 파트 1 형식에 맞는가 (`cs_tools.input_problems`)
- 하나라도 안 되면 문제를 **모두** 이어 쓴 실행 전 오류 : `Pre-run check failed: Tools without an implementation: …; Key environment variable not set: TAVILY_API_KEY; lookup_order input: orders.json not found; …`
- 통과하면 결과를 `conditions.tool_preflight` 와 매니페스트 v0.6 `task.tool_preflight` 에 남긴다 (`{check, tools_implemented, keys, inputs_dir, input_problems}`)
- 검색 설정의 유무는 시나리오 스키마가 이미 막는다 (파트 2). 모델 호출 키(`KMU_API_KEY`) 검사는 이전 그대로 이 뒤에 있다

**PM 검색 확인 도구** (`tools/probe_search.py`, `search-probe-v1`) — 코딩 에이전트는 실행하지 않고 오프라인 테스트만 했다

- LLM 호출 없이 Tavily 1 회 (`multi-agent LLM system failure causes`, 결과 5, basic, general), arXiv 1 회 (`all:"multi-agent" AND all:failure`, 결과 5, relevance)
  — 고정 질의·설정은 도구 안의 상수이고 결과에 기록된다. 요청은 실행기와 **같은 요청 조립 함수**(`search_tools.build_request`)로 만든다
- 저장 : `runs/search-probes/search-probe-<id>/` 에 `tavily-response.json`, `arxiv-response.xml` (받은 그대로, 키가 섞여 오면 가림), `result.json`
- 비교 : 응답과 fixture(`tests/fixtures/search/`) 의 **모양**(JSON 경로·타입, XML 요소·속성 경로)을 비교해 응답에 없는 경로, 응답에만 있는 경로,
  타입 차이, 도구가 읽는 필드의 존재, 도구 정규화 결과(건수·첫 결과)를 낸다. arXiv 항목에 없을 수 있는 요소(`arxiv:comment`·`journal_ref`·`doi`·`affiliation`)가
  빠진 것은 변화로 치지 않는다. 판정 `all_ok` = 두 응답 모두 200 + 모양 같음 + 도구 필드 있음 + 정규화 성공
- 키 : `TAVILY_API_KEY` 에서만 읽는다. 없으면 아무것도 보내지 않고 종료 코드 2. 끝에 결과 폴더의 모든 파일에서 키 값을 찾아 `secret_scan` 에 남긴다
- 종료 코드 : 0 (모두 통과, 결과 폴더에 키 값 없음), 1 (모양 차이·HTTP 오류·응답 없음·키 값 발견), 2 (`TAVILY_API_KEY` 미설정, 전송 0)

**통합 오프라인 테스트** (`tests/test_dialogue_tool_flows.py`, 실제 실행기 + 메모리 프록시 + 가짜 업스트림 + 실제 도구, 검색은 가짜 HTTP 계층)

| 흐름 | 확인한 것 |
|---|---|
| CS 형태 (라우터) | 접수 `lookup_order`(A-100) → 환불 담당 `read_policy`(refund.md) → 접수 완료 선언 `success`. 판정 함수가 호출 기록에서 주문 조회를 확인. 재판정 전부 같음 |
| CS 조회 실패 | 없는 주문만 조회하고 그 주문으로 완료 선언 → 완료 주장 거절 (`order_id_not_looked_up`), 세션은 `max_steps` |
| MR 형태 (가짜 Tavily) | 검색 1 회, 원문 바이트 저장·호출 기록의 해시 참조, 출처 URL 이 저장된 결과에 있어 `success`. 재판정은 전송 계층이 막힌 상태에서 전부 같음 (`searched_again: false`). 실행 루트 전체(실행 폴더·프록시 로그) 어디에도 키 문자열 없음 |
| MR 결과 밖 출처 | 저장된 결과에 없는 URL → 완료 주장 거절, `max_steps` |
| MR 검색 실패 | 시간 초과 → 오류 결과, step `failed`·세션 계속, 재시도 없음 (요청 1 번) |
| LR 형태 (가짜 arXiv) | 검색 2 회 (step 2·5), 두 번째는 3 초 간격을 기다림, 논문 ID 2 개가 결과에 있어 `success`. 매니페스트 v0.6 의 `task.tool_settings`·`task.search`·`search`·`task.tool_preflight`, D-11 검사에 Tavily 패턴 포함·깨끗함 |
| 실행 전 검사 | 키 없음 (요청 0, 실행 폴더 없음), 구현 없음 + 입력 없음을 한 문장에 모두, `inputs_dir` 없음, 통과 기록 |
| 검색 확인 도구 | fixture 모양 응답 통과·저장, 모양 변화 보고, arXiv 선택 요소 없음은 통과, 키 없으면 전송 0, 네트워크 오류·되돌아온 키 가림 |

- 네트워크 : 전체 오프라인 테스트의 감사 훅(`tools/run_offline_tests.py`)이 소켓 접속 0 (`network_attempts: []`) 을 확인한다

**PM 실행 명령 (검색 확인, C-18 시험 실행 전)** — 한 줄에 명령 하나. 키는 Tavily 콘솔에서 복사한 뒤 직접 입력한다

```bash
cd ~/AI-agent-guardrail-harness
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY} ${TAVILY_API_KEY:0:4}
venv/bin/python tools/probe_search.py
```

- 결과 폴더는 `runs/search-probes/` 아래 (`runs/` 는 `.gitignore` 대상). 커밋은 D-11 검사 뒤 `git add -f` (기존 probe 와 같은 절차)
