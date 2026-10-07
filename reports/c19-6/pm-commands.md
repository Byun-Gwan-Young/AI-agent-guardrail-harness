# C-19-6 PM 명령서 — 데모 기록 DB 적재 + 조회 API (로컬)

블록 하나에 명령 하나입니다 (DM-53). 비밀번호를 쓰지 않습니다 : Homebrew PostgreSQL 은 이 맥의 사용자 계정으로 `127.0.0.1` 접속을 비밀번호 없이 받습니다.
C-19-6 작업 당시 이 맥에는 PostgreSQL 서버가 없었습니다 (`psql`·`pg_isready` 가 PATH 에 없음, 5432 포트 응답 없음, Homebrew 에는 클라이언트 라이브러리 `libpq` 17.4 만). 그래서 1 절이 설치부터 시작합니다. 설치는 PM 이 합니다 (코딩 에이전트는 패키지를 설치하지 않음).

## 1. PostgreSQL 설치 · 켜기

```bash
brew install postgresql@17
```

```bash
brew services start postgresql@17
```

```bash
/opt/homebrew/opt/postgresql@17/bin/pg_isready -h 127.0.0.1
```

`127.0.0.1:5432 - accepting connections` 가 나오면 됩니다.

## 2. DB 만들기 (`guardrail_demo`, 전에 만든 데모 DB 와 따로)

```bash
/opt/homebrew/opt/postgresql@17/bin/createdb -h 127.0.0.1 guardrail_demo
```

## 3. 창 준비 (C-19-6 worktree, 합치기 전)

```bash
cd ~/AI-agent-guardrail-harness-c19-6
```

psycopg 가 C 라이브러리 libpq 를 찾게 합니다 (Homebrew PostgreSQL 은 keg-only 라 기본 경로에 없음. 이 창에서만 유효).

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/opt/postgresql@17/lib"
```

```bash
export GUARDRAIL_DB_URL="postgresql://127.0.0.1:5432/guardrail_demo"
```

## 4. 스키마 → 적재 → 확인 쿼리

```bash
~/AI-agent-guardrail-harness/venv/bin/python -B -m service.load_demo schema
```

```bash
~/AI-agent-guardrail-harness/venv/bin/python -B -m service.load_demo load
```

`"loaded"` 아래 `tables` 가 scenarios 15 · sessions 115 · steps 932 · aggregates 1 이면 됩니다. 연결된 DB 이름이 `guardrail_demo` 가 아니면 아무것도 쓰지 않고 멈춥니다. 다시 돌려도 같은 결과입니다 (한 트랜잭션으로 지우고 다시 넣음).

```bash
~/AI-agent-guardrail-harness/venv/bin/python -B -m service.load_demo check --output reports/c19-6/check-postgres.json
```

맨 위 `"ok": true` 이고 `comparisons` 가 모두 `"same": true` 면 됩니다 (유효 67, 제외 사유별 13·9·3·3·2, 오탐 4/24 와 그중 2, 탐지 8/9, 평균 절감 60.8 %, 차단 절감 CL 66.7 % · CT 59.0 %). 하나라도 다르면 종료 코드 1 이고, 그 출력을 Claude Code 에 넘깁니다.

```bash
~/AI-agent-guardrail-harness/venv/bin/python -B -m unittest service.test_live_db
```

`Ran 5 tests … OK` (skipped 없음) 이면 됩니다.

## 5. API 띄우기 · 브라우저로 보기

```bash
~/AI-agent-guardrail-harness/venv/bin/python -B -m service.api
```

이 창은 서버가 차지합니다. 다른 창에서 엽니다. `/docs` 의 화면 파일(Swagger UI)은 브라우저가 `cdn.jsdelivr.net` 에서 받으므로 인터넷이 필요합니다. `/api/summary` 는 인터넷 없이 됩니다.

```bash
open http://127.0.0.1:8020/docs
```

```bash
open http://127.0.0.1:8020/api/summary
```

멈출 때는 서버 창에서 `Ctrl+C` 를 누릅니다.

```bash
unset GUARDRAIL_DB_URL
```

## 6. 합치기 (C-19-3·C-19-4 먼저)

`c19-3-demo-ui` (C-19-3 · C-19-4) 를 먼저 합칩니다. C-19-4 명령서에 합치는 명령이 있으면 그것을 씁니다. 아래는 같은 명령입니다.

```bash
cd ~/AI-agent-guardrail-harness
```

```bash
git merge --ff-only c19-3-demo-ui
```

fast-forward 가 안 되면 :

```bash
git merge --no-edit c19-3-demo-ui
```

그다음 C-19-6 :

```bash
git merge --no-edit c19-6-db-api
```

충돌이 나면 손대지 말고 그 출력을 Claude Code 에 넘깁니다. 합친 뒤 main 에서 전체 오프라인 테스트와 동결 확인 :

```bash
env -u KMU_API_KEY -u TAVILY_API_KEY -u GUARDRAIL_DB_URL venv/bin/python -B tools/run_offline_tests.py --baseline tests/fixtures/p0-3-mechanism-test-ids.json --output reports/c19-6/tests-after-merge.json
```

```bash
venv/bin/python -B tools/final_freeze.py check
```

합친 뒤에는 4·5 절의 명령을 `~/AI-agent-guardrail-harness` 에서 `venv/bin/python` 으로 돌리면 됩니다. worktree 정리는 합친 뒤 :

```bash
git worktree remove ../AI-agent-guardrail-harness-c19-6
```
