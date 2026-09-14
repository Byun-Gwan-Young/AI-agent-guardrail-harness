# scenario-v1 스키마 — S3-B 첫 검토

실제 파일은 scenarios/*.yaml, 기계 스키마는 scenarios/scenario.schema.json이다.
scenario_schema.load_scenario는 Pydantic 검증만 수행하며 에이전트·명령을 실행하지 않는다.

| 필드 | 의미 |
|---|---|
| schema_version / scenario_id / group / title | 정의 버전·고유 ID·A/B/C군·이름 |
| model / agents / task | 모델 식별자, 역할별 시스템 메시지·권한 선언, 공동 과제 |
| termination | 성공 또는 max_steps 종료, step당 모델 호출 상한, 관측 경보는 observe_only |
| seed / seed_support / temperature / max_tokens | 실험 요청 조건. 미지원·미확인 seed는 null |
| progress_source / progress_metric | conversation/artifact/both와 사용할 S3-A 지표 목록 |
| conversation_collection | 구조화 A+B 동시 보관 또는 운영 추출 B |
| expected_outcome | 설계 기대값. 실제 성공 판정이나 detector 입력으로 사용하지 않음 |
| success_criteria | 공개 인수 테스트 또는 구조화 제약의 기계 판정 기준 |
| termination_context_collection | 선언 역할·구조화 필드·근거·누락 처리 |
| criteria_version | S3-C에서 고정한 deadlock-v0.1 |
| fixture_dir / monitored_paths / initial_issue_ids | 작업 시작 코드·고정 파일 관측 범위·공유 쟁점 초기 ID |
| token_estimate | 예상 호출 수와 입출력 가정. assumed=true 필수 |

## 그룹별 검증
A는 both + 테스트 기반 success_criteria + fixture_dir가 필수다.
B는 conversation이며 작업 산출물 fixture가 없다. 성공은 JSON 제약/평가기 등으로 검증한다.
C는 과제에 따라 소스를 선택한다. 아직 A-1 외의 시나리오는 만들지 않았다.

## step, 모델 요청, 종료
step은 에이전트 한 번의 작업 활성화와 그 작업의 도구 실행까지다. 한 step에 모델
요청이 여러 개 있을 수 있어 max_llm_calls_per_step을 따로 둔다. 재시도는 새 step이 아니다.
S3-C 경보로 실험을 강제 종료하지 않는다. 종료는 기계 성공 + 리뷰어의 완료 선언,
또는 max_steps/호출 상한에 따른 실행기 종료다. 상한 종료를 자동으로 교착 정답으로 만들지 않는다.

실험용 에이전트 출력은 scenarios/agent-output.schema.json을 따른다.
narrative는 발화, state는 구조화 관측이며 운영 추출기 B에는 narrative만 전달한다.
state의 누락/모름은 null이다. 빈 목록은 실제로 쟁점·새 정보가 없다고 보고한 경우다.

리뷰어의 completion_declared=true가 최초 관측된 step을 선언 위치로 고정한다.
선언 전에 정상 형식의 관측과 공유 상태가 확인되면 none, 필수 출력이 깨지면 unknown이다.
선언 후에는 같은 declared_step을 계속 전달한다. 테스트 실패인데 완료를 주장해도
그 선언 사실은 남기며 기계 성공과 혼동하지 않는다. 실행기는 해당 주장을 성공으로 받아들이지 않는다.
그 뒤의 반복은 S3-C의 grace/termination_failure 기준으로 관측한다.

## 테스트 묶음과 성공
suite_identity.compute_test_suite_id는 테스트 디렉터리의 모든 파일, 공개 인수 조건,
검사 도구, 실행 명령을 SHA-256으로 식별한다. pycache/pyc는 제외한다.
구현 파일은 제외하므로 정상 수정 때 ID가 유지된다. 테스트 추가·수정·삭제 또는 조건/
검사 도구 변경은 새 ID가 되어 비교 불가이며 성공 판정도 거부한다.
S3-A에 보고하는 ID는 매 관측 시 실제 파일로 다시 계산한 값이어야 한다.
YAML에 고정된 원본 ID를 수정된 테스트에 그대로 붙이면 안 된다.

원본 시나리오 YAML·기준 파일은 에이전트 작업 폴더 밖에서 보존하고, 매 실행은 fixture를
새 폴더로 복사해야 한다. 권한 목록은 실행기가 구현할 역할 권한 계약이며 현재 OS 샌드박스 구현은 아니다.
검사 도구는 JUnit XML과 JSON 결과를 만든다. scenario_checks.check_acceptance는
원본 suite ID 일치와 기대 테스트 전체 통과를 함께 확인한다.

## 토큰 추정
예상 입출력 = 예상 모델 요청 수 × (가정한 평균 입력 + max_tokens × 평균 출력 비율).
max_tokens는 출력 제한이며 입력 누적·재시도까지 포함한 총 토큰 상한이 아니다.
token_estimate()가 계산하며 실측값으로 기록하지 않는다.
시나리오·인수 테스트를 변경하면 scenario/schema/test_suite 식별을 함께 검토한다.
S3-C criteria_version과 N은 이 작업에서 변경하지 않는다.

## 이번 범위
스키마와 A-1의 시작 코드·공개 테스트·로컬 검사 도구만 구현했다.
AutoGen 실행기, 실험 실행, A-2~C-11 작성은 하지 않았다. 다음 검토 승인 후 진행한다.
