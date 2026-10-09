#!/usr/bin/env bash
# C-19-7 (DM-91 ⑧, DM-93 ⑤) : remove the demo server's AWS resources, from the PM's Mac. Claude Code never runs this.
#
#   deploy/aws/teardown.sh
#
# Finds by tag project=guardrail-demo (and by name for the key pair and security group) : the instance(s), the
# Elastic IP(s), the security group and the key pair. Shows the list, and deletes only after the PM types "delete" :
# Elastic IP disassociated and released, instance terminated (its 20 GiB volume goes with it), security group and key
# pair deleted. The DNS record, the IAM access key and the budget alert are the PM's console steps (printed at the end).
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

[[ $# -eq 0 ]] || { sed -n '2,10p' "$0"; exit 0; }
command -v aws >/dev/null || die "AWS CLI 가 없다 (aws --version)"
awsq() { aws --region "$GUARDRAIL_REGION" --output text "$@"; }

ACCOUNT=$(awsq sts get-caller-identity --query Account) || die "AWS 자격 증명이 없다 : aws configure"
say "AWS 계정 : $ACCOUNT (화면에만) · 리전 $GUARDRAIL_REGION"
unset ACCOUNT

TAG_FILTER="Name=tag:$GUARDRAIL_TAG_KEY,Values=$GUARDRAIL_TAG_VALUE"
INSTANCES=$(awsq ec2 describe-instances --filters "$TAG_FILTER" \
    Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' | tr '\t' ' ')
ADDRESSES=$(awsq ec2 describe-addresses --filters "$TAG_FILTER" --query 'Addresses[].[AllocationId,PublicIp,AssociationId]')
SG=$(awsq ec2 describe-security-groups --filters "Name=group-name,Values=$GUARDRAIL_SG_NAME" --query 'SecurityGroups[0].GroupId')
[[ "$SG" == sg-* ]] || SG=
KEY_ID=$(awsq ec2 describe-key-pairs --filters "Name=key-name,Values=$GUARDRAIL_KEY_NAME" --query 'KeyPairs[0].KeyPairId')
[[ "$KEY_ID" == key-* ]] || KEY_ID=
INSTANCES=$(printf '%s' "$INSTANCES" | tr -s ' ' | sed 's/^ //; s/ $//; s/^None$//')

say ""
say "지울 것"
say "  인스턴스 : ${INSTANCES:-없음}"
if printf '%s' "$ADDRESSES" | grep -q eipalloc-; then
    printf '%s\n' "$ADDRESSES" | awk '/eipalloc-/{print "  탄력적 IP : " $2 " (" $1 ")"}'
else
    say "  탄력적 IP : 없음"
fi
say "  보안 그룹 $GUARDRAIL_SG_NAME : ${SG:-없음}"
say "  키 페어 $GUARDRAIL_KEY_NAME : ${KEY_ID:-없음}"
if [[ -z "$INSTANCES" && -z "$SG" && -z "$KEY_ID" ]] && ! printf '%s' "$ADDRESSES" | grep -q eipalloc-; then
    say "지울 것이 없다."
    exit 0
fi

read -r -p "모두 지운다 (되돌릴 수 없다). 계속하려면 delete : " answer
[[ "$answer" == delete ]] || die "delete 가 아니라 멈췄다"

while read -r alloc ip assoc; do
    [[ "${alloc:-}" == eipalloc-* ]] || continue
    if [[ "${assoc:-None}" != None ]]; then
        awsq ec2 disassociate-address --association-id "$assoc" >/dev/null
    fi
    awsq ec2 release-address --allocation-id "$alloc" >/dev/null
    say "탄력적 IP 해제 : $ip"
done <<< "$ADDRESSES"

if [[ -n "$INSTANCES" ]]; then
    # shellcheck disable=SC2086 # instance IDs, space separated
    awsq ec2 terminate-instances --instance-ids $INSTANCES >/dev/null
    say "인스턴스 종료 요청 : $INSTANCES (끝나기를 기다린다)"
    # shellcheck disable=SC2086
    awsq ec2 wait instance-terminated --instance-ids $INSTANCES
fi

if [[ -n "$SG" ]]; then
    for attempt in 1 2 3 4 5 6; do
        if awsq ec2 delete-security-group --group-id "$SG" >/dev/null 2>&1; then
            say "보안 그룹 삭제 : $SG"; break
        fi
        (( attempt < 6 )) || die "보안 그룹 $SG 를 지우지 못했다 (네트워크 인터페이스가 아직 붙어 있으면 몇 분 뒤 다시)"
        sleep 10
    done
fi

if [[ -n "$KEY_ID" ]]; then
    awsq ec2 delete-key-pair --key-pair-id "$KEY_ID" >/dev/null
    say "키 페어 삭제 : $GUARDRAIL_KEY_NAME"
fi

say ""
say "남은 PM 할 일 (콘솔) :"
say "  - 도메인 A 레코드 지우기 (Route 53 또는 등록 업체)"
say "  - IAM 사용자 guardrail-deploy 의 접근 키 비활성화 · 삭제"
say "  - 맥의 개인 키 $HOME/.ssh/$GUARDRAIL_KEY_NAME.pem 와 deploy/aws/target.env 는 필요 없으면 지운다"
