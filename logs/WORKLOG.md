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
## 2026-02-20 19:31 EST
- Phase 1 (minimal memory refactor) implemented only:
  - added `shared/memory/` skeleton
  - versioned Topic + WakePacket schemas
  - TopicStore CRUD + alias-only retrieval (normalized string matching)
  - `memory.sleep()` / `memory.wake()` entrypoints (no embeddings, no graph)
  - added focused test + runnable demo harness for sleep->wake alias recall
- Validation:
  - `pytest tests/test_memory_phase1.py` passed
  - demo output confirms "remember the party" alias retrieval after sleep/wake
## 2026-02-20 19:38 EST
- Applied Phase 1 follow-up fixes:
  - tightened alias extraction to user-text only with stopwords/glue filtering and token validity checks
  - added typed shapes for NumberEntry and NotableEvent in memory schema
  - documented stable sleep() return keys in docstring
  - added regression tests:
    - glue-word query (`noted`) returns no topic
    - recency tie-break for shared alias returns most recent topic
- Validation: `pytest tests/test_memory_phase1.py` => 3 passed
## 2026-02-20 19:50 EST
- Implemented Phase 2 (without graph/skills/responses wiring):
  - EmbeddingProvider interface + deterministic local embedding provider
  - SemanticIndex interface + HnswlibSemanticIndex with disk persistence (index.bin + meta.json)
  - retrieval module with light/deep retrieval, trigger detection, low-confidence trigger, and UTC time windows (yesterday/last week/before sleep)
  - topic markdown renderer for prompt injection (`render_topic_md`)
  - semantic index sync helper for Topic JSON source of truth
- Added Phase 2 tests and demo script.
- Validation:
  - `pytest tests/test_memory_phase1.py tests/test_memory_phase2.py` => 5 passed
  - demo confirms alias miss + semantic recall and before-sleep boost behavior.
## 2026-02-20 20:02 EST
- Applied approved pre-Phase3 improvements:
  1) EmbeddingProvider now supports `embed_batch(texts)` with `embed(text)` wrapper.
  2) Semantic score normalization clarified and enforced to [0..1] (higher better) for cosine distance conversion.
  3) Retrieval tuning moved to `RetrievalConfig` dataclass (K values, boosts, confidence thresholds).
- Implemented Phase 3 (no graph):
  - skill manifest schema + loader (`shared/memory/skill_routing.py`)
  - light skill routing always (top 1-2)
  - deep skill search on triggers (repo-edit/tests/docs/debug/multi-step)
  - added example manifests: `skills/write_docs/manifest.json`, `skills/debug_trace/manifest.json`
  - added routing tests + demo harness
- Validation:
  - pytest (phase tests): 9 passed
  - demo output shows docs query -> write_docs and stack trace -> debug_trace
## 2026-02-20 20:19 EST
- Implemented Phase 4 runtime integration entrypoint:
  - `run_turn(conversation_buffer, user_msg, now, stores, config, model_adapter)`
  - always-on light topic/skill retrieval each turn
  - deep retrieval only via triggers/low-confidence (topic retrieval path)
  - model tool-calling loop with topics/memory/skills/repo tool surface
  - sleep policy via token estimate threshold; sleep then wake+resume within same turn
- Added Phase 4 tests:
  - tool calling loop (repo.write_file)
  - sleep/wake integration trigger
- Added demo script showing old topic recall, tool call execution, and sleep->wake resume.
## 2026-02-20 20:32 EST
- Verified third-party claimed graph/utility implementation against actual repo state.
- Findings:
  - No `tests/test_memory_graph.py` exists.
  - No TopicEdge type in `shared/memory/types.py`.
  - No edge persistence in `shared/memory/store.py`.
  - No graph expansion logic in `shared/memory/retrieval.py`.
  - No `topics.link` tool in phase4 runtime tool surface.
  - No utility decay math implemented in memory store/runtime.
- Test verification:
  - full suite green: 68 passed, 0 failed.
- Conclusion: claimed graph/utility work is not present in current branch; no unit-test fixes required now.
## 2026-02-20 23:13 EST
- Implemented Chunk A only (data model + store):
  - Added versioned `TopicEdge` schema and `EdgeType` enum.
  - Added edge persistence in `_edges.json` alongside topics JSON.
  - Added edge CRUD APIs (upsert/list/neighbors/delete) + `link_topics` compatibility alias.
  - Added utility fields defaults in topic stats: `utility_score`, `last_utility_update_at`.
  - Added store-layer utility math: `update_utility`, `apply_decay`, and pure `decay_utility_value`.
- Added deterministic unit tests for Chunk A:
  - edge round-trip
  - neighbor lookup/type filter
  - utility bump+decay math with fixed timestamps
- Reconciled externally-added graph tests with Chunk A scope:
  - co-activation test updated to assert no auto-linking yet (runtime behavior intentionally deferred to Chunk B).
- Validation:
  - full test suite passes: 74 passed.
## 2026-02-20 23:22 EST
- Started Chunk B (runtime + retrieval graph integration).
- Implemented sleep co-activation linking:
  - touched topics are alias-upsert topics from compacted slice
  - pairwise RELATES_TO edge bump (+0.5, cap 5.0), bidirectional via link_topics
- Implemented deep retrieval 1-hop expansion:
  - expand neighbors from top-N deep-ranked nodes with min-weight threshold
  - add neighbor bonus in ranking
