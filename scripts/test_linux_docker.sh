#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="sheriffclaw-linux-test:latest"

cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not installed on this host"
  exit 1
fi

docker build -f docker/linux-test.Dockerfile -t "$IMAGE" .

docker run --rm -t \
  -v "$ROOT_DIR":/workspace \
  -w /workspace \
  "$IMAGE" \
  bash -lc '
    python -m venv .venv
    . .venv/bin/activate
    pip install -U pip
    pip install ".[dev]"
    pytest -q
    chmod +x scripts/e2e_cli_simulation.sh scripts/e2e_installation_check.sh
    ./scripts/e2e_cli_simulation.sh
    SHERIFF_MASTER_PASSWORD=masterpass SHERIFF_LLM_PROVIDER=stub ./scripts/e2e_installation_check.sh
  '

echo "Linux docker test suite passed"
