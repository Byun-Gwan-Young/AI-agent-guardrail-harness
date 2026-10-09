#!/usr/bin/env bash
# C-19-7 (DM-91 ②) : set the site's shared password. Runs ON THE SERVER as root (deploy/aws/remote.sh password).
#
#   sudo bash set-password.sh
#
# Asks a user name and the password twice without echo, makes the bcrypt hash with `caddy hash-password` (the password
# goes in on standard input, never on a command line), and writes only the user name and hash to /etc/guardrail/caddy.env
# (root, 600). The plain password is not written anywhere. When the guardrail Caddyfile is installed, Caddy is checked
# and reloaded. Temporary : C-19-8 replaces the shared password with Google sign-in (DM-92 ②).
set -euo pipefail

ENV_FILE=/etc/guardrail/caddy.env
die() { printf '중단 : %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "root 로 돌린다 (sudo bash set-password.sh)"
command -v caddy >/dev/null || die "Caddy 가 없다 (server-setup.sh 먼저)"
[[ -t 0 ]] || die "터미널에서 돌린다 (ssh -t)"

read -r -p "사용자 이름 (Enter = guardrail) : " user
user=${user:-guardrail}
[[ "$user" =~ ^[A-Za-z0-9._-]{1,32}$ ]] || die "사용자 이름은 영문·숫자·._- 32 자까지"
read -r -s -p "비밀번호 (12 자 이상, 화면에 안 보임) : " pw1; printf '\n'
read -r -s -p "한 번 더 : " pw2; printf '\n'
[[ "$pw1" == "$pw2" ]] || { unset pw1 pw2; die "두 번 입력이 다르다"; }
(( ${#pw1} >= 12 )) || { unset pw1 pw2; die "12 자 이상으로"; }
hash=$(printf '%s\n' "$pw1" | caddy hash-password)
unset pw1 pw2
[[ "$hash" =~ ^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$ ]] || { unset hash; die "caddy hash-password 결과가 bcrypt 모양이 아니다"; }

tmp=$(umask 077 && mktemp "$ENV_FILE.XXXXXX")
{
    [[ -f "$ENV_FILE" ]] && grep -v -e '^GUARDRAIL_BASIC_AUTH_USER=' -e '^GUARDRAIL_BASIC_AUTH_HASH=' "$ENV_FILE" || true
    printf 'GUARDRAIL_BASIC_AUTH_USER=%s\n' "$user"
    printf "GUARDRAIL_BASIC_AUTH_HASH='%s'\n" "$hash"
} > "$tmp"
unset hash
chown root:root "$tmp" && chmod 600 "$tmp" && mv "$tmp" "$ENV_FILE"
printf '해시를 %s 에 넣었다 (비밀번호 원문은 어디에도 남기지 않았다).\n' "$ENV_FILE"

if grep -q 'agent-guardrail demo server' /etc/caddy/Caddyfile 2>/dev/null; then
    ( set -a; . "$ENV_FILE"; set +a; caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null )
    systemctl reload-or-restart caddy
    printf 'Caddy 를 다시 읽었다.\n'
else
    printf 'Caddyfile 은 아직 기본값이다. 배포 (deploy.sh) 때 이 해시를 쓴다.\n'
fi
