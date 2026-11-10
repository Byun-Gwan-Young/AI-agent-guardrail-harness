# Storage (PostgreSQL + Redis)

멀티 AI 에이전트 가드레일 프로젝트의 PostgreSQL 영구 기록과 Redis 실행 상태 캐시를 담당하는 Storage 모듈입니다.

## 팀원용 로컬 개발 가이드 (Windows 11 + WSL2)

이 가이드는 **각 팀원의 로컬 PC**에서 개발용 PostgreSQL과 Redis를 따로 구동하는 방식입니다. 서버를 한 명이 항상 켜두거나 팀원끼리 서로의 `localhost`에 연결할 필요가 없습니다. 프록시/Backend 호출부는 아직 Redis 어댑터를 자동으로 사용하지 않으므로, 아래의 설치 성공이 전체 제품 연동 완료를 뜻하지는 않습니다.

### 1. 준비물과 Python 가상환경

- Windows 11, VS Code + PowerShell, Git, PostgreSQL(Windows 로컬), WSL2 Ubuntu(로컬 Redis용).
- Python 버전은 **전체 저장소의 실행 조건**과 맞추세요(루트 `README.md` 빠른 시작은 Python 3.14 사용). Windows Storage 테스트는 Python 3.13에서 확인했지만, 이것만으로 전체 실험 실행기의 Windows 호환성을 보장하지 않습니다.
- 현재 `requirements.txt`는 `psycopg[binary]==3.3.5`와 `redis==8.1.0`을 고정합니다. 팀원마다 임의로 재설치/업그레이드하지 마세요.

새로 clone한 팀원이 프로젝트 루트에서 처음 설정하는 예시입니다. 기존 가상환경이 있다면 새로 만들 필요는 없습니다.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
python -m pip list | Select-String 'psycopg|redis'
```

`venv/`는 `.gitignore`에 포함되어 있습니다. PowerShell에서 스크립트 실행이 차단되면 정책을 무조건 변경하지 말고 조직의 실행 정책에 맞는 터미널/활성화 방법을 사용하세요. **`pip check` 통과만으로 본체/바이너리 간 버전 일치가 보장되지는 않습니다.** 두 Psycopg 패키지가 모두 `3.3.5`인지 확인하세요. 버전 불일치가 있으면 다음 명령으로 재설치할 수 있습니다.

```powershell
python -m pip install 'psycopg[binary]==3.3.5'
```

### 2. 각자 PostgreSQL 설치 및 접속

Windows에 PostgreSQL 서버를 최초 한 번 설치한 뒤, 자신의 로컬 PostgreSQL 서비스를 실행합니다. PostgreSQL 자체는 Python 패키지 설치만으로 실행되지 않습니다. 프로젝트 루트의 `.env`(Git 추적 금지)에 각자 **자신의** 접속 정보를 넣습니다.

```env
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=guardrail_agent_v2
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_local_password_here
```

`GUARDRAIL_DB_URL`이 설정되어 있으면 `POSTGRES_*`보다 우선합니다. 뜻하지 않은 원격/운영 DB를 연결하지 않도록 **테스트 전에 항상 DB 이름을 확인**하세요. `.env`나 비밀번호, 연결 URL을 채팅·로그·커밋에 붙여 넣지 마세요.

```powershell
# 비밀번호를 출력하지 않고 현재 접속 DB만 조회
python -c "from storage.db import get_connection; c=get_connection(); print('DB:', c.execute('SELECT current_database()').fetchone()[0]); c.close()"
```

새 개발용 DB/스키마가 필요한 경우에만 다음 명령을 실행합니다. `init`은 DB가 없을 때 생성 시도하고 기존 스키마를 보강할 수 있으므로, **실제 서비스 DB에는 무심코 실행하지 않습니다.** 이미 DB가 준비된 팀원은 생략할 수 있습니다.

```powershell
python -m storage init
python -m storage projects
```

이 명령은 owner 없는 writable 사용자 프로젝트를 자동 생성하지 않습니다. 사용자 프로젝트는 인증된 Backend의 `storage.accounts.create_project` 흐름에서 만들어야 합니다.

### 3. Redis 최초 설치 (각 PC에서 한 번)

Windows PowerShell에서 `wsl --install -d Ubuntu`로 WSL2/Ubuntu를 준비할 수 있습니다(관리자 권한·재부팅이 필요할 수 있음). 이미 Ubuntu가 설치되어 있다면 건너뜁니다.

```powershell
wsl -d Ubuntu
```

**Ubuntu 터미널 안에서** 다음을 실행합니다.

```bash
sudo apt update
sudo apt install redis-server -y
sudo service redis-server start
redis-cli ping
```

`PONG`이 나오면 Ubuntu 쪽 Redis 서버가 응답한 것입니다. `Redis 7.0.15` 및 Windows Python `redis 8.1.0` 조합은 로컬 테스트에서 사용했으며, 두 버전은 서버/클라이언트라 번호가 달라도 됩니다.

### 4. Redis 실행·조회·종료 (Windows 11 + WSL2)

현재 Windows 개발 환경에서는 WSL2 Ubuntu의 `systemd`가 활성화되어 있고, `redis-server` 서비스가 `enabled` 상태입니다.

Redis 서버는 Ubuntu가 시작될 때 자동으로 실행됩니다. 다만 WSL 자체는 유휴 상태에서 종료될 수 있으므로, Windows Python에서 Redis를 계속 사용하려면 개발하는 동안 WSL을 실행 상태로 유지해야 합니다.

**개발 시작 — Windows PowerShell**

```powershell
Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", "Ubuntu", "--", "sleep", "infinity") -WindowStyle Hidden
```

이 명령어는 Ubuntu에서 백그라운드 대기 프로세스를 실행해 WSL을 유지합니다. 별도의 Ubuntu 터미널을 계속 열어둘 필요가 없습니다.

**Redis 상태 확인**

```powershell
wsl -l -v
wsl -d Ubuntu -- systemctl is-active redis-server
wsl -d Ubuntu -- redis-cli ping
```

정상 상태는 Ubuntu `Running`, Redis `active`, `PONG`입니다.

**Windows Python에서 실제 연결 확인**

가상환경을 활성화한 PowerShell에서 실행합니다.

```powershell
python -c "import redis; print(redis.Redis(host='127.0.0.1', port=6379).ping())"
```

정상 출력은 `True`입니다. Ubuntu 내부에서 `PONG`이 나오더라도 Windows Python 연결이 성공했는지 별도로 확인해야 합니다.

**개발 종료**

다른 Ubuntu 작업이 없을 때 다음 명령으로 종료할 수 있습니다.

```powershell
wsl --terminate Ubuntu
```

이 설정은 Windows 부팅 시 WSL 자체를 자동 실행하는 기능은 아닙니다. Windows를 다시 켜거나 WSL이 종료된 경우에는 개발 시작 명령어를 다시 실행해야 합니다.

본 개발 환경에서는 백그라운드 WSL 실행 후 Windows Python의 Redis `PING=True`까지 확인했습니다. 다른 팀원의 PC에서는 서비스 설정과 연결 상태를 각각 확인해야 합니다.


#### WSL 백그라운드 실행 시 주의사항

`Start-Process ... -WindowStyle Hidden`은 숨김 파일을 생성하거나 Windows 시작 프로그램을 등록하는 명령이 아닙니다. Ubuntu에서 `sleep infinity`라는 대기 프로세스를 실행하여 개발하는 동안 WSL을 유지하는 로컬 개발용 방법입니다.

- 개발 세션을 시작할 때 한 번만 실행합니다. 반복 실행하면 대기 프로세스가 중복될 수 있습니다.
- WSL이 실행되는 동안 메모리 등 시스템 자원을 사용합니다.
- Windows 재부팅 시 자동으로 다시 실행되지는 않습니다.
- Redis를 사용하지 않는 팀원에게 이 실행 방법은 필수가 아닙니다.
- 다른 Ubuntu 작업이 없을 때만 `wsl --terminate Ubuntu`로 종료합니다. 이 명령은 Redis뿐 아니라 해당 Ubuntu에서 실행 중인 다른 작업도 종료합니다.
- 대기 프로세스는 Redis 자체의 데이터 저장이나 백업 기능을 제공하지 않습니다.
- 이 방식은 Windows 11 + WSL2 로컬 개발 환경에서 검증한 편의 기능이며, 실제 서버 배포나 운영 환경에서는 별도의 서비스 관리 방식을 사용해야 합니다.

백그라운드 실행을 원하지 않으면 기존처럼 Ubuntu 터미널을 열어두고 사용할 수도 있습니다.

### 5. 자주 사용하는 Storage/Redis 검증 명령어

프로젝트 루트의 **가상환경이 활성화된 PowerShell** 기준입니다.

```powershell
# 프로젝트와 DB 상태 확인
python -m storage projects
python -m storage
python -m pip check
python -m pip list | Select-String 'psycopg|redis'

