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
    set -euo pipefail
    export HOME="$(mktemp -d)"
    export SHERIFF_INSTALL_DIR="$HOME/.sheriffclaw"
    export SHERIFF_REPO_URL="/workspace"
    export SHERIFF_MASTER_PASSWORD="masterpass"
    export SHERIFF_LLM_PROVIDER="stub"
    export SHERIFF_NON_INTERACTIVE=1

    ./install_sheriffclaw.sh

    "$SHERIFF_INSTALL_DIR/venv/bin/sheriff" --help >/dev/null
    "$SHERIFF_INSTALL_DIR/venv/bin/sheriff-ctl" factory-reset --yes >/dev/null

    [ ! -e "$SHERIFF_INSTALL_DIR/gw" ] && [ ! -e "$SHERIFF_INSTALL_DIR/llm" ]
    echo "Docker fresh-install E2E passed"
  '
