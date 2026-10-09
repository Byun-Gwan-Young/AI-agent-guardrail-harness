#!/usr/bin/env bash
# C-19-7 (DM-91, DM-97 ①) : deploy main's committed files to the demo server, from the PM's Mac (repository root).
# Claude Code never runs this against a server.
#
#   deploy/aws/deploy.sh                        bundle main → send → install on the server → check → fetch result
#   deploy/aws/deploy.sh --bundle-only DIR      only build and check the bundle into DIR (no network)
#
# 1. deploy/aws/bundle.py : `git archive main` of the include list minus the exclusion list (both in bundle.py), the
#    demo screen built with --api, and the checks (no excluded path, no key pattern, no model text, no large file).
# 2. scp the bundle and remote-install.sh to the server, run it with sudo : release folder → venv →
#    storage init → storage demo-all → service.load_demo check (any difference stops before the switch) → API restart →
#    Caddy reload.
# 3. Fetch the server's check result to reports/c19-7/server-check-postgres.json.
# 4. https://DOMAIN/api/summary through Caddy : curl asks the site password (typed here, never stored).
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$SCRIPT_DIR/../.." && pwd)
. "$SCRIPT_DIR/lib.sh"

REF=main
BUNDLE_ONLY=
while (( $# )); do
    case "$1" in
        --bundle-only) shift; BUNDLE_ONLY=${1:-}; [[ -n "$BUNDLE_ONLY" ]] || die "--bundle-only 에 폴더를 준다" ;;
        --ref) shift; REF=${1:-main} ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) die "모르는 인자 : $1" ;;
    esac
    shift
done

PYTHON="$REPO/venv/bin/python"
[[ -x "$PYTHON" ]] || die "venv/bin/python 이 없다"
[[ -n "$BUNDLE_ONLY" ]] || load_target "$SCRIPT_DIR/target.env"

if [[ -n "$BUNDLE_ONLY" ]]; then
    WORK=$BUNDLE_ONLY
else
    WORK=$(mktemp -d "${TMPDIR:-/tmp}/guardrail-deploy.XXXXXX")
    trap 'rm -rf "$WORK"' EXIT
fi

say "== 묶음 만들기 ($REF 의 커밋된 파일만)"
"$PYTHON" -B "$SCRIPT_DIR/bundle.py" build --ref "$REF" --out "$WORK" > "$WORK/bundle-summary.json" \
    || { cat "$WORK/bundle-summary.json"; die "묶음 검사에 걸렸다 (problems)"; }
"$PYTHON" -I -c 'import json, sys; s = json.load(open(sys.argv[1]))
print(f"commit {s[\"commit\"][:12]} · 파일 {s[\"files\"]} 개 · 압축 전 {s[\"bytes\"]:,} B · 묶음 {s[\"bundle_bytes\"]:,} B · 화면 세션 {s[\"screen\"][\"sessions\"]}")' \
    "$WORK/bundle-summary.json"
if [[ -n "$BUNDLE_ONLY" ]]; then
    say "묶음만 만들었다 : $WORK/bundle.tar.gz (목록 $WORK/bundle-files.txt)"
    exit 0
fi

say "== 서버로 보내기 ($GUARDRAIL_SERVER_IP)"
ssh "${SSH_OPTS[@]}" "$SSH_DEST" 'rm -rf /tmp/guardrail-deploy && mkdir -m 700 /tmp/guardrail-deploy'
scp "${SSH_OPTS[@]}" "$WORK/bundle.tar.gz" "$WORK/remote-install.sh" "$SSH_DEST:/tmp/guardrail-deploy/"

say "== 서버에서 설치 · 적재 · 확인"
set +e
ssh "${SSH_OPTS[@]}" "$SSH_DEST" "sudo bash /tmp/guardrail-deploy/remote-install.sh /tmp/guardrail-deploy/bundle.tar.gz '$GUARDRAIL_DOMAIN'"
status=$?
set -e

say "== 확인 결과 가져오기"
mkdir -p "$REPO/reports/c19-7"
if scp "${SSH_OPTS[@]}" "$SSH_DEST:/opt/guardrail/checks/check-postgres-latest.json" \
        "$REPO/reports/c19-7/server-check-postgres.json"; then
    "$PYTHON" -I -c 'import json, sys; r = json.load(open(sys.argv[1]))
bad = [c["check"] for c in r.get("comparisons", []) if not c.get("same")]
print(f"서버 PostgreSQL check : ok={r.get(\"ok\")} · 비교 {len(r.get(\"comparisons\", []))} 개 · 다름 {bad or 0}")' \
        "$REPO/reports/c19-7/server-check-postgres.json"
fi
ssh "${SSH_OPTS[@]}" "$SSH_DEST" 'rm -rf /tmp/guardrail-deploy' || true
(( status == 0 )) || die "서버 설치가 멈췄다 (위 출력). 서버는 이전 릴리스 그대로다"

say "== https://$GUARDRAIL_DOMAIN/api/summary (Caddy 경유)"
read -r -p "사이트 사용자 이름 (Enter = guardrail) : " site_user
site_user=${site_user:-guardrail}
code=$(curl -sS -u "$site_user" -o "$WORK/summary.json" -w '%{http_code}' "https://$GUARDRAIL_DOMAIN/api/summary") || true
if [[ "$code" == 200 ]] && grep -q '"headline"' "$WORK/summary.json"; then
    say "응답 200 · headline 있음. 브라우저로 https://$GUARDRAIL_DOMAIN/ 를 연다"
else
    die "https://$GUARDRAIL_DOMAIN/api/summary 응답 $code (DNS 반영 · 인증서 발급 직후면 몇 분 뒤 다시 : deploy/aws/remote.sh status)"
fi
