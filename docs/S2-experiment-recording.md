# S2 실험 조건 기록과 healthz

## 실행과 설정
기존 가상환경에서 `python -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --workers 1`.
추가 외부 패키지 설치 없이 기존 PyYAML을 사용한다.
설정 기본 경로는 proxy.py 옆 guardrail.yaml, GUARDRAIL_CONFIG로 변경 가능하다.
log.truncate=null은 절단 없음. 0 이상의 정수면 저장 텍스트의 최대 문자 수다.
업스트림 요청·클라이언트 응답은 절단하지 않는다.

## meta 계약
세션에 model, temperature, seed, max_tokens, scenario_id, run_index,
framework_version, started_at, ended_at, termination_reason을 저장한다.
model/temperature/max_tokens는 최초 chat 요청값이다. 누락 시 null이며
업스트림의 기본값을 추정하지 않는다. 각 턴의 request_params도 함께 저장한다.
중간에 조건이 달라지면 meta.conditions_mixed=true이며 최초 값을 유지한다.

시나리오 등 클라이언트만 알 수 있는 정보는 헤더로 받는다:
- X-Guardrail-Scenario → scenario_id
- X-Guardrail-Run-Index → run_index (1 이상의 정수)
- X-Guardrail-Framework-Version → framework_version (호출자가 보고한 값)

started_at은 세션 생성 시점 UTC, ended_at은 종료 API 호출 시점 UTC다.
POST /sessions/end 본문 {"termination_reason":"max_messages"}처럼 전달한다.
이유를 제공하지 않으면 null이며 실패 유형이나 종료 이유를 추정하지 않는다.
종료 API 반복 호출은 최초 시각·이유를 보존한다. 구 S1 로그에서 모르는 시각은 null이다.
종료 API를 쓰지 않은 세션은 active이며 ended_at/termination_reason은 null이다.

models.<model>.seed_supported가 false이면 seed=null, seed_status=unsupported,
seed_note에 미지원, requested_seed에는 원래 요청값을 보존한다. 해당 seed는 전송하지 않는다.
true일 때 seed는 요청값이다. 미등록/미확인 모델은 seed=null, unverified다.
미확인 상태에서는 원래 업스트림 요청은 그대로 전달하되 requested_seed로만 기록한다.
이번에는 외부 API 금지 조건에 따라 실제 모델 지원 여부를 확인하거나 설정하지 않았다.

## 시간과 재시도
모든 간격은 monotonic 시계로 측정하며 단위는 ms다.
- upstream_ms: 실패·성공을 포함한 모든 업스트림 시도의 소요 시간 합계
- retry_wait_ms: 재시도 대기에 실제 소모한 시간 합계
- total_ms: 세션 획득·조건 기록 이후부터 응답 분석 완료 시점까지의 처리 시간
- retry_delays_ms: 예정 대기 간격; retry_count: 실제 수행한 재시도 대기 횟수

total_ms에는 클라이언트 전송·세션 복원·최종 파일 저장 시간이 포함되지 않는다.
total_ms - retry_wait_ms는 재시도 대기를 제외한 처리 시간이다. 판정기가 없으므로
이 값을 판정 지연으로 간주하면 안 된다. 구 elapsed 값은 새 턴에 기록하지 않는다.
429 재시도는 최초 요청 외 최대 6회, 지수 증가와 equal jitter. 자세한 문서 오류는
discrepancies.md에 기록했다. 400/500 등 다른 상태 및 네트워크 오류는 여기서 재시도하지 않는다.

## 도구 호출
각 턴 tool_calls는 정상 JSON 응답의 모든 choices에서 반환한 tool_calls 개수 합계다.
구 function_call도 한 건으로 센다. 정상 응답에서 없으면 0, 오류/구조 미확인이면 null이다.
프레임워크가 실제 도구를 실행했는지와는 구별한다.

## GET /healthz
업스트림을 호출하지 않는다. 반환값:
- status: 로컬 활성 세션 수 집계 가능 시 ok, 집계 실패 시 degraded
- uptime: 프로세스 기동 후 초
- active_sessions: 디스크와 메모리를 합친 활성 세션 수; 집계 실패는 null
- upstream_reachable: 마지막 중계 시도에서 HTTP 응답 수신 시 true, 연결 실패 시 false,
  호출 이력이 없으면 null
- upstream_checked_at: 캐시 관측 시각 UTC, 미관측 null
- policy_version: 설정값, 정책 미구현인 기본 상태에서는 null

업스트림 HTTP 429/5xx도 도달 자체는 true다. 정상 서비스 여부나 최신 도달 가능성을
보장하지 않는다. 캐시 시각과 상태를 함께 검토해야 한다. healthz 자체는 HTTP 200을 반환하며
블루/그린 판단 시 본문을 읽어야 한다. 이 endpoint만으로 배포 준비 완료를 단정하지 않는다.

## 검증
`python -m unittest discover -s tests -p 'test_*.py' -v`
S1 회귀 16개 + healthz 1개 + S2 9개 = 26개. MockTransport와 가상 시계를 사용한다.
외부 API 호출·실측 세션 수집은 없다. S3/S4는 착수하지 않았다.
