# P0-3: 닫힌 쟁점 어휘

PM 결정 D-13(방식 A′), D-14(도출 규칙), D-16(`unlisted_issues` 제한), D-17(어휘 위반과
strict 연속 중단). 역할마다 같은 쟁점을 다른 문자열로 적어 progress 비교가 성립하지 않던
문제(G0-3)를 시나리오가 고정한 허용 목록으로 막는다.

## 버전 식별자

- 출력 계약 `output-contract-v2`, 실행기 프로토콜 `tool-capable-step-v7-issue-ids`.
  v7 은 v6(`independent-sources-v1`) 위에 어휘 계약을 더한 것이므로 v2 는 독립 수집
  정책에서만 실행한다. 다른 조합은 실행 전 오류다.
- conditions.json 에 `output_contract_version`, `allowed_issues_sha256` 을 기록한다.
  해시는 (ID, 정의) 쌍을 ID 순으로 정렬한 정규 JSON 의 SHA-256 이다. 정의가 바뀌면 해시도 바뀐다.
- v1 은 `--output-contract output-contract-v1` 로 명시 선택한다. v1 의 스키마·응답 형식·파서·
  프로토콜 표기·step 기록은 바뀌지 않는다. 기본값은 v2 이며, 허용 목록이 없는 시나리오
  (예: 기존 A-1)는 v2 로 실행하면 실행 전 오류가 난다. 자동 추정은 없다.

## D-13 계약

- 시나리오 `allowed_issues` : 각 항목은 공백 없는 ID 와 한 줄 정의. ID 중복·빈 값 거부.
  `initial_issue_ids` 는 허용 ID 의 부분집합이어야 한다. 필드가 없으면(null) 기존 시나리오다.
- `open_issue_ids` 는 허용 ID 만. 중복은 형식 오류다. 허용 밖 ID 가 하나라도 있으면 최종 출력
  전체가 계약 위반이다 (코드 `open_issue_id_not_allowed`).
- 새 쟁점은 `unlisted_issues` 에 설명 문자열 목록 또는 null(모름), [] 는 없음. 관측의
  `issue_report` 에 기록만 하고 progress-v2 계산에는 넣지 않는다. 빈 문자열·중복 거부.
- 충돌 : `unlisted_issues` 항목이 허용 ID 와 문자열로 정확히 같으면 전체 거부
  (코드 `unlisted_issue_id_collision`). 자동 이동·삭제·정규화 없음.
- 정규화·의미 별칭·퍼지 매칭·등록 방식 없음. 제공자 측 enum 은 보내지 않고 로컬 검증만 한다.
- 프롬프트(역할 시스템 메시지, 최종 요청)에 허용 ID·정의·충돌 규칙을 명시한다.
- 계약 위반 시 P0-2 정책대로 대화 관측은 버리고 산출물은 실제 수집값만 보존한다.
  step 은 failed, 오류 이력은 유지한다. SDK 최종 검증·실행기 파싱·P0-2 원문 검증이 같은
  계약 객체를 쓴다. 위반 코드는 step 의 `strict_failure`·`failure_reasons` 와 원문 검증 사유
  (`final output contract violation: <코드>`)에 남는다.
- `agent_id` 는 모델 계약에 없고 실행기가 부여한다.

## D-14 허용 목록 도출

- 인수 조건 문서의 기능 조건 항목 1개 = ID 1개. 사람이 쪼개는 단위를 정하지 않는다.
- 과정 쟁점은 `requirements`(SPEC 재량 영역 미결정), `acceptance-review`(리뷰가 실제 테스트
  결과로 인수 기준 충족 확인) 두 개만 둔다.
- 근거는 에이전트가 읽을 수 있는 시나리오 파일에만 둔다. 실행 로그의 ID 는 근거가 아니다.
- ID 마다 근거 파일:행을 시나리오 YAML 주석으로 기록한다. 주석은 스키마 필드가 아니므로
  모델에 전달되지 않지만 시나리오 파일 해시에는 포함된다.
- 첫 적용 : `scenarios/A-1-v2-ambiguous-task-query.yaml`. A-1 과의 차이는 `scenario_id`,
  `allowed_issues`, 주석뿐이다. A-1 과 A-1-v2 세션은 섞지 않는다.

## D-16 `unlisted_issues` 항목 제한

항목당 1~240자, 한 줄. 공백만 있는 항목도 빈 항목으로 거부한다. 길이 제한은 제공자 strict
스키마의 `minLength`/`maxLength` 로도 전달되며, 제공자의 수용 여부는 확인되지 않았다
(`strict_support: unverified`, `tools/probe_groq_strict.py`).

## D-17 어휘 위반과 strict 연속 중단

- 어휘 위반(`open_issue_id_not_allowed`, `unlisted_issue_id_collision`)은 모델이 형식에 맞는
  JSON 을 낸 상태에서 값만 틀린 것이다. observe 수집은 세션을 끝까지 진행해야 반사실
  비교가 성립하므로, 어휘 위반으로 세션을 끝내지 않는다.
- 어휘 위반 step 은 failed 이고 대화 관측은 버리며 산출물은 보존한다.
- strict 연속 중단 카운터에서는 어휘 위반 step 을 strict 실패가 아닌 step 으로 본다
  (카운터 초기화). 형식 오류·HTTP 실패 등 기존 strict 실패는 지금처럼 센다.
  중복 ID 처럼 어휘와 형식 위반이 겹치면 형식 오류로 분류한다.
- 별도 기록 : step 에 `vocabulary_violation`, `consecutive_vocabulary_violations`,
  `vocabulary_violations_total`, 세션 summary 에 `vocabulary_violation_steps`,
  `vocabulary_violations_total`. v2 에서만 기록하며 v1 기록 형태는 그대로다.
- v7 로 수행한 실제 실행 로그가 아직 없으므로 프로토콜 버전을 올리지 않고 v7 안에서
  수정했다. 이 변경 이전 v7 로그는 존재하지 않는다.

## 알려진 공백

- v2 로그의 offline replay 경로가 없다. `tools/replay_preserved_observations.py` 는 계약 없이
  v1 로 파싱하며 기존 v1 로그 전용이다 (Stage 2 에서 검토).
- 제공자 strict 수용 여부 미확인. 사용자가 probe 를 1회 실행해 확인한다. 1회 결과는
  신뢰성이나 토큰 단위 강제를 증명하지 않는다.
- 다른 역할에 `[구조화 출력 없음]` 을 전달하는 동작(G0-13)은 어휘 위반에도 그대로다.
