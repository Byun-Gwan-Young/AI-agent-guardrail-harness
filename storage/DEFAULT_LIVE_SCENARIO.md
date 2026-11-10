# 방식 B — 프로젝트별 기본 Live 시나리오

## 구현 상태와 설계 충돌 해결

Storage 함수·전용 YAML·테스트를 추가했다. Backend의 Live 시작 endpoint와
Proxy 이벤트 연결은 이 패치에 포함하지 않았다. 기존 `sessions.scenario_id NOT NULL`,
10개 테이블, `storage.live` 공개 함수, 실험용 `scenario_schema.py`는 변경하지 않는다.

`ScenarioV2.task_kind`는 `artifact`/`dialogue`만 허용하고 실행용 필수 필드가 있다.
따라서 이전 2026-11-04 설계 초안의 `scenario-v2` + `task_kind: live` 조합은 사용하지 않는다.
새 정의는 **Storage 전용 `storage-live-v1`**이다. 에이전트 실행 계획이 아니라
일반 Live 세션의 FK 연결용 메타데이터다. `ScenarioV2` 검증을 통과했다고 주장하지 않는다.
기존 DB는 schema_version/task_kind를 문자열로 저장하므로 migration은 필요 없다.

| 필드 | 값 |
|---|---|
| `scenario_key` | `live-default` |
| `schema_version` | `storage-live-v1` |
| `name` | `Default Live Session` |
| `task_kind` | `live` |
| `config.purpose` | `session-linkage` |
| `config.definition_version` | 양의 정수, 최초 1 |
| `scenario_hash` | 기본 YAML 원본 바이트 SHA-256 |

기본 파일: `storage/fixtures/default_live_scenario_v1.yaml`.
Storage 전용 검증기는 정확한 필드만 허용하고 중복 YAML 키·알 수 없는 스키마·
원문/비밀 필드·잘못된 타입을 거부한다. 요청에서 YAML 경로나 config를 받지 않는다.
파일명 v1은 최초 fixture 이름이며 정의를 갱신하면 raw hash가 새 버전을 구분한다.

이 파일과 `scenarios.config`를 실험 실행기에 전달하지 않는다. 기존
`scenario_schema.load_scenario()`는 `storage-live-v1`을 지원하지 않아 정상적인
스키마 검증 경로에서는 거부된다(제공된 코드의 버전 분기 기준).
실제 Backend/runner 호출부 전체는 제공되지 않았으므로 직접 dict를 실행기에 넘기는
우회 경로가 없는지는 통합 담당자가 확인해야 한다. 실험을 실행하려면 실제 검증된
`scenario-v2` 정의를 별도로 전달한다. raw/demo importer도 기존 `scenario-v2` 계약을 유지한다.

## 공개 함수와 반환 계약

```python
from storage.default_live_scenario import ensure_default_live_scenario

identity = ensure_default_live_scenario(project_id, user_id=authenticated_user_id)
# {
#   "scenario_id": 123,                # DB scenarios.id (정수)
#   "scenario_key": "live-default",    # YAML scenario_id와 같은 문자열 식별자
#   "scenario_hash": "<SHA-256 64자리>",
#   "schema_version": "storage-live-v1",
# }
```

제안된 project_id 단독 형태보다 한 가지 인자가 추가됐다. 인증 자체는 Backend 책임이지만,
Storage가 소유권을 재검사할 수 있도록 **인증 결과의 user_id를 필수 keyword 인자**로 받는다.
클라이언트가 요청 본문에 적은 user_id를 신뢰해서 넘기면 안 된다.
API key 경로라면 검증된 키에 연결된 프로젝트/소유자를 사용하고 요청 프로젝트와의 일치도 확인한다.
owner 없는 legacy/system 프로젝트는 자동 등록 대상에서 제외한다. 기존 명시적 live 경로의
owner 없는 프로젝트 호환 정책은 그대로 유지한다.

