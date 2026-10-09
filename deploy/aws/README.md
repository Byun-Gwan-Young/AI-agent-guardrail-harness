# deploy/aws — 데모 서버 (AWS EC2 한 대)

데모 화면과 조회 API 를 팀원 · 교수님만 볼 수 있게 AWS 서버 한 대로 엽니다 (C-19-7, DM-91 · DM-93). Claude Code 는 AWS 에 접속하지 않습니다. 이 폴더의 스크립트는 **PM 이 맥과 서버에서** 돌립니다. 순서와 명령은 [`reports/c19-7/pm-commands.md`](../../reports/c19-7/pm-commands.md) 에 있습니다.

## 구조

```text
브라우저 (팀원 · 교수님)
   │ HTTPS · 사이트 비밀번호 (basic auth, 임시 — C-19-8 에서 구글 로그인으로)
   ▼
Caddy  (서버, 80 · 443 만 열림, 인증서 자동)
   ├─ /                         → 데모 화면 정적 파일 (/opt/guardrail/app/site/index.html, --api 로 빌드)
   └─ /api/* · /docs · /redoc · /openapi.json
                                → 조회 API (service/api.py, 127.0.0.1:8020, 읽기 전용, systemd guardrail-api)
                                     │ 유닉스 소켓 · peer 인증 (비밀번호 없음)
                                     ▼
                                  PostgreSQL guardrail_demo (같은 서버, 외부 포트 없음)
```

화면은 서버에서 열리면 같은 서버의 `/api/summary` 를 물어보고, 응답이 오면 대시보드 카드 · 세션 표 · 세션 step 을 API(DB)에서 읽습니다. 응답이 없으면 화면 안에 담긴 기록을 그대로 씁니다. 화면 맨 아래 출처 줄에 어느 쪽인지 나옵니다 ("데이터 : DB (조회 API)" / "데이터 : 파일에 담긴 기록").

## 파일

| 파일 | 어디서 | 하는 일 |
|---|---|---|
| [`provision.sh`](provision.sh) | 맥 (AWS CLI) | 키 페어 · 보안 그룹 (SSH 는 지금 공인 IP/32 만, 80 · 443 전체) · EC2 (서울, Ubuntu 24.04, t3.small, 20 GiB gp3) · 탄력적 IP · (Route 53 이면) A 레코드. `--dry-run` 이 기본, `--apply` 일 때만 만든다. `--update-ssh-ip` 는 SSH 허용 IP 만 바꾼다. 결과로 `target.env` 를 쓴다 |
| [`teardown.sh`](teardown.sh) | 맥 (AWS CLI) | 태그 `project=guardrail-demo` 로 찾은 인스턴스 · 탄력적 IP · 보안 그룹 · 키 페어를 보여 주고, `delete` 를 입력해야 지운다 |
| [`configure.sh`](configure.sh) | 맥 | `provision.sh` 를 쓰지 않았을 때 도메인 · 서버 IP · SSH 키 경로를 물어 `target.env` 에 쓴다 |
| [`remote.sh`](remote.sh) | 맥 | `target.env` 값으로 서버에 접속 (`ssh`), 서버 준비 (`setup`), 비밀번호 설정 (`password`), 상태 (`status`) |
| [`server-setup.sh`](server-setup.sh) | 서버 (sudo, 한 번) | PostgreSQL · Caddy (공식 apt 저장소) · uv · Python 3.14, 사용자 `guardrail`, 폴더, DB 역할 · DB, 서비스 가상환경. 다시 돌려도 안전 |
| [`set-password.sh`](set-password.sh) | 서버 (sudo) | 사이트 비밀번호를 두 번 입력받아 bcrypt 해시만 `/etc/guardrail/caddy.env` 에 넣는다 |
| [`deploy.sh`](deploy.sh) | 맥 | 묶음 만들기 → 보내기 → 서버 설치 (`remote-install.sh`) → 확인 결과 가져오기 → `https://도메인/api/summary` 확인 |
| [`bundle.py`](bundle.py) | 맥 | 서버로 가는 묶음 : `git archive main` 의 포함 목록 − 제외 목록, 화면 빌드, 검사 |
| [`remote-install.sh`](remote-install.sh) | 서버 (deploy 가 실행) | 릴리스 폴더 → 가상환경 → `storage init` · `storage demo-all` · `service.load_demo check` (하나라도 다르면 멈춤, 이전 릴리스 유지) → API 재시작 → Caddy |
| [`Caddyfile.template`](Caddyfile.template) | 서버 `/etc/caddy/Caddyfile` | HTTPS, 사이트 전체 basic auth, API 로 가는 경로 목록, 보안 헤더. 도메인 · 해시는 환경 파일에서 |
| [`guardrail-api.service`](guardrail-api.service) | 서버 systemd | 조회 API (`guardrail` 사용자, `127.0.0.1:8020`, `Restart=always`) |
| [`lib.sh`](lib.sh) | — | 위 스크립트가 함께 쓰는 값 · 함수 |

