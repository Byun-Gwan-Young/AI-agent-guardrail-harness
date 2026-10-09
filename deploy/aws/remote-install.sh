#!/usr/bin/env bash
# C-19-7 (DM-91, DM-97 ①) : install one bundle ON THE SERVER as root. deploy.sh sends and runs it ; not run by hand.
#
#   sudo bash remote-install.sh BUNDLE.tar.gz DOMAIN
#
# 1. Unpack into a new release folder /opt/guardrail/releases/<commit>-<time>, update the service venv from the bundle's
#    service/requirements-server.txt (uv).
# 2. From that release, as user guardrail (peer authentication) : `python -m storage init`, `python -m storage demo-all`,
#    `python -m service.load_demo check` (the merged loader). The check result stays in /opt/guardrail/checks/. If any
#    check differs (or a step fails) the script stops HERE : the running API and site keep the previous release.
# 3. Point /opt/guardrail/app at the release, install the API unit and the Caddyfile, restart the API, reload Caddy,
#    and wait for the API on 127.0.0.1:8020. The three newest releases are kept.
set -euo pipefail

BUNDLE=${1:-}
DOMAIN=${2:-}
DB_URL='postgresql:///guardrail_demo?host=/var/run/postgresql'
PY=/opt/guardrail/venv/bin/python
CHECKS=/opt/guardrail/checks
CADDY_ENV=/etc/guardrail/caddy.env
export UV_PYTHON_INSTALL_DIR=/opt/guardrail/python

die() { printf '중단 : %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }
as_guardrail() { runuser -u guardrail -- env -i PATH=/usr/bin:/bin LANG=C.UTF-8 GUARDRAIL_DB_URL="$DB_URL" "$PY" -B "$@"; }

[[ $(id -u) -eq 0 ]] || die "root 로 돌린다"
[[ -f "$BUNDLE" ]] || die "묶음 파일이 없다 : $BUNDLE"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || die "도메인 모양이 아니다"
[[ -x "$PY" ]] || die "서비스 가상환경이 없다 (server-setup.sh 먼저)"
grep -q '^GUARDRAIL_BASIC_AUTH_HASH=' "$CADDY_ENV" 2>/dev/null || die "사이트 비밀번호가 아직 없다 (remote.sh password 먼저)"

step "풀기"
stage=$(mktemp -d /opt/guardrail/releases/.incoming.XXXXXX)
tar -xzf "$BUNDLE" -C "$stage" --no-same-owner
commit=$("$PY" -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' "$stage/DEPLOY_INFO.json")
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "DEPLOY_INFO.json 의 commit 이 없다"
release=/opt/guardrail/releases/${commit:0:12}-$(date -u +%Y%m%dT%H%M%SZ)
mv "$stage" "$release"
chown -R root:root "$release" && chmod -R a+rX,go-w "$release"
printf '릴리스 %s\n' "$release"

step "서비스 가상환경 갱신"
uv pip install --python "$PY" -q -r "$release/service/requirements-server.txt"
chmod -R a+rX /opt/guardrail/venv

step "DB : storage init → storage demo-all → service.load_demo check (DM-97 ①)"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
result="$CHECKS/check-postgres-$stamp.json"
cd "$release"
as_guardrail -m storage init
as_guardrail -m storage demo-all
set +e
as_guardrail -m service.load_demo check --output "$result" > "$CHECKS/check-postgres-$stamp.out"
status=$?
set -e
cp "$result" "$CHECKS/check-postgres-latest.json" 2>/dev/null || true
chmod 644 "$CHECKS"/check-postgres-* 2>/dev/null || true
if (( status != 0 )); then
    tail -n 40 "$CHECKS/check-postgres-$stamp.out" >&2 || true
    die "check 가 같지 않다 (종료 코드 $status). API 와 화면은 이전 릴리스 그대로다. 결과 : $result"
fi
printf 'check : 모두 같음 (%s)\n' "$result"

step "전환 : /opt/guardrail/app → 이 릴리스, API 재시작"
ln -sfn "$release" /opt/guardrail/app.next && mv -T /opt/guardrail/app.next /opt/guardrail/app
install -m 644 "$release/deploy/aws/guardrail-api.service" /etc/systemd/system/guardrail-api.service
systemctl daemon-reload
systemctl enable guardrail-api >/dev/null 2>&1
systemctl restart guardrail-api

step "Caddy : 도메인 → caddy.env, Caddyfile 설치, 확인, 다시 읽기"
tmp=$(umask 077 && mktemp "$CADDY_ENV.XXXXXX")
{ grep -v '^GUARDRAIL_DOMAIN=' "$CADDY_ENV" || true; printf 'GUARDRAIL_DOMAIN=%s\n' "$DOMAIN"; } > "$tmp"
chmod 600 "$tmp" && mv "$tmp" "$CADDY_ENV"
install -m 644 "$release/deploy/aws/Caddyfile.template" /etc/caddy/Caddyfile
( set -a; . "$CADDY_ENV"; set +a; caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null )
systemctl reload-or-restart caddy

step "API 응답 (127.0.0.1:8020)"
for _ in $(seq 1 20); do
    if curl -fsS -o /dev/null http://127.0.0.1:8020/api/summary; then
        printf 'API 응답 확인\n'
        break
    fi
    sleep 1
done
curl -fsS -o /dev/null http://127.0.0.1:8020/api/summary || { journalctl -u guardrail-api -n 30 --no-pager >&2; die "API 가 응답하지 않는다"; }

step "옛 릴리스 정리 (최근 3 개 남김)"
ls -1dt /opt/guardrail/releases/*/ | tail -n +4 | while read -r old; do
    [[ "$(readlink -f /opt/guardrail/app)/" == "$old" ]] || rm -rf -- "$old"
done
printf '\n배포 끝 : %s (commit %s)\n' "$release" "${commit:0:12}"
