#!/usr/bin/env bash
set -euo pipefail

echo "Running Python setup..."
python3 -m pip install -U pip >/dev/null
python3 -m pip install -e ".[dev]" >/dev/null

echo "Running pytest..."
pytest -q

echo "Running E2E Bash Scenarios..."
chmod +x scripts/e2e_scenarios.sh
./scripts/e2e_scenarios.sh --quick
