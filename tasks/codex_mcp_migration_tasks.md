# Codex MCP Migration Task Breakdown

## Scope

This plan assumes a hard cutover. Backward compatibility is not a goal.

Rules for this migration:

- old `ai-worker` behavior may be deleted instead of adapted
- old file-native `agent_workspace` turn protocol may be deleted instead of preserved
- old session semantics may be replaced outright
- the repo may be broken between tasks
- only the final state needs to be healthy

## Target End State

SheriffClaw stops acting like a wrapper around an interactive Codex CLI terminal and instead becomes a host for a
long-lived `codex mcp-server` runtime with:

- one MCP-backed private main session
- one MCP-backed session per Telegram group topic
- repo-backed shared memory
- repo-backed task tracking
- repo-backed session metadata
- scheduler-driven maintenance flows
- explicit session hydration after service restart

## Progress Snapshot

Completed in the repo already:

- Task 1
- Task 2
- Task 3
- Task 4
- Task 5
- Task 6
- Task 7
- Task 13
- most of Task 14
- most of Task 15

Still materially outstanding:

- Task 8
- Task 9
- Task 10 hardening beyond the current hydration scaffold
- Task 11
- Task 12
- Task 16 final broad cleanup and health pass

## Current System Seams To Replace

- `shared/worker/worker_runtime.py`: current interactive terminal/file protocol
- `services/ai_worker/service.py`: old `agent.session.*` RPC surface
- `services/sheriff_gateway/service.py`: currently hard-coded to `primary_session`
- `services/telegram_listener/service.py`: currently ignores Telegram topic-based session identity
- `services/sheriff_ctl/service_runner.py`: current service graph still assumes `ai-worker`
- `services/sheriff_ctl/system.py`: reset/update cleanup still targets old runtime state
- `shared/paths.py` and state layout: current roots are built around `agent_workspace/`

## Repository Target Layout

Adopt one durable agent repo layout and make all new runtime code use it:

```text
agent_repo/
  memory/
  tasks/
  sessions/
  prompts/
  skills/
  system/
  logs/
```

This can live under the SheriffClaw state root, but it should become the only supported persistent agent state model.

## Task List

### Task 1: Freeze the new architecture contract

Create a single source of truth for the migration target.

Work:

- convert `tasks/codex_mcp.md` and `tasks/codex_system.md` into implementation constraints
- document the final service names, state roots, and RPC contracts
- explicitly declare deleted legacy concepts: `primary_session`, `agent_workspace/`, terminal scraping, transcript-driven resume

Deliverable:

- new architecture decision doc under `tasks/` or `.codex/`

Broken state allowed after task:

- none

### Task 2: Introduce the new repo-backed state model

Build the filesystem contract before wiring runtime code to it.

Work:

- add a shared state layout module for `agent_repo/`
- define file helpers for `memory/`, `tasks/`, `sessions/`, `system/`, and `logs/`
- stop creating new files under `agent_workspace/` for any new feature
- add bootstrap/init helpers for empty repo creation

Main code areas:

- `shared/paths.py`
- new shared module for agent repo storage
- `services/sheriff_ctl/system.py`

Broken state allowed after task:

- old runtime still in place
- both old and new state trees may coexist temporarily

### Task 3: Replace the worker runtime abstraction

Delete the terminal-driven Codex runtime abstraction and replace it with an MCP-oriented runtime library.

Work:

- create a new runtime module that owns a long-lived `codex mcp-server` subprocess over stdio
- implement MCP lifecycle: spawn, health check, reconnect, shutdown
- implement tool discovery and strict support for `codex` and `codex-reply`
- delete terminal scraping, prompt-menu parsing, and file-based pending reply mechanics

Main code areas:

- replace `shared/worker/worker_runtime.py`
- add MCP client/runtime modules under `shared/worker/` or `shared/codex_mcp/`

Broken state allowed after task:

- `ai-worker` RPCs may fail until the new service surface is wired

### Task 4: Define the new session registry

Add the application-owned session model that maps Telegram identity to process-lifetime MCP thread IDs.

Work:

- create `sessions/sessions.json` plus per-session metadata files
- define session keys:
  private chat -> `private_main`
  group topic -> `group_<chat_id>_topic_<topic_id>`
- persist metadata such as `thread_id`, `status`, `last_used_at`, `summary_path`, `task_refs`, and `restart_generation`
- mark sessions stale on service restart because MCP `threadId` persistence is not assumed

Main code areas:

- new shared session registry module
- new runtime/session manager module

Broken state allowed after task:

- no callers need to use the registry yet

### Task 5: Replace `agent.session.*` with MCP-native service operations

Stop exposing the old worker API and replace it with operations that match the new architecture.

Work:

- remove or deprecate `agent.session.open`, `agent.session.close`, `agent.session.user_message`, `agent.session.tool_result`
- add explicit operations such as:
  - `codex.session.ensure`
  - `codex.session.send`
  - `codex.session.invalidate`
  - `codex.session.hydrate`
  - `codex.memory.refresh`
- make request and event payloads session-key based, not handle based

Main code areas:

- `services/ai_worker/service.py` or its replacement service
- callers in gateway and scheduler paths

Broken state allowed after task:

- old gateway code will break until migrated

### Task 6: Rebuild gateway routing around real session identity

Make gateway routing stop pretending the whole product is one `primary_session`.

Work:

- derive session key from channel metadata
- private chat routes to `private_main`
- group chat routes to topic session key
- change queueing to serialize by session key or principal/session composite, not global fake session
- remove transcript writes that assume one transcript file per fake session

Main code areas:

- `services/sheriff_gateway/service.py`
- shared identity helpers

Broken state allowed after task:

- Telegram group topics may still not pass enough metadata until listener migration lands

