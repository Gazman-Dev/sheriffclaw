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

# Start with policy disabled: should not require telegram master password.
echo '{"allow_telegram_master_password":false}' > "$STATE/master_policy.json"
"$BIN" call sheriff-secrets secrets.lock --json '{}' >/dev/null
BOOT_DISABLED="$TMP_ROOT/boot_disabled.out"
"$BIN" call sheriff-requests requests.boot_check --json '{}' > "$BOOT_DISABLED"
grep -q '"status": "ok"' "$BOOT_DISABLED"

# Enable policy and run boot check again: should require master password.
echo '{"allow_telegram_master_password":true}' > "$STATE/master_policy.json"
BOOT_OUT="$TMP_ROOT/boot.out"
"$BIN" call sheriff-requests requests.boot_check --json '{}' > "$BOOT_OUT"
grep -q '"status": "master_password_required"' "$BOOT_OUT"

# Verify simulated telegram gate got notification persisted.
EVENTS="$STATE/gate_events.jsonl"
grep -q 'master_password_required' "$EVENTS"

# Repeated wrong passwords should fail and not create accepted event.
BAD1="$TMP_ROOT/bad1.out"
BAD2="$TMP_ROOT/bad2.out"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"wrong"}' > "$BAD1"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"wrong-again"}' > "$BAD2"
grep -q '"ok": false' "$BAD1"
grep -q '"ok": false' "$BAD2"
if grep -q 'master_password_accepted' "$EVENTS"; then
  echo "unexpected acceptance after wrong passwords"
  exit 1
fi

# Correct password once should succeed.
OK1="$TMP_ROOT/ok1.out"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"masterpass"}' > "$OK1"
grep -q '"ok": true' "$OK1"
grep -q 'master_password_accepted' "$EVENTS"

# Repeated correct submission is idempotent (still ok, no crash).
OK2="$TMP_ROOT/ok2.out"
"$BIN" call sheriff-requests requests.submit_master_password --json '{"master_password":"masterpass"}' > "$OK2"
grep -q '"ok": true' "$OK2"

# Ensure ordering: required event appears before accepted event.
REQ_LINE=$(grep -n 'master_password_required' "$EVENTS" | head -n1 | cut -d: -f1)
ACC_LINE=$(grep -n 'master_password_accepted' "$EVENTS" | head -n1 | cut -d: -f1)
[ -n "$REQ_LINE" ] && [ -n "$ACC_LINE" ] && [ "$REQ_LINE" -lt "$ACC_LINE" ]

# NOTE: unlocked-state continuity is process-lifecycle dependent in current architecture,
# so we validate policy/notify transitions above and avoid asserting a second boot_check status here.

# Use debug mode to deterministically verify post-unlock message handling still works.
"$SHERIFF_BIN" --debug on >/dev/null
cat > "$STATE/debug.agent.jsonl" <<'EOF'
{"text":"post-unlock-debug-ok"}
EOF
MSG_OUT="$TMP_ROOT/msg.out"
"$SHERIFF_BIN" "hello after unlock" > "$MSG_OUT"
grep -q 'post-unlock-debug-ok' "$MSG_OUT"

echo "E2E telegram-simulated(debug) passed"
