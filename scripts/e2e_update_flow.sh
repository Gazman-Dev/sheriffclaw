#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null

BAD_OUT="$TMP_ROOT/update_bad.out"
GOOD_OUT="$TMP_ROOT/update_good.out"

"$BIN" update --master-password wrong --no-pull > "$BAD_OUT" || true
grep -q 'Invalid master password' "$BAD_OUT"

"$BIN" update --master-password masterpass --no-pull > "$GOOD_OUT"
grep -q 'Update completed' "$GOOD_OUT"

echo "E2E update flow passed"
