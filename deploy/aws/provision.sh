#!/usr/bin/env bash
# C-19-7 (DM-93) : the AWS side of the demo server, from the PM's Mac with the AWS CLI. Claude Code never runs this.
#
#   deploy/aws/provision.sh [--dry-run] [--domain DOMAIN]     show what exists and what would be made (default)
#   deploy/aws/provision.sh --apply [--domain DOMAIN]         make what is missing, then write deploy/aws/target.env
#   deploy/aws/provision.sh --update-ssh-ip                   only move the SSH rule to this Mac's public IP now
#
# Seoul region. Key pair guardrail-demo (private key ~/.ssh/guardrail-demo.pem, mode 400), security group
# guardrail-demo-sg (SSH from this Mac's public IP/32 only, 80 and 443 from anywhere), one t3.small Ubuntu 24.04
# instance (latest AMI from the SSM public parameter, 20 GiB gp3, IMDSv2 only), one Elastic IP, all tagged
# project=guardrail-demo. Existing resources are found by name or tag and reused, never made twice. With a public
# Route 53 hosted zone for the domain the A record is upserted; otherwise the record to enter at the registrar is
# printed. Credentials stay in ~/.aws (aws configure); the account ID is shown on screen only, never written.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

MODE=dry-run
DOMAIN=
TARGET_ENV="$SCRIPT_DIR/target.env"
KEY_FILE="$HOME/.ssh/$GUARDRAIL_KEY_NAME.pem"
while (( $# )); do
    case "$1" in
        --dry-run) MODE=dry-run ;;
        --apply) MODE=apply ;;
        --update-ssh-ip) MODE=ssh-ip ;;
        --domain) shift; DOMAIN=${1:-} ;;
        --target-env) shift; TARGET_ENV=${1:-} ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) die "모르는 인자 : $1" ;;
    esac
    shift
done

command -v aws >/dev/null || die "AWS CLI 가 없다 (aws --version)"
command -v curl >/dev/null || die "curl 이 없다"
awsq() { aws --region "$GUARDRAIL_REGION" --output text "$@"; }

ACCOUNT=$(awsq sts get-caller-identity --query Account) || die "AWS 자격 증명이 없다 : aws configure (IAM 사용자 guardrail-deploy)"
say "AWS 계정 : $ACCOUNT (화면에만 보이고 파일에 쓰지 않는다) · 리전 $GUARDRAIL_REGION"
unset ACCOUNT

MY_IP=$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]') || die "지금 공인 IP 를 알 수 없다"
valid_ipv4 "$MY_IP" || die "공인 IP 응답이 IPv4 모양이 아니다"
say "지금 공인 IP : $MY_IP (SSH 는 이 주소/32 만)"

VPC=$(awsq ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId')
[[ "$VPC" == vpc-* ]] || die "서울 리전에 기본 VPC 가 없다"
SG=$(awsq ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=$GUARDRAIL_SG_NAME" \
    --query 'SecurityGroups[0].GroupId')
[[ "$SG" == sg-* ]] || SG=

ssh_cidrs() {
    awsq ec2 describe-security-groups --group-ids "$SG" \
        --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' | tr '\t' '\n' | grep -v '^None$' || true
}

# Allow one rule; a rule that is already there is fine (InvalidPermission.Duplicate), any other error stops.
allow() {
    local port=$1 cidr=$2 err
    if ! err=$(awsq ec2 authorize-security-group-ingress --group-id "$SG" \
            --ip-permissions "IpProtocol=tcp,FromPort=$port,ToPort=$port,IpRanges=[{CidrIp=$cidr}]" 2>&1 >/dev/null); then
        [[ "$err" == *InvalidPermission.Duplicate* ]] || die "보안 그룹 규칙 추가 실패 (포트 $port) : $err"
    fi
}

# SSH only from this Mac's public IP now: drop every other port-22 range, then allow MY_IP/32.
set_ssh_rule() {
    local cidr
    for cidr in $(ssh_cidrs); do
        [[ "$cidr" == "$MY_IP/32" ]] && continue
        awsq ec2 revoke-security-group-ingress --group-id "$SG" \
            --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$cidr}]" >/dev/null
        say "  SSH 규칙 뺌 : $cidr"
    done
    allow 22 "$MY_IP/32"
    say "  SSH 규칙 : $MY_IP/32"
}

if [[ "$MODE" == ssh-ip ]]; then
    [[ -n "$SG" ]] || die "보안 그룹 $GUARDRAIL_SG_NAME 이 없다 (provision.sh --apply 먼저)"
    say "SSH 허용 IP 를 $MY_IP/32 로 바꾼다 (보안 그룹 $SG)"
    set_ssh_rule
    exit 0
fi