# PostgreSQL/Redis 저장 계층의 기본 단위·회귀 테스트
python -m unittest discover -s tests -p 'test_storage_*.py' -v
python -m unittest discover -s tests -p 'test_storage_redis_adapter.py' -v
python -m unittest discover -s tests -p 'test_storage_redis_b1_regression.py' -v  # 새 B1/I1 회귀 테스트

# Redis를 실행한 뒤, 실제 Redis 통합 테스트(개발용 localhost에만)
$env:GUARDRAIL_REDIS_TEST_URL='redis://127.0.0.1:6379/0'
python -m unittest discover -s tests -p 'test_storage_redis_integration.py' -v
python -m unittest discover -s tests -p 'test_storage_redis_recovery_integration.py' -v
python -m unittest discover -s tests -p 'test_storage_redis_b1_regression.py' -v  # 실제 Redis 경쟁 재현 포함
Remove-Item Env:GUARDRAIL_REDIS_TEST_URL
```

다음 테스트는 **자신의 개발용 PostgreSQL DB에 임시 테스트 데이터를 쓰는 opt-in 테스트**입니다. 실행 전 위의 DB 확인 명령으로 대상이 올바른지 검증하세요. 테스트는 생성한 임시 행만 정리하도록 설계됐지만, 예외로 정리가 남을 수 있으므로 운영 DB에서 실행하지 마세요.

```powershell
$env:GUARDRAIL_REDIS_TEST_URL='redis://127.0.0.1:6379/0'
$env:GUARDRAIL_REDIS_PG_TEST='1'
python -m unittest discover -s tests -p 'test_storage_redis_pg_integration.py' -v
Remove-Item Env:GUARDRAIL_REDIS_TEST_URL
Remove-Item Env:GUARDRAIL_REDIS_PG_TEST
```

일반 `test_storage_*.py` 회귀 실행 시 실제 PostgreSQL/Redis 테스트는 위의 opt-in 환경변수가 없으면 `skipped`가 나올 수 있습니다(실패가 아님). 기존 `test_storage_postgres_integration.py`는 별도 `GUARDRAIL_DB_URL` opt-in 계약을 따르므로, 해당 테스트를 의도적으로 실행할 때만 추가 설정하세요.

### 6. 문제 해결 체크리스트

| 현상 | 확인할 부분 |
|---|---|
| `WinError 10061` / Redis 연결 거부 | `wsl -l -v`로 Ubuntu 실행 상태 확인. WSL이 종료됐다면 4번 항목의 백그라운드 실행 명령 사용 후 Redis 상태와 Windows Python 연결 확인 |
| Ubuntu에서는 `PONG`, Windows에서는 연결 실패 | WSL이 계속 실행 중인지 확인하고, `Test-NetConnection 127.0.0.1 -Port 6379`로 Windows 연결 상태 점검 |
| PostgreSQL `TypeError: connect() takes no keyword arguments` | `psycopg`/`psycopg-binary` 버전 불일치 확인; 모두 3.3.5로 맞춰 재검증 |
| `pip check`는 성공인데 DB 연결 실패 | `pip check`는 모든 런타임/ABI 호환성을 검증하지 않음; 실제 DB 연결 테스트 필요 |
| `GUARDRAIL_DB_URL`이 예상과 다른 DB를 가리킴 | URL이 `POSTGRES_*`보다 우선. DB 이름만 출력하여 확인하고 환경 설정 수정 |
| Redis 조회값 `None` / 만료 | 캐시 miss는 세션 생성/종료 증거가 아님. Backend가 권한 확인 후 PostgreSQL authoritative 조회 경로 사용 |
| Windows에서 전체 실험 테스트 실패 | 다른 팀의 POSIX 의존 기능(`signal.getitimer` 등)일 수 있음. Storage 오류로 오인하지 말고 Linux/WSL/CI에서 재검증 |

## Redis 연동 상태와 운영 원칙

- `storage/redis_client.py`: 로컬 Redis 클라이언트. 환경변수 `GUARDRAIL_REDIS_URL`을 지정하지 않으면 `redis://127.0.0.1:6379/0` 사용.
- `storage/redis_state.py`: 현재 step/상태/선택 규칙 판정 등 **짧게 유지되는 구조화 캐시**. 원문 대화·요청·응답과 API 키는 저장하지 않음.
- `storage/redis_adapter.py`: **옵트인** PostgreSQL-first 연동. `storage.live` 함수의 성공 후 Redis를 최선으로 갱신; Redis 장애는 이미 성공한 PostgreSQL 쓰기 결과를 실패로 바꾸지 않음. 조회 시 miss/장애는 PostgreSQL에서 재구성.
- `RedisLiveStateStore(..., selected_rule_id='deadlock-v0.3', prefix='guardrail:dev-local:live:session')`처럼 **Backend/PM과 합의한 표시 규칙**과 환경별 namespace를 명시할 수 있음. 선택 규칙은 Redis 키의 `:rule:<rule_id>:` 구간으로 분리되어 서로 다른 표시 규칙의 판정이 섞이지 않습니다. 기존 버전의 rule 미분리 캐시는 새 선택 규칙 키에서 조회하지 않으며 TTL에 따라 자연 만료됩니다. 규칙을 지정하지 않은 기존 키 형식은 유지됩니다. 예시는 확정된 서비스 정책이 아닙니다.
- `get_state(session_id)`는 캐시가 살아 있으면 오래된 값을 반환할 수 있음. **차단·종료·권한 판정에는 사용 금지**. DB 기준의 강한 조회는 `get_authoritative_state(session_id)` 이용.
- Backend는 호출자의 세션/프로젝트 접근 권한을 검증해야 함. 어댑터는 인증/인가 미들웨어가 아니며, async 핸들러에서 동기 Redis/Psycopg 호출을 직접 하면 이벤트 루프를 막을 수 있으니 worker thread로 오프로딩해야 함.
- 현재 `proxy.py`는 JSON `session_store.py`로 대화/관찰 복구를 수행하며 `storage.live`/Redis 어댑터로 **자동 연결되지 않음**. Redis는 에이전트 프로세스, 대화 원문, 이전 STOP 이력, 모든 observation을 재현하지 않으므로 JSON 복구를 대체할 수 없음. 단일-worker 제약도 그대로 유지됨.
- **M1**: PostgreSQL은 `(session_id, step, rule_id)` 판정을 저장함. 어댑터는 선택된 규칙의 **현재 관찰 Step** 판정만 Redis 캐시에 표시하고, 늦은 판정은 과거로 되돌리지 않음.
- **M2 (보완)**: 캐시 miss 시 Redis `WATCH`를 건 뒤 PostgreSQL snapshot을 다시 읽고, 충돌(동시 갱신/키 소실) 시 snapshot을 폐기하고 DB부터 재조회합니다. 이는 지연된 복구가 최신 캐시를 덮어쓰는 경쟁 조건을 줄이기 위한 조치입니다. Redis는 여전히 표시용 캐시이므로 장애 중 발생한 DB 변경을 살아 있는 캐시에 자동 동기화하지는 않습니다. 종료·차단 근거에는 `get_authoritative_state()`를 사용하세요.
- 개발 서버 Redis 설정이나 임시 상태를 **팀원 간 공유하지 않음**. 실제 Backend가 어댑터를 호출하도록 전환하는 작업, selected rule/인가/async 경계 검토는 통합 팀과 합의 후 별도로 검증해야 함.

