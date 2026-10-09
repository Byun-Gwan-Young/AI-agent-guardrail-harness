#!/usr/bin/env bash
# C-19-7 (DM-91) : write deploy/aws/target.env by asking, when the server was made without provision.sh.
#
#   deploy/aws/configure.sh
#
# Asks the domain, the server's public IP, the SSH private key path and the SSH user. Writes them to the git-ignored
# deploy/aws/target.env (mode 600). No secret is asked or written.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

TARGET_ENV="$SCRIPT_DIR/target.env"
[[ $# -eq 0 ]] || { sed -n '2,8p' "$0"; exit 0; }

read -r -p "도메인 (예 : demo.example.com) : " domain
domain=$(printf '%s' "$domain" | tr '[:upper:]' '[:lower:]')
valid_domain "$domain" || die "도메인 모양이 아니다"
read -r -p "서버 공인 IP (탄력적 IP) : " ip
valid_ipv4 "$ip" || die "IPv4 모양이 아니다"
read -r -p "SSH 개인 키 경로 (Enter = $HOME/.ssh/$GUARDRAIL_KEY_NAME.pem) : " key
key=${key:-$HOME/.ssh/$GUARDRAIL_KEY_NAME.pem}
key=${key/#\~/$HOME}
[[ -f "$key" ]] || die "키 파일이 없다 : $key"
perm=$(stat -f '%Lp' "$key" 2>/dev/null || stat -c '%a' "$key")
[[ "$perm" == 400 || "$perm" == 600 ]] || say "주의 : 키 파일 권한이 $perm 이다 (chmod 400 권장)"
read -r -p "SSH 사용자 (Enter = ubuntu) : " user
user=${user:-ubuntu}
[[ "$user" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "사용자 이름 모양이 아니다"

write_target "$TARGET_ENV" "$domain" "$ip" "$key" "$user"
say "$TARGET_ENV 를 썼다 (git 제외)."
