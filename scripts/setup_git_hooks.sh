#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

git config core.hooksPath .githooks
chmod +x .githooks/pre-push

echo "Configured git hooks path: .githooks"
