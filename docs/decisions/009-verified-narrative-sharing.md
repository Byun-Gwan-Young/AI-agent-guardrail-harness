# G0-13: 검증된 최종 보고는 다른 역할에 전달한다

PM 결정 D-15. `docs/findings/005` 의 결함 후보를 G0-8 전에 수정한다.

- 범위 : output-contract-v2 (`tool-capable-step-v7-issue-ids`, 독립 수집 정책) 만. v7 로 수행한
  실제 실행이 없으므로 v7 안에서 고쳤다. v1 계약, v5 legacy, v6 independent 경로의 전달 동작은 불변.
- 전달 규칙 (다른 역할의 `recent_messages`)
  1. 실행기 파싱이 성공한 step → 그 narrative (기존과 같음)
  2. 파싱 경로가 실패했지만 P0-2 원문 검증(`observation_report`)이 `valid` 인 step → 그 narrative
  3. 그 밖 → `[구조화 출력 없음]`
- 어휘 위반(D-17)은 계약 위반이므로 원문 검증이 `invalid` 이고 3 으로 간다.
- 실행 종료 판단(완료 선언)은 지금처럼 실행기 파싱 결과만 쓴다. 관측용 선언 이력과 분리한 P0-2
  원칙을 유지한다. 전달 narrative 만 바뀌며 관측·progress·criteria 입력은 바뀌지 않는다.
- 기록 : steps.json `shared_narrative_source` (v2 에서만).
