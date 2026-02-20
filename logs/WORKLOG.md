## 2026-02-20 08:49 EST
- User requested mandatory write-only progress log for transparency.
- Decision: maintain append-only development log at `logs/WORKLOG.md`.
- Current state snapshot:
  - Implemented terminal chat routing (`/` -> Sheriff, others -> Agent).
  - Added `sheriff-cli-gate` service and `sheriff-ctl chat` command.
  - Added test model route support (`--model-ref test/default`).
  - Fixed installer entrypoint (`install_sheriffclaw.sh`) and non-interactive onboarding path.
  - Added/updated tests; suite green locally in dev venv (`51 passed`).
- Issues encountered so far:
  - Python 3.9 compatibility failures (`zip(..., strict=False)` and runtime assumptions).
  - service binary lookup failed due to resolved interpreter symlink path.
  - non-interactive install failed due to getpass TTY behavior.
- Deployment notes:
  - Multiple direct pushes to `main` completed during this cycle.
  - Release workflow is producing prerelease snapshots on push.
- Process update:
  - From now on, append every meaningful step/problem/deploy note here before reporting status.
## 2026-02-20 08:52 EST
- User requested to continue to completion.
- Next steps: run fresh install, verify service startup in installed env, run `sheriff-ctl chat` scripted E2E for Sheriff+Agent routes, patch failures immediately.
## 2026-02-20 08:58 EST
- Ran clean install test from script after venv-binary and non-interactive onboarding fixes.
- Install now succeeds in non-interactive mode using env vars.
- Executed scripted E2E chat:
  - `/status` returned healthy services
  - plain text (`what / do?`) routed to Agent and returned TestBot response
  - `/ yes I agree` routed to Sheriff
- Identified a UX consistency gap: installer still referenced daemon status flow; updated to on-demand startup messaging.
- Added sheriff-cli-gate to `/status` check list in cli gate service.
## 2026-02-20 09:06 EST
- Deployed commit `e6ba500` to `main`.
- Performed post-deploy clean install from GitHub clone path via installer.
- Post-deploy E2E verification passed:
  - `/status` => all services healthy, including `sheriff-cli-gate`
  - plain text route => Agent response (`TestBot[test/default]: what / do?`)
  - slash text route => Sheriff response (`Sheriff received: / yes I agree`)
- Acceptance criteria covered on macOS local environment.
