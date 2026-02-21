#!/bin/bash
set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/Gazman-Dev/sheriffclaw/main/sheriffclaw.sh"
TS="$(date +%s)"
SCRIPT_URL="${BASE_URL}?ts=${TS}"
TMP_SCRIPT="$(mktemp)"
trap 'rm -f "$TMP_SCRIPT"' EXIT

curl -fsSL "$SCRIPT_URL" -o "$TMP_SCRIPT"
bash "$TMP_SCRIPT"
