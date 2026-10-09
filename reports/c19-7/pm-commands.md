# C-19-7 AWS 배포 준비 — PM 명령서

데모 화면과 조회 API 를 AWS 서버 한 대(서울)에 올려 팀원 · 교수님만 보게 한다 (DM-91 · DM-93). Claude Code 는 AWS 에 접속하지 않았다. 아래는 모두 **PM 이 맥의 저장소 루트(main)에서** 돌린다. 블록 하나에 명령 하나다. 비밀번호 · AWS 접근 키는 채팅 · 파일 · 저장소에 쓰지 않는다. 구성과 파일 설명은 [`deploy/aws/README.md`](../../deploy/aws/README.md).

```text
브라우저 ──HTTPS · 사이트 비밀번호──▶ Caddy (80·443) ──/──▶ 데모 화면 (정적, --api 빌드)
                                          └──/api/* · /docs · /redoc · /openapi.json──▶ 조회 API 127.0.0.1:8020 ──소켓·peer──▶ PostgreSQL guardrail_demo
```

## ⓪ AWS 준비 (콘솔 + 맥, 한 번)

콘솔에서 (Claude Code 가 대신하지 않는다) :

1. IAM 사용자 `guardrail-deploy` 를 만들고 권한 `AmazonEC2FullAccess` 를 붙인다. 도메인 DNS 를 Route 53 에서 관리하면 `AmazonRoute53FullAccess` 도 붙인다 (없으면 `provision.sh` 가 등록 업체에 넣을 값을 출력한다). 루트 계정 키는 만들지 않는다
2. 그 사용자의 접근 키를 만든다 (용도 "CLI")
3. 결제 → 예산에서 월 예산 알림을 켠다 (DM-93 ⑥)

`AmazonEC2FullAccess` 에는 SSM 파라미터 읽기 권한이 없다. `provision.sh` 는 SSM 공개 파라미터를 먼저 읽고, 거절되면 Canonical 이미지 목록(EC2 권한)에서 최신 Ubuntu 24.04 를 찾는다. 권한을 더 붙일 필요는 없다.

AWS CLI 확인 (없으면 `brew install awscli`)

```bash
aws --version
```

접근 키를 넣는다 (대화형 — 키는 이 창에만 입력한다. 리전은 `ap-northeast-2`, 출력 형식 `json`)

```bash
aws configure
```

```bash
aws sts get-caller-identity
```

`Arn` 이 `…:user/guardrail-deploy` 인지 본다. 계정 ID 는 화면에만 둔다.

## ① 서버 만들기 (`provision.sh`)

먼저 dry-run : 도메인을 묻고, 이미 있는 것 · 만들 것을 보여 준다. 아무것도 만들지 않는다.

```bash
deploy/aws/provision.sh
```

계획이 맞으면 만든다 (도메인을 다시 묻고, `yes` 를 입력해야 만든다). 키 페어 `~/.ssh/guardrail-demo.pem` (권한 400), 보안 그룹 (SSH 는 지금 공인 IP/32 만), t3.small · 20 GiB gp3, 탄력적 IP, (Route 53 이면) A 레코드, 그리고 `deploy/aws/target.env` (git 제외).

```bash
deploy/aws/provision.sh --apply
```

Route 53 이 아니면 끝에 나온 A 레코드 (이름 · A · 탄력적 IP · TTL 300) 를 도메인 등록 업체에 넣는다. 반영 확인 :

```bash
deploy/aws/remote.sh dns
```

장소가 바뀌어 SSH 가 막히면 SSH 허용 IP 만 바꾼다 :

```bash
deploy/aws/provision.sh --update-ssh-ip
```

`provision.sh` 를 쓰지 않고 콘솔로 만들었다면 대신 :

```bash
deploy/aws/configure.sh
```

## ② 첫 SSH 접속 확인

켜진 직후면 1~2 분 기다린다. 호스트 키를 기억하고 로그인한다. 확인 뒤 `exit`.

```bash
deploy/aws/remote.sh ssh
```

## ③ 서버 준비 (한 번, 다시 돌려도 안전)

PostgreSQL · Caddy (공식 apt 저장소) · uv · Python 3.14, 사용자 `guardrail`, DB 역할 · DB `guardrail_demo` (비밀번호 없음), 서비스 가상환경. 몇 분 걸린다.

```bash
deploy/aws/remote.sh setup
```

끝에 PostgreSQL 버전, `listen_addresses` (`localhost` 여야 함), Caddy · uv · 서비스 Python 버전이 나온다.

## ④ 사이트 비밀번호 (임시 — C-19-8 에서 구글 로그인으로 바꾼다)

사용자 이름 (Enter = `guardrail`) 과 비밀번호 (12 자 이상, 두 번, 화면에 안 보임) 를 서버에서 입력한다. 해시만 서버 `/etc/guardrail/caddy.env` 에 남는다. 비밀번호는 팀에 따로 전한다.

```bash
deploy/aws/remote.sh password
```

## ⑤ 배포

main 의 커밋된 파일만 간다. 맥에서 묶음 (화면 `--api` 빌드 + 검사) → 서버로 보내기 → 서버에서 `storage init` · `storage demo-all` · `service.load_demo check` (19 개 중 하나라도 다르면 멈추고 이전 상태 유지) → API 재시작 → Caddy. 끝에 `https://도메인/api/summary` 를 사이트 비밀번호로 확인한다 (curl 이 비밀번호를 묻는다).

```bash
git log --oneline -1 main
```

