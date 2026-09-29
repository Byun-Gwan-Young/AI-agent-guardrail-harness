# 데모 트랙 실행기 확장 설계 (C-16 파트 2)

- 상태 : **설계안.** 구현은 C-17
- 대상 : 파일 산출물·인수 테스트가 없는 T1 과제 (CS·MR·LR). T2·T3 는 기존 산출물 경로를 쓴다 (CT 승인 절차만 추가)
- 불변 : 기존 A-1 경로(시나리오 스키마 `scenario-v1`, output-contract-v1/v2, 프로토콜 v7~v10, `deadlock-v0.2`)는 바꾸지 않는다

## 1. 현재 실행기의 제약 (코드 기준)

| 위치 | 제약 |
|---|---|
| `experiments/run_scenario.py:303` | 역할 ID 가 정확히 {planner, developer, reviewer} 가 아니면 실행 전 오류 |
| `run_scenario.py:305` | `success_criteria.test_suite` 와 `fixture_dir` 필수 |
| `run_scenario.py:434-435` | 차례는 `(step - 1) % len(agents)` 고정 순환 |
| `run_scenario.py:237-269` `Workspace.tools` | 도구는 `read_file`·`write_file`·`replace_in_file`·`run_tests` 4 종뿐. 권한 이름으로 고름 |
| `run_scenario.py:556` | 성공 = 인수 테스트 `machine_success` + (필요 시) 완료 선언 |

## 2. T1 과제를 받는 방법

**시나리오 스키마 `scenario-v2` (제안)** : `scenario-v1` 은 그대로 두고, 새 버전에서만 아래 필드를 허용한다.

| 필드 | 뜻 |
|---|---|
| `task_kind` | `artifact`(기존) 또는 `dialogue`(T1) |
| `agents[].tools` | 역할별 도구 이름 목록 (권한 이름 대신 도구 이름을 직접 명시) |
| `turn_order` | `fixed` 또는 `router` (3 절) |
| `status_values` | T1 처리 상태의 순서 있는 목록 (예 : `[received, triage, assigned, resolved]`) + 종료 상태 `escalated` |
| `deliverable_schema` | 최종 산출물(`deliverable`)의 JSON 스키마. 계약 v3 가 strict 스키마에 끼워 넣는다 |
| `judge` | 완료 판정 함수의 모듈 경로. **에이전트가 읽을 수 없는 경로** (`scenario_judges/<ID>.py`, fixture 밖) |
| `inputs_dir` | 에이전트 도구가 읽는 자료 폴더 (T1 은 파일 쓰기 없음) |

**실행 흐름 (T1)**

- 매 step 끝에 판정 함수를 최신 `deliverable` 과 도구 기록(검색 캐시)에 적용한다
  - `gate = {machine_success, result: resolved|escalated|unfinished, missing: [...]}`
  - 산출물 경로의 `acceptance()` 자리를 대신한다
- `progress_source: conversation`. `artifact` 관측은 `null` 이 아니라 **수집 안 함** 으로 명시한다 (T1 은 산출물이 없다)
- 성공 종료 : `gate.result == resolved` + 완료 선언 (T2 와 같은 규칙). `escalated` 는 종료 사유 `escalated` 로 끝낸다
  - 계속 돌리면 에이전트가 이미 과제 결함을 선언한 뒤의 소비가 되기 때문이다
  - 판정 결과 집계는 PM 결정 (demo-scenarios 7 절 4)
- 분기는 `task_kind` 하나로만 한다. `task_kind: artifact` 경로의 요청 본문은 v10 과 바이트 동일해야 한다 (C-17 테스트)

## 3. 차례 방식 — **PM 결정**

