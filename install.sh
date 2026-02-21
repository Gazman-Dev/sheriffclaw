#!/bin/bash
set -euo pipefail

SCRIPT_URL="https://raw.githubusercontent.com/Gazman-Dev/sheriffclaw/main/sheriffclaw.sh"
TMP_SCRIPT="$(mktemp)"
trap 'rm -f "$TMP_SCRIPT"' EXIT

curl -fsSL "$SCRIPT_URL" -o "$TMP_SCRIPT"
bash "$TMP_SCRIPT"
