#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S_BIN="${ROOT_DIR}/.venv/bin/sheriff"
C_BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

if [ ! -x "$S_BIN" ] || [ ! -x "$C_BIN" ]; then
  echo "missing sheriff binaries in .venv"
  echo "run: python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install '.[dev]'"
  exit 1
fi

"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

# onboard in non-interactive-friendly mode first
"$C_BIN" onboard \
  --master-password masterpass \
  --llm-provider stub \
  --llm-api-key "" \
  --llm-bot-token "" \
  --gate-bot-token "" \
  --deny-telegram >/dev/null

# one-shot to agent
ONE_OUT="$TMP_ROOT/one_shot.out"
"$S_BIN" "hello from e2e" > "$ONE_OUT"
grep -Eq "\[AGENT\]|\[TOOL\]" "$ONE_OUT"

# one-shot slash route to sheriff
SLASH_OUT="$TMP_ROOT/slash.out"
"$S_BIN" "/status" > "$SLASH_OUT"
grep -q "\[SHERIFF\]" "$SLASH_OUT"

# restart auth gate (bad password should not restart)
RESTART_BAD="$TMP_ROOT/restart_bad.out"
printf "restart\nwrong\n" | "$S_BIN" > "$RESTART_BAD" || true
grep -q "Invalid master password" "$RESTART_BAD"

# factory reset via menu and verify wipe
RESET_OUT="$TMP_ROOT/reset.out"
printf "factory reset\ny\ny\n" | "$S_BIN" > "$RESET_OUT"
[ ! -e "$TMP_ROOT/gw" ] && [ ! -e "$TMP_ROOT/llm" ]

echo "E2E sheriff entry script passed"
