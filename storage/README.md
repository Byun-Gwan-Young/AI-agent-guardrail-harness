# Storage (PostgreSQL)

멀티 AI 에이전트 가드레일 프로젝트의 PostgreSQL 저장 모듈입니다.

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

### 현재 의도적인 한계

- `get_session_progress(session_id, after_step)`의 cursor는 step 단위라 **late judgement까지 무손실로 보장하는 event cursor가 아닙니다.**
- 일반 live 요청에서 `scenario_key` / `scenario_hash`를 어떻게 확보할지는 Proxy/Backend와의 팀 계약이 필요합니다.
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
python -m storage run A-1-v4
```

`A-1-v4`로 시작하는 raw run이 딱 하나라면 긴 UUID를 생략할 수 있습니다.
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
python -m storage.import_run A-1-v4-e174aafe805b4f59bb62d7c95716b8b7
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

아래 항목은 Storage 내부에서 임의로 결정하면 Proxy/Backend/Dashboard와 계약이 어긋날 수 있어
**최종 통합 전에 PM과 함께 결정해야 합니다.** 현재 Storage 구현은 기존 함수 시그니처를 유지하며
이 결정을 강제로 추측하지 않습니다.

1. **Live scenario identity 전달 경로**
   - `start_live_session(project_id, session_id, scenario_key, scenario_hash, ...)`는 정확한 scenario version을 요구합니다.
   - 실제 Proxy/Backend가 `scenario_key`와 `scenario_hash`를 어떤 요청/세션 메타데이터에서 얻어 Storage에 넘길지 확정해야 합니다.
   - 이 값이 없는 일반 live 요청을 지원하려면 `scenario_id` nullable 여부를 포함해 별도 계약 변경이 필요합니다.

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

## 루트 README 에서 옮긴 절

아래 두 절은 루트 `README.md` 에 있던 내용을 그대로 옮긴 것입니다 (C-19-7, DM-97 ④).

### DB 통합 변경 범위 (2026-10-08 원본 대비)

이번 `db-unify` 작업은 Storage/PostgreSQL 통합에 필요한 범위만 수정했습니다. 2026-10-08 원본과 비교했을 때 **기존 파일의 의미 있는 변경은 아래 7개**이며, 프록시·실행기·판정기·시나리오 핵심 로직은 기능적으로 수정하지 않았습니다.

| 파일 | 변경 이유 |
|---|---|
| `README.md` | `storage/` 통합 계층, 기여자, 현재 서비스 진행 상태와 Windows/POSIX 개발 환경 주의사항을 문서화 |
| `service/README.md` | `service/`가 PostgreSQL 스키마/적재를 소유하지 않고 unified Storage를 읽는 read-only API라는 책임 경계를 명확화 |
| `service/load_demo.py` | 통합 후 이중 writer를 막기 위해 PostgreSQL `schema`/`load` 쓰기 명령을 퇴역시키고 `storage init` / `storage demo-all`로 안내 |
| `service/queries.py` | 기존 데모 API 응답 모양과 발표 지표를 유지하면서 unified 10-table Storage schema에서 같은 값을 읽도록 조회 계층을 변환 |
| `service/schema.sql` | 실제 PostgreSQL canonical schema가 아니라 기존 service API 오프라인/SQLite 계약 테스트용 legacy fixture임을 명시 |
| `service/store.py` | service의 PostgreSQL 쓰기를 방어적으로 차단하고 unified DB read-only 조회 및 TIMESTAMPTZ UTC 직렬화를 지원 |
| `service/test_live_db.py` | 옛 service 전용 4-table DB 검사가 아니라 unified PostgreSQL의 demo-record/read-only API 계약을 검사하도록 갱신 |

새로운 Storage 구현은 `storage/`와 관련 테스트 파일로 추가되었습니다. 다른 팀 소유 영역의 수정이 필요해 보이는 문제는 기능 코드를 임의로 바꾸지 않고 README의 한계/인수인계 항목으로 남깁니다.


### Windows 개발 환경 주의

#### 바이트 해시와 줄바꿈 재현성

`scenario_hash`처럼 **파일 원본 바이트의 SHA-256**을 사용하는 값은 YAML 의미가 같아도 줄바꿈이 `LF`에서 `CRLF`로 바뀌면 달라집니다. 따라서 Windows에서 `git clone`할 때 Git의 `core.autocrlf` 설정 등에 의해 줄바꿈이 변환되면 YAML 파싱과 일반 실행은 정상이어도 byte-hash/reproducibility 검사는 실패할 수 있습니다.

이 문제를 해결하기 위해 저장소 전체 파일을 일괄 변환하지 않습니다. 전체 LF 강제는 다른 팀 파일과 동결 자료를 불필요하게 건드릴 수 있기 때문입니다. 최종적으로 hash-sensitive canonical input 범위가 확정되면 해당 파일만 `.gitattributes`에서 `text eol=lf`로 고정하는 방식이 우선입니다.

현재 단계에서는 다음 원칙을 따릅니다.

- 줄바꿈 차이만 있는 대규모 파일 변경은 커밋하지 않습니다.
- 동결 파일은 `tools/final_freeze.py check` 결과를 우선합니다.
- byte-hash-sensitive 파일의 정확한 범위가 확정되기 전에는 다른 팀 파일을 일괄 수정하지 않습니다.
- Windows 개발 환경에서는 이 재현성 차이를 인지하고, 필요 시 WSL/Linux/CI에서 공식 재현성 검사를 수행합니다.
현재 공식 오프라인 테스트 실행기(`tools/run_offline_tests.py`)와 일부 기존 테스트/도구는 POSIX(macOS/Linux) 동작을 전제로 합니다. Windows 로컬 환경에서는 다음 차이로 전체 저장소 테스트가 실패할 수 있습니다.

- `signal.getitimer` / `ITIMER_REAL` 기반 모듈 timeout은 Windows Python에서 제공되지 않습니다.
- 일부 기존 도구의 `strftime('%-m/%-d')` 형식은 Windows에서 지원되지 않습니다.
- 심볼릭 링크 테스트는 Windows의 개발자 모드/권한 설정에 따라 `WinError 1314`가 날 수 있습니다.
- 바이트 해시와 재현성 검사는 Git checkout의 CRLF/LF 변환 영향을 받을 수 있습니다.

이 차이를 통과시키기 위해 Storage 작업 범위를 넘어 기존 판정기·실험·데모 UI·시나리오 코드를 수정하지 않습니다. Windows에서는 Storage/service 핵심 테스트와 `tools/final_freeze.py check`를 별도로 확인하고, 전체 공식 오프라인 runner는 POSIX 호환 환경(예: Linux/WSL/CI)에서 최종 검증합니다. Windows 전용 호환 수정이 필요하면 별도 작업으로 다룹니다.
