# C-19-1 실행 명령 — 본 실행이 끝난 뒤 (DM-53 형식)

PM 이 본 실행 종료를 알린 뒤 main 작업 트리에서, 본 실행을 돌린 창 하나(키가 있는 창)에서 차례로 실행한다.
브랜치 `c19-1-aggregate-replay` 는 `tools/`·`tests/`·`reports/c19-1/`·시험 세션의 `record/replay.json` 만 바꾼다. 최종 동결 61 파일·실행기·배치 실행기·프록시는 바꾸지 않으므로
합친 뒤에도 `final_freeze.py check` 는 그대로 통과해야 한다.

## 1. 브랜치 합치기

```bash
cd ~/AI-agent-guardrail-harness
git status --short
git merge --no-edit c19-1-aggregate-replay
venv/bin/python -B tools/final_freeze.py check
```

`git status --short` 가 비어 있지 않으면 합치기 전에 멈춘다.

## 2. 본 실행 기록 다시 만들기 (replay.json 포함)

C-18-4 명령서 6 절의 `record` 를 이미 했어도 다시 한다 (`record` 가 이제 `record/replay.json` 도 쓴다. 기존 record 파일 세 개도 다시 쓰인다).

```bash
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index
unset KMU_API_KEY TAVILY_API_KEY
```

## 3. 집계 → 대표 세션 선정 → 재생 페이지

```bash
venv/bin/python -B tools/aggregate_demo.py --plan demo-main-v1 --final-freeze-sha256 "$(shasum -a 256 docs/criteria/demo-final-freeze.json | cut -d ' ' -f 1)" --output-json reports/c19/aggregate-main.json --output-md reports/c19/aggregate-main.md
venv/bin/python -B tools/replay_demo.py pages reports/c19/aggregate-main.json --output-dir reports/c19/replay
```

대표 세션은 집계 출력의 `representatives` 에 선정 근거와 함께 있다. `pages` 는 대표 세션마다 `reports/c19/replay/<세션 ID>.html` 과 `index.html` 을 만든다.
`replay_missing` 이 비어 있지 않으면 2 절 `record` 를 빠뜨린 것이다.

## 4. 기록 커밋

```bash
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1
git add reports/c19
git commit -m "chore: C-19 main run records, aggregation and replay pages"
```
