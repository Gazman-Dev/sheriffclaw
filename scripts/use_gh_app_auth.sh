#!/usr/bin/env bash
# Source this from repo root: source scripts/use_gh_app_auth.sh
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${ROOT_DIR}/bin:${PATH}"
echo "gh wrapper enabled for this shell: ${ROOT_DIR}/bin/gh"
