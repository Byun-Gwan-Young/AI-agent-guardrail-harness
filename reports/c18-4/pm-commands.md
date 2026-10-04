# C-18-4 PM 명령 (DM-53 형식)

모든 창은 저장소 폴더에서 시작한다. 키는 창마다 직접 붙여 넣고 길이만 확인하며, 창을 닫기 전에 `unset` 한다.
v0.3 동결 해시는 C-18-4 에서 바뀌지 않았다 (`4fa93919…`). 그래도 프록시는 새로 띄운다.

## 1. CS·MR 재시험 (`batch_plans/demo-trial-c18-4.yaml`, 4 세션, 레인 2 개)

예상 크레딧 (추정, `reports/c18-4/estimate-retest.json`) : C-18-3 시험 실측 합 141.23, 위쪽 값 512.08 (세션마다 30 step MR 정상판 실측 128.02).

창 P — 관측 프록시 (포트 8000)

```bash
cd ~/AI-agent-guardrail-harness
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --log-level info
```

창 1 — 레인 1 = CS 2 개 (계정 A)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-trial-c18-4.yaml --lane 1 --lanes 2 --account-label A
unset KMU_API_KEY
```

창 2 — 레인 2 = MR 2 개 (계정 B, Tavily 키도)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-trial-c18-4.yaml --lane 2 --lanes 2 --account-label B
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-trial-c18-4.yaml --lanes 2
unset KMU_API_KEY TAVILY_API_KEY
```

요약은 레인 기록 `runs/demo-batches/demo-trial-c18-4/lane-{1,2}-of-2.jsonl` 에 한 줄씩 남는다 (각 창의 키로 검사). 이 두 파일을 붙여 주면 된다.

## 2. 재시험 기록 커밋 (재시험 결과를 확인한 뒤)

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-trial-c18-4
venv/bin/python -B tools/demo_records.py check --plan demo-trial-c18-4 --index
venv/bin/python -B tools/demo_records.py stage --plan demo-trial-c18-4
git commit -m "chore: commit the C-18-4 CS and MR retest records under demo-records-v1"
```

## 3. 최종 동결 (DM-33)

```bash
venv/bin/python -B tools/final_freeze.py create
git add docs/criteria/demo-final-freeze.json
git commit -m "chore: demo final freeze before the C-19 main run (DM-33)"
venv/bin/python -B tools/final_freeze.py check
```

`create` 는 동결 범위의 파일이 커밋되지 않았으면 거절한다. 재시험 결과로 시나리오를 다시 고쳐야 하면 이 단계 전에 멈춘다.

## 4. 차단 프록시 (포트 8001) — 창 P 의 관측 프록시와 함께 띄운다

창 Q

```bash
cd ~/AI-agent-guardrail-harness
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu-block.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8001 --log-level info
```

## 5. 본 실행 (`batch_plans/demo-main-v1.yaml`, 70 세션, 레인 4 개, 창마다 다른 계정)

레인 1~3 은 MR 항목이 섞이므로 `KMU_API_KEY` + `TAVILY_API_KEY`, 레인 4 는 LR 전용이라 `KMU_API_KEY` 만. 최종 동결 `check` 가 실패하면 레인은 세션을 시작하지 않는다.

창 1 (계정 A)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 1 --lanes 4 --account-label A
unset KMU_API_KEY TAVILY_API_KEY
```

창 2 (계정 B)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 2 --lanes 4 --account-label B
unset KMU_API_KEY TAVILY_API_KEY
```

창 3 (계정 C)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 3 --lanes 4 --account-label C
unset KMU_API_KEY TAVILY_API_KEY
```

창 4 (계정 D, LR 전용)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-main-v1.yaml --lane 4 --lanes 4 --account-label D
unset KMU_API_KEY
```

진행 확인 (아무 창에서나)

```bash
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-main-v1.yaml --lanes 4
```

멈췄을 때 다시 켜기 : 그 창에서 같은 `run` 명령을 다시 실행한다 (끝난 항목은 건너뛴다). `runner_error`·중단 항목까지 다시 돌릴 때만 끝에 `--rerun-failed` 를 붙인다
(같은 창·같은 계정 키로, 새 세션은 `rerun_of` 를 남긴다). 레인 번호를 바꾸지 않는다.

## 6. 본 실행 뒤 — 기록 커밋과 원본 백업 (저장소 밖)

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1
git commit -m "chore: commit the C-19 main run records under demo-records-v1"
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1 --output ../demo-backup/demo-main-v1-raw.tar.gz
venv/bin/python -B tools/demo_records.py backup --plan demo-trial-c18-4 --output ../demo-backup/demo-trial-c18-4-raw.tar.gz
```

압축 파일은 팀 드라이브에 올린다. `backup` 은 키 검사가 깨끗하지 않거나 같은 파일이 이미 있으면 쓰지 않는다.
