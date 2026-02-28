# SheriffClaw Project Overview

## What This Project Is
SheriffClaw is a Python multi-service system that gates AI-agent actions behind deterministic policy, approvals, and secrets isolation.

## Primary Goals
- Keep secrets out of agent context.
- Route all sensitive actions through Sheriff services.
- Require explicit approval for privileged capabilities.
- Keep behavior testable with deterministic debug/stub flows.

## Main Subsystems
- Gateway and policy plane: approval + routing + controls.
- Secrets and request plane: encrypted secrets state + approval records.
- Tools/web plane: controlled command/web operations.
- Worker/LLM plane: agent runtime and provider integrations.
- Integration plane: CLI and Telegram adapters.

## Entry Points
- CLI: `sheriff` and `sheriff-ctl` (see `pyproject.toml` scripts).
- Individual service binaries (e.g. `sheriff-gateway`, `sheriff-secrets`, `ai-worker`).

## Data Roots
- Default root: `~/.sheriffclaw`.
- Override root for tests/dev: `SHERIFFCLAW_ROOT=<path>`.
- Islands:
- `gw/` for Sheriff-side state.
- `llm/` for agent-side state.

## Current Maturity
- Pre-alpha with strong automated test coverage.
- Emphasis on iterative hardening and predictable operations.
