# Storage (PostgreSQL)

멀티 AI 에이전트 가드레일 프로젝트의 PostgreSQL 저장 모듈입니다.

## 핵심 구조

```text
projects
 ├─ api_keys
 └─ scenarios
      └─ sessions
           ├─ observations
           ├─ judgements
           └─ llm_calls
```

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

1. `.env`의 `POSTGRES_DB`가 없으면 DB 생성
2. `schema.sql`의 최종 7개 테이블 생성
3. 프로젝트가 하나도 없으면 터미널에서 값을 물어보고 `projects` 행 생성

따라서 테이블 생성이나 프로젝트 등록 때문에 SQL INSERT를 직접 칠 필요가 없습니다.

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

`.env`에 `POSTGRES_PROJECT_ID`가 없어도 projects가 정확히 1개면 자동 선택합니다.

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

## .env 예시

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=guardrail_agent_v2
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

프로젝트가 하나뿐이면 `POSTGRES_PROJECT_ID`는 없어도 됩니다.
여러 프로젝트가 생기면 그때 지정합니다.

실제 `.env`는 GitHub에 올리지 않습니다.

## 파일

- `schema.sql`: **현재 최종 7개 테이블 구조만** 들어 있는 스키마
- `db.py`: PostgreSQL 연결/프로젝트 자동 선택
- `init_db.py`: pgAdmin 없이 DB/schema/project 준비
- `import_utils.py`: 공통 검증/변환 함수
- `import_run.py`: 실제 raw run 저장
- `import_demo.py`: GitHub demo record 저장
- `__main__.py`: `python -m storage` 메뉴/짧은 명령
- `postgres.env.example`: 환경변수 예시
- `requirements-storage.txt`: 필요한 Python 패키지
