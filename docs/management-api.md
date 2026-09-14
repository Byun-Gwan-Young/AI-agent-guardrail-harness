# 관리 API 목록 — S3-A 시점

| 메서드·경로 | 역할 | 구현 상태 |
|---|---|---|
| GET /sessions | 세션 목록 조회 | 계획, 미구현 |
| POST /sessions | 새 세션 명시적 시작, 기존 키 409 | 추가 구현 |
| POST /sessions/end | 세션 종료, status=ended 저장 | 추가 구현 |
| POST /sessions/observations | 작업 단위 관측 제출·진전도 계산 | 구현 |
| GET /stats | 절감 토큰·개입 횟수 조회 | 계획, 미구현 |
| PUT /policy | 임계값·모드 변경 | 계획, 미구현 |
| GET /healthz | uptime·활성 세션 수·업스트림 캐시·정책 버전 | 구현 (외부 호출 없음) |
| GET /log | 헤더로 지정한 세션 기록 조회 | 구현 |

POST /v1/chat/completions는 관리 API가 아닌 중계 API이며 자동 시작·복원을 지원한다.
POST /sessions 및 POST /sessions/end는 선택적 실행 관리용이다.

## 발표자료 23페이지와 비교
다운로드 폴더의 `9-15_팀발표_멀티에이전트_가드레일.html`과 `(1)`, `(2)` 사본을
확인했다. 세 파일의 관리 API 표기는 동일하다: POST /v1/chat/completions,
GET /sessions, GET /stats, PUT /policy, GET /healthz.
현재 구현에는 POST /sessions(선택적 시작), POST /sessions/end(명시적 종료)가 추가되었다.
기존 GET /sessions와 POST /sessions는 메서드와 역할이 다르다.
추가 설명: chat만으로 자동 시작되며, 재시작 후 active는 복원·경고, ended는 409다.
이번 구현은 관측 진전도 계산까지이며 차단·정책 판정은 미구현이다. 위 표의 계획 항목을
구현 완료로 발표하면 안 된다. 발표자료 자체는 수정하지 않았다.


S3-A 추가: POST /sessions/observations는 실행기 훅의 관측을 받으며 원문과 계산 결과를 저장한다. 동일 step_id의 동일 입력은 멱등적이며 상충 입력은 409다. persisted=false면 디스크 저장에 실패한 상태다. 현재 HTML의 24페이지는 일정표이고 관리 API는 23페이지다. 세부 결정은 decisions/003-progress-observations.md에 기록했다.

