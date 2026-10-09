# C-19-7 (DM-91, DM-93) : shared helpers for the deploy/aws scripts. Sourced, not run.
# The deployment target (domain, server IP, SSH key path) lives only in deploy/aws/target.env, which git ignores.
# Nothing here prints or writes AWS credentials, the account ID, a password or a key.
# The Mac side runs macOS /bin/bash 3.2, so these scripts avoid bash 4 features (mapfile, associative arrays).

GUARDRAIL_TAG_KEY=project
GUARDRAIL_TAG_VALUE=guardrail-demo
GUARDRAIL_NAME=guardrail-demo
GUARDRAIL_KEY_NAME=guardrail-demo
GUARDRAIL_SG_NAME=guardrail-demo-sg
GUARDRAIL_REGION=ap-northeast-2
GUARDRAIL_INSTANCE_TYPE=t3.small
GUARDRAIL_VOLUME_GIB=20
GUARDRAIL_AMI_PARAM=/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id
GUARDRAIL_DB_NAME=guardrail_demo
GUARDRAIL_DB_URL='postgresql:///guardrail_demo?host=/var/run/postgresql'

die() { printf '중단 : %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

valid_domain() { [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; }

valid_ipv4() {
    [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
    local part
    for part in "${BASH_REMATCH[@]:1}"; do (( part <= 255 )) || return 1; done
}

# target.env is read as data (KEY=value lines), never sourced, so a stray line cannot run a command.
target_value() {
    local file=$1 key=$2
    sed -n "s/^${key}=//p" "$file" | tail -n 1
}

load_target() {
    local file=$1
    [[ -f "$file" ]] || die "$file 이 없다. provision.sh --apply 또는 configure.sh 를 먼저 돌린다"
    GUARDRAIL_DOMAIN=$(target_value "$file" GUARDRAIL_DOMAIN)
    GUARDRAIL_SERVER_IP=$(target_value "$file" GUARDRAIL_SERVER_IP)
    GUARDRAIL_SSH_KEY=$(target_value "$file" GUARDRAIL_SSH_KEY)
    GUARDRAIL_SSH_USER=$(target_value "$file" GUARDRAIL_SSH_USER)
    GUARDRAIL_SSH_USER=${GUARDRAIL_SSH_USER:-ubuntu}
    valid_domain "$GUARDRAIL_DOMAIN" || die "target.env 의 GUARDRAIL_DOMAIN 이 도메인 모양이 아니다"
    valid_ipv4 "$GUARDRAIL_SERVER_IP" || die "target.env 의 GUARDRAIL_SERVER_IP 가 IPv4 모양이 아니다"
    [[ -f "$GUARDRAIL_SSH_KEY" ]] || die "SSH 키 파일이 없다 (target.env 의 GUARDRAIL_SSH_KEY)"
    SSH_OPTS=(-i "$GUARDRAIL_SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
    SSH_DEST="$GUARDRAIL_SSH_USER@$GUARDRAIL_SERVER_IP"
}

# Writes target.env with owner-only permissions. Arguments: file domain ip key user.
write_target() {
    local file=$1 tmp
    tmp=$(umask 077 && mktemp "${file}.XXXXXX")
    {
        printf '# deploy/aws/target.env — git 제외 (C-19-7). provision.sh / configure.sh 가 썼다. 비밀값 없음.\n'
        printf 'GUARDRAIL_DOMAIN=%s\n' "$2"
        printf 'GUARDRAIL_SERVER_IP=%s\n' "$3"
        printf 'GUARDRAIL_SSH_KEY=%s\n' "$4"
        printf 'GUARDRAIL_SSH_USER=%s\n' "$5"
        printf 'GUARDRAIL_AWS_REGION=%s\n' "$GUARDRAIL_REGION"
    } > "$tmp"
    mv "$tmp" "$file"
}
