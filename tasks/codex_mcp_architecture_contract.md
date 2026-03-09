# Codex MCP Architecture Contract

## Purpose

This document freezes the intended end-state contract for the Codex MCP migration. It replaces ambiguous legacy
behavior with explicit target rules.

## Non-Goals

- no backward compatibility guarantee for old worker-era contracts
- no requirement that intermediate migration tasks keep the system healthy
- no attempt to preserve `primary_session` semantics
- no attempt to preserve the old terminal-driven Codex interaction model

## Final Runtime Model

SheriffClaw will host a long-lived `codex mcp-server` process and talk to it over stdio through a dedicated runtime
service.

Only the documented MCP tool surface is assumed:

- `codex`
- `codex-reply`

MCP `threadId` values are treated as process-lifetime handles. After a runtime restart, old thread IDs are assumed
stale unless future official documentation proves otherwise.

## Session Model

The application owns stable session keys. Codex owns live MCP thread IDs.

Stable session keys:

- private chat: `private_main`
- group topic: `group_<chat_id>_topic_<topic_id>`

Session metadata is repo-backed and must include at least:

- `session_key`
- `thread_id`
- `status`
- `last_used_at`
- `summary_path`
- `task_refs`
- `restart_generation`

## Persistent State Model

All long-lived agent cognition must live in a repo-backed state tree under `agent_repo/`.

Required top-level directories:

- `memory/`
- `tasks/`
- `sessions/`
- `prompts/`
- `skills/`
- `system/`
- `logs/`

The repo-backed state model replaces transcript accumulation as the durable source of context.

Host services may capture raw inputs and preserve operational state, but they must not perform agent cognition on
Codex's behalf. In particular:

- task decomposition and task status decisions belong to Codex turns, not gateway heuristics
- summary rewriting and memory promotion belong to Codex turns, not deterministic host reconciliation
- heartbeat and daily update behavior should be expressed in prompts and executed by Codex, not precomputed in Python

## Service Contract Direction

The old worker-era RPC surface is scheduled for removal:

- `agent.session.open`
- `agent.session.close`
- `agent.session.user_message`
- `agent.session.tool_result`

The replacement direction is session-key based operations:

- `codex.session.ensure`
- `codex.session.send`
- `codex.session.invalidate`
- `codex.session.hydrate`
- `codex.memory.refresh`

Exact payload schemas can evolve during implementation, but all new operations must use stable application session keys
instead of ephemeral worker session handles.

## Routing Contract

Gateway routing must stop collapsing all traffic into `primary_session`.

Required routing behavior:

- private Telegram chat -> `private_main`
- Telegram group topic -> `group_<chat_id>_topic_<topic_id>`

Queueing must serialize on real session identity, not on a fake global session.

## Restart Contract

On service restart:

- session metadata stays
- shared memory stays
- task state stays
- old live `thread_id` may be invalidated
- a fresh MCP thread may be created per active session
- the new thread must be hydrated from repo-backed summaries, tasks, and memory

## Legacy Concepts Scheduled For Deletion

These concepts are not part of the final architecture:

- `primary_session`
- `agent_workspace/` as the durable cognitive store
- terminal output scraping
- interactive menu parsing from CLI stdout
- file-based pending-reply protocol
- transcript-driven session resume

## Temporary Coexistence Rule

During migration, legacy and new state trees may coexist. New features should target `agent_repo/`. Legacy state may be
read only when required to keep the tree moving toward the final cutover.

## Current Repo Status

The current tree has already crossed the main cutover points:

- session routing is session-key based
- Telegram routing is topic-aware
- the public runtime service is `codex-mcp-host`
- the old `agent.session.*` RPC surface is removed
- the old terminal/file-protocol worker runtime is removed
- the repo-backed `agent_repo/` layout is the primary persistent state root

Remaining work is focused on richer memory/task systems, scheduled maintenance, repo-state automation, and final
cleanup.
