#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/.venv/bin/sheriff-ctl"

if [ ! -x "$BIN" ]; then
  echo "missing $BIN"
  echo "run: python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install '.[dev]'"
  exit 1
fi

"${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
export SHERIFFCLAW_ROOT="$TMP_ROOT"
trap 'rm -rf "$TMP_ROOT"' EXIT

"$BIN" onboard \
  --master-password masterpass \
  --llm-provider stub \
  --llm-api-key "" \
  --llm-bot-token "" \
  --gate-bot-token "" \
  --deny-telegram

OUTPUT_FILE="$TMP_ROOT/chat.out"

cat <<'EOF' | "$BIN" chat --model-ref scenario/default > "$OUTPUT_FILE"
/status
scenario secret gh_token
/unlock masterpass
/secret gh_token supersecret
scenario exec python
/allow-tool python
scenario last tool
/exit
EOF

# Assertions

grep -q "\[SHERIFF\] sheriff-secrets: ok" "$OUTPUT_FILE"
grep -q '"status": "needs_secret"' "$OUTPUT_FILE"
grep -q "\[SHERIFF\] Vault unlocked\." "$OUTPUT_FILE"
grep -q "\[SHERIFF\] Secret gh_token: approved" "$OUTPUT_FILE"
grep -q '"status": "needs_tool_approval"' "$OUTPUT_FILE"
grep -q "\[SHERIFF\] allow-tool python: approved" "$OUTPUT_FILE"
grep -q "Scenario\[scenario/default\] last tool result" "$OUTPUT_FILE"

POLICY_OUT="$TMP_ROOT/policy.out"
REQ_OUT="$TMP_ROOT/requests.out"

"$BIN" call sheriff-policy policy.get_decision --json '{"principal_id":"default","resource_type":"tool","resource_value":"python"}' > "$POLICY_OUT"
"$BIN" call sheriff-requests requests.get --json '{"type":"secret","key":"gh_token"}' > "$REQ_OUT"

grep -q '"decision": "ALLOW"' "$POLICY_OUT"
grep -q '"status": "approved"' "$REQ_OUT"

echo "E2E CLI simulation passed"
