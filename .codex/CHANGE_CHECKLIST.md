# Change Checklist

## Always

- Confirm scope and affected services/modules.
- Keep operation names and wire contracts consistent.
- Add or update tests for behavior changes.
- Run relevant tests before finishing.
- Summarize risk and verification done.

## If You Touch `shared/secrets_state.py` or Secrets Flows

- Validate init, verify, unlock, lock behavior.
- Validate persistence and migration safety.
- Validate no plaintext leakage in logs/errors.

## If You Touch Tool Execution / Web Access

- Validate reject paths for unsafe inputs.
- Validate policy/approval gating still applies.
- Validate command and path sanitization behavior.

## If You Touch Service Startup/Update/Factory Reset

- Validate start/stop/status behavior.
- Validate update plan/run behavior (including skip/force).
- Validate state cleanup semantics for reset.

## If You Touch Skills

- Ensure each skill folder has valid `manifest.json`.
- Ensure loader/sandbox constraints still pass.
- Update routing tests if skill selection logic changed.

## Minimum Test Bar

- Focused tests for changed module(s).
- `pytest -q` for broad or multi-module changes.
- Scenario scripts when changing CLI orchestration or update flows.
