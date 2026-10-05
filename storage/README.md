# Storage

멀티 AI 에이전트 가드레일 프로젝트의 PostgreSQL 저장 기능입니다.
아직 초안입니다. . . . .

## 주요 파일

- `db.py`
  - PostgreSQL 연결을 담당합니다.

- `import_run.py`
  - `runs/`에 생성된 실험 결과 JSON을 PostgreSQL에 저장합니다.

- `schema.sql`
  - PostgreSQL에 필요한 7개 테이블을 생성합니다.

- `postgres.env.example`
  - PostgreSQL 연결에 필요한 환경변수 예시입니다.


## PostgreSQL 환경변수 설정

`postgres.env.example`을 참고하여 프로젝트 루트의 `.env`에 아래 값을 추가합니다.

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=guardrail_agent_v2
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password_here
```

실제 비밀번호가 들어간 `.env` 파일은 GitHub에 올리지 않습니다.


## 필요한 Python 패키지

```bash
pip install "psycopg[binary]" python-dotenv
```


## DB 테이블 생성

새 PostgreSQL 데이터베이스를 만든 후 `schema.sql`을 실행합니다.

생성되는 테이블:

- projects
- api_keys
- scenarios
- sessions
- llm_calls
- observations
- judgements



## 사전 준비

`import_run.py` 실행 전에 PostgreSQL에 `projects`와 `scenarios`가 먼저 등록되어 있어야 합니다.

실행 결과의 `scenario_key`와 `scenario_revision`이 DB의 시나리오 정보와 일치해야 합니다.

`import_run.py`는 실행 결과를 다음 테이블에 자동 저장합니다.

- sessions
- observations
- judgements
- llm_calls



## 실행 결과 저장

`runs/` 폴더에 생성된 실험 결과를 PostgreSQL에 저장합니다.

프로젝트 루트에서 아래 형식으로 실행합니다.

```bash
python -m storage.import_run <run_folder_name>
```

예시:

```bash
python -m storage.import_run A-1-v2-705302628fef4777aae2a2fc4877035f
```

여기서 `<run_folder_name>`은 `runs/` 안에 있는 저장할 실험 결과 폴더의 이름입니다.

예를 들어 아래 폴더를 저장하려면:

```text
runs/
└─ A-1-v2-705302628fef4777aae2a2fc4877035f/
```

다음과 같이 실행합니다.

```bash
python -m storage.import_run A-1-v2-705302628fef4777aae2a2fc4877035f
```

자동 저장 대상:

- sessions
- llm_calls
- observations
- judgements

같은 run을 다시 실행해도 중복으로 추가하지 않고 기존 데이터를 갱신합니다.