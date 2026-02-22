#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

ROOT_A="$(mktemp -d)"
ROOT_B="$(mktemp -d)"
trap 'rm -rf "$ROOT_A" "$ROOT_B"' EXIT

# Setup A
export SHERIFFCLAW_ROOT="$ROOT_A"
"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
mkdir -p "$ROOT_A/gw/state"
echo '{"allow_telegram_master_password":true}' > "$ROOT_A/gw/state/master_policy.json"
"$BIN" call sheriff-secrets secrets.lock --json '{}' >/dev/null
"$BIN" call sheriff-requests requests.boot_check --json '{}' >/dev/null

# Setup B (separate state)
export SHERIFFCLAW_ROOT="$ROOT_B"
"$BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
mkdir -p "$ROOT_B/gw/state"

# B should have no gate events until its own boot_check call.
[ ! -f "$ROOT_B/gw/state/gate_events.jsonl" ] || [ ! -s "$ROOT_B/gw/state/gate_events.jsonl" ]

# A should have required event.
grep -q 'master_password_required' "$ROOT_A/gw/state/gate_events.jsonl"

# Now trigger B and ensure files remain distinct.
echo '{"allow_telegram_master_password":true}' > "$ROOT_B/gw/state/master_policy.json"
"$BIN" call sheriff-secrets secrets.lock --json '{}' >/dev/null
"$BIN" call sheriff-requests requests.boot_check --json '{}' >/dev/null
grep -q 'master_password_required' "$ROOT_B/gw/state/gate_events.jsonl"

# Ensure no cross-root file identity.
[ "$ROOT_A" != "$ROOT_B" ]

echo "E2E state isolation passed"
