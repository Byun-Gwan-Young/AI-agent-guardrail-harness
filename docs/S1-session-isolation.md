# S1 세션 격리 — 재시작 복원 보완

실행: `python -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --workers 1`.
기존 가상환경을 사용한다. GUARDRAIL_LOG_DIR 기본값은 실행 디렉터리의 logs/.

프레임워크는 시작 API 없이 chat만 보내도 자동 시작된다. 실험은 실행마다 새
X-Guardrail-Session 키를 사용한다. POST /sessions로 새 실행을 선언하고
POST /sessions/end로 종료할 수도 있다. 두 API는 선택 사항이다.

파일은 {session_id}.json이며 session_id, status(active/ended), turns를 저장한다.
활성 세션의 다음 턴은 이어 쓰고, 재시작 후 active 파일은 복원·경고 후 이어 쓴다.
ended 파일의 chat과 기존 키로 POST /sessions 호출은 409다.
POST /sessions/end와 GET /log도 재시작 후 파일을 읽을 수 있다.

헤더가 없으면 messages[0] 해시, 없으면 연결 단위 임시 키와 경고를 사용한다.
해시·연결 키는 독립 실행 경계를 보장하지 않는다. 종료 API 없이 active로 남는
세션을 finish_reason으로 자동 종료하지 않는다.

로그 생성·저장·읽기 장애는 경고 후 fail-open이다. 읽기 장애 시 기존 파일은 쓰지 않는다.
파일 손상·상태 불명확은 파일을 보존하고 409다. 저장 실패한 최신 턴/종료 상태는
재시작 때 복원되지 않을 수 있다. 파일 교체는 원자적으로 수행한다.
현재 단일 worker만 지원한다. 저장소 경계는 SessionRepository의 create/load/save이며
Redis 전환 시 분산 동시성·비동기 접근은 추가 구현이 필요하다.

최종 4xx/5xx도 요청당 한 턴으로 기록하고, 토큰 누락은 null, 실제 0은 0이다.
오류 응답 empty는 null로 정상 빈 응답과 구분한다.

검증: `python -m unittest discover -s tests -p test_session_isolation.py -v`.
외부 API 대신 MockTransport를 사용한다. S2~S4는 아직 수행하지 않았다.
상세 결정: decisions/002-session-lifecycle.md. API 목록: management-api.md.