### Task 7: Rebuild Telegram ingestion for topic-aware routing

The listener must extract enough Telegram metadata to support the new session model.

Work:

- detect private chat vs group chat vs topic message
- capture `chat_id`, `message_thread_id`, and message metadata needed for routing
- pass topic identity to gateway
- define fallback behavior for group messages without topics
- keep Sheriff-channel unlock/admin flows separate from Codex chat flows

Main code areas:

- `services/telegram_listener/service.py`

Broken state allowed after task:

- non-Telegram callers may still use older payloads until updated

### Task 8: Implement repo-backed shared memory

Add the durable memory model described in the spec instead of relying on transcript accumulation.

Work:

- create canonical memory files such as `user_profile.md`, `preferences.md`, `ongoing_projects.md`, `decisions.md`
- create session summary files under `memory/summaries/`
- build read/write helpers with deterministic front matter or schema
- define when runtime reads memory into hydration prompts

Main code areas:

- new shared memory module
- runtime hydration builder

Broken state allowed after task:

- memory may exist without automatic upkeep

### Task 9: Implement the repo-backed task system

Move from ad hoc conversational continuity to explicit durable task state.

Work:

- add `tasks/task_index.json` and human-readable task views
- define task schema: id, title, status, owner, session_key, refs, timestamps
- add task creation and update helpers
- define how chat flows can attach messages and memory entries to tasks

Main code areas:

- new shared tasks module
- gateway/runtime integration points

Broken state allowed after task:

- no automated decomposition or maintenance yet

### Task 10: Implement restart-safe session hydration

This is the key bridge between process-lifetime MCP threads and durable cognition.

Work:

- when a session has no live `threadId`, create a new MCP thread
- build a hydration prompt from:
  - session summary
  - open linked tasks
  - global memory
  - recent relevant repo state
- update session registry with the new live `threadId`
- record restart generation and prior thread invalidation

Main code areas:

- new session manager
- MCP runtime send/start logic

Broken state allowed after task:

- old sessions are intentionally abandoned

### Task 11: Add the scheduler and maintenance prompts

Build the proactive system behaviors from the spec.

Work:

- add heartbeat and daily update jobs
- prevent heartbeat from overlapping daily update
- create prompts for memory reconciliation, task review, and session cleanup
- write job state to `system/maintenance_state.json`

Main code areas:

- new scheduler service or extend an existing daemon
- `prompts/`
- `system/`

Broken state allowed after task:

- jobs may run before commit/revert automation exists

### Task 12: Add repo-state Git workflows for the agent repo

The new architecture assumes Codex can maintain its repo-backed state safely.

Work:

- define allowed Git commands and wrapper helpers
- support diff, status, commit, and revert flows
- create commit policies for heartbeat and daily update
- decide whether the agent repo is the main SheriffClaw repo or a nested state repo and implement that choice consistently

Main code areas:

- new shared repo manager module
- tool execution/policy integration where needed

Broken state allowed after task:

- autonomous maintenance may still be conservative or disabled

### Task 13: Rework service orchestration and naming

The runtime topology must match the new system, not the old worker-era product.

Work:

- decide whether `ai-worker` is renamed or repurposed as a Codex MCP host service
- update `LLM_ORDER`, managed services, health checks, and logs
- remove startup assumptions specific to terminal Codex interaction
- update doctor/debug flows to inspect MCP runtime state instead of terminal logs

Main code areas:

- `services/sheriff_ctl/service_runner.py`
- `services/sheriff_ctl/doctor.py`
- `services/sheriff_ctl/utils.py`

Broken state allowed after task:

- installer/startup scripts may still refer to old names until final cleanup

### Task 14: Delete legacy runtime code paths

Once the new path exists, remove the compatibility burden completely.

Work:

- delete `agent_workspace` protocol handling
- delete fake menu-selection handling and terminal UI scraping
- delete legacy codex state bundle handling if the MCP architecture no longer needs it
- remove stale tests that only validate the deleted behavior

Main code areas:

- `shared/worker/worker_runtime.py`
- gateway and ctl code
- tests covering deleted contracts

Broken state allowed after task:

- test suite will be heavily red until rewritten

### Task 15: Rewrite tests around the new architecture

This is where the tree starts becoming healthy again.

Work:

- replace tests that assert `primary_session`, `agent.session.*`, or `agent_workspace` behavior
- add tests for:
  - session-key routing
  - topic-aware Telegram routing
  - session hydration after restart
  - memory/task persistence
  - scheduler exclusivity
  - service restart with stale `threadId`s

Main code areas:

- `tests/test_gateway_service.py`
- `tests/test_worker_runtime.py`
- `tests/test_ctl_*.py`
- Telegram and integration tests

Broken state allowed after task:

- some edges may still fail until docs and tooling are cleaned up

### Task 16: Final cleanup and health pass

Bring the repo into a coherent shippable state only after all migration work is in.

Work:

- remove dead imports, commands, docs, and stale state cleanup logic
- align onboarding, debug, update, and reset flows with the new architecture
- run broad tests
- update architecture docs to describe only the new world

Completion criteria:

- only MCP-backed runtime path remains
- only repo-backed memory/task/session state remains
- Telegram private and topic flows route correctly
- restart hydration works by creating fresh live threads
- broad tests pass

## Suggested Execution Order

Execute tasks in this exact order:

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7
8. Task 8
9. Task 9
10. Task 10
11. Task 11
12. Task 12
13. Task 13
14. Task 14
15. Task 15
16. Task 16

## Recommended First Implementation Slice

Start with Tasks 2 through 6 as one coding wave. That wave establishes:

- the new state layout
- the MCP runtime core
- the session registry
- the replacement service contract
- the gateway routing model

Once those land, the rest of the system can be migrated onto a real foundation instead of the current fake
single-session worker model.
