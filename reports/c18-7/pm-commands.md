# C-18-7 PM 명령 — 합치기 · 프록시 재기동 · 재실행 · 제외 목록 · 기록·집계 (DM-53 형식)

순서 : **브랜치 합치기 → 프록시 재기동 → 레인 1·2·3 `--rerun-failed` → 제외·대체 목록 → 기록·집계**. 명령 블록 하나에 명령 하나.
키는 창마다 직접 붙여 넣고 길이만 확인하며, 창을 닫기 전에 `unset` 한다. 모든 창은 저장소 폴더(`~/AI-agent-guardrail-harness`)에서 한다.

## 0. 지금 상태 (10/6 15:08 KST 기록 기준, `reports/c18-7/exclusions-before-rerun.json`)

**레인 3 은 돌고 있지 않다.** 15:08 KST 에 runner_error 2 번 연속(`DEMO-CL-stall-v1:block:3` 업스트림 502, `DEMO-CT-stall-v1:block:3` 120 초 시간 초과)으로 스스로 멈췄고 (`lane_stopped`), 아직 돌지 않은 항목이 2 개 있다.
레인 1·2·4 와 LR 보충은 `lane_finished`. 그래서 지금은 **아무 세션도 돌지 않는다** — 합치기·프록시 재기동을 해도 끊길 세션이 없다.

| 레인 · 계정 | 다시 돌 항목 (`--rerun-failed` 가 돌리는 것) | 추정 크레딧 | 추정 시간 |
|---|---|---|---|
| 1 · A | 실패 7 : CL-normal 관측 #1, CL-stall 관측 #2, CT-stall 관측 #1·#4, MR-normal 관측 #5, CT-stall 차단 #1, MR-stall 차단 #1 | 488.47 | 약 102 분 |
| 2 · B | 실패 2 : CT-stall 관측 #5, CT-stall 차단 #2 | 162.17 | 약 32 분 |
| 3 · C | 실패 3 : CT-stall 관측 #3, CL-stall 차단 #3, CT-stall 차단 #3 + **대기 2** : CS-stall 차단 #3, MR-stall 차단 #3 | 259.03 | 약 56 분 |
| 합 | 14 세션 | 909.67 | 동시에 돌리면 약 1.7 시간 |

추정은 C-18-6 명령서 0 절의 시나리오별 시험 실측(관측 1 세션, 차단은 첫 STOP 까지)을 더한 값이다. CT 교착판은 이제 120 초 넘는 생성이 끊기지 않으므로 시간이 이보다 길 수 있다.

## 1. 브랜치 합치기 (창 1)

```bash
cd ~/AI-agent-guardrail-harness
```

```bash
git status --short
```

출력이 비어 있어야 한다. 비어 있지 않으면 멈춘다.

```bash
git merge --ff-only c18-7
```

fast-forward 가 안 되면 다음을 쓴다.

```bash
git merge --no-edit c18-7
```

```bash
git log --oneline -6
```

```bash
venv/bin/python -B tools/final_freeze.py check
```

`"ok": true`, `sha256` `6a7bf8dc…` 이어야 한다 (`proxy.py` 는 동결 62 파일 밖).

```bash
git worktree remove ../AI-agent-guardrail-harness-c18-7
```

## 2. 프록시 재기동 (DM-79 ③)

창 P·창 Q 의 프록시를 Ctrl+C 로 끄고, 같은 창에서 다시 띄운다. 새 프록시는 업스트림 읽기 시간 제한이 600 초다.

창 P — 관측 프록시 (포트 8000)

```bash
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --log-level info
```

창 Q — 차단 프록시 (포트 8001)

```bash
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu-block.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8001 --log-level info
```

조건 확인 (창 1)

```bash
curl -s http://127.0.0.1:8000/conditions
```

```bash
curl -s http://127.0.0.1:8001/conditions
```

```bash
grep -n "UPSTREAM_TIMEOUT = " proxy.py
```

기대값 : 두 프록시 모두 `criteria_version` `deadlock-v0.3`, `criteria_sha256` `a93cc2d6…`, `criteria_freeze_sha256` `4fa93919…`, 고정 모델 `glm-5.3-flash`, `guardrail_mode` 는 8000 observe · 8001 block. `grep` 은 `httpx.Timeout(120, read=600)`. 하나라도 다르면 시작하지 않는다.

## 3. 레인 1·2·3 `--rerun-failed` (각자 자기 계정 창에서, 동시에)