- Added `topics.link` tool compatibility in phase4 runtime with explicit schema (`edge_type`, `weight`, `mode`).
- Added utility bump hook in sleep (+1 per touched topic, optional +3 correction signal, +2 skill-success signal) and decay application once per sleep.
- Added/updated tests and demo for graph expansion effect.
- Validation: full suite 75 passed.
## 2026-02-20 23:43 EST
- Implemented reinstall-focused onboarding UX updates per request:
  - Removed SHERIFF_FORCE_ONBOARD-based skip behavior from installer.
  - On second install detection (existing vault), installer now prompts for aggressive reinstall.
  - If onboarding exits in interactive mode, installer now offers aggressive reinstall prompt.
  - Added `sheriff-ctl onboarding` alias command.
  - Added `sheriff-ctl reinstall` command to aggressively wipe Sheriff/Agent state (`gw` + `llm`).
- Verified reinstall command end-to-end in isolated `SHERIFFCLAW_ROOT` temp directory.
- Added parser tests for onboarding alias + reinstall command.
## 2026-02-20 23:50 EST
- Fixed onboarding behavior for `curl | bash` installs:
  - if stdin is piped but `/dev/tty` exists, installer now runs onboarding interactively via `/dev/tty`.
  - second-install reinstall prompt also uses `/dev/tty` in piped mode.
- Updated reinstall UX:
  - `sheriff-ctl reinstall` now asks two yes/no confirmations.
  - added `--yes` for automation/non-interactive tests.
- Verified:
  - parser tests updated and passing
  - onboarding+reinstall flow validated in isolated root with `--yes` path
## 2026-02-21 00:36 EST
- Added cache busting into `install.sh` itself by appending `?ts=$(date +%s)` to fetched installer URL.
- Improved onboarding password UX:
  - master password now requires confirmation; mismatch retries.
- Added Codex auth method options in onboarding:
  - OpenAI Codex (API key)
  - OpenAI Codex (auth token)
  - stub
- Added Telegram activation infrastructure and onboarding flow:
  - identity now stores pending activation codes and bot bindings (`llm`, `sheriff`).
  - activation code API added to secrets service (`create/claim/status`).
  - ai/sheriff telegram services now return activation_required with 5-letter code for unknown users and accept `activate <code>`.
  - onboarding prompts activation in order: AI bot first, then Sheriff bot.
- Non-interactive onboarding now skips activation prompts safely.
- Full test suite green: 79 passed.
## 2026-02-21 00:52 EST
- Clarified ChatGPT subscription auth request feasibility:
  - Removed misleading 'paste auth token' UX from onboarding.
  - Added explicit message that ChatGPT subscription auth flow is not available in this build.
- Added vault auth lifecycle support primitives:
  - `llm_auth` structure in encrypted secrets state
  - secrets ops: get/set/clear llm_auth
  - `sheriff-ctl logout-llm` command clears stored LLM auth/api key from vault
- Kept Codex API-key path intact and secure.
## 2026-02-21 01:05 EST
- Implemented Device Code auth flow for ChatGPT subscription Codex per provided endpoints/constants:
  - `shared/llm/device_auth.py` with usercode request, token polling, oauth exchange, refresh helper.
  - always prints full verification URL + user code.
  - supports Enter-to-cancel while polling (TTY).
- Onboarding now supports:
  - API key path
  - ChatGPT subscription login path (device flow)
  - retry loop to switch method if cancelled/fails.
- Vault auth persistence:
  - stores auth object (type/access/refresh/id token/obtained/expires) in encrypted secrets, not llm_api_key.
  - added clear/logout command and secrets ops for get/set/clear auth.
- Gateway/runtime integration:
  - when provider is `openai-codex-chatgpt`, uses vault auth access token.
  - refreshes access token when expired using refresh_token and persists updated auth.
  - routes subscription auth calls via ChatGPT backend codex endpoint provider.
- Test status: full suite 80 passed.
## 2026-02-21 01:14 EST
- Addressed onboarding auth flow crash and UX polish from user repro:
  - device-code polling now handles pending/error responses without traceback; 403 no longer crashes onboarding loop.
  - login URL now includes embedded code query param and attempts browser auto-open.
  - cancel key changed from Enter to Esc during polling.
  - moved device-auth import to lazy import path so warning filter is installed first.
- Added warning suppression gate in CLI (`SHERIFF_DEBUG` enables warnings; default hides NotOpenSSLWarning).
## 2026-02-21 01:23 EST
- Replaced device-code auth with browser OAuth + PKCE localhost callback flow per updated spec:
  - authorize URL uses required params (`id_token_add_organizations`, `codex_cli_simplified_flow`, scope, pkce, state)
  - callback server on `127.0.0.1:1455/auth/callback`
  - validates state and exchanges code at oauth token endpoint
  - prints full URL always and tries to open browser automatically
  - stores token expiry derived from id_token exp
- Keeps refresh_token grant path for subsequent token refresh.
- Full test suite still green: 80 passed.
## 2026-02-21 01:35 EST
- Fixed onboarding UX/flow bugs from latest user repro:
  - AI bot token is now requested and activated first; only then asks for Sheriff token and activates it.
  - activation now relies on bot listener + status polling (no manual code typing in CLI).
  - onboarding Ctrl-C now exits gracefully without traceback.
- Improved auth login flow UX:
  - URL includes embedded code and browser auto-open remains best-effort.
  - Esc remains cancellation key in prior device flow logic, but browser OAuth is default path.
## 2026-02-21 01:49 EST
- Fixed additional onboarding issues:
  - moved Telegram unlock-policy question to after both bot activations complete.
  - activation flow now polls Telegram Bot API updates directly, generates/sends activation code to every unbound DM sender, and waits for pasted code.
  - onboarding no longer asks for both bot tokens up front; asks AI token -> activate -> asks Sheriff token -> activate.
  - updated auth type label to `chatgpt_browser_oauth` and wording to browser login.
  - Ctrl-C in activation prompt remains graceful (no traceback).
