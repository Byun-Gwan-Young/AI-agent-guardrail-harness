# S3-A 진전도 관측 — 구현과 사용 계약

## 이번 구현
두 소스 계산기와 왕복 이력, 구조화/텍스트 추출 경로, 실행기용 산출물 훅,
POST /sessions/observations를 구현했다. 외부 API·실제 에이전트 실행은 하지 않았다.
S3-B 시나리오, S3-C 교착 기준, S3-D 실행 준비는 아직 수행하지 않았다.

## 모듈
- progress_schema.py: 입력 검증. 제안값은 단위가 포함된 키(예: timeout_ms)를 사용한다.
- progress_signal.py: 관측 이력만 받아 계산하는 순수 함수. 파일·모델 접근 없음.
- conversation_extract.py: B 규칙 추출 및 A와의 필드 비교.
- artifact_hook.py: 실행기 측 파일 해시·JUnit 결과 수집, 관측 조립·명시적 제출.
- observation_api.py: 순서·중복·LLM 턴 참조 검증과 저장.

## 로그 구조 예시
```json
{
  "step_id": 3,
  "llm_turns": [4, 5],
  "progress_source": "both",
  "progress_metric": {
    "conversation": ["proposal_value_delta", "open_issues_count", "new_info_ratio"],
    "artifact": ["test_pass_count", "files_changed", "build_status"]
  },
  "conversation": {
    "source_kind": "structured",
    "proposal_values": {"timeout_ms": 500},
    "open_issue_ids": ["issue-2"],
    "info_items": ["빈 문자열은 거부한다"]
  },
  "artifact": {
    "file_hashes": null,
    "files_scope_id": null,
    "test_pass_count": 8,
    "test_total_count": 10,
    "test_suite_id": "acceptance-v1",
    "build_status": "passed",
    "reasons": {"file_hashes": "수집 실패"}
  }
}
```
위 숫자는 스키마 설명 예시이며 실측값이 아니다. 계산 결과 progress는 서버가 붙인다.
입력에 progress를 넣으면 422다. 필수 관측에서 null은 변화 없음이 아니다.
source_kind는 conversation 내부에 있으며 관측 경로마다 기록된다.

## 지표와 상태
제안값은 키별 부호 있는 변화량을 보존한다. 서로 다른 단위를 임의로 합산하지 않는다.
키 집합이 달라지면 비교 범위 변경으로 표시한다. epsilon·단일 점수·이동평균·N턴
교착 판정은 S3-C에서 사전 정의할 항목이며 여기서는 적용하지 않는다.

현재 값이 직전 값과 다르고 같은 키의 과거 값과 같으면 oscillation이다.
닫힌 쟁점 ID가 다시 열리면 reopen, 파일이 과거 SHA-256으로 돌아오면 revert다.
파일 생성 후 삭제로 이전의 '없음' 상태로 돌아가는 것도 revert에 포함한다.
즉시 같은 값인 경우는 변화 없음이며 왕복으로 세지 않는다.
기준 상태는 원본 observations에 유지되어 재시작 후에도 동일하게 계산된다.

쟁점 개수가 같더라도 ID 교체는 변화다. info_items는 유니코드·공백·대소문자 정규화
후 누적 이력에 없는 항목의 비율이며 의미 동등성을 보장하는 모델은 아니다.
표현만 달라진 항목을 완벽히 구분하지 못한다는 한계가 있다.

테스트는 동일 test_suite_id와 전체 테스트 수일 때만 비교한다. 파일 비교는 동일
files_scope_id일 때만 한다. build_status의 미실행은 움직임으로 세지 않는다.
통과 수 감소·빌드 실패 전환은 regressed 이벤트로 남긴다. progress라는 상태는
현재 설계에서 관측 가능한 비왕복 변화이며 성공 방향 개선을 보장하는 이름이 아니다.
파일 변경과 테스트 정체가 함께 있으면 test_plateau를 붙이되 그것만으로 stagnant를 만들지 않는다.

모든 움직임이 왕복이고 필요한 관측이 완전하면 oscillating. 새 변화가 섞이면 progress.
관측이 완전하고 움직임이 없으면 stagnant. 누락은 unmeasured. 처음은 baseline.
source_kind가 바뀐 직후에는 A/B 값을 직접 비교하지 않는다. 선택 지표가 달라지면
unmeasured로 기록한다. 하나의 실험에서는 소스와 지표 선택을 고정해야 한다.

