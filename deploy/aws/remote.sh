#!/usr/bin/env bash
# C-19-7 : reach the demo server with the values of deploy/aws/target.env, from the PM's Mac. Claude Code never runs this.
#
#   deploy/aws/remote.sh ssh        log in (first connection : accepts and remembers the host key)
#   deploy/aws/remote.sh setup      send server-setup.sh and run it with sudo (once ; safe to repeat)
#   deploy/aws/remote.sh password   send set-password.sh and run it with sudo in a terminal (the site password)
#   deploy/aws/remote.sh status     API · Caddy · PostgreSQL state and the deployed commit
#   deploy/aws/remote.sh dns        does the domain's A record point at the server IP yet (dig, from this Mac)
#   deploy/aws/remote.sh open       open https://DOMAIN/ in the browser
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

load_target "$SCRIPT_DIR/target.env"
case "${1:-}" in
    ssh)
        exec ssh "${SSH_OPTS[@]}" "$SSH_DEST" ;;
    setup)
        scp "${SSH_OPTS[@]}" "$SCRIPT_DIR/server-setup.sh" "$SSH_DEST:/tmp/guardrail-server-setup.sh"
        ssh "${SSH_OPTS[@]}" "$SSH_DEST" 'sudo bash /tmp/guardrail-server-setup.sh && rm -f /tmp/guardrail-server-setup.sh' ;;
    password)
        scp "${SSH_OPTS[@]}" "$SCRIPT_DIR/set-password.sh" "$SSH_DEST:/tmp/guardrail-set-password.sh"
        ssh -t "${SSH_OPTS[@]}" "$SSH_DEST" 'sudo bash /tmp/guardrail-set-password.sh; rm -f /tmp/guardrail-set-password.sh' ;;
    status)
        ssh "${SSH_OPTS[@]}" "$SSH_DEST" 'systemctl is-active guardrail-api caddy postgresql; \
            cat /opt/guardrail/app/DEPLOY_INFO.json 2>/dev/null | head -n 4 || echo "아직 배포 안 됨"' ;;
    dns)
        resolved=$(dig +short "$GUARDRAIL_DOMAIN" A | tail -n 1)
        if [[ "$resolved" == "$GUARDRAIL_SERVER_IP" ]]; then
            say "DNS 반영됨 : $GUARDRAIL_DOMAIN → $resolved"
        else
            die "아직 아니다 : $GUARDRAIL_DOMAIN → ${resolved:-없음} (서버 $GUARDRAIL_SERVER_IP). 몇 분 뒤 다시"
        fi ;;
    open)
        open "https://$GUARDRAIL_DOMAIN/" ;;
    *)
        sed -n '2,10p' "$0"; exit 2 ;;
esac
