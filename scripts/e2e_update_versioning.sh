#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"
PY="${ROOT_DIR}/.venv/bin/python"

[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
[ -x "$PY" ] || { echo "missing $PY"; exit 1; }

"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
VERSIONS_FILE="${ROOT_DIR}/versions.json"
VERSIONS_BAK="$(mktemp)"
cp "$VERSIONS_FILE" "$VERSIONS_BAK"

cleanup() {
  cp "$VERSIONS_BAK" "$VERSIONS_FILE" || true
  rm -f "$VERSIONS_BAK" || true
  rm -rf "$TMP_ROOT" || true
}
trap cleanup EXIT

export SHERIFFCLAW_ROOT="$TMP_ROOT"

# Ensure no leftover daemons interfere with temp-root assertions
"$BIN" stop >/dev/null 2>&1 || true

# Stable baseline versions for deterministic assertions
cat > "$VERSIONS_FILE" <<'JSON'
{
  "agent": "1.0.0",
  "sheriff": "1.0.0",
  "secrets": "1.0.0"
}
JSON

"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null

SKIP_OUT="$TMP_ROOT/update_skip.out"
FORCE_OUT="$TMP_ROOT/update_force.out"
REQ_MP_OUT="$TMP_ROOT/update_req_mp.out"
SECRETS_OK_OUT="$TMP_ROOT/update_secrets_ok.out"

# First update applies 1.0.0 -> update state
"$BIN" update --master-password masterpass --no-pull >/dev/null

# No version bump: should skip, no password required
"$BIN" update --no-pull > "$SKIP_OUT"
grep -q 'update skipped' "$SKIP_OUT"

# Force update: should run even unchanged, no password required
"$BIN" update --no-pull --force > "$FORCE_OUT"
grep -q 'Update completed' "$FORCE_OUT"

# Bump only secrets version -> should require password
cat > "$VERSIONS_FILE" <<'JSON'
{
  "agent": "1.0.0",
  "sheriff": "1.0.0",
  "secrets": "1.0.1"
}
JSON

"$BIN" update --no-pull > "$REQ_MP_OUT" || true
grep -q 'Master password required for secrets update' "$REQ_MP_OUT"

"$BIN" update --master-password masterpass --no-pull > "$SECRETS_OK_OUT"
grep -q 'Update completed' "$SECRETS_OK_OUT"

"$BIN" stop >/dev/null 2>&1 || true

echo "E2E update versioning flow passed"