`target.env` (도메인 · 서버 IP · SSH 키 경로) 는 git 에서 제외됩니다. 비밀번호 · AWS 자격 증명 · 계정 ID 는 어느 파일에도 쓰지 않습니다 (자격 증명은 맥의 `~/.aws` 에만).

## 서버로 가는 것 · 가지 않는 것

- **간다** (main 의 커밋된 파일만, `bundle.py` 의 `INCLUDE`) : `service/`, `storage/`, `deploy/aws/`, 그 둘이 가져다 쓰는 모듈 (`tools/analyze_session.py` · `tools/gateway_prices.py` · `experiments/` 의 계약 · 프로토콜 상수 3 파일 · `scenario_schema.py` · `json_subset.py` · `progress_schema.py`), 적재 · API 가 읽는 작은 기록 (`reports/c19/aggregate-main.json`, `reports/c18-8/` 제외 목록 · 계정 보정, 세션별 `summary.json` · `scenario.yaml` · `conditions.json` · `record/*.json`, `scenarios/`, `batch_plans/`, 동결 기록), 맥에서 빌드한 화면 `site/index.html`
- **가지 않는다** (`bundle.py` 의 `EXCLUDE`, 묶음 목록에서 한 번 더 검사) : 프록시 · 실행기 · 배치 실행기, KMU · Tavily 키 (`.env*`, `*.pem` 등), 세션 원본 (`logs/`, `session.json`, `steps.json` 등), `docs/handoff`, venv
- 묶음의 모든 파일을 키 패턴 · 모델 발언 필드 (narrative · reasoning 본문 · 메시지 내용) · 1 MiB 넘는 파일로 검사하고, 하나라도 걸리면 묶음을 만들지 않습니다

## 다시 배포하기

main 에 커밋한 뒤 맥에서 `deploy/aws/deploy.sh` 를 다시 돌립니다. 새 릴리스 폴더에서 적재 · 확인이 모두 같을 때만 전환하고, 최근 릴리스 3 개를 남깁니다.

## 끄기 · 비용

- **잠시 멈춤** : EC2 콘솔에서 인스턴스 중지 (디스크 · 탄력적 IP 는 남는다. 멈춘 인스턴스에 붙은 탄력적 IP 와 디스크는 계속 과금)
- **완전히 끄기** (발표 뒤) : `deploy/aws/teardown.sh` → 도메인 A 레코드 삭제 → IAM 사용자 `guardrail-deploy` 의 접근 키 비활성화 · 삭제
- 비용 (서울, 대략) : t3.small 켜 둔 동안 시간당 요금 + gp3 20 GiB + 공인 IPv4 주소 시간당 요금. 예산 알림은 PM 이 콘솔에서 직접 켭니다 (DM-93 ⑥)
