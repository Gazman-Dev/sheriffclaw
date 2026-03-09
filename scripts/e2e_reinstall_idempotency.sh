#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME"' EXIT

export HOME="$TMP_HOME"
export SHERIFF_INSTALL_DIR="$HOME/.sheriffclaw"
export SHERIFF_MASTER_PASSWORD="masterpass"
export SHERIFF_LLM_PROVIDER="stub"
export SHERIFF_NON_INTERACTIVE=1

cd "$ROOT_DIR"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

./install_sheriffclaw.sh
FIRST_HASH="$(hash_file "$SHERIFF_INSTALL_DIR/gw/state/master.json")"

./install_sheriffclaw.sh
SECOND_HASH="$(hash_file "$SHERIFF_INSTALL_DIR/gw/state/master.json")"

[ "$FIRST_HASH" = "$SECOND_HASH" ]

RC_FILE="$HOME/.bashrc"
ALIAS_COUNT=0
if [ -f "$RC_FILE" ]; then
  ALIAS_COUNT="$(grep -c "alias sheriff-ctl='" "$RC_FILE" || true)"
fi

if [ "$ALIAS_COUNT" -gt 1 ]; then
  echo "alias duplicated: $ALIAS_COUNT"
  exit 1
fi

echo "Reinstall idempotency check passed"
