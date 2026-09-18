# P0-2: 대화·산출물 독립 보존

PM 승인: 선택지 B. 기본 수집 정책은 `independent-sources-v1`, 실행기 프로토콜은
`tool-capable-step-v6-independent-observations`이다. 기존 동작은
`--collection-policy legacy-failed-step-v1`로 선택하며 프로토콜은
`tool-capable-step-v5-strict`다. conditions.json에 둘 다 기록한다.

## 제출 조건

- 대화는 같은 step의 마지막 strict 최종 요청에 대한 HTTP 정상 응답이며,
  finish_reason=stop, assistant 메시지, 도구 결과/호출 없음,
  parse_output 전체 통과, 원본 proxy turn 연결을 모두 확인해야 제출한다.
- 실행 중에는 HTTP 원문과 SDK가 반환한 최종 출력의 일치도 확인한다.
  다음 호출과 step 시작 때 증거를 초기화하여 과거 응답을 재사용하지 않는다.
- 부분 파싱은 인정하지 않는다. 유효 JSON 일부나 이전 호출의 정상 텍스트로
  실패한 최종 보고를 대신하지 않는다.
- 산출물은 최종 출력과 독립적으로 실제 acceptance 수집값을 제출한다.
  수집 못 한 필드는 null 및 collection.metric_status의 unmeasured로 남긴다.
- failed, failure_reasons, tool_errors, strict 실패 연속 수, abort, 실행 종료 조건을
  바꾸지 않는다. 관측용 종결 선언 이력도 실행 종료 판단 이력과 분리한다.
- 회복 narrative는 관측에만 사용한다. recent_messages 전달 정책은 유지한다.

## 호환과 스키마

Observation.collection은 선택 필드다. 정책, 최종 출력 상태/사유/source_turn,
선택 지표의 수집 상태/누락 사유를 기록한다. source_turn은 llm_turns에 속해야 한다.
steps.json에는 collection과 observed_final_report도 남긴다.
measurement_status는 입력의 수집 범위이며 progress 판정이나 step 성공이 아니다.
모델 출력 계약·프롬프트에는 agent_id를 요구하지 않으며 실행기가 부여한다.

기존 관측에 collection이 없어도 수용한다. 기존 테스트의 기대값은 변경하지 않고
legacy 정책을 명시한다. progress-v2, deadlock-v0.2 및 v1 계산 파일은 변경하지 않는다.
G0-5 우선순위는 현재 동작으로 고정하며 G0-6 도구 is_error, G0-7 절단 원인은 수정하지 않는다.

## 검증

tests/fixtures/p0-2-baseline-test-ids.json은 변경 전 discovery에서 얻은 테스트 ID다.
tools/run_offline_tests.py가 기존/신규를 분리 집계한다. 보호 파일 SHA-256 fixture로
판정기·기존 replay·출력 계약·원본 로그 불변을 검사한다.
실행기 테스트는 HTTP MockTransport/ASGITransport만 사용한다.
오프라인 replay는 원본 v1 재현과 저장 P0-1 결과 일치가 선행 조건이다.
폐기된 산출물의 당시 스냅샷이 없으면 복원하지 않는다.