**기존 로컬 테스트 기록 (2026-10-29, B1 수정 전):** Redis 자체 오프라인 12개, 설치 스크립트 3개, 어댑터 오프라인 16개, 실제 Redis 통합 5개, Redis 복구 통합 3개, 실제 PostgreSQL+Redis 결합 통합 1개에서 모두 성공 결과를 확인했습니다. 이 기록은 **모듈 검증**이며 실제 Backend/Proxy 전체 E2E 검증을 뜻하지 않습니다. B1/I1 수정 후 로컬 재검증에서는 B1 전용 5/5, 실제 Redis 기본 5/5, Redis 복구 3/3, PostgreSQL+Redis 결합 1/1이 통과했습니다. Storage 전체 회귀 테스트는 139개 실행, 128개 통과, 11개 opt-in skip, 실패 0개입니다. 실제 Backend/Proxy E2E 연동은 아직 검증하지 않았습니다.

### 기존 캐시 키 전환 주의사항 (I1)

- 새 버전은 `selected_rule_id`를 지정하면 `<prefix>:rule:<rule_id>:<session_id>` 형태로 규칙별 캐시를 분리합니다. 반면 `selected_rule_id=None`은 이전 버전과 같은 `<prefix>:<session_id>` 키를 사용합니다.
- **이전 버전에서 같은 키에 저장한 선택 규칙의 STOP/CONTINUE 판정이 남아 있다면**, 새 규칙 미지정 모드가 그 값을 표시할 수 있습니다. 새 인스턴스만 새로 실행했다고 기존 키가 사라지는 것은 아닙니다.
- **Backend 연동 또는 표시 규칙 변경 전에** 실행 환경별로 새로운 `prefix`를 지정하세요. 예: `prefix='guardrail:dev-local:v2:live:session'`. 같은 실행 환경의 모든 인스턴스에서 동일한 신규 prefix와 표시 규칙 계약을 사용해야 합니다. 새 prefix는 기존 캐시를 읽지 않고, PostgreSQL 원본으로부터 다시 복구합니다.
- 기존 키의 제한적 정리는 소유한 애플리케이션의 명확한 키 범위를 확인한 경우에만 선택할 수 있습니다. **다른 팀원의 캐시를 지우거나 `FLUSHALL`/`FLUSHDB`를 실행하지 마세요.** Redis 조회값은 표시용일 뿐이며 종료·차단 판단에는 `get_authoritative_state()`를 사용해야 합니다.

