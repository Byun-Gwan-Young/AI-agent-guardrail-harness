#!/usr/bin/env bash
# C-19-7 (DM-91) : prepare the demo server once. Runs ON THE SERVER as root (deploy/aws/remote.sh setup sends it).
# Safe to run again : every step checks first and skips what is already there.
#
#   sudo bash server-setup.sh
#
# Installs PostgreSQL (Ubuntu 24.04 package), Caddy (official apt repository), pipx and uv, and Python 3.14 through
# uv (the repository runs on 3.14 ; Ubuntu 24.04 ships 3.12). Makes the system user guardrail, the folders under
# /opt/guardrail and /etc/guardrail, the PostgreSQL role guardrail (same name as the system user : Unix-socket peer
# authentication, no password) owning the database guardrail_demo, the service venv, the API environment file (the
# database URL only) and the systemd drop-in that hands /etc/guardrail/caddy.env to Caddy. PostgreSQL keeps its default
# (localhost only) and the security group has no database port.
set -euo pipefail

PYTHON_VERSION=3.14
DB_NAME=guardrail_demo
DB_URL='postgresql:///guardrail_demo?host=/var/run/postgresql'
export UV_PYTHON_INSTALL_DIR=/opt/guardrail/python
export PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin

die() { printf '중단 : %s\n' "$*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

[[ $(id -u) -eq 0 ]] || die "root 로 돌린다 (sudo bash server-setup.sh)"
. /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || die "Ubuntu 24.04 가 아니다 (${PRETTY_NAME:-?})"
export DEBIAN_FRONTEND=noninteractive

step "패키지 (PostgreSQL · pipx · Caddy 저장소 준비)"
apt-get update -q
apt-get install -y -q postgresql debian-keyring debian-archive-keyring apt-transport-https curl gnupg pipx

step "Caddy (공식 apt 저장소)"
if [[ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]]; then
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
fi
if [[ ! -f /etc/apt/sources.list.d/caddy-stable.list ]]; then
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
fi
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get install -y -q caddy

step "uv · Python $PYTHON_VERSION"
command -v uv >/dev/null || pipx install uv
install -d -o root -g root -m 755 /opt/guardrail /opt/guardrail/releases /opt/guardrail/python
uv python install "$PYTHON_VERSION"

step "사용자 guardrail · 폴더"
id guardrail >/dev/null 2>&1 || useradd --system --home-dir /opt/guardrail --no-create-home --shell /usr/sbin/nologin guardrail
install -d -o guardrail -g guardrail -m 755 /opt/guardrail/checks
install -d -o root -g guardrail -m 750 /etc/guardrail

step "서비스 가상환경 /opt/guardrail/venv (패키지는 deploy 때 requirements-server.txt 로)"
[[ -x /opt/guardrail/venv/bin/python ]] || uv venv --python "$PYTHON_VERSION" /opt/guardrail/venv
chmod -R a+rX /opt/guardrail/python /opt/guardrail/venv

step "PostgreSQL 역할 guardrail · DB $DB_NAME (유닉스 소켓 peer 인증, 비밀번호 없음)"
systemctl enable --now postgresql
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'guardrail'" | grep -q 1; then
    runuser -u postgres -- createuser guardrail
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
    runuser -u postgres -- createdb -O guardrail "$DB_NAME"
fi

step "API 환경 파일 (DB 주소만) · Caddy 환경 drop-in"
printf 'GUARDRAIL_DB_URL=%s\n' "$DB_URL" > /etc/guardrail/api.env
chown root:guardrail /etc/guardrail/api.env && chmod 640 /etc/guardrail/api.env
[[ -f /etc/guardrail/caddy.env ]] || install -o root -g root -m 600 /dev/null /etc/guardrail/caddy.env
install -d -m 755 /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/guardrail.conf <<'EOF'
# systemd drop-in for caddy.service (C-19-7) : hands the domain to Caddy (Caddyfile {$...}).
[Service]
EnvironmentFile=-/etc/guardrail/caddy.env
EOF
systemctl daemon-reload

step "확인"
printf 'PostgreSQL : %s\n' "$(runuser -u postgres -- psql -tAc 'SHOW server_version')"
printf 'listen_addresses : %s\n' "$(runuser -u postgres -- psql -tAc 'SHOW listen_addresses')"
printf 'Caddy : %s\n' "$(caddy version | head -n 1)"
printf 'uv : %s\n' "$(uv --version)"
printf '서비스 Python : %s\n' "$(/opt/guardrail/venv/bin/python --version)"
printf '\n준비 끝. 다음 : 배포 (deploy/aws/deploy.sh)\n'
