# C-19-4 실시간 모니터 — PM 명령서

브랜치 `c19-3-demo-ui` (worktree `../AI-agent-guardrail-harness-c19-3`) 에 C-19-3 과 C-19-4 가 함께 있다. 합치기는 한 번이다 (DM-88 ④). 블록 하나에 명령 하나다. 키는 4 절의 실시간 실행에만 필요하다.

모니터 서버 `tools/demo_live.py` 는 세션이 step 마다 쓰는 파일(실행기의 `runs/demo/<id>/steps.json`, 프록시의 `logs/demo/<id>.json`)을 읽기만 한다. `127.0.0.1:8010` 에만 열린다. 프록시·실행기·배치 실행기는 그대로다.

## 0. 발표용 실시간 실행 항목 (`batch_plans/demo-live-v1.yaml`)

| 레인 | 항목 | 역할 | 본 실행 차단 세션 실측 (같은 시나리오·차단) | 예상 시간 | 예상 크레딧 |
|---|---|---|---|---|---|
| 1 (계정 A) | `DEMO-CT-stall-v1:block:1` | 주 | 유효 2 세션 : 15·17 step 에서 차단 (첫 STOP step 14·16), 13.2·9.0 분, 55.36·56.80 크레딧 | 약 9~13 분 | 약 55~57 |
| 2 (계정 B) | `DEMO-CL-stall-v1:block:1` | 대비 | 유효 3 세션 : 11·12·15 step 에서 차단 (첫 STOP step 10·11·14), 9.3·8.1·12.2 분, 34.64·31.95·50.02 크레딧 | 약 8~12 분 | 약 32~50 |

- 두 레인을 동시에 돌리므로 벽시계 시간은 긴 쪽 (약 13 분 안), 합계 약 87~107 크레딧이다. 실측 3~2 세션의 범위일 뿐이다. 교착이 안 나면 30 step 까지 가고 더 든다 (본 실행 교착판 관측 세션은 30 step 에 약 130~150 크레딧).
- DM-77 ④ 의 "step 9 STOP, 약 30~35 크레딧·6~8 분" 은 C-18 시험 값이다. 본 실행 차단 세션은 위 표처럼 STOP 이 더 늦었다.
- 실시간 실행은 교착이 안 날 수 있다. **기록 재생 화면(세션 메뉴)을 늘 대비로 둔다.**
- 계획 항목은 한 번만 돈다 (배치 실행기가 끝난 항목을 건너뛴다). 리허설로 이 계획을 한 번 돌리면 발표 때 다시 돌릴 항목이 없다. 리허설용 계획을 따로 둘지는 PM 이 정한다.

## 1. main 에 합치기 (main 작업 트리에서)

```bash
git merge --ff-only c19-3-demo-ui
```

fast-forward 가 안 되면 :

```bash
git merge --no-edit c19-3-demo-ui
```

## 2. 합친 뒤 main 에서 화면 다시 만들기

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

파일로 연 화면의 "실시간 모니터" 메뉴는 "실시간 서버가 꺼져 있습니다. 기록 재생을 쓰세요." 만 보인다 (요청 코드가 없다).

## 3. 모니터 서버 띄우기 (창 M, main 작업 트리)

```bash
venv/bin/python -B tools/demo_live.py serve
```

```bash
open http://127.0.0.1:8010/#live
```

`runs/demo` 의 세션 폴더를 기록 파일이 바뀐 순서로 12 개까지 보여 준다. 본 실행은 끝났으므로 모두 "끝" 으로 나온다. 끌 때는 창 M 에서 Ctrl+C.

## 4. 발표용 실시간 실행

창 Q — 차단 프록시 (포트 8001). 두 항목 모두 차단이라 관측 프록시는 필요 없다.

```bash
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu-block.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8001 --log-level info
```

조건 확인 (창 1)

```bash
curl -s http://127.0.0.1:8001/conditions
```

기대값 : `criteria_version` `deadlock-v0.3`, `criteria_sha256` `a93cc2d6…`, `criteria_freeze_sha256` `4fa93919…`, 고정 모델 `glm-5.3-flash`, `guardrail_mode` `block`. 다르면 시작하지 않는다.

```bash
venv/bin/python -B tools/final_freeze.py check
```

`differences` 가 빈 목록이어야 한다 (계획에 `requires_final_freeze` 가 있어 아니면 레인이 시작하지 않는다).

창 1 (계정 A) — 레인 1 : CT 교착판 차단

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-live-v1.yaml --lane 1 --lanes 2 --account-label A
```

```bash
unset KMU_API_KEY
```

창 2 (계정 B) — 레인 2 : CL 교착판 차단 (창 1 과 동시에)

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-live-v1.yaml --lane 2 --lanes 2 --account-label B
```

```bash
unset KMU_API_KEY
```

진행 확인 (아무 창)

```bash
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-live-v1.yaml --lanes 2
```

모니터 화면 (`http://127.0.0.1:8010/#live`) 에서 두 세션이 맨 위에 "진행 중" 으로 뜬다. 세션을 고르면 타임라인이 step 마다 늘고, STOP 이 나면 알림 카드에 원인 문장이 뜨고, 다음 칸이 403 으로 끝난다. 화면은 2.5 초마다 파일을 다시 읽는다. 끝나면 창 Q 의 프록시를 Ctrl+C 로 끈다.

이 세션들은 계획 ID `demo-live-v1` 이라 본 실행 집계(`demo-main-v1`)에 들어가지 않는다. 기록·커밋은 이 명령서 범위가 아니다.
