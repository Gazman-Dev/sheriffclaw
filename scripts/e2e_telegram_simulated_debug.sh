#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"
SHERIFF_BIN="${ROOT_DIR}/.venv/bin/sheriff"

[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
[ -x "$SHERIFF_BIN" ] || { echo "missing $SHERIFF_BIN"; exit 1; }
"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Onboard with clean local state.
"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null

STATE="$TMP_ROOT/gw/state"
mkdir -p "$STATE"

# Simulate user enabling telegram master-password unlock policy.
echo '{"allow_telegram_master_password":true}' > "$STATE/master_policy.json"

# Lock vault to trigger boot_check gate request path.
"$BIN" call sheriff-secrets secrets.lock --json '{}' >/dev/null

BOOT_OUT="$TMP_ROOT/boot.out"
"$BIN" call sheriff-requests requests.boot_check --json '{}' > "$BOOT_OUT"
grep -q '"status": "master_password_required"' "$BOOT_OUT"

# Verify simulated telegram gate got notification persisted.
EVENTS="$STATE/gate_events.jsonl"
grep -q 'master_password_required' "$EVENTS"

# Wrong then correct password submission over request API (telegram-equivalent flow).
BAD="$TMP_ROOT/bad.out"
OK="$TMP_ROOT/ok.out"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"wrong"}' > "$BAD"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"masterpass"}' > "$OK"
grep -q '"ok": false' "$BAD"
grep -q '"ok": true' "$OK"
grep -q 'master_password_accepted' "$EVENTS"

# Use debug mode to deterministically verify post-unlock message handling still works.
"$SHERIFF_BIN" --debug on >/dev/null
cat > "$STATE/debug.agent.jsonl" <<'EOF'
{"text":"post-unlock-debug-ok"}
EOF
MSG_OUT="$TMP_ROOT/msg.out"
"$SHERIFF_BIN" "hello after unlock" > "$MSG_OUT"
grep -q 'post-unlock-debug-ok' "$MSG_OUT"

echo "E2E telegram-simulated(debug) passed"
