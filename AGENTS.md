# SheriffClaw Codex Workspace Guide

## Mission

- Build and maintain SheriffClaw as a secure AI firewall with deterministic control boundaries.
- Preserve security guarantees first: no secret exposure, explicit approvals, bounded tool execution.

## Repository Shape

- `services/`: runtime daemons and CLI-facing services.
- `shared/`: cross-service primitives (RPC, secrets state, policy, memory, tool execution, LLM providers).
- `skills/`: manifest-based skills (`manifest.json` + optional `run.py`).
- `tests/`: unit and integration tests (pytest, async-heavy).
- `scripts/`: QA and e2e shell scenarios.

## Critical Runtime Concepts

- Multi-service architecture split into two islands:
- `gw` island (sheriff/security side)
- `llm` island (agent side)
- Stateful root defaults to `~/.sheriffclaw`; override with `SHERIFFCLAW_ROOT`.
- Service startup/order is defined in `services/sheriff_ctl/service_runner.py` (`GW_ORDER`, `LLM_ORDER`,
  `MANAGED_SERVICES`).
- Secrets lifecycle and lock/unlock behavior are centered in `shared/secrets_state.py`.

## Development Rules

- Keep service APIs stable: do not rename operation keys without updating callers and tests.
- Prefer small, targeted edits over broad refactors.
- Any security-sensitive behavior change must include/adjust tests.
- Keep skills manifest-driven; avoid legacy ad hoc skill loading patterns.
- Preserve cross-platform behavior (Windows + macOS/Linux; shell scripts are mostly bash-oriented).

## Fast Start Commands

- Create env + install:
- `python -m venv .venv`
- `.venv\Scripts\Activate.ps1` (PowerShell) or `source .venv/bin/activate` (bash)
- `pip install -U pip`
- `pip install -e ".[dev]"`
- Unit tests:
- `pytest -q`
- Focused tests:
- `pytest -q tests/test_ctl_cli.py`
- CLI smoke example:
-
`sheriff-ctl onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram`
- `sheriff-ctl status`

## QA Expectations Before Finish

- Run targeted tests for edited modules.
- Run at least `pytest -q` for broad changes.
- If changes affect onboarding/update/sandbox/skills/routing, run relevant `scripts/e2e_*.sh` when feasible.
- Report what was run and what was not run.

## High-Risk Areas (Be Extra Careful)

- `shared/secrets_state.py`
- `services/sheriff_gateway/service.py`
- `services/sheriff_requests/service.py`
- `shared/tools_exec.py`
- `services/sheriff_ctl/system.py` and `services/sheriff_ctl/service_runner.py`

## Where To Read First

- `.codex/PROJECT_OVERVIEW.md`
- `.codex/ARCHITECTURE_MAP.md`
- `.codex/DEV_WORKFLOW.md`
- `.codex/CHANGE_CHECKLIST.md`
