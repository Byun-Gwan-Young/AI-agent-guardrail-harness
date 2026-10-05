# C-18-5 PM 명령 (DM-53 형식)

모든 창은 저장소 폴더에서 시작한다. 키는 창마다 직접 붙여 넣고 길이만 확인하며, 창을 닫기 전에 `unset` 한다.
v0.3 동결 해시는 C-18-5 에서 바뀌지 않았다 (`4fa93919…`). C-19-1 브랜치는 main 에 합쳐졌다 (`f564e22`). 프록시는 새로 띄운다.
C-18-4 재시험 4 세션의 기록은 C-18-5 파트 0 (`61f4f02`) 에서 이미 커밋했다.

## 1. MR 재시험 (`batch_plans/demo-trial-c18-5.yaml`, 2 세션, 레인 1 개)

예상 크레딧 (추정, `reports/c18-5/estimate-retest.json`) : C-18-4 MR 재시험 실측 합 25.75, 위쪽 값 256.04 (두 세션 모두 30 step MR 정상판 실측 128.02).

창 P — 관측 프록시 (포트 8000)

```bash
cd ~/AI-agent-guardrail-harness
GUARDRAIL_CONFIG=guardrail-deadlock-v0.3-kmu.yaml venv/bin/python -m uvicorn proxy:app --host 127.0.0.1 --port 8000 --log-level info
```

창 1 — 레인 1 = MR 2 개 (KMU 키 + Tavily 키)

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-trial-c18-5.yaml --lane 1 --lanes 1 --account-label A
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-trial-c18-5.yaml --lanes 1
```

키는 2 절이 끝날 때까지 이 창에 둔다 (기록 키 검사에 쓴다). 요약은 `runs/demo-batches/demo-trial-c18-5/lane-1-of-1.jsonl` 에 한 줄씩 남는다. 이 파일을 붙여 주면 된다.

**판단 (DM-72)** : MR 정상판이 success 면 동결로 간다. 아니면 (다) 대로 MR 을 고치지 않고 **그대로 동결로 간다** (MR 정상판 결과는 "대화 과제에서 역할 사이 정보 전달이 끊기는 하네스 한계" 로 보고, T1 정상판 성공·오탐 비교는 CS·LR 로). 어느 쪽이든 아래 순서다.

## 2. 재시험 기록 커밋 (창 1 에서, 키가 있는 채로)

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-trial-c18-5
venv/bin/python -B tools/demo_records.py check --plan demo-trial-c18-5 --index
venv/bin/python -B tools/demo_records.py stage --plan demo-trial-c18-5
git commit -m "chore: commit the C-18-5 MR retest records under demo-records-v1"
unset KMU_API_KEY TAVILY_API_KEY
```

## 3. 최종 동결 (DM-33)

```bash
git status --short
venv/bin/python -B tools/final_freeze.py create
git add docs/criteria/demo-final-freeze.json
git commit -m "chore: demo final freeze before the C-19 main run (DM-33)"
venv/bin/python -B tools/final_freeze.py check
```

`git status --short` 가 비어 있지 않으면 `create` 전에 멈춘다. `create` 는 동결 범위의 파일이 커밋되지 않았으면 거절한다.

## 4. 프록시 — 관측 (8000, 창 P 그대로) + 차단 (8001)

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

## 6. 본 실행 뒤 — 기록 → 집계 → 재생 페이지 → 커밋 → 원본 백업

키가 있는 창 하나에서 차례로 실행한다 (`record`·`stage` 의 키 검사).

```bash
cd ~/AI-agent-guardrail-harness
export KMU_API_KEY="$(pbpaste)"
echo ${#KMU_API_KEY}
export TAVILY_API_KEY="$(pbpaste)"
echo ${#TAVILY_API_KEY}
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index
venv/bin/python -B tools/aggregate_demo.py --plan demo-main-v1 --final-freeze-sha256 "$(shasum -a 256 docs/criteria/demo-final-freeze.json | cut -d ' ' -f 1)" --output-json reports/c19/aggregate-main.json --output-md reports/c19/aggregate-main.md
venv/bin/python -B tools/replay_demo.py pages reports/c19/aggregate-main.json --output-dir reports/c19/replay
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1
git add reports/c19
git commit -m "chore: C-19 main run records, aggregation and replay pages"
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1 --output ../demo-backup/demo-main-v1-raw.tar.gz
venv/bin/python -B tools/demo_records.py backup --plan demo-trial-c18-4 --output ../demo-backup/demo-trial-c18-4-raw.tar.gz
venv/bin/python -B tools/demo_records.py backup --plan demo-trial-c18-5 --output ../demo-backup/demo-trial-c18-5-raw.tar.gz
unset KMU_API_KEY TAVILY_API_KEY
```

`replay_demo.py pages` 의 `replay_missing` 이 비어 있지 않으면 `record` 를 빠뜨린 것이다. 대표 세션은 집계 출력의 `representatives` 에 선정 근거와 함께 있다.
압축 파일은 팀 드라이브에 올린다. `backup` 은 키 검사가 깨끗하지 않거나 같은 파일이 이미 있으면 쓰지 않는다.
