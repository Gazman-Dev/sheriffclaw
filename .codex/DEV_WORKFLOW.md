# Development Workflow

## Environment Setup

- Windows PowerShell:
- `python -m venv .venv`
- `.venv\Scripts\Activate.ps1`
- `pip install -U pip`
- `pip install -e ".[dev]"`
- macOS/Linux bash:
- `python3 -m venv .venv`
- `source .venv/bin/activate`
- `pip install -U pip`
- `pip install -e ".[dev]"`

## Core Commands

- Run tests: `pytest -q`
- Run one test file: `pytest -q tests/test_gateway_service.py`
- Run one test: `pytest -q tests/test_ctl_cli.py::test_update_parses`
- Show CLI help: `sheriff-ctl --help`
- Onboard deterministic local mode:
-
`sheriff-ctl onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram`
- Service status/logs:
- `sheriff-ctl status`
- `sheriff-ctl logs sheriff-gateway`

## QA Scripts

- Full local QA (bash): `scripts/qa_cycle.sh`
- Scenario suite (bash): `scripts/e2e_scenarios.sh --quick`
- Linux Docker suite: `scripts/test_linux_docker.sh`

## Typical Change Loop

1. Read impacted module(s) and adjacent tests.
2. Implement minimal change.
3. Run focused tests first.
4. Run broader regression tests for affected subsystem.
5. Update docs/manifests if behavior or interfaces changed.

## Security-Sensitive Change Checklist

- For changes touching secrets, approvals, tool execution, policy, or update:
- verify deny paths, not only allow paths.
- verify lock/unlock semantics.
- verify serialization/state format compatibility.
- verify no command-injection or path-escape regression.

## Platform Notes

- Many integration scripts are bash-focused; on Windows, prefer pytest + direct CLI commands unless using WSL/Git Bash.
