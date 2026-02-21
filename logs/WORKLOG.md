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
## 2026-02-20 09:15 EST
- New scope: build deterministic agent simulation for CLI tests (unit + e2e) covering permissions and secret-management flows.
- Plan:
  1) add scenario provider in worker runtime
  2) implement scripted tool-call triggers
  3) add scenario-focused unit tests
  4) add e2e harness script that drives `sheriff-ctl chat` stdin/stdout
  5) run tests + deploy
## 2026-02-20 09:28 EST
- Implemented deterministic `scenario/default` model path in worker runtime.
  - `scenario secret <handle>` => emits `secure.secret.ensure`
  - `scenario exec <tool>` => emits `tools.exec`
  - `scenario web <host>` => emits `secure.web.request`
  - `scenario last tool` => echoes latest tool-result from session history
- Added unit coverage for scenario simulation and gateway locked-secret handling.
- Built scripted E2E harness: `scripts/e2e_cli_simulation.sh`.
  - Drives `sheriff-ctl chat` with mixed Sheriff/Bot lines.
  - Validates secret-management flow (`/unlock`, `/secret`) and permission flow (`/allow-tool`).
  - Verifies persisted policy/requests state via `sheriff-ctl call` assertions.
- Fixed gateway crash path on locked secret lookup (was KeyError on missing `result`).
- Current local validation:
  - `pytest`: 55 passed
  - `./scripts/e2e_cli_simulation.sh`: passed
## 2026-02-20 09:36 EST
- New request: add installation testing and Linux validation via Docker container.
- Plan: create install-focused smoke test script + dockerized linux test runner that executes unit tests and installer E2E.
## 2026-02-20 09:41 EST
- Added installer-focused E2E script: `scripts/e2e_installation_check.sh`.
- Added Linux docker test harness:
  - `docker/linux-test.Dockerfile`
  - `scripts/test_linux_docker.sh`
  - Runner executes unit tests + CLI E2E + installer E2E in container.
- Local validation:
  - `pytest` passed (55)
  - installation E2E passed.
- Host limitation encountered: `docker` binary is not installed on this machine, so Linux container run cannot execute locally yet. Added explicit precheck/error message in docker runner script.
## 2026-02-20 12:21 EST
- Resumed full Linux blank-environment validation with Docker/Colima.
- Hardened installer:
  - auto-installs missing git/python on Linux/macOS package managers
  - install lock to prevent concurrent duplicate installation runs
  - idempotent source/venv reuse and onboarding skip when already initialized
  - non-interactive enforcement when `SHERIFF_MASTER_PASSWORD` is provided or `SHERIFF_NON_INTERACTIVE=1`
- Added reinstall idempotency test script.
- Ran full docker suite to completion:
  - unit tests passed (55)
  - CLI simulation E2E passed
  - installation E2E passed
  - reinstall idempotency check passed
  - final result: `Linux docker test suite passed`
## 2026-02-20 12:32 EST
- Started OpenAI Codex integration using secrets storage only (no host CLI auth dependency).
- Added `OpenAICodexProvider` against OpenAI Responses API.
- Updated default model resolution to `gpt-5.3-codex`.
- Plumbed provider/api key from Sheriff secrets through gateway -> ai-worker -> runtime.
- Added `/api-login <key> [provider]` sheriff command to save LLM provider+API key into encrypted vault.
- Added secrets ops for `secrets.set_llm_provider` and `secrets.set_llm_api_key`.
## 2026-02-20 12:40 EST
- Aligned Sheriff behavior with product definition: removed user-initiated auth provisioning from Sheriff chat.
- Removed `/api-login` command from Sheriff channel help/README/tests.
- Kept Codex secrets-backed provider plumbing, but credential provisioning is no longer exposed as Sheriff-action.
- Validation: pytest passed (56).
## 2026-02-20 12:52 EST
- Proceeding with non-Sheriff LLM provisioning path: add `sheriff-ctl configure-llm` command.
- Goal: keep Sheriff channel firewall-only while enabling explicit local setup command for provider + API key in secure vault.
## 2026-02-20 12:56 EST
- Added explicit non-Sheriff LLM setup command: `sheriff-ctl configure-llm`.
  - Stores provider + API key into encrypted Sheriff secrets.
  - If vault is locked, requires `--master-password` to unlock first.
- Updated docs to point auth setup to `configure-llm` (not Sheriff chat).
- Added parser test for new command.
- Validation:
  - pytest: 57 passed
  - install-path E2E: passed
## 2026-02-20 13:05 EST
- Added wiki documentation per request:
  - `docs/WIKI_ROLES.md` (LLM vs Sheriff responsibilities + trust boundary)
  - `docs/WIKI_USAGE.md` (installation, config, runtime usage, testing, troubleshooting)
- Added README wiki links section for discoverability.
## 2026-02-20 14:24 EST
- Moved wiki docs from main repo into GitHub wiki repo (`sheriffclaw.wiki`).
- Organized wiki pages:
  - Home
  - Roles-LLM-vs-Sheriff
  - How-to-Use-SheriffClaw
- Updated main README wiki links to GitHub wiki URLs.
- Removed duplicated docs from main repo (`docs/WIKI_ROLES.md`, `docs/WIKI_USAGE.md`).
## 2026-02-20 14:42 EST
- Simplified wiki for non-technical audience:
  - one-line curl|bash install
  - happy-path onboarding language
  - minimized terminal usage guidance
- Added bootstrap installer entrypoint `install.sh` for curl usage.
- Updated onboarding prompts in `sheriff-ctl onboard` to be friendlier and flow-oriented:
  - choose LLM with simple menu
  - set OpenAI key when needed
  - explicit Telegram-first setup prompts
- Updated README quick install command to `install.sh` raw URL.
- Validation: pytest passed (57).
