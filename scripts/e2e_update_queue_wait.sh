#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S_BIN="${ROOT_DIR}/.venv/bin/sheriff"
C_BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

[ -x "$S_BIN" ] && [ -x "$C_BIN" ] || { echo "missing binaries"; exit 1; }
"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

"$C_BIN" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
"$S_BIN" --debug on >/dev/null
mkdir -p "$TMP_ROOT/gw/state"
echo '{"text":"long-op"}' > "$TMP_ROOT/gw/state/debug.agent.jsonl"

# Start one in-flight message (one-shot waits ~10s)
("$S_BIN" "hello" > "$TMP_ROOT/msg.out") &
MSG_PID=$!
sleep 1

START=$(date +%s)
"$C_BIN" update --master-password masterpass --no-pull > "$TMP_ROOT/update.out"
END=$(date +%s)
ELAPSED=$((END-START))

wait $MSG_PID

grep -q 'Update completed' "$TMP_ROOT/update.out"
# update should have waited for in-flight processing (allow some variance)
[ "$ELAPSED" -ge 7 ]

echo "E2E update queue-wait passed"
