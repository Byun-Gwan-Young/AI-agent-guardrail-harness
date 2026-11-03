#!/usr/bin/env bash
# DM-108 : put the Google OAuth web client ID into the git-ignored deploy/aws/target.env, by asking.
#
#   deploy/aws/set-google-client.sh
#
# The client ID is public (the sign-in page shows it) but stays out of the repository like the domain. The client
# secret is never asked : the Google sign-in button only needs the ID. The next deploy/aws/deploy.sh hands it to the
# server's backend.env.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

TARGET_ENV="$SCRIPT_DIR/target.env"
[[ $# -eq 0 ]] || { sed -n '2,8p' "$0"; exit 0; }
[[ -f "$TARGET_ENV" ]] || die "$TARGET_ENV 이 없다. provision.sh --apply 또는 configure.sh 를 먼저 돌린다"

read -r -p "구글 OAuth 클라이언트 ID (웹 애플리케이션) : " cid
cid=$(printf '%s' "$cid" | tr -d '[:space:]')
valid_google_client_id "$cid" || die "클라이언트 ID 모양이 아니다 (숫자-문자열 로 시작하는 구글 주소 하나)"

tmp=$(umask 077 && mktemp "${TARGET_ENV}.XXXXXX")
{ grep -v '^GUARDRAIL_GOOGLE_CLIENT_ID=' "$TARGET_ENV" || true; printf 'GUARDRAIL_GOOGLE_CLIENT_ID=%s\n' "$cid"; } > "$tmp"
mv "$tmp" "$TARGET_ENV"
say "$TARGET_ENV 에 구글 클라이언트 ID 를 넣었다 (git 제외). 다음 : deploy/aws/deploy.sh"