| 안 | 방식 | 장점 | 단점 |
|---|---|---|---|
| (a) 고정 순서 (현행) | 모든 T1 과제를 역할 순환으로 | 코드 변화 최소. 판정 규칙의 "역할 한 바퀴 = 3 step" 구조가 그대로 | CS 의 "담당을 넘긴다" 가 실제 차례에 반영되지 않는다. 환불↔배송 왕복이 접수를 거쳐 희석된다 |
| (b) 라우터 | 직전 step 의 `handoff_to` 가 다음 차례. 없거나 허용 밖이면 고정 순서로 되돌아간다 | CS 의 책임 떠넘기기가 실제 차례로 드러난다. 왕복 횟수가 직접 측정된다 | 차례가 모델 출력에 달려 한 역할이 여러 번 연속할 수 있다. 판정 규칙의 "전역 3 step" 이 역할 한 바퀴를 뜻하지 않게 된다 |
| (c) 혼합 (권장) | CS 만 라우터, MR·LR·T2·T3 는 고정 | 과제 성격에 맞춘다. 라우터 코드가 CS 한 곳에만 쓰인다 | 두 방식을 모두 테스트해야 한다 |

- 라우터에서 `handoff_to` 가 허용 밖 값이면 어휘 위반과 같이 step failed 로 기록하고 고정 순서로 진행한다 (D-17 과 같은 원칙 : 연속 중단 카운터에 넣지 않음)

## 4. T1 최종 보고 계약 — `output-contract-v3` (제안)

v2 의 필드(`narrative`, `open_issue_ids`, `info_items`, `completion_declared`, `unlisted_issues`)에 다음을 더한다. v2 는 불변.

| 필드 | 타입 | 뜻 |
|---|---|---|
| `status` | 시나리오 `status_values` 중 하나 (enum) | 현재 처리 상태. 모든 역할이 전체 상태를 보고 |
| `handoff_to` | 역할 ID 또는 null | 다음에 일할 역할. 라우터에서만 차례에 쓰이고, 고정 순서에서는 기록만 |
| `adopted_items` | 문자열 목록 또는 null | 지금까지 채택된 항목 ID 전체. MR : `<제품>:<칸>`, LR : 논문 ID. CS 는 빈 목록 |
| `deliverable` | `deliverable_schema` 또는 null | 최종 산출물. 판정 함수의 입력 |
| `spec_approved` | bool 또는 null | T2 CT 승인 절차용 (reviewer 만 의미 있음). 다른 과제는 null |

- 스키마는 strict. `status` 는 enum 을 제공자에게 보낸다
  - 쟁점 ID enum 을 보내지 않은 것(D-13)과 다르다. 상태 목록은 짧고 닫혀 있어 로컬 검증만으로는 이득이 없다
  - 게이트웨이 strict 수용은 probe 로 확인한다 (C-17)
- `adopted_items` 는 **전체 목록**으로 받는다 (증분 아님). 진전 계산은 세션 안에서 처음 나온 ID 수로 한다 (v0.3)

**허용 쟁점 ID (D-14) 의 T1 적용** — 기능 조건 1 개 = ID 1 개 규칙을 과제 문서에 그대로 적용한다.

| 과제 | 과제 문서 | ID (제안) |
|---|---|---|
| CS | `handling_codes.md` 의 판정 필드 | `ownership`, `handling-code`, `customer-reply` |
| MR | `brief.md` 의 칸 | 칸마다 1 개 (예 : `pricing`, `features`). 교착판은 `market-share` 추가 |
| LR | `brief.md` 의 선정 규칙·요약 | `paper-selection`, `summaries`. 교착판은 `benchmark-condition` 추가 |

- 과정 쟁점 2 개는 T1 의미로 다시 정의한다 : `requirements` = 과제 해석 미결정, `acceptance-review` = 최종 산출물이 판정 필드를 채웠는지 확인 안 됨
- 교착판은 유도 조건에 해당하는 ID 가 1 개 더 있다. 이것이 한 변수 원칙에 따른 유일한 차이다

## 5. 도구 인터페이스

