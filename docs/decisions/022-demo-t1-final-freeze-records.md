# 데모 기록 커밋 규칙 · DEMO-CS·MR·LR (T1) · 최종 동결 (C-18-3)

- 상태 : C-18-3 구현 기록
- 근거 : 가이드라인 13 장 DM-5·DM-6·DM-13·DM-15·DM-18·DM-19·DM-21·DM-26·DM-29·DM-31·DM-33·DM-45·DM-46·DM-51·DM-52·DM-63·DM-64,
  설계 `docs/design/demo-scenarios.md` 1~3 절, `docs/design/demo-runner-extension.md` 2~5 절, 결정 문서 016·018·021
- PM 의 CT·CT-N 시험(DM-64 ⑥)과 같은 시간에 진행했다. 이 단위는 그 시험이 만드는 `runs/demo`·`logs/demo`·`runs/demo-batches` 파일을
  읽거나 커밋하지 않았다. 작업은 별도 git worktree 에서 하고 끝에 main 으로 옮겼다 (작업 중 수정이 시험 세션의 코드·`git_dirty` 에 섞이지 않게)

## 파트 0 — 데모 기록 커밋 규칙 (DM-64 ⑤) `tools/demo_records.py` (`demo-records-v1`)

**규칙** : 데모 세션 폴더 `runs/demo/<id>/` 에서 저장소에 넣는 파일은 아래 `COMMIT_FILES` 뿐이다. 나머지와 `logs/demo/` 는 로컬에 두고
저장소 밖 압축 백업으로 보관한다.

| 커밋한다 (작은 파일) | 커밋하지 않는다 (원본, 백업) |
|---|---|
| `conditions.json`, `summary.json`, `scenario.yaml`, `registered-tools.json`, `prompt-trend.json` (실행기 기록) | `session.json` (프록시 로그 사본, 교착 세션 약 7 MB) |
| `record/manifest.json` (`analyze_session` 매니페스트, phase demo) | `steps.json` (모델 보고 포함), `observations/` (원 관측) |
| `record/demo-summary.json` (요약 도구 출력, 키 검사 포함) | `workspace/`, `search/` (검색 원문), `tool-dispatch.json` |
| `record/judgements.json` (step 별 진전 상태·판정·STOP·원인 설명 문장과 값·`judgement_ns`. 모델 문장 없음) | `logs/demo/<id>.json` (프록시 로그) |

- **크기 상한** : 파일 하나 256 KiB, 세션 하나(커밋 파일 합) 1 MiB. C-18-1 세 세션은 35 KB · 53 KB · 216 KB (30 step 교착판의 `judgements.json` 99 KB 가 가장 크다).
  원본은 세션 폴더 + 프록시 로그로 각각 0.13 · 2.18 · 14.95 MB (프록시 로그가 `session.json` 으로 한 벌 더 있다)
- **`.gitignore` 로 막기** : `runs/`·`logs/` 는 이미 전부 무시 대상이다 (S-29). 그래서 일반 `git add` 로는 세션 파일이 하나도 들어가지 않고,
  들어가는 길은 `git add -f` 뿐이다. 그 길을 `stage` 하나로 좁혔다 (허용 목록만 `-f`). 작은 파일을 `.gitignore` 예외(`!`)로 풀지 않은 이유 :
  풀면 그 파일들이 추적 안 된 파일로 보여 다음 세션의 `git_dirty` 가 참이 된다 (`git status --untracked-files=all`, S-7). 병렬 본 실행의 모든 세션이
  dirty 로 기록된다. `.gitignore` 에는 규칙을 주석으로 적었다
- **도구**
  - `record <세션>…` : `record/` 세 파일을 만든다. 폴더 키 검사(D-11 패턴 + 이 창의 `KMU_API_KEY`·`TAVILY_API_KEY` 값)가 깨끗하지 않으면 아무것도 쓰지 않는다
  - `check <세션>…` / `check --index` : 필수 파일·크기 상한 / 지금 인덱스의 `runs/demo`·`logs/demo` 추적 파일이 규칙을 지키는지 (테스트가 이 체크아웃에 돈다)
  - `stage <세션>…` : 검사 + 커밋 파일 키 검사 뒤 정확히 그 파일만 `git add -f`. 커밋은 사람이 한다
  - `backup <세션>… --output <저장소 밖>.tar.gz` : 세션 폴더 전체 + 프록시 로그를 한 파일로. 묶기 전에 원본 전체를 키 검사하고 걸리면 쓰지 않는다.
    저장소 안 경로·이미 있는 파일은 거절한다. 압축 안 `backup-files.json` 에 파일마다 크기·sha256, 프록시 로그가 없는 세션 목록
- **C-18-1 시험 세션 3 개** : 이 규칙으로 맞췄다. `git rm --cached` 로 원본 254 개 파일과 `logs/demo` 3 개를 인덱스에서 뺐고(파일은 로컬에 남음),
  `record` 로 만든 세 파일을 더해 세션마다 8 개, 합 24 개만 추적한다. 이력은 다시 쓰지 않았다 (원본은 이전 커밋 `85a70aa` 에 남아 있다)
- **C-19 재생 페이지** : 로컬 원본(또는 백업)에서 만들고, 페이지에 필요한 값만 담은 결과물을 커밋한다 (C-19-1)

테스트 `tests/test_c18_3_part0.py` : `record` 세 파일과 모델 문장 없음, 키가 있으면 아무것도 안 씀(패턴·환경 변수 값), phase 검사, 크기 상한·필수 파일,
허용 목록에 원본 없음, 임시 git 저장소에서 `stage` 가 무시된 폴더의 커밋 파일만 더함, 기록 없는 세션 거절, `check --index` 가 원본·프록시 로그를 짚음,
백업 내용·해시·프록시 로그 없음 표시, 저장소 안·덮어쓰기 거절, 원본에 키가 있으면 백업 안 씀, 이 체크아웃의 인덱스가 규칙을 지키고 원본이 무시되며
C-18-1 교착판 기록의 첫 STOP 이 step 15 E6 (DM-62 문장 그대로).