## Backend 연동 계약 — 기본 Live 시나리오 자동 등록 (방식 B)

Storage 전용 등록 함수 `storage.default_live_scenario.ensure_default_live_scenario(project_id, *, user_id)`를 추가했습니다.
반환된 key/hash를 기존 `RedisLiveAdapter.start_live_session()`에 넘깁니다. Backend/Proxy 호출부 연결은 별도 작업입니다.

**설계 초안 정정:** 기본 정의는 `scenario-v2`가 아니라 **`storage-live-v1`**입니다.
`task_kind: live`는 실행용 ScenarioV2에서 유효하지 않으므로, 가짜 에이전트 정의 없이 Storage 메타데이터로 분리했습니다.
10개 테이블, `sessions.scenario_id NOT NULL`, 기존 live 함수와 raw/demo import 계약은 유지합니다.

- 활성 소유자·쓰기 가능한 프로젝트만 등록/조회할 수 있습니다. 인증된 user_id를 필수로 전달합니다.
- 동일 key/hash는 재사용하며 기존 정의가 다르면 오류입니다. 사용자 → 프로젝트 잠금과 UNIQUE + DO NOTHING으로 보호합니다.
- 새 YAML 버전은 새 행을 만듭니다. 기존 세션 재시도는 최초 key/hash를 재사용해야 합니다.
- 이 메타데이터를 실험 실행기에 전달하지 않습니다. 새로운 스키마명을 사용하는 Backend 분기와 표시 정책을 확인하세요.
- 자세한 반환값·오류·팀 인계·Windows 검증 명령은 [방식 B 구현 계약](DEFAULT_LIVE_SCENARIO.md)을 참고하세요.
## AI / 유지보수 인수인계 요약

이 절은 **다른 팀원이나 AI가 Storage 코드를 처음 읽을 때 가장 먼저 보는 계약 요약**입니다.
기존 코드를 "더 간단하게" 만들거나 다른 계층의 문제까지 한 번에 해결하려고 하기 전에 아래 목적과
경계를 먼저 확인합니다.

### 이 계층의 목적

Storage의 역할은 멀티에이전트 가드레일 실행에서 나온 **구조화된 사실과 판정 메타데이터를
PostgreSQL에 안전하고 재현 가능하게 저장하는 것**입니다.

```text
인증/프로젝트
users -> projects -> api_keys

실행 정의/기록
projects -> scenarios -> sessions
                         |- observations  (판정 입력)
                         |- judgements    (progress/criteria 계산 결과)
                         `- llm_calls     (토큰/지연/상태 메타데이터)
