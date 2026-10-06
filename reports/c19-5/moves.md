# C-19-5 파트 1 — 옮기기 결과

> 근거 : `reports/c19-5/inventory.md` 7 절 (분류가 문서·보고·기타이고 전체 경로·파일 이름·모듈 이름 참조가 모두 0 인 파일 129 개 : 문서 30, 보고 99).

## 결과 : 옮긴 파일 0 개

옮기려던 8 개의 `git mv` 가 이 세션의 권한 분류기에서 거부됐다 ("Modify Shared Resources"). 다른 방법으로 우회하지 않았다. 아래 명령은 PM 이 원할 때 직접 실행한다.

### 옮기려던 것 — `docs/` 바로 아래의 초기 메모 → `docs/early/`

| 경로 | 이유 |
|---|---|
| `docs/A-1-review.md` | 참조 0, 상대 링크 없음, 2026-09-15 초기 메모 |
| `docs/A1-revision2-budget.md` | 같음 |
| `docs/A1-tool-failure-recovery.md` | 같음 |
| `docs/P0-2-replay-protocol.md` | 같음 |
| `docs/S1-session-isolation.md` | 같음 |
| `docs/S3-B-runner-review.md` | 같음 |
| `docs/S3-C-legacy-results.md` | 같음 |
| `docs/scenario_schema.md` | 같음 |

PM 명령 (저장소 루트, 한 블록에 명령 하나) :

```bash
mkdir -p docs/early
```

```bash
git mv docs/A-1-review.md docs/A1-revision2-budget.md docs/A1-tool-failure-recovery.md docs/P0-2-replay-protocol.md docs/S1-session-isolation.md docs/S3-B-runner-review.md docs/S3-C-legacy-results.md docs/scenario_schema.md docs/early/
```

옮긴 뒤에는 `docs/README.md` 의 마지막 표 링크 8 개를 `early/…` 로 고치고, `venv/bin/python -B -m unittest tests.test_repository_maps` 를 다시 돌린다 (링크가 실제 경로인지 검사).

## 옮기지 않은 것 (참조 0 이지만)

| 묶음 | 수 | 이유 |
|---|---|---|
| `docs/S3-A-progress.md` | 1 | 본문에 상대 링크(`decisions/005-…`)가 있어 옮기면 링크가 깨진다. 내용을 고쳐야 하므로 애매 → 그대로 |
| `docs/S3-C-기존로그적용결과.md` | 1 | `docs/S3-C-legacy-results.md` 와 바이트가 같은 사본. 옮기면 한글 경로를 새로 만드는 것이라 금지. 지우는 것도 금지 → PM 판단 (보고 6 절) |
| `docs/decisions/` 번호 문서 | 18 | 번호 순 묶음의 일부. 하나씩 빼면 묶음이 깨진다 |
| `docs/findings/` 근거 파일 | 2 | 같은 폴더의 분석 문서가 쓰는 자료 |
| `reports/` 단위 폴더의 파일 | 97 | 단위 폴더가 곧 그 작업의 기록이다. 테스트 결과·preflight·재판정 기록을 폴더 밖으로 빼면 기록 묶음이 흩어진다 (DM-84 ①) |
| `reports/` 바로 아래 파일 | 2 | `A-1-initial-tests.json`, `A-1-token-estimate.json` (초기 A-1 결과). `reports/README.md` 에 설명만 붙임 |

합 : 8 (옮기려던 것) + 1 + 1 + 18 + 2 + 97 + 2 = 129.

## 추적되지 않는 캐시·잡동사니 (지우지 않음)

| 경로 | `.gitignore` | 비고 |
|---|---|---|
| `__pycache__/`, `experiments/__pycache__/`, `tools/__pycache__/`, `tests/__pycache__/`, `scenario_judges/__pycache__/` | 있음 (`__pycache__/`, `*.pyc`) | — |
| `.DS_Store`, `docs/.DS_Store` | **없음** (추적 안 됨으로 보임) | macOS 폴더 정보. `.gitignore` 에 `.DS_Store` 를 넣을지 PM 판단 |
| `docs/handoff/experiment_config.py` | 있음 (`docs/handoff/`) | 루트 `experiment_config.py` (8,359 바이트) 와 다른 105,181 바이트 파일 (내용은 열지 않음). 인계 폴더에 섞인 것으로 보임 → PM 확인 |
| `runs/demo/` 원본, `logs/demo/`, `runs/demo-batches/` | 있음 (`runs/`, `logs/`) | DM-64 ⑤ 대로 로컬·백업 |