| 도구 | 인자 | 반환 | 과제 | 비고 |
|---|---|---|---|---|
| `lookup_order` | `order_id: str` | 주문 레코드 JSON 또는 "not found" | CS | `inputs_dir/orders.json` 읽기 전용 |
| `read_policy` | `name: str` | 정책 문서 본문 | CS | `inputs_dir/policies/` 의 허용 목록만. 경로 탈출 금지 (`safe_path` 재사용) |
| `web_search` | `query: str`, `max_results: int = 5` | 결과 목록 (제목, URL, 발췌) | MR | 제공자 : Tavily 제안, **PM 확인 대기 (DM-13)** |
| `academic_search` | `query: str`, `max_results: int = 5` | 결과 목록 (ID, 제목, 저자, 연도, 초록 발췌) | LR | arXiv 또는 Semantic Scholar, **PM 결정** |

- 키 : `TAVILY_API_KEY` 등 환경변수에서만 읽는다
  - 로그·캐시·매니페스트에 넣지 않는다. D-11 검사에 해당 환경변수 값 자체를 추가한다
  - arXiv 는 키가 없다
- 호출 한도 : 도구 호출도 step 당 모델 호출 예산(3) 안에서 일어난다. 추가 제한은 두지 않는다

**검색 결과 저장 (DM-13)** — `runs/demo/<session>/search-cache.jsonl`, 호출 1 건 = 1 줄 :

```json
{"seq": 7, "step_id": 4, "agent_id": "searcher", "tool": "web_search", "query": "...", "max_results": 5,
 "provider": "tavily", "requested_at": "<ISO8601>", "http_status": 200,
 "response_raw": {...}, "results": [{"id": "...", "title": "...", "url": "...", "excerpt": "..."}]}
```

- `response_raw` 는 제공자 응답 원문 그대로 (키·헤더 제외). `results` 는 모델에게 준 정규화 결과
- **replay** : `--search-replay <cache>` 로 실행하면 (도구, 질의, 같은 질의의 n 번째 호출) 로 저장 결과를 돌려준다. 외부 호출은 없다. 캐시에 없는 호출은 오류로 기록한다
  - 판정 재계산과 대시보드 재생이 같은 결과를 낸다
- **오프라인 테스트** : `tests/fixtures/search/` 에 가짜 응답(질의 → 결과)을 두고, 같은 replay 경로로 주입한다. 테스트는 네트워크 감사 훅(`run_offline_tests.py`)에서 외부 접속 0 을 확인한다
- 판정 함수는 이 캐시로 "출처 URL·논문 ID 가 실제 검색 결과에 있었는가" 를 확인한다 (MR·LR)

## 6. CT 승인 절차 (T2, demo-scenarios 4 절 안 (b) 채택 시)

- 시나리오 필드 `write_gate: {role: developer, requires: spec_approved, set_by: reviewer}`
- reviewer 의 검증된 최종 출력에 `spec_approved: true` 가 처음 나온 step 이후에만 developer 쓰기 도구가 동작한다. 그 전에는 도구 오류 "SPEC.md 가 아직 승인되지 않았습니다"
  - G0-6 `tool_executions.is_error` 로 기록된다
  - v10 최종 요청에 `is_error` 가 남는다 (S-31)
- 승인 뒤 SPEC.md 가 바뀌면 승인을 해제할지 : **해제하지 않는다** (제안. 규칙을 단순하게)

## 7. 기록

- `conditions.json`·매니페스트 : `phase: demo`, `task_kind`, `turn_order`, `output_contract_version`, `search_providers`, `search_cache_sha256`, `guardrail_mode`, `criteria_version`
- 세션 폴더 `runs/demo/<session>/`, 프록시 로그는 `GUARDRAIL_LOG_DIR=logs/demo` (제안). 데이터셋 경로와 섞지 않는다 (C-16 금지 사항)

## 8. PM 결정 필요

1. 차례 방식 : (a) 고정 / (b) 라우터 / (c) CS 만 라우터 (권장)
2. `status` enum 을 제공자 strict 스키마에 보낼지 (제안 : 보냄. probe 로 확인)
3. 검색 제공자 : MR Tavily (DM-13 확인 대기), LR arXiv / Semantic Scholar
4. `escalated` 종료 사유를 둘지 (제안 : 둠)
