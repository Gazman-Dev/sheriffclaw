#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf "$HOME/.sheriffclaw"

SHERIFF_MASTER_PASSWORD="${SHERIFF_MASTER_PASSWORD:-masterpass}" \
SHERIFF_LLM_PROVIDER="${SHERIFF_LLM_PROVIDER:-stub}" \
./install_sheriffclaw.sh

OUT_FILE="$(mktemp)"
trap 'rm -f "$OUT_FILE"' EXIT

cat <<'EOF' | "$HOME/.sheriffclaw/venv/bin/sheriff-ctl" chat --model-ref scenario/default > "$OUT_FILE"
/status
scenario secret gh_token
/unlock masterpass
/secret gh_token supersecret
scenario exec python
/allow-tool python
scenario last tool
/exit
EOF

grep -q "\[SHERIFF\] sheriff-secrets: ok" "$OUT_FILE"
grep -q '"status": "needs_secret"' "$OUT_FILE"
grep -q "\[SHERIFF\] Vault unlocked\." "$OUT_FILE"
grep -q "\[SHERIFF\] Secret gh_token: approved" "$OUT_FILE"
grep -q '"status": "needs_tool_approval"' "$OUT_FILE"
grep -q "\[SHERIFF\] allow-tool python: approved" "$OUT_FILE"
grep -q "Scenario\[scenario/default\] last tool result" "$OUT_FILE"

echo "Installation E2E passed"
