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
