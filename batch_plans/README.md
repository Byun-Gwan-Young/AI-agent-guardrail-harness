# batch_plans — 배치 실행 계획

`tools/run_batch.py` 가 읽는 계획 파일입니다. 항목마다 시나리오·모드(관측 / 차단)·반복 번호가 있고, 레인 수로 나눠 창마다 한 레인씩 돌립니다.
계획 파일은 실행 기록(레인 기록의 `plan_sha256`)과 바이트 단위로 맞아야 하므로 **내용도 이름도 바꾸지 않습니다** (DM-84). `demo-main-v1.yaml` 은 최종 동결 62 파일에 들어 있습니다.

## 본 실행 (C-19)

| 파일 | 무엇인지 | 항목 | sha256 (앞 8 자리) | 결정 |
|---|---|---|---|---|
| [`demo-main-v1.yaml`](demo-main-v1.yaml) | 데모 본 실행 — 관측 55 + 차단 15, 레인 4 개 (계정 A·B·C + LR 전용 D) | 70 | `d12faf74` | DM-63, DM-75 |
| [`demo-main-v1-lr2.yaml`](demo-main-v1-lr2.yaml) | LR 보충 — arXiv 장애로 뺀 본 실행 LR 13 항목을 다시 (관측 10 + 차단 3) | 13 | `09cc3ef0` | DM-78 ④, DM-80 |
| [`demo-main-v1-mr2.yaml`](demo-main-v1-mr2.yaml) | MR 보충 — 검색 키 오타(401)로 뺀 MR 3 항목을 다시 | 3 | `e45d2ca0` | DM-81, DM-82 |

## 발표용 실시간 실행 (C-19-4 · C-19-7)

| 파일 | 무엇인지 | 항목 | sha256 (앞 8 자리) | 결정 |
|---|---|---|---|---|
| [`demo-live-v1.yaml`](demo-live-v1.yaml) | 발표 당일 실시간 실행 — CT 교착판 차단 1 (주) + CL 교착판 차단 1 (대비), 레인 2 개 | 2 | `83a25d44` | DM-88 ③, DM-94 |
| [`demo-live-rehearsal-v1.yaml`](demo-live-rehearsal-v1.yaml) | 리허설 — `demo-live-v1` 과 항목 · 레인 · 조건이 같고 계획 ID 만 다름 (리허설이 발표 항목을 써 버리지 않게) | 2 | `790cbeac` | DM-94 ① |

명령은 `reports/c19-4/pm-commands.md` 4 절 (발표), `reports/c19-7/pm-commands.md` (리허설) 에 있습니다.

## 시험 실행 (C-18, 과제가 의도대로 동작하는지 확인)

| 파일 | 무엇인지 | 결정 |
|---|---|---|
| [`demo-trial-c18-2.yaml`](demo-trial-c18-2.yaml) | DEMO-CT 정상판·교착판, DEMO-CT-N 시험 각 1 회 (관측) | DM-65 |
| [`demo-trial-c18-3.yaml`](demo-trial-c18-3.yaml) | DEMO-CS·MR·LR 정상판·교착판 시험 각 1 회 (관측) | DM-67 |
| [`demo-trial-c18-4.yaml`](demo-trial-c18-4.yaml) | DEMO-CS·MR 정상판·교착판 재시험 각 1 회 (관측) | DM-69, DM-70 |
| [`demo-trial-c18-5.yaml`](demo-trial-c18-5.yaml) | DEMO-MR 정상판·교착판 재시험 각 1 회 (관측) | DM-73, DM-74 |

실행 명령과 순서는 `reports/c18-6/pm-commands.md` (본 실행), `reports/c18-7/pm-commands.md` (재실행), `reports/c18-8/pm-commands.md` (기록·집계) 에 있습니다.
