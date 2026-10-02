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