```bash
deploy/aws/deploy.sh
```

**서버의 첫 PostgreSQL 확인 결과** (DM-97 ②) 는 `reports/c19-7/server-check-postgres.json` 으로 내려온다. 화면에 `서버 PostgreSQL check : ok=True · 비교 19 개 · 다름 0` 이 나와야 한다. 커밋해 둔다 (C-19-8 파트 0 이 확인한다) :

```bash
git add reports/c19-7/server-check-postgres.json
```

```bash
git commit -m "C-19-7: server PostgreSQL check result"
```

묶음만 미리 보고 싶으면 (네트워크 없음, `/tmp/guardrail-bundle/bundle-files.txt` 에 파일 목록) :

```bash
deploy/aws/deploy.sh --bundle-only /tmp/guardrail-bundle
```

## ⑥ 확인 (브라우저)

```bash
deploy/aws/remote.sh open
```

- 비밀번호 창 → 데모 화면. **맨 아래 출처 줄이 "데이터 : DB (조회 API) — …"** 이면 API 모드다 ("데이터 : 파일에 담긴 기록 (조회 API 응답 없음 …)" 이면 API 가 응답하지 않은 것)
- 대시보드 카드 : 오탐 4 / 24 (그중 2) · 교착 탐지 8 / 9 · 아꼈을 토큰 60.8 % · 판정 p99 0.41 ms — 최종 보고서와 같아야 한다
- 같은 창 주소 뒤에 `/api/summary` 와 `/docs` (Swagger 화면은 브라우저가 `cdn.jsdelivr.net` 에서 받는다. 발표장 인터넷이 없으면 `/api/summary` 로 보여 준다, DM-90 ③)
- 실시간 모니터 메뉴는 "실시간 서버가 꺼져 있습니다" 가 맞다 (실시간 실행은 맥에서)

서버 상태 :

```bash
deploy/aws/remote.sh status
```

## ⑦ 다시 배포

main 에 커밋한 뒤 같은 명령. 새 릴리스에서 확인이 모두 같을 때만 바뀐다 (최근 3 개 보관).

```bash
deploy/aws/deploy.sh
```

## ⑧ 끄기 (발표 뒤)

태그 `project=guardrail-demo` 자원을 보여 주고, `delete` 를 입력해야 지운다 (탄력적 IP 해제 · 인스턴스 종료 · 보안 그룹 · 키 페어).

```bash
deploy/aws/teardown.sh
```

그다음 콘솔에서 : 도메인 A 레코드 삭제, IAM 사용자 `guardrail-deploy` 의 접근 키 **비활성화 → 삭제**, 예산 알림 확인. 잠시만 멈추려면 EC2 콘솔에서 인스턴스 "중지" (멈춘 동안에도 디스크 · 공인 IP 는 과금).

## ⑨ 합치기 뒤 worktree 정리 (`c19-3`, `c19-6`)

두 브랜치는 main 에 합쳐졌고 (C-19-4 · C-19-6), 두 worktree 에 커밋 안 된 파일이 없다 (10/9 확인).

```bash
git worktree list
```

```bash
git worktree remove ../AI-agent-guardrail-harness-c19-3
```

```bash
git worktree remove ../AI-agent-guardrail-harness-c19-6
```

```bash
git branch -d c19-3-demo-ui
```

```bash
git branch -d c19-6-db-api
```

## 리허설용 실시간 실행 (DM-94 ①, 맥 프록시)

계획 `batch_plans/demo-live-rehearsal-v1.yaml` — 발표용 `demo-live-v1` 과 항목 · 레인 · 조건이 같고 계획 ID 만 다르다 (리허설이 발표 항목을 써 버리지 않게). CT 교착판 차단 1 (레인 1, 계정 A) + CL 교착판 차단 1 (레인 2, 계정 B), 두 레인 동시 약 13 분 · 87~107 크레딧 (C-19-4 명령서 0 절의 실측 범위). 교착이 안 나면 30 step 까지 가고 더 든다. 서버 게이트웨이로 도는 리허설 · 발표 계획은 C-19-9 에서 정한다.

모니터 (창 M)

```bash
venv/bin/python -B tools/demo_live.py serve
```

```bash
open http://127.0.0.1:8010/#live
```

창 Q — 차단 프록시 (포트 8001)

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

`differences` 가 빈 목록이어야 한다.

창 1 (계정 A) — 레인 1 : CT 교착판 차단

```bash
export KMU_API_KEY="$(pbpaste)"
```

```bash
echo ${#KMU_API_KEY}
```

```bash
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-live-rehearsal-v1.yaml --lane 1 --lanes 2 --account-label A
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
venv/bin/python -B tools/run_batch.py run --plan batch_plans/demo-live-rehearsal-v1.yaml --lane 2 --lanes 2 --account-label B
```

```bash
unset KMU_API_KEY
```

진행 확인 (아무 창)

```bash
venv/bin/python -B tools/run_batch.py status --plan batch_plans/demo-live-rehearsal-v1.yaml --lanes 2
```

모니터 화면에서 두 세션이 "진행 중" 으로 뜨고, STOP 이 나면 원인 문장 알림과 403 칸이 보인다. 끝나면 창 Q 의 프록시와 창 M 의 모니터를 Ctrl+C 로 끈다. 리허설 세션은 계획 ID `demo-live-rehearsal-v1` 이라 본 실행 집계에 들어가지 않는다. 기록 · 커밋은 이 명령서 범위가 아니다.