| 상황 | 결과 |
|---|---|
| 활성 소유자 + writable 프로젝트 | 현재 fixture 버전 등록 또는 기존 행 반환 |
| 같은 버전 재요청 | 같은 scenario_id; 기존 행 UPDATE 없음 |
| 다른 프로젝트 | 별도 행 |
| 파일 바이트 변경 | 새 hash/새 행; 과거 행·session 참조 유지 |
| 같은 key/hash에 다른 정의 | `ValueError`; 기존 행 변경 없음 |
| 다른 소유자/없는/read-only/ownerless 프로젝트 | `LookupError` (동일 메시지) |
| 없는 사용자 | `LookupError` |
| pending 계정 | `RuntimeError`, 기존 기본 행이 있어도 거부 |
| ID 타입·fixture 오류 | `ValueError` (파일 I/O 오류는 별도 전파) |
| DB 오류 | Psycopg 예외 전파; transaction rollback |

Backend는 오류 원문을 HTTP 응답에 그대로 노출하지 않는다. 프로젝트 접근 실패는 404/403,
pending 계정은 복구가 필요하다는 응답, 잘못된 서버 fixture·정의 충돌은 서버 설정/무결성
오류로 구분한다. fixture의 ValueError를 무조건 사용자 요청 422로 매핑하지 않는다.

## 트랜잭션·동시성

같은 `get_connection()` transaction에서 사용자 `FOR SHARE` → 소유 프로젝트
`FOR SHARE` → 시나리오 INSERT/조회 순서다. 프로젝트 조회는 잠금 획득 후 실제 owner와
read_only 조건을 확인한다. 계정 탈퇴·purge가 먼저 사용자 잠금을 잡으면 기다린 뒤
pending/없음을 확인해 거부한다. 등록이 먼저 잡으면 탈퇴가 등록 commit까지 기다린다.

동시 생성은 기존 UNIQUE(project_id, scenario_key, scenario_hash)와
`ON CONFLICT DO NOTHING`을 사용한다. 그 뒤 별도 SELECT로 승리한 행을 읽고 모든 정의를
비교한다(기존 기본 READ COMMITTED 연결 계약). 기존 행을 DO UPDATE하지 않는다.
DB 오류는 transaction 전체를 rollback한다. 높은 격리 수준에서 serialization 오류가
발생하면 호출자가 전체 등록 연산을 재시도한다. 원본 정의를 수정해서 재시도하지 않는다.

등록과 세션 시작은 **서로 다른 transaction**이다. 등록 직후 탈퇴하면 기존
`start_live_session()`이 신규 세션을 차단한다. 이때 사용되지 않은 유효한 scenario 행은
남을 수 있으며 불완전한 세션 데이터가 아니다. 나중에 계정 purge가 기존 소유 관계를
따라 함께 삭제한다. 새로운 테이블이나 분산 transaction은 추가하지 않는다.

## Backend 인수인계 — 실제 연결 순서

1. 로그인/API key를 검증하고 프로젝트 접근 권한과 소유자를 확정한다.
2. 명시적 scenario_key/hash가 둘 다 있으면 기존 경로로 처리한다.
   둘 중 하나만 있거나 명시된 시나리오가 잘못됐으면 거부한다. 기본 정의로 자동 우회하지 않는다.
3. 둘 다 없는 **새 일반 Live 요청**에서만 ensure 함수를 호출한다.
4. 반환된 key/hash를 기존 `RedisLiveAdapter.start_live_session()`에 전달한다.
5. 실제 observation/judgement/LLM-call 이벤트마다 기존 어댑터 함수를 호출한다.
6. 종료 시 `end_live_session()`을 호출한다.

```python
# 아래 코드는 인증된 신규 일반 Live 요청의 호출 예시다. endpoint 구현은 아니다.
identity = ensure_default_live_scenario(project_id, user_id=user["id"])
result = adapter.start_live_session(
    project_id, session_id, identity["scenario_key"], identity["scenario_hash"],
    mode, model, execution_config,
)
```

mode는 프로젝트 설정과 일치해야 한다. 사용자 프롬프트·API key 등은 execution_config에 넣지 않는다.
어댑터가 PostgreSQL 쓰기도 하므로 `live.start_live_session()`과 어댑터를 둘 다 호출하지 않는다.
async Backend에서는 등록 함수와 어댑터의 동기 I/O를 worker thread로 실행한다.

