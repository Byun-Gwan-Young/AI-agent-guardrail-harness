# C-18-8 PM 명령 — 합치기 · 제외 목록 · 기록 · 집계 · 재생 페이지 · 커밋 · 원본 백업 (DM-53 형식)

순서 : **브랜치 합치기 → 키 넣기 → 제외·대체 목록 → 계획마다 `record`·`check` → 제외·보정을 넣은 `aggregate` → `pages` → 계획마다 `stage` → 커밋 → 계획마다 원본 백업**. 명령 블록 하나에 명령 하나. 모두 창 1, 저장소 폴더(`~/AI-agent-guardrail-harness`)에서 한다. 외부 호출과 세션 실행은 없다.

## 0. 지금 상태 (C-18-8 시작 시)

- `demo-main-v1` 레인 1~4, `demo-main-v1-lr2`, `demo-main-v1-mr2` 모두 `lane_finished`. 세션 98 개 (본 실행 82 · LR 보충 13 · MR 보충 3), 아직 `record` 된 세션 0 개
- 제외·대체 목록을 미리 돌린 값 (같은 기록) : 제외 31 (`env_search_unavailable` 13, `env_search_key_invalid` 3, `incomplete_after_retry` 2, `env_upstream_timeout` 9, `env_upstream_502` 3, `run_interrupted` 1), 대체 28, `unresolved` 0. 항목 70 개 중 유효 67, 유효 세션 없음 3 (`DEMO-CL-stall-v1:observe:2`, `DEMO-CT-stall-v1:block:3`, `DEMO-LR-stall-v1:block:3`)
- **LR 보충의 `445ab1ba…` (0 step `user_interrupted`) 는 `steps.json` 이 없어서 `record` 가 오류로 멈춘다.** 그래서 `demo-main-v1-lr2` 의 `record`·`check`·`stage` 는 `--plan` 대신 나머지 12 세션을 이름으로 준다. 이 세션은 제외 목록(`run_interrupted`)과 원본 백업에만 남는다

## 1. 브랜치 합치기

```bash
cd ~/AI-agent-guardrail-harness
```

```bash
git status --short
```

출력이 비어 있어야 한다. 비어 있지 않으면 멈춘다.

```bash
git checkout main
```

```bash
git merge --ff-only c18-8
```

fast-forward 가 안 되면 다음을 쓴다.

```bash
git merge --no-edit c18-8
```

```bash
venv/bin/python -B tools/final_freeze.py check
```

`"ok": true`, `sha256` `6a7bf8dc…` 이어야 한다.

## 2. 키 넣기 (기록 키 검사용)

`record`·`stage`·`backup` 은 이 창에 있는 키 값이 파일에 없는지도 검사한다. **Tavily 키는 길이를 꼭 본다** (9 글자면 잘못 붙여 넣은 것, DM-81).

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

## 3. 제외·대체 목록

```bash
venv/bin/python -B tools/demo_exclusions.py --plan demo-main-v1 --plan demo-main-v1-lr2 --plan demo-main-v1-mr2 --output reports/c18-8/exclusions.json
```

끝 코드가 0 이고 `counts` 가 0 절의 값과 같아야 한다. 끝 코드가 1 (`unresolved` 있음)이면 멈추고 출력을 보고한다.