**동시에 돌리기를 제안한다.** 근거 : ① 레인마다 자기 항목만 돌린다 (배치 실행기가 항목을 레인에 고정해 나누므로 세 레인의 항목이 겹치지 않는다) ② 계정이 달라 실측 크레딧이 섞이지 않는다 ③ 본 실행에서 4 레인이 동시에 돌 때 429 는 0 건이었다 (DM-78 ①) ④ 한 레인씩이면 약 3.2 시간, 동시면 가장 긴 레인 1 의 약 1.7 시간. 레인 3 의 대기 2 항목도 이 명령이 함께 돌린다 (처음 도는 항목이라 `rerun_of` 는 없다).
재실행도 runner_error 로 끝나면 그 항목은 "실행 환경 사유 미완료" 로 두고 세 번째로 돌리지 않는다 (DM-79 ③). runner_error 2 번 연속이면 레인이 스스로 멈춘다 — 그때도 다시 켜지 않는다.

창 1 (계정 A)

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
export TAVILY_API_KEY="$(pbpaste)"
```

```bash
echo ${#TAVILY_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 1 --lanes 4 --account-label A --rerun-failed
```

창 2 (계정 B)

```bash
cd ~/AI-agent-guardrail-harness
```

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
export TAVILY_API_KEY="$(pbpaste)"
```

```bash
echo ${#TAVILY_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 2 --lanes 4 --account-label B --rerun-failed
```

창 3 (계정 C)

```bash
cd ~/AI-agent-guardrail-harness
```

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
export TAVILY_API_KEY="$(pbpaste)"
```

```bash
echo ${#TAVILY_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 3 --lanes 4 --account-label C --rerun-failed
```

진행 확인 (창 1)

```bash
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-main-v1.yaml --lanes 4
```

창 2·3 은 레인이 끝나면 닫기 전에 실행한다. 창 1 은 4 절을 마칠 때까지 키를 둔다 (기록 키 검사).

```bash
unset KMU_API_KEY TAVILY_API_KEY
```

**재실행으로 채울 수 없는 항목** : LR 보충의 `DEMO-LR-stall-v1:block:3` (`445ab1ba…`, 0 step `user_interrupted`). 배치 실행기는 이 종료를 "끝남" 으로 보므로 `--rerun-failed` 로도 다시 돌지 않는다. 그대로 두면 LR 교착판 차단은 3 회 중 2 회만 유효하다 (보고 6 절 PM 결정).

## 4. 재실행이 끝난 뒤 — 제외·대체 목록 → 기록 → 집계 → 재생 페이지 → 커밋 → 원본 백업 (창 1)

세 레인이 모두 끝난 뒤(`status` 에서 레인 1~3 의 `pending` 0) 차례로 실행한다.

```bash
venv/bin/python -B tools/demo_exclusions.py --plan demo-main-v1 --plan demo-main-v1-lr2 --output reports/c18-7/exclusions.json
```

끝 코드가 1 이면 (`unresolved` 가 있음) 멈추고 출력을 보고한다. 출력의 `items_without_valid_session` 이 재실행 뒤에도 유효 세션이 없는 항목이다.

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1
```

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1-lr2
```

```bash
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index
```

```bash
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1-lr2 --index
```

```bash
venv/bin/python -B tools/aggregate_demo.py --plan demo-main-v1 --plan demo-main-v1-lr2 --final-freeze-sha256 "$(shasum -a 256 docs/criteria/demo-final-freeze.json | cut -d ' ' -f 1)" --exclusions reports/c18-7/exclusions.json --output-json reports/c19/aggregate-main.json --output-md reports/c19/aggregate-main.md
```

출력 머리의 "목록에 없는 세션" 줄이 있으면 목록이 기록보다 오래된 것이다 → 첫 명령부터 다시 한다.

```bash
venv/bin/python -B tools/replay_demo.py pages reports/c19/aggregate-main.json --output-dir reports/c19/replay
```

```bash
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1
```

```bash
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1-lr2
```

```bash
git add reports/c19 reports/c18-7/exclusions.json
```

```bash
git commit -m "chore: C-19 main run and LR supplement records, exclusion list, aggregation and replay pages"
```

```bash
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1 --output ../demo-backup/demo-main-v1-raw.tar.gz
```

```bash
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1-lr2 --output ../demo-backup/demo-main-v1-lr2-raw.tar.gz
```

```bash
unset KMU_API_KEY TAVILY_API_KEY
```

## 참고 — 재실행 전에 제외 목록만 다시 보기 (저장소 밖으로 출력)

합치기 뒤 재실행 전에 기록을 다시 계산해 보고 싶을 때. 저장소 안에 파일을 쓰면 재실행 세션이 `git_dirty: true` 가 되므로 출력은 저장소 밖에 둔다.

```bash
venv/bin/python -B tools/demo_exclusions.py --plan demo-main-v1 --plan demo-main-v1-lr2 --output ../c18-7-exclusions-check.json
```