**재시도 주의:** 기존 session_id의 재시도는 최초의 scenario key/hash, mode/model/config를 재사용한다.
매번 ensure로 최신 fixture를 다시 선택하면 배포 중 YAML 버전 변경으로 다른 scenario가 선택될 수 있다.
또한 ensure는 pending 계정을 거부하므로, 기존 세션의 exact retry 허용 정책을 구현할 때 먼저
기존 세션·소유권을 확인하고 최초 identity로 기존 start 함수를 호출한다. 기존 세션을 새 버전으로
옮기지 않는다. 이 분기는 Backend가 연결해야 하며 이번 패치가 endpoint에 자동 삽입하지 않는다.

Redis는 기존 PostgreSQL-first 계약을 따른다. 장애가 DB 저장 성공을 취소하지 않으며,
캐시가 살아 있으면 과거 상태일 수 있다. 종료/차단/권한 판단은 PostgreSQL 기준이다.
환경/규칙별 namespace와 기존 캐시 전환 정책은 기존 README를 따른다. JSON session_store는 별개다.

## YAML 바이트·Windows 줄바꿈

`storage/fixtures/.gitattributes`는 이 새 YAML에만 `text eol=lf`를 지정한다.
기존 실험/demo YAML이나 루트 attributes는 변경하지 않는다. 파싱 후 재직렬화한 해시는 쓰지 않는다.
파일을 한 번 읽은 동일 바이트로 파싱·해시를 계산한다. CRLF 입력은 오류로 거부하므로
에디터에서 UTF-8/LF로 저장한다. Git 설정이나 에디터가 LF 정책을 덮는 경우도 확인한다.
주석/공백 변경도 hash를 바꾸므로 버전 변경으로 취급한다.

```powershell
git check-attr text eol -- storage/fixtures/default_live_scenario_v1.yaml
python -c "import hashlib,pathlib; p=pathlib.Path('storage/fixtures/default_live_scenario_v1.yaml'); b=p.read_bytes(); print('CRLF:', b'\r' in b); print(hashlib.sha256(b).hexdigest())"
```

## 검증 명령

```powershell
python -m unittest discover -s tests -p 'test_storage_default_live_scenario.py' -v
python -m unittest discover -s tests -p 'test_storage_live*.py' -v
python -m unittest discover -s tests -p 'test_storage_redis_adapter.py' -v
python -m unittest discover -s tests -p 'test_storage*.py' -v
```

실제 DB 테스트는 일반 GUARDRAIL_DB_URL/POSTGRES_* 설정을 사용하지 않고 **별도 opt-in URL**만 사용한다.
운영 DB나 guardrail_agent_v2 실데이터 대신 폐기 가능한 별도 테스트 DB를 준비한다.
테스트는 그 안에 임의 이름의 schema를 만들고 해당 schema만 DROP CASCADE로 정리한다.
schema 생성 권한이 필요하며 예기치 않은 프로세스 종료 시 임시 schema가 남을 수 있다.

```powershell
$env:GUARDRAIL_WAYB_TEST='1'
$env:GUARDRAIL_WAYB_TEST_DB_URL='postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/guardrail_wayb_test'
# 선택: 새 기본 identity를 실제 Redis 어댑터까지 연결하는 테스트
$env:GUARDRAIL_REDIS_TEST_URL='redis://127.0.0.1:6379/0'
python -m unittest discover -s tests -p 'test_storage_default_live_scenario_integration.py' -v
Remove-Item Env:GUARDRAIL_WAYB_TEST
Remove-Item Env:GUARDRAIL_WAYB_TEST_DB_URL
Remove-Item Env:GUARDRAIL_REDIS_TEST_URL -ErrorAction SilentlyContinue
```

URL의 예시 자격증명은 각자의 테스트 DB 값으로 교체하되 커밋/공유하지 않는다.
실제 DB 없는 실행의 skipped는 성공한 통합 검증이 아니다. 이 패치 생성 환경의 결과와
미검증 범위는 동봉한 `REPORT_KO.md`를 참고한다.
