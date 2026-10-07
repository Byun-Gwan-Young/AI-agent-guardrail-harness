# C-19-3 데모 화면 — PM 명령서

화면 파일 하나 `reports/c19-3/demo.html` (서버·외부 요청 없음, 더블클릭으로 열림). 본 실행 집계 `reports/c19/aggregate-main.json` 과 세션별 `record/replay.json` (커밋 `4ba401a`) 으로 만들었다. 브랜치 `c19-3-demo-ui`, worktree `../AI-agent-guardrail-harness-c19-3` (C-19-4 가 같은 worktree 를 쓰므로 지우지 않는다).

블록 하나에 명령 하나다. 키는 필요 없다.

## 1. 합치기 전에 화면 열기 (worktree 의 파일)

```bash
open ../AI-agent-guardrail-harness-c19-3/reports/c19-3/demo.html
```

메뉴를 바로 열려면 주소 끝에 `#session`, `#compare`, `#stats`, `#system`, `#guide` 를 붙인다. 시험 데이터 화면은 `reports/c19-3/demo-trial.html` 이다.

## 2. main 에 합치기 (main 작업 트리에서, C-19-2 커밋 `a968ef6` 뒤)

```bash
git merge --ff-only c19-3-demo-ui
```

fast-forward 가 안 되면 :

```bash
git merge --no-edit c19-3-demo-ui
```

## 3. 합친 뒤 main 에서 화면 다시 만들기

```bash
venv/bin/python -B tools/demo_ui.py build --aggregate reports/c19/aggregate-main.json --output reports/c19-3/demo.html
```

```bash
git diff --stat reports/c19-3/demo.html
```

차이가 없어야 정상이다 (같은 입력, 같은 출력). 차이가 있으면 커밋하지 말고 알려 준다.

```bash
open reports/c19-3/demo.html
```

## 4. 시험 데이터로 다시 만들 때 (참고)

```bash
venv/bin/python -B tools/demo_ui.py build --aggregate reports/c19-3/aggregate-trial.json --output reports/c19-3/demo-trial.html
```
