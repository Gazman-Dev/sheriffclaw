#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

. .venv/bin/activate

echo "[qa] running unit tests"
pytest -q

echo "[qa] onboarding smoke (non-interactive)"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT
SHERIFFCLAW_ROOT="$TMP_ROOT" sheriff-ctl onboarding --master-password mp --llm-provider stub --llm-api-key '' --llm-bot-token '' --gate-bot-token '' --deny-telegram >/dev/null

if [ ! -f "$TMP_ROOT/gw/state/master.json" ]; then
  echo "[qa] missing master.json"; exit 1
fi

echo "[qa] factory-reset smoke"
SHERIFFCLAW_ROOT="$TMP_ROOT" sheriff-ctl factory-reset --yes >/dev/null
[ ! -e "$TMP_ROOT/gw" ] && [ ! -e "$TMP_ROOT/llm" ]

echo "[qa] ok"