```

Storage는 판정 규칙 자체를 결정하지 않고, Proxy/Backend/UI의 동작을 대신 추측하지 않습니다.
판정기에서 계산된 값을 **의미를 바꾸지 않고 보존**하고, 계정/프로젝트 소유권과 쓰기 경계를 지키는
것이 목표입니다.

### 데이터가 들어오는 두 경로

1. **canonical demo import**
   - `runs/demo`의 커밋된 record를 읽어 시스템 소유 `데모` 프로젝트에 저장합니다.
   - 이 프로젝트는 `read_only=TRUE`이며 발표/재현용 exact mirror입니다.
   - source에 없는 observation/LLM call을 추측해서 만들지 않습니다.
   - `demo-all`은 모든 payload를 먼저 검증한 뒤 한 트랜잭션에서 교체합니다.

2. **raw/live write**
   - raw run은 writable 사용자 프로젝트에만 import합니다.
   - live write는 `storage/live.py`의 공개 함수 계약을 통해서만 저장합니다.
   - 종료와 child write의 race를 막기 위해 session row lock을 사용합니다.

### 절대 깨면 안 되는 불변조건

- **canonical schema는 `storage/schema.sql` 하나**입니다. 현재 10개 테이블이며 `steps` 테이블은 만들지 않습니다.
- `scenario_hash`는 파싱된 YAML 내용이 아니라 **실행에 사용된 `scenario.yaml` 원본 바이트의 SHA-256**입니다.
- `observations`는 판정 **입력**, `judgements`는 progress/criteria **계산 결과**입니다. 둘을 한 JSON에 중복 저장하지 않습니다.
- LLM/user 원문, reasoning 본문, request/response body, DB 비밀번호, Provider API key 원문은 PostgreSQL에 저장하지 않습니다.
- Guardrail API key 원문은 발급 시 한 번만 반환하고 DB에는 **SHA-256 hash + prefix**만 저장합니다.
- `projects.provider`는 의미 단위이고 `projects.upstream_url`은 실제 routing endpoint입니다. Provider credential은 둘 다에 넣지 않습니다.
- 시스템 `데모` 프로젝트는 사용자 소유 프로젝트와 분리하고 항상 read-only로 취급합니다. raw/live writer가 여기에 쓰면 안 됩니다.
- live judgement는 같은 step의 observation이 먼저 있어야 하며, exact retry는 idempotent하고 conflicting retry는 거부합니다.
- `observe` / `block`만 현재 구현된 mode입니다. `warn`은 실제 구현 전까지 schema/API 값으로 미리 넣지 않습니다.
- 기존 demo/criteria/frozen 파일의 테스트를 통과시키기 위해 Storage 범위를 넘어 판정기·시나리오·실험 코드를 임의 수정하지 않습니다.

### 인증 경계에서 자주 오해하는 점

`upsert_user_from_google(...)`는 **Google 토큰을 직접 검증하는 함수가 아닙니다.**
Backend/auth 계층이 Google 인증 결과를 검증한 뒤 `google_sub`, `email`, `name`을 넘기는 저장 함수입니다.
로그인 허용 여부도 Backend가 `is_email_allowed(email)`로 확인한 뒤 사용자 upsert 흐름을 진행해야 합니다.
즉 Storage는 OAuth UI/토큰 검증을 구현하지 않고, 검증된 identity와 감사 이벤트를 저장합니다.

### 감사 후 보강된 저장 경계

- canonical demo는 **115 sessions / 926 judgements / 15 scenario versions**가 모두 준비된 경우에만 bulk sync를 진행합니다. 일부 폴더가 빠진 입력은 DB를 열기 전에 거부합니다.
- demo `scenario.yaml`의 manifest hash는 현재 파일 바이트와 **정확히 일치**해야 하며, `runs/demo/*/scenario.yaml`은 `.gitattributes`에서 LF로 고정합니다.
- raw 재import는 기존 session의 `source`/scenario identity를 바꾸지 못합니다. 같은 session ID를 다른 프로젝트·scenario로 옮기는 입력은 거부합니다.
- live observation에는 judgement 결과(`progress`, `criteria` 등)를 넣을 수 없고, judgement의 agent/rule 중복 필드는 같은 step의 observation/result와 일치해야 합니다.
- API key 검증은 `revoked_at IS NULL` 조건부 갱신을 마지막 성공 기준으로 사용해 revoke와의 경쟁에서 폐기된 키를 성공으로 반환하지 않습니다.
- 기존 DB의 제약 보강처럼 데이터 정책이 필요한 변경은 일반 `init`에 파괴적으로 숨기지 않고 별도 migration/PM 합의 대상으로 둡니다.

### 현재 의도적인 한계

- `get_session_progress(session_id, after_step)`의 cursor는 step 단위라 **late judgement까지 무손실로 보장하는 event cursor가 아닙니다.**
- 일반 Live 기본 YAML·등록 함수는 구현됐습니다. 기본 정의는 `storage-live-v1`이며 Backend 호출부는 별도 연결해야 합니다. 명시적 실험과 기존 세션 재시도는 원래 identity를 사용합니다.
- 기존 `service/` demo API와 live 조회 API를 합칠지 분리할지는 Backend/Dashboard 계약입니다.
- OpenAI-compatible provider는 현재 구조로 routing할 수 있지만, 전혀 다른 wire protocol/provider는 Proxy adapter가 별도로 필요할 수 있습니다.
- Windows에서 기존 repository-wide POSIX 테스트가 실패한다고 해서 Storage가 다른 팀 소유 판정/실험 파일을 수정하지 않습니다. 전체 공식 runner는 POSIX/WSL/CI에서 최종 확인합니다.

### 다른 사람/AI가 수정할 때의 안전한 순서

1. 먼저 `storage/README.md`와 대상 함수의 공개 계약을 읽습니다.
2. schema 변경이면 `storage/schema.sql`을 canonical source로 수정하고 기존 데이터 삭제를 자동으로 넣지 않습니다.
3. 비밀/모델 원문을 새 컬럼이나 JSON에 저장하지 않는지 `storage/safety.py` 경계를 확인합니다.
4. demo와 live/raw 경로를 섞지 않고, read-only demo가 쓰기 대상으로 선택되지 않는지 확인합니다.
5. 변경 후 Storage/service 핵심 단위 테스트, 실제 PostgreSQL health check, `tools/final_freeze.py check`를 각각 확인합니다.
6. Proxy/Backend/Dashboard 의미까지 바뀌는 결정이면 코드에서 임의 확정하지 말고 아래 "최종 통합 시 확인할 팀 계약"에 handoff로 남깁니다.


## 핵심 구조

```text
users
 ├─ projects
 │   ├─ api_keys
 │   └─ scenarios
 │        └─ sessions
 │             ├─ observations
 │             ├─ judgements
 │             └─ llm_calls
 └─ auth_events
allowed_emails
```

- `users`: Google 로그인으로 확인된 사용자
- `allowed_emails`: 로그인 허용 이메일 allow-list
- `auth_events`: 로그인/키 발급·폐기 등 감사 이벤트
- `projects`: 서비스의 상위 작업 공간
- `api_keys`: 우리 Guardrail 서비스 키의 **hash**
- `scenarios`: 실행할 과제/실험 정의
- `sessions`: scenario를 실제로 한 번 실행한 기록
- `observations`: 판정기에 들어간 **입력**
- `judgements`: progress + criteria **계산 결과**
- `llm_calls`: 호출별 토큰/지연/상태 같은 **메타데이터**

`steps` 테이블은 만들지 않습니다.

## 가장 쉬운 사용법

프로젝트 루트의 VS Code 터미널에서 이것만 실행합니다.

```powershell
python -m storage
```

그러면 다음 메뉴가 나옵니다.

```text
1. DB/스키마 초기화 (pgAdmin 없이)
2. raw run 저장
3. demo 1개 저장
4. demo 전체 저장
5. 프로젝트 목록
6. 허용 이메일 목록
7. 허용 이메일 추가
8. 허용 이메일 삭제
0. 종료
```

긴 session UUID를 직접 복사하기 싫으면 **메뉴에서 번호로 선택**하면 됩니다.

> 이미 `guardrail_agent_v2`를 최종 구조로 만든 경우 1번 초기화를 다시 할 필요가 없습니다.

## pgAdmin 없이 초기 설정

새 환경에서는 VS Code에서 다음처럼 실행할 수 있습니다.

```powershell
python -m storage init
```

이 명령은 가능한 경우 다음을 자동으로 처리합니다.

1. 설정된 대상 DB가 없을 때만 DB 생성 시도
2. `schema.sql`의 통합 10개 테이블 생성/보강
3. 현재 프로젝트 목록 안내

`init`은 **owner 없는 writable 프로젝트를 자동 생성하지 않습니다.** 사용자 프로젝트는
Google 로그인/Backend의 인증된 흐름에서 `storage.accounts.create_project(owner_user_id, name, mode)`로
생성합니다. 따라서 새 서버에서 DB/schema 준비와 사용자 소유권 경계가 섞이지 않습니다.

## 시나리오는 수동 등록하지 않음

`import_run.py`와 `import_demo.py`가 `scenario.yaml`을 읽어 `scenarios`에 **자동 등록**합니다.

식별 기준은 다음입니다.

```text
project_id + scenario_key + scenario_hash
```

`scenario_hash`는 `scenario.yaml` 파일 바이트의 SHA-256입니다.
같은 `scenario_key`라도 YAML이 달라 hash가 다르면 별도 scenario로 저장됩니다.

구버전 `scenario_revision` 값이 YAML에 있으면 `config` JSONB 안에 그대로 남습니다.

## 짧은 명령도 사용 가능

메뉴 대신 명령어를 쓰고 싶다면 아래처럼 짧게 쓸 수 있습니다.

### raw run

```powershell
python -m storage run A-1-v2
```

`A-1-v2`로 시작하는 raw run이 딱 하나라면 긴 UUID를 생략할 수 있습니다.
여러 개가 매칭되면 더 길게 입력하라는 메시지가 나옵니다.

### demo 한 개

```powershell
python -m storage demo
```

폴더 목록을 검색하고 번호로 선택할 수 있습니다.

### demo 전체

```powershell
python -m storage demo-all
```

### 프로젝트 확인

```powershell
python -m storage projects
```

## 기존 상세 명령도 유지

필요하면 예전 방식도 그대로 쓸 수 있습니다.

```powershell
python -m storage.import_run A-1-v2-b51f67df2fb9402ba15fccb35c3db53e
python -m storage.import_demo DEMO-CL-normal-v1-108968e505cf4890ab930759f0cf67e5
python -m storage.import_demo --all
```

`.env`에 `POSTGRES_PROJECT_ID`가 없어도 **쓰기 가능한** projects가 정확히 1개면 raw importer가 자동 선택합니다. 읽기 전용 `데모` 프로젝트는 자동 선택하지 않습니다.

## raw run import

raw run에는 보통 다음 자료가 필요합니다.

- `summary.json`
- `session.json`
- `conditions.json`
- `scenario.yaml`
- `observations/*.ack.json`

저장 대상:

- scenarios
- sessions
- observations
- judgements
- llm_calls

같은 run을 다시 넣어도 `ON CONFLICT`로 기존 행을 갱신합니다.

### observations / judgements 구분

```text
observation_data
= 판정에 들어간 입력

result_data
= progress + criteria 계산 결과
```

따라서 `observation_data`에는 계산된 `progress`, `criteria`를 중복 저장하지 않습니다.

## demo import

GitHub demo record에는 원본 observation/개별 LLM call이 없을 수 있습니다.
없는 데이터를 억지로 만들지 않습니다.

Demo 저장 대상:

- scenarios
- sessions
- judgements

Demo에서 만들지 않는 대상:

- observations
- llm_calls

현재 검증한 최신 main 기준으로 `runs/demo`에는 record가 있는 실행 115개와 judgement 926개가 있었습니다.
`record/replay.json`의 step 수를 judgement 수로 사용하지 않습니다.

## 저장하지 않는 데이터

다음 원문은 일반 DB에 저장하지 않습니다.

- LLM 전체 request body
- LLM 전체 response body
- reasoning 본문
- 외부 Provider API Key 원문
- DB password

`reasoning_tokens` 같은 **숫자 사용량**은 저장할 수 있습니다.

## PostgreSQL 접속 설정 (2-6 계약)

접속 우선순위는 하나로 통일합니다.

```text
1. GUARDRAIL_DB_URL          서버/AWS 배포 우선
2. POSTGRES_*               기존 로컬 .env fallback
```

서버에서는 하나의 URL만 설정할 수 있습니다. Unix socket + peer 인증을 쓰면 DB 비밀번호가 필요하지 않습니다.

```env
# AWS/Linux 예시 (password 없음)
GUARDRAIL_DB_URL=postgresql:///guardrail_agent_v2?host=/var/run/postgresql
```

기존 Windows/local 개발 환경은 그대로 유지됩니다.

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=guardrail_agent_v2
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

`POSTGRES_PASSWORD`는 코드상 필수가 아닙니다. 로컬 PostgreSQL 인증 방식이 비밀번호를 요구할 때만 설정합니다.
`GUARDRAIL_DB_URL`과 `POSTGRES_*`가 동시에 있으면 **GUARDRAIL_DB_URL이 항상 우선**합니다.
DSN/비밀번호는 로그나 예외 메시지에 출력하지 않습니다.

쓰기 가능한 프로젝트가 하나뿐이면 `POSTGRES_PROJECT_ID`는 없어도 됩니다.
읽기 전용 `데모` 프로젝트만 있으면 raw importer는 의도적으로 자동 선택하지 않습니다.
쓰기 가능한 프로젝트가 여러 개면 `POSTGRES_PROJECT_ID`를 지정합니다. 이 값은 DB 접속 정보가 아니라 importer/CLI의 project 선택 편의 설정입니다.

실제 `.env`와 운영 `GUARDRAIL_DB_URL`은 GitHub에 올리지 않습니다.

## 파일

- `schema.sql`: **현재 통합 10개 테이블 구조**의 canonical 스키마
- `db.py`: PostgreSQL 연결/프로젝트 자동 선택
- `init_db.py`: pgAdmin 없이 DB/schema 준비 (ownerless writable project는 만들지 않음)
- `import_utils.py`: 공통 검증/변환 함수
- `import_run.py`: 실제 raw run 저장
- `import_demo.py`: GitHub demo record 저장
- `__main__.py`: `python -m storage` 메뉴/짧은 명령
- `postgres.env.example`: 환경변수 예시
- `requirements-storage.txt`: 필요한 Python 패키지

## Provider / upstream 역할

프로젝트에는 `provider`와 `upstream_url`을 둘 다 둡니다. 둘은 같은 정보가
아니라 역할이 다릅니다.

- `provider`: 사용자가 이해하고 선택하는 의미 단위 (`kmu`, `groq`, `openai`, `custom` 등)
- `upstream_url`: 프록시가 실제 요청을 보낼 resolved endpoint

일반 provider의 URL은 서버 설정/registry에서 결정하고, `custom`일 때만 명시적 URL을
받습니다. Provider API Key 원문은 Storage에 저장하지 않습니다. 이 분리는 사용자에게
URL 입력을 강요하지 않으면서 기존 프록시의 `upstream_url` 계약을 유지하기 위한 것입니다.

`custom` provider는 SSRF 위험 때문에 **기본 비활성화**입니다. 서버 운영자가
`GUARDRAIL_ALLOW_CUSTOM_PROVIDER=1`을 명시한 경우에만 사용할 수 있습니다. 활성화된
경우에도 URL의 literal IP와 DNS 해석 결과가 모두 public/global 주소여야 하며 loopback,
private, link-local, unspecified, multicast, reserved 주소는 거절합니다. 이 검사는 프로젝트
설정 시점의 admission check이므로, redirect 또는 DNS rebinding까지 막으려면 프록시/네트워크
계층에서도 요청 시점의 egress 제한을 유지해야 합니다.

`set_project_provider(...)`로 같은 프로젝트의 provider를 바꿀 수 있습니다. 이미 시작한
live session은 `session_data.provider`에 시작 당시 provider를 snapshot하므로, 나중에 프로젝트가
Groq -> KMU -> OpenAI로 바뀌어도 과거 session의 실행 맥락은 바뀌지 않습니다.

새 사용자 프로젝트 생성에는 서버 측 기본 provider 설정이 필요합니다. 일반 배포는 예를 들어:

```env
GUARDRAIL_DEFAULT_PROVIDER=kmu
GUARDRAIL_PROVIDER_KMU_URL=https://<school-gateway>/v1
```

`groq`/`openai`는 알려진 OpenAI-compatible base URL을 코드가 해석하고, `kmu`처럼 배포마다
endpoint가 다른 provider는 `GUARDRAIL_PROVIDER_<NAME>_URL`을 서버에서 설정합니다.
이 URL에는 API key/token/password 같은 credential query parameter를 넣을 수 없습니다. Provider key는
요청 시 비밀 채널/서버 설정으로 전달하고 PostgreSQL에는 저장하지 않습니다.

## Live session 저장 계약

`storage/live.py`는 서버 프록시가 실시간으로 호출하는 Storage 경계입니다.

- `start_live_session`: 새 session의 `mode`는 현재 `projects.mode`와 같아야 합니다.
- `add_observation` -> `add_judgement`: judgement는 같은 step의 observation이 먼저 있어야 합니다.
- `add_observation`, `add_judgement`, `add_llm_call`, `end_live_session`은 session 행을 잠가
  종료와 child write가 동시에 진행되는 race를 막습니다.
- 같은 값의 retry는 idempotent하고, 같은 키에 다른 값을 다시 쓰는 conflicting retry는 거부합니다.
- `decision`/`progress_state`와 `result_data` 안의 복사본이 서로 다르면 저장하지 않습니다.
- 모델 발언, reasoning 본문, request/response 원문, provider/Guardrail key는 저장하지 않습니다.
- `session_data.provider`에는 live session 시작 당시 provider 이름만 보존하고 credential은 보존하지 않습니다.

### `get_session_progress(after_step)` 주의사항

현재 PM 계약의 `after_step`은 **step 기반 호환 cursor**입니다. event ID 기반 cursor가 아니므로,
backend가 observation step N을 먼저 보고 cursor를 N으로 영구 이동한 뒤 judgement N이 늦게 commit되면
그 judgement를 놓칠 수 있습니다. Storage는 기존 함수 의미를 몰래 바꾸지 않고 이 제한을 명시합니다.
실시간 대시보드가 lossless incremental polling을 요구하면 backend/proxy와 함께 event/id cursor 또는
"step 완료 watermark" 계약을 추가해야 합니다. 이 항목은 최종 통합 검토 때 PM과 확인합니다.

## 최종 통합 시 확인할 팀 계약

아래 항목은 Proxy/Backend/Dashboard와 함께 구현·검증해야 합니다. **1번은 Storage 기본 등록이 구현됐지만 Backend 연결 전**이고, 나머지는 최종 통합 전에 PM과 세부 계약을 확인해야 합니다. 현재 Storage 구현은 기존 공개 함수 시그니처를 유지합니다.

1. **Live scenario identity 전달 경로 — 방식 B Backend 연결 필요**
   - `start_live_session(project_id, session_id, scenario_key, scenario_hash, ...)`는 정확한 scenario version을 요구합니다.
   - 명시적 시나리오가 있는 실험은 기존 key/hash를 유지합니다. 일반 Live 요청에는 프로젝트별 `live-default` 기본 YAML을 별도 Storage 함수로 원자적으로 등록/조회한 뒤 key/hash를 전달합니다.
   - Storage 전용 기본 YAML과 `ensure_default_live_scenario(project_id, user_id=...)`는 구현됐으며 Backend/Proxy 연결은 별도 작업입니다. `sessions.scenario_id NOT NULL` 제약과 기존 `storage.live` 호출 계약은 유지합니다.
   - 위 **「Backend 연동 계약 — 기본 Live 시나리오 자동 등록 (방식 B)」** 절에 구현 조건과 담당을 정리했습니다.

2. **Lossless live polling cursor**
   - 현재 `get_session_progress(session_id, after_step)`의 `after_step`은 호환성을 위한 **step cursor**입니다.
   - observation step N을 본 뒤 judgement N이 늦게 commit되는 경우, 단순히 cursor를 N으로 올리면 같은 step의 늦은 event를 놓칠 수 있습니다.
   - 대시보드가 무손실 증분 조회를 요구하면 event ID/cursor 또는 step-complete watermark를 Backend와 함께 도입해야 합니다.

3. **Demo 조회 API와 Live 조회 API의 경계**
   - 현재 `service/`의 established demo API는 `demo-record` 데이터를 기준으로 기존 발표 응답 계약을 보존합니다.
   - live session을 같은 API에 합칠지, live 전용 endpoint/stream을 둘지는 Dashboard/Backend 요구사항과 함께 결정해야 합니다.

### 현재 Storage가 의도적으로 확정한 불변조건

- 프로젝트 `mode`는 현재 구현된 `observe` / `block`만 허용합니다. `warn`은 roadmap이며 실제 구현 시 schema/API를 함께 변경합니다.
- `api_keys.key_prefix`는 새 Guardrail key에서 항상 생성되므로 `NOT NULL`입니다. 원문 key와 hash는 목록/API 응답에 노출하지 않습니다.
- `sessions.guardrail_mode`는 값이 있을 때 `observe` / `block`만 허용합니다.
- Provider 선택(`provider`)과 실제 routing endpoint(`upstream_url`)는 역할을 분리해서 유지합니다. Provider credential 원문은 PostgreSQL에 저장하지 않습니다.
