# A-1 strict 최종 보고 적용

## 적용

runner_protocol은 **tool-capable-step-v5-strict**, scenario_revision은 **4**다. 네 필드 flat-state-v2 계약은 유지한다. 이전 세 실행 및 v4-preflight와 직접 비교하거나 같은 조건의 반복 표본으로 합치지 않는다.

1. 작업 호출에는 역할별 tools와 tool_choice auto만 사용하며 response_format을 넣지 않는다.
2. 최종 보고 호출에는 tools/tool_choice를 생략하고 **json_schema + strict:true**를 넣는다. schema 이름 state_report_probe와 네 필드 스키마는 성공 probe의 response_format 객체와 정확히 같다. probe와 실행기가 공용 생성 함수를 사용한다.
3. 최종 호출의 reasoning_effort는 probe와 같은 low다. 이 값을 conditions.json에 별도로 기록한다. 실제 과제 messages, 시나리오 temperature, max_tokens=1200은 과제 조건을 유지한다. probe의 max_tokens=256과 단순 확인 문장을 그대로 과제에 복사하지 않는다. 요청 전체가 byte 단위로 같다는 뜻은 아니다.
4. 도구 없는 최종 프롬프트 분리와 실행기의 agent_id/step_id 부여는 유지한다. 보고 필드는 narrative/open_issue_ids/info_items/completion_declared뿐이다. 목록의 null을 빈 목록으로 바꾸지 않는다.
5. 작업 호출에서 일반 텍스트가 일찍 나와도 그것만으로 완료시키지 않는다. 다음 호출을 strict 보고로 전환한다. 예를 들어 첫 호출이 텍스트면 두 번째가 최종 strict 호출이다. 도구를 두 번 사용하면 세 번째가 최종 strict 호출이다. **step당 최대 3회, 전체 최대 18 step/54회는 유지**한다.

## 실패 처리

- 최종 strict 요청의 HTTP 400: strict_http_400.
- 200이어도 JSON/필수 필드/타입/추가 필드 검증 실패, 잘린 출력, 예상 밖 도구 응답: strict_schema_mismatch. 예상 밖 도구 응답은 AutoGen 도구 실행 전에 거부한다.
- 해당 step을 failed/unmeasured로 기록하고 no_final_output과 상세 원인을 남긴다. 실제 파일·테스트 결과 및 proxy response_body는 원자료로 보존한다.
- **같은 세션의 연속된 두 step이 strict 실패**하면 종료한다. agent가 달라도 연속 step이면 센다. 중간 step에 strict 실패가 없으면 카운터는 0으로 초기화한다. 첫 실패는 단독으로 세션을 종료시키지 않는다.
- 두 번째 실패도 pending/ack·step·토큰 추이 기록을 저장한 뒤 종료한다. termination_reason=strict_output_failures, error=two_consecutive_strict_failed_steps다.
- 새로운 호출로 같은 step의 strict를 자동 재시도하지 않으며 B로 자동 전환하지 않는다. 앞 호출의 미등록 도구·인자 오류 및 인증/통신 오류는 기존 정책과 구분한다.
- step마다 strict_used, strict_failure, consecutive_strict_failures를 기록한다. 오류 응답 usage가 없으면 토큰은 null이며 확인된 소계와 구분한다.

## probe 근거

원본: runs/strict-probes/strict-probe-3472654ecfca4274b03383123aa03131/.
보존 위치: **reports/strict-probe-3472654ecfca4274b03383123aa03131/**의 request.json, response.json, result.json. 원본 세 파일을 수정 없이 복사했다.

확인된 값은 probe_passed, strict_request_accepted=true, schema_valid=true, model=openai/gpt-oss-120b, 총 282토큰(입력 225/출력 57)이다.

**1건의 성공은 항상 성공한다는 뜻이 아니며 신뢰성이나 토큰 수준 강제를 증명하지 않는다.** 원본 result.json의 이 단서를 그대로 보존했다. 이번 구현 작업에서는 실제 외부 API를 호출하지 않았다.

## B 대안 유지

기존 docs/A1-strict-preflight-and-fallback.md의 B 설계를 유지한다. strict가 실제 세션에서 불안정하면 사용자 결정 후 전환한다.

- 마지막 호출에 report_state만 제공하고 해당 함수를 지정한다.
- 동일한 네 필드만 인자로 받고 식별자는 실행기가 부여한다.
- 유효 보고 수신은 step 종료이며, 과제 성공은 리뷰어 선언·인수 테스트로 판단한다.
- B 전환 시 별도 runner_protocol/시나리오 revision을 사용한다. 실패한 strict 생성물을 자동으로 상태 보고에 편입하지 않는다.

## 테스트 및 재실행

전체 **122개 테스트 통과**. 기존 118개에 probe 원문과 실제 직렬화 response_format/최종 reasoning_effort 비교, 조기 텍스트의 strict 확인, 연속 실패 저장 후 중단, 성공 사이의 카운터 초기화 테스트를 추가했다. HTTP는 모두 MockTransport/인메모리 프록시로 검증했다.

재실행은 사용자가 새 output-root와 새 세션으로 수행한다. 실행 후 conditions.json의 v5-strict, 최종 요청의 response_format, strict_failure 필드, summary의 종료 사유를 확인한다. B는 구현하지 않았으며 자동 전환도 없다.
