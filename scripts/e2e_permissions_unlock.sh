#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

# onboard
"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null

# permissions + secrets roundtrip through chat
OUT_FILE="$TMP_ROOT/chat.out"
cat <<'EOF' | "$BIN" chat --model-ref scenario/default > "$OUT_FILE"
scenario secret gh_token
/unlock masterpass
/secret gh_token supersecret
scenario exec python
/allow-tool python
scenario last tool
/exit
EOF

grep -q '"status": "needs_secret"' "$OUT_FILE"
grep -q 'Secret gh_token: approved' "$OUT_FILE"
grep -q '"status": "needs_tool_approval"' "$OUT_FILE"
grep -q 'allow-tool python: approved' "$OUT_FILE"

# restart/lock policy flow simulation
"$BIN" call sheriff-secrets secrets.lock --json '{}' >/dev/null

STATE="$TMP_ROOT/gw/state"
mkdir -p "$STATE"

echo '{"allow_telegram_master_password":false}' > "$STATE/master_policy.json"
NO_REQ="$TMP_ROOT/boot_no_req.out"
"$BIN" call sheriff-requests requests.boot_check --json '{}' > "$NO_REQ"
grep -q '"status": "ok"' "$NO_REQ"

echo '{"allow_telegram_master_password":true}' > "$STATE/master_policy.json"
REQ_OUT="$TMP_ROOT/boot_req.out"
"$BIN" call sheriff-requests requests.boot_check --json '{}' > "$REQ_OUT"
grep -q '"status": "master_password_required"' "$REQ_OUT"

BAD_UNLOCK="$TMP_ROOT/unlock_bad.out"
GOOD_UNLOCK="$TMP_ROOT/unlock_good.out"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"wrong"}' > "$BAD_UNLOCK"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"masterpass"}' > "$GOOD_UNLOCK"
grep -q '"ok": false' "$BAD_UNLOCK"
grep -q '"ok": true' "$GOOD_UNLOCK"

echo "E2E permissions+unlock passed"