## 훅 사용
실행기는 작업·도구 실행이 끝난 뒤 capture_artifact를 호출한다. 고정된 작업 폴더와
명시적 상대 파일 목록만 읽는다. 같은 파일의 반복 수정도 내용 해시로 감지한다.
파일이 새로 생길 가능성이 있는 경로도 목록에 포함한다. 목록/작업 루트가 바뀌면
scope가 달라져 이전 관측과 직접 비교하지 않는다. 디렉터리 자동 순회는 하지 않는다.

테스트 실행 자체는 실행기의 책임이다. 해당 작업에서 갓 생성한 JUnit XML 경로와
고정 테스트 정의·설정에 대응하는 test_suite_id를 전달한다. 파일 수정으로 테스트가
변경되면 suite ID도 변경해야 한다. 이전 실행의 오래된 XML을 재사용하면 안 된다.
훅은 테스트 명령을 실행하지 않으며 XML의 failure/error/skipped는 통과로 세지 않는다.
빌드 상태도 실행기가 실제 명령 결과를 전달하고, 실행하지 않았다면 null/not_run이다.

make_observation은 structured 입력이 있으면 A와 B를 함께 보존하고, 없으면 B만 쓴다.
submit_observation은 호출자가 제공한 로컬 프록시 클라이언트로 명시적으로 제출한다.
실행기는 실패 또는 persisted=false를 확인하고 같은 step_id/내용으로 재시도해야 한다.
상충하는 재전송은 409이며 이미 기록된 관측을 수정하지 않는다.

## 운영용 B 범위
현재 규칙은 timeout/타임아웃 + ms, RAM/메모리 + GB, budget/예산 + 달러,
issue-ID + open/closed/resolved/reopened 등의 명시 표현, new info:/새 정보:를 지원한다.
단순 문장이나 문맥 추론이 필요한 발화는 미추출(null)과 이유를 남긴다.
서로 다른 제안값이 같은 발화에 있으면 하나를 임의 선택하지 않는다.
쟁점 목록은 '텍스트에서 관측한 ID' 범위이며 실제 전체 쟁점의 완전성은 보장하지 않는다.
운영 추출기는 응답 원문을 절단 전에 읽고, 실패해도 업스트림 응답을 전달한다.
프록시는 턴별 B 값을 기록한다. 산출물 작업 단위로 합치는 동작은 실행기/수집기가 담당한다.

A와 B 비교는 proposal_values/open_issue_ids/info_items의 필드 일치를 기록한다.
A가 null인 필드는 평가 불가다. 에이전트가 스스로 출력한 A의 사실성은 별도 확인이 필요하다.
학습·대규모 정확도 집계나 경량 모델 훈련은 수행하지 않았다.

## 검증
`python -m unittest discover -s tests -p 'test_*.py' -v`
S1/S2 기존 26개 + S3-A 31개, 총 57개 통과.
필수 세 왕복 사례는 oscillating, 두 오탐 방지 사례는 progress로 확인했다.
같은 파일 재수정·생성/삭제 복귀, 테스트 묶음 변경, 누락, 재시작, 중복 제출,
저장 실패 후 재시도, 추출 실패 fail-open, A→B 정답 유출 방지도 검증했다.

## 발표자료 차이
현재 다운로드 폴더 HTML의 관리 API는 23페이지다. 24페이지는 일정표다.
추가할 항목은 POST /sessions/observations이며, 기존 시작·종료 POST도 원본 표에 없다.
산출물 진전도에는 실행기 훅이 필요하다는 설명도 함께 추가해야 한다.
관리 API 목록과 결정 문서를 갱신했으며 발표 HTML은 수정하지 않았다.

## P0-1 관측 스키마 확장 — 역할 식별

관측 최상위에 `agent_id: str | null`을 추가한다. 값은 실행기가 선택한
`agents[index].name`이며 실패 step에도 전달한다. 모델의 AgentOutput·strict JSON
스키마·출력 검증·프롬프트에는 agent_id를 추가하지 않는다. 원문 대화나 모델의
자기보고에서 역할 ID를 가져오지 않는다. 빈 문자열은 허용하지 않는다.

기존 관측 입력/파일의 호환성을 위해 필드는 선택적이다. progress-v1은 이 필드를
사용하지 않는다. progress-v2는 역할 식별이 없으면 unmeasured로 남기고 전역
비교로 대체하지 않는다. 같은 step의 역할 ID를 바꾼 재전송은 기존 충돌 검사로
거부한다. 상세 기준과 이력 의미는 decisions/004-role-scoped-progress.md에 기록한다.