if [[ -z "$DOMAIN" ]]; then
    read -r -p "도메인 (예 : demo.example.com) : " DOMAIN
fi
DOMAIN=$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]')
valid_domain "$DOMAIN" || die "도메인 모양이 아니다 : $DOMAIN"

# The SSM public parameter first. AmazonEC2FullAccess alone (DM-93 ③) has no ssm:GetParameters, so on a refusal the
# newest Canonical (owner 099720109477) Ubuntu 24.04 amd64 gp3 image from DescribeImages (an EC2 permission) is used.
AMI=$(awsq ssm get-parameters --names "$GUARDRAIL_AMI_PARAM" --query 'Parameters[0].Value' 2>/dev/null || true)
if [[ "$AMI" != ami-* ]]; then
    AMI=$(awsq ec2 describe-images --owners 099720109477 \
        --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' Name=state,Values=available \
        --query 'sort_by(Images,&CreationDate)[-1].ImageId')
    say "AMI : SSM 공개 파라미터를 읽지 못해 Canonical 이미지 목록에서 찾았다 ($AMI)"
fi
[[ "$AMI" == ami-* ]] || die "Ubuntu 24.04 AMI 를 찾지 못했다"
KEY_ID=$(awsq ec2 describe-key-pairs --filters "Name=key-name,Values=$GUARDRAIL_KEY_NAME" --query 'KeyPairs[0].KeyPairId')
[[ "$KEY_ID" == key-* ]] || KEY_ID=
INSTANCES=$(awsq ec2 describe-instances \
    --filters "Name=tag:$GUARDRAIL_TAG_KEY,Values=$GUARDRAIL_TAG_VALUE" Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].[InstanceId,State.Name]')
(( $(printf '%s' "$INSTANCES" | grep -c 'i-' || true) <= 1 )) || die "태그 $GUARDRAIL_TAG_KEY=$GUARDRAIL_TAG_VALUE 인스턴스가 둘 이상이다 (teardown.sh 로 정리)"
INSTANCE=$(printf '%s' "$INSTANCES" | awk '/i-/{print $1}')
STATE=$(printf '%s' "$INSTANCES" | awk '/i-/{print $2}')
read -r ALLOC EIP EIP_INSTANCE <<< "$(awsq ec2 describe-addresses --filters "Name=tag:$GUARDRAIL_TAG_KEY,Values=$GUARDRAIL_TAG_VALUE" \
    --query 'Addresses[0].[AllocationId,PublicIp,InstanceId]')"
[[ "$ALLOC" == eipalloc-* ]] || { ALLOC=; EIP=; EIP_INSTANCE=; }

# Route 53 : the public hosted zone whose name is the longest suffix of the domain (none, or no permission, is fine).
ZONE=
ZONES=$(awsq route53 list-hosted-zones --query 'HostedZones[?Config.PrivateZone==`false`].[Id,Name]' 2>/dev/null || true)
best=0
while read -r zid zname; do
    [[ -n "${zid:-}" && "$zid" != None ]] || continue
    zname=${zname%.}
    if [[ "$DOMAIN" == "$zname" || "$DOMAIN" == *".$zname" ]] && (( ${#zname} > best )); then
        ZONE=${zid##*/}; best=${#zname}
    fi
done <<< "$ZONES"

have() { if [[ -n "$1" ]]; then printf '있음 (%s) → 다시 씀' "$1"; else printf '없음 → 만든다'; fi; }
say ""
say "계획 ($MODE)"
say "  키 페어 $GUARDRAIL_KEY_NAME      : $(have "$KEY_ID") · 개인 키 $KEY_FILE $( [[ -f "$KEY_FILE" ]] && echo 있음 || echo 없음)"
say "  보안 그룹 $GUARDRAIL_SG_NAME : $(have "$SG") · SSH $MY_IP/32 만 · 80·443 전체"
[[ -n "$SG" ]] && say "    지금 SSH 규칙 : $(ssh_cidrs | tr '\n' ' ')"
say "  인스턴스 (태그 $GUARDRAIL_TAG_KEY=$GUARDRAIL_TAG_VALUE) : $(have "$INSTANCE")${STATE:+ · $STATE} · $GUARDRAIL_INSTANCE_TYPE · $AMI · ${GUARDRAIL_VOLUME_GIB} GiB gp3"
say "  탄력적 IP : $(have "$EIP")"
if [[ -n "$ZONE" ]]; then
    say "  DNS : Route 53 호스팅 영역 $ZONE 에 A 레코드 $DOMAIN → 탄력적 IP (UPSERT)"
else
    say "  DNS : Route 53 호스팅 영역 없음 → 등록 업체에 넣을 A 레코드를 끝에 보여 준다"
fi
say "  target.env : $TARGET_ENV"

if [[ "$MODE" == dry-run ]]; then
    say ""
    say "dry-run : 아무것도 만들지 않았다. 만들려면 --apply"
    exit 0
fi

read -r -p "위 계획대로 AWS 자원을 만든다. 계속하려면 yes : " answer
[[ "$answer" == yes ]] || die "yes 가 아니라 멈췄다"

TAGS="{Key=$GUARDRAIL_TAG_KEY,Value=$GUARDRAIL_TAG_VALUE},{Key=Name,Value=$GUARDRAIL_NAME}"

if [[ -z "$KEY_ID" ]]; then
    [[ ! -e "$KEY_FILE" ]] || die "$KEY_FILE 이 이미 있다. 덮어쓰지 않는다 (옛 키면 옮기고 다시)"
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    tmp=$(umask 077 && mktemp "$HOME/.ssh/.guardrail-demo.XXXXXX")
    awsq ec2 create-key-pair --key-name "$GUARDRAIL_KEY_NAME" --key-type ed25519 \
        --tag-specifications "ResourceType=key-pair,Tags=[$TAGS]" --query KeyMaterial > "$tmp"
    mv "$tmp" "$KEY_FILE" && chmod 400 "$KEY_FILE"
    say "키 페어 만듦 : 개인 키 $KEY_FILE (권한 400)"
else
    [[ -f "$KEY_FILE" ]] || die "AWS 에 키 페어 $GUARDRAIL_KEY_NAME 이 있는데 개인 키 $KEY_FILE 이 없다 (teardown.sh 로 지우고 다시)"
fi

if [[ -z "$SG" ]]; then
    SG=$(awsq ec2 create-security-group --group-name "$GUARDRAIL_SG_NAME" --vpc-id "$VPC" \
        --description "agent-guardrail demo: SSH from PM IP, HTTP/HTTPS" \
        --tag-specifications "ResourceType=security-group,Tags=[$TAGS]" --query GroupId)
    say "보안 그룹 만듦 : $SG"
fi
allow 80 0.0.0.0/0
allow 443 0.0.0.0/0
set_ssh_rule

if [[ -z "$INSTANCE" ]]; then
    INSTANCE=$(awsq ec2 run-instances --image-id "$AMI" --instance-type "$GUARDRAIL_INSTANCE_TYPE" \
        --key-name "$GUARDRAIL_KEY_NAME" --security-group-ids "$SG" --count 1 \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$GUARDRAIL_VOLUME_GIB,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}" \
        --metadata-options HttpTokens=required,HttpEndpoint=enabled \
        --tag-specifications "ResourceType=instance,Tags=[$TAGS]" "ResourceType=volume,Tags=[$TAGS]" \
        --query 'Instances[0].InstanceId')
    say "인스턴스 만듦 : $INSTANCE (켜지기를 기다린다)"
elif [[ "$STATE" == stopped || "$STATE" == stopping ]]; then
    awsq ec2 wait instance-stopped --instance-ids "$INSTANCE"
    awsq ec2 start-instances --instance-ids "$INSTANCE" >/dev/null
    say "멈춰 있던 인스턴스를 켠다 : $INSTANCE"
fi
awsq ec2 wait instance-running --instance-ids "$INSTANCE"

if [[ -z "$ALLOC" ]]; then
    read -r ALLOC EIP <<< "$(awsq ec2 allocate-address --domain vpc \
        --tag-specifications "ResourceType=elastic-ip,Tags=[$TAGS]" --query '[AllocationId,PublicIp]')"
    say "탄력적 IP 만듦 : $EIP"
fi
if [[ "${EIP_INSTANCE:-}" != "$INSTANCE" ]]; then
    awsq ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC" >/dev/null
    say "탄력적 IP $EIP → $INSTANCE 연결"
fi

if [[ -n "$ZONE" ]]; then
    change="{\"Comment\":\"agent-guardrail demo (C-19-7)\",\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN\",\"Type\":\"A\",\"TTL\":300,\"ResourceRecords\":[{\"Value\":\"$EIP\"}]}}]}"
    awsq route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch "$change" >/dev/null
    say "Route 53 : A $DOMAIN → $EIP (TTL 300)"
fi

write_target "$TARGET_ENV" "$DOMAIN" "$EIP" "$KEY_FILE" ubuntu
say ""
say "끝. $TARGET_ENV 를 썼다 (git 제외)."
if [[ -z "$ZONE" ]]; then
    say "등록 업체 DNS 에 넣을 레코드 : 이름 $DOMAIN · 형식 A · 값 $EIP · TTL 300"
fi
say "다음 : deploy/aws/remote.sh ssh 로 첫 접속을 확인한다 (켜진 직후면 1~2 분 기다린다)"