## 4. 기록 (`record` → `check`)

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1
```

```bash
venv/bin/python -B tools/demo_records.py record runs/demo/DEMO-LR-normal-v1-2ca98307d99344be837b416875873b96 runs/demo/DEMO-LR-normal-v1-447141e1675941319897a94157fb786b runs/demo/DEMO-LR-normal-v1-7ed9090de9d04c56a166599c9c5fe5d6 runs/demo/DEMO-LR-normal-v1-af33de48dd324447b205dc711caf619f runs/demo/DEMO-LR-normal-v1-f8caef5d1e56489397d29198dccd488c runs/demo/DEMO-LR-stall-v1-53b21638e64745aba1048f342229208c runs/demo/DEMO-LR-stall-v1-69bf46e3950045668c6686756f0134ec runs/demo/DEMO-LR-stall-v1-6e073f2122c14377bee7b55a00a84196 runs/demo/DEMO-LR-stall-v1-7c6a57c507ae4dcfb3da6c581f0949d9 runs/demo/DEMO-LR-stall-v1-8a25037bd6f04bd2b3e1b8bf482373d0 runs/demo/DEMO-LR-stall-v1-b9da451106144cecae3f68734dc832dc runs/demo/DEMO-LR-stall-v1-c0618659f74043fdb78d4fd6314eb57a
```

```bash
venv/bin/python -B tools/demo_records.py record --plan demo-main-v1-mr2
```

```bash
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1 --index
```

```bash
venv/bin/python -B tools/demo_records.py check runs/demo/DEMO-LR-normal-v1-2ca98307d99344be837b416875873b96 runs/demo/DEMO-LR-normal-v1-447141e1675941319897a94157fb786b runs/demo/DEMO-LR-normal-v1-7ed9090de9d04c56a166599c9c5fe5d6 runs/demo/DEMO-LR-normal-v1-af33de48dd324447b205dc711caf619f runs/demo/DEMO-LR-normal-v1-f8caef5d1e56489397d29198dccd488c runs/demo/DEMO-LR-stall-v1-53b21638e64745aba1048f342229208c runs/demo/DEMO-LR-stall-v1-69bf46e3950045668c6686756f0134ec runs/demo/DEMO-LR-stall-v1-6e073f2122c14377bee7b55a00a84196 runs/demo/DEMO-LR-stall-v1-7c6a57c507ae4dcfb3da6c581f0949d9 runs/demo/DEMO-LR-stall-v1-8a25037bd6f04bd2b3e1b8bf482373d0 runs/demo/DEMO-LR-stall-v1-b9da451106144cecae3f68734dc832dc runs/demo/DEMO-LR-stall-v1-c0618659f74043fdb78d4fd6314eb57a
```

```bash
venv/bin/python -B tools/demo_records.py check --plan demo-main-v1-mr2
```

세 `check` 모두 `"ok": true` 여야 한다.

## 5. 집계 (제외 목록 + 계정 보정) → 재생 페이지

```bash
venv/bin/python -B tools/aggregate_demo.py --plan demo-main-v1 --plan demo-main-v1-lr2 --plan demo-main-v1-mr2 --final-freeze-sha256 "$(shasum -a 256 docs/criteria/demo-final-freeze.json | cut -d ' ' -f 1)" --exclusions reports/c18-8/exclusions.json --account-corrections reports/c18-8/account-corrections.json --output-json reports/c19/aggregate-main.json --output-md reports/c19/aggregate-main.md
```

출력 머리에 "제외·대체 목록 (demo-exclusions-v2)" 줄이 있어야 하고, **"목록에 없는 세션" 줄이 없어야 한다** (있으면 3 절부터 다시). 집계는 기록이 있는 세션만 보므로 `445ab1ba…` 는 집계에 나오지 않는다 (제외 목록에는 있음). 끝에 "계정별 실측 크레딧" 과 "보정 표 적용" 두 절이 함께 나온다.

```bash
venv/bin/python -B tools/replay_demo.py pages reports/c19/aggregate-main.json --output-dir reports/c19/replay
```

## 6. stage → 커밋

```bash
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1
```

```bash
venv/bin/python -B tools/demo_records.py stage runs/demo/DEMO-LR-normal-v1-2ca98307d99344be837b416875873b96 runs/demo/DEMO-LR-normal-v1-447141e1675941319897a94157fb786b runs/demo/DEMO-LR-normal-v1-7ed9090de9d04c56a166599c9c5fe5d6 runs/demo/DEMO-LR-normal-v1-af33de48dd324447b205dc711caf619f runs/demo/DEMO-LR-normal-v1-f8caef5d1e56489397d29198dccd488c runs/demo/DEMO-LR-stall-v1-53b21638e64745aba1048f342229208c runs/demo/DEMO-LR-stall-v1-69bf46e3950045668c6686756f0134ec runs/demo/DEMO-LR-stall-v1-6e073f2122c14377bee7b55a00a84196 runs/demo/DEMO-LR-stall-v1-7c6a57c507ae4dcfb3da6c581f0949d9 runs/demo/DEMO-LR-stall-v1-8a25037bd6f04bd2b3e1b8bf482373d0 runs/demo/DEMO-LR-stall-v1-b9da451106144cecae3f68734dc832dc runs/demo/DEMO-LR-stall-v1-c0618659f74043fdb78d4fd6314eb57a
```

```bash
venv/bin/python -B tools/demo_records.py stage --plan demo-main-v1-mr2
```

```bash
git add reports/c19 reports/c18-8/exclusions.json
```

```bash
git status --short | head -20
```

```bash
git commit -m "chore: C-19 main run, LR and MR supplement records, exclusion list v2, aggregation with account corrections, replay pages (C-18-8 part 4)"
```

## 7. 원본 백업 (계획마다, 저장소 밖)

```bash
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1 --output ../demo-backup/demo-main-v1-raw.tar.gz
```

```bash
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1-lr2 --output ../demo-backup/demo-main-v1-lr2-raw.tar.gz
```

```bash
venv/bin/python -B tools/demo_records.py backup --plan demo-main-v1-mr2 --output ../demo-backup/demo-main-v1-mr2-raw.tar.gz
```

LR 보충 백업은 `445ab1ba…` 를 포함한 13 세션이다. 세 출력 모두 `key_scan` 의 `clean` 이 true 여야 한다. 백업 파일 3 개를 팀 드라이브에 옮긴다.

```bash
unset KMU_API_KEY TAVILY_API_KEY
```

## 다음

이 명령을 마치면 C-19-2 (본 실행 검증 + 최종 보고) 의 시작 조건이 채워진다 (`reports/c19/aggregate-main.json` 이 제외·대체 목록을 넣고 만들어짐).
