# Remaining Product Work

## Status

Core migration cutover is already in place:

- `codex-mcp-host` is the active runtime service
- session routing is session-key based
- Telegram routing is topic-aware
- repo-backed `agent_repo/` is the primary persistent state root
- legacy terminal/file-protocol worker runtime is removed
- durable task and memory stores exist
- scheduler service exists

What remains is product completion, not architectural cutover.

## Active Backlog

### 1. Automatic Task Decomposition

Goal:

- incoming user requests should automatically create or update durable tasks
- complex requests should be split into explicit sub-work rather than staying only in chat history

Needed work:

- define task extraction rules from inbound messages
- decide when to create a new task vs attach to an existing session task
- add session-aware task upsert flow in gateway/session manager
- support child/sub-task structure or linked task refs

Acceptance:

- a normal user request creates durable task state without manual intervention
- follow-up messages update the right task when appropriate

Current progress:

- the host now preserves raw inbound message state in repo-backed memory so Codex can inspect it during its turn
- task creation and updates are still expected to be agent-driven from prompts and repo context

Still missing:

- prompt wiring so normal user turns explicitly tell Codex to reconcile task state
- richer decomposition into multiple subtasks
- stronger duplicate detection across longer time windows
- intent-based status transitions like `blocked`, `done`, or `cancelled`

### 2. Memory Reconciliation

Goal:

- memory should become curated durable cognition instead of raw append-only notes

Needed work:

- summarize session inbox into session summaries
- extract preferences, decisions, and project facts into canonical memory files
- define how daily update rewrites or consolidates memory
- define safe overwrite vs append rules per memory file

Acceptance:

- session summaries improve over time
- global memory files become more structured and useful after maintenance runs

Current progress:

- raw memory artifacts exist and are available to Codex during hydration and maintenance turns
- maintenance prompt files now explicitly instruct Codex to perform summary and memory management itself

Still missing:

- actual agent-authored summary rewriting during normal and maintenance turns
- promotion into `user_profile.md`, `preferences.md`, and `global_facts.md`
- better deduplication and overwrite rules
- richer extraction of durable project facts from free-form inbox entries

### 3. Maintenance Job Behavior

Goal:

- `heartbeat` and `daily_update` should do meaningful maintenance, not only send generic prompts

Needed work:

- tighten prompt contents for heartbeat and daily update
- make heartbeat review pending tasks and blocked items
- make daily update reconcile summaries, memory, and task state
- persist clearer job result artifacts beyond `last_result`
- harden overlap and retry behavior

Acceptance:

- maintenance runs leave measurable state changes in memory/tasks
- heartbeat never runs while daily update is active

Current progress:

- scheduler runs heartbeat and daily-update as Codex turns without precomputing task or memory mutations in host code

Still missing:

- stronger lock/overlap semantics
- better retry and error-recovery behavior
- more targeted heartbeat/daily-update prompts tied to repo state and active sessions

### 4. Repo-State Git Workflows

Goal:

- maintenance jobs and future self-management should be able to diff, commit, and revert repo-backed state safely

Needed work:

- add controlled git helper module for `status`, `diff`, `commit`, and `revert`
- define which repo is authoritative for state commits
- add maintenance commit policy and commit message conventions
- expose safe entry points to the MCP runtime or maintenance layer

Acceptance:

- state changes can be committed intentionally with meaningful messages
- rollback path exists for bad maintenance changes

### 5. Task Lifecycle Enrichment

Goal:

- tasks should support stronger lifecycle management than simple status buckets

Needed work:

- add priority, blockers, due/review timestamps, and optional parent/child relationships
- improve rendered task views
- attach request and memory refs consistently

Acceptance:

- task data is rich enough for heartbeat and daily update to act on intelligently

### 6. Maintenance Skills

Goal:

- recurring maintenance workflows should be skill-driven where that improves repeatability

Needed work:

- add dedicated skills for memory management
- add dedicated skills for task management
- add dedicated skills for cron/scheduler maintenance
- decide whether Sheriff integration gets its own maintenance skill now or later

Acceptance:

- at least the main maintenance workflows are captured in reusable skills

### 7. Final Broad Validation

Goal:

- finish the migration with a healthy repo-wide state

Needed work:

- run broader pytest surface beyond focused suites
- reconcile remaining docs and operational text
- remove any dead code or stale tests still outside touched areas

Acceptance:

- broad tests pass
- docs describe only the MCP-era system

## Recommended Next Execution Order

1. Automatic Task Decomposition
2. Memory Reconciliation
3. Maintenance Job Behavior
4. Repo-State Git Workflows
5. Task Lifecycle Enrichment
6. Maintenance Skills
7. Final Broad Validation

## Current Next Task

Work on `Memory Reconciliation` and `Maintenance Job Behavior` next.
