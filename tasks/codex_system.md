Below is a solid implementation-oriented tech spec you can hand to your AI.

# Tech Spec: Telegram-Codex Persistent Agent System

## 1. Purpose

Build a single-user AI system that uses Codex as the main reasoning and execution engine, with persistent memory, task tracking, and long-running conversational continuity across Telegram chats.

The system must support two conversation modes:

* **Private chat**: one persistent **main session**
* **Group chat**: one persistent **session per Telegram topic**

The system must feel persistent and self-maintaining, with shared memory across all sessions, durable task tracking, periodic self-review, and repo-backed state.

The entire operational state must live inside a local repository so Codex can inspect, update, commit, and revert its own working state.

---

## 2. Core Product Goals

The system should:

* preserve long-lived conversational continuity
* maintain shared memory across all chats and topics
* think in tasks rather than only replies
* track what is done, in progress, blocked, or pending
* periodically review and improve its own memory and summaries
* periodically check for unfinished work and proactively act on it
* use Codex skills for recurring workflows
* keep all state in a repo with local commits, even without a remote
* allow Codex to safely commit and revert repo changes
* support future integration with a “Sheriff” subsystem

---

## 3. High-Level Architecture

The system consists of the following major parts:

### 3.1 Telegram Interface Layer

Responsible for:

* receiving Telegram updates
* distinguishing private chat vs group chat
* resolving topic identity for group chats
* routing messages into the correct Codex session
* sending responses back to Telegram

### 3.2 Session Manager

Responsible for:

* maintaining one persistent **main session** for private chat
* maintaining one persistent **session per group topic**
* mapping Telegram conversation identity to Codex session identity
* resuming prior Codex sessions when new messages arrive
* storing session metadata in the repo

### 3.3 Shared Memory System

Responsible for:

* durable cross-session memory
* topic summaries
* user preferences
* project knowledge
* operational notes
* learned skills candidates
* long-term agent state

This memory is file-based and repo-backed.

### 3.4 Task System

Responsible for:

* converting incoming requests into explicit tasks
* tracking task decomposition
* tracking status and ownership
* linking tasks to sessions, summaries, and memory
* enabling heartbeat and daily review flows

### 3.5 Skill System

Responsible for:

* reusable agent workflows
* memory maintenance
* task decomposition and reconciliation
* cron job operations
* future Sheriff integration

### 3.6 Cron/Daemon Scheduler

Responsible for:

* running recurring agent prompts/jobs
* daily update flow
* hourly heartbeat flow
* preventing heartbeat from running during daily update

### 3.7 Repo State Manager

Responsible for:

* storing all persistent system data
* exposing Git operations to Codex
* allowing commit/revert workflows
* ensuring heartbeats commit pending changes
* preserving auditability of agent changes

---

## 4. Conversation Model

## 4.1 Private Chat Flow

Private chat is treated as a single ongoing conversation.

Behavior:

* one fixed session called the **main session**
* all private user messages route into this session
* the main session shares the same global memory and task system as all other sessions
* private chat can create tasks, modify memory, and influence shared state

Suggested logical ID:

```text
session_type: private
session_key: private_main
```

## 4.2 Group Chat Flow

Each Telegram topic in a group chat gets its own persistent session.

Behavior:

* one session per `(chat_id, topic_id)`
* messages in the same topic resume the same Codex session
* different topics remain conversationally separated
* all topics share the same global memory and task system

Suggested logical ID:

```text
session_type: group_topic
session_key: group_<chat_id>_topic_<topic_id>
```

## 4.3 Shared Cross-Session Behavior

Even though sessions are separated, they must all share:

* common memory files
* common task registry
* common repo state
* common learned skills
* common periodic maintenance flows

This means the system has **separate conversational threads** but **shared durable cognition**.

---

## 5. Codex Session Strategy

The system should not rely on one immortal process for everything.

Preferred approach:

* persist Codex session identity per session
* resume existing sessions when new messages arrive
* keep topic-local continuity in Codex session history
* use repo-backed files for long-term memory and task continuity

This gives:

* good continuity
* restart safety
* reduced context pollution
* clean separation between topics
* shared memory without mixing transcripts

---

## 6. Repo-Backed State Model

All memory, tasks, and operational state must live inside a local Git repo.

Initially there is no remote, but the repo must still support:

* local commits
* revert/reset workflows
* diffs
* history inspection

Codex should be allowed to modify files in the repo and use Git operations within configured safety limits.

### 6.1 Why Repo-Backed State

This enables:

* auditable memory evolution
* safe experimentation
* rollback of bad agent edits
* reviewable system history
* better self-maintenance by Codex

### 6.2 Commit Expectations

The system should support autonomous commits for maintenance activity.

Rules:

* heartbeat should commit pending changes when appropriate
* daily update may also produce commits
* commits should be meaningful, not spammy
* commit messages should reflect the maintenance action

Examples:

```text
heartbeat: reconcile pending task and memory updates
daily-update: refresh summaries, sessions, and skill candidates
topic-session: update android topic summary and task state
```

---

## 7. Repository Structure

Suggested structure:

```text
agent-repo/
  AGENTS.md
  README.md

  memory/
    user_profile.md
    preferences.md
    global_facts.md
    ongoing_projects.md
    decisions.md
    inbox.md
    learned_patterns.md
    skill_candidates.md
    summaries/
      private_main.md
      group_<chat_id>_topic_<topic_id>.md

  tasks/
    task_index.json
    open_tasks.md
    completed_tasks.md
    blocked_tasks.md
    task_history/
      YYYY-MM-DD.md

  sessions/
    sessions.json
    private_main.json
    group_<chat_id>_topic_<topic_id>.json

  skills/
    memory-manager/
      SKILL.md
    task-manager/
      SKILL.md
    cron-job/
      SKILL.md
    sheriff/
      SKILL.md

  prompts/
    daily_update.md
    heartbeat.md
    task_decomposition.md

  logs/
    runtime.log
    scheduler.log
    telegram.log

  system/
    config.json
    policies.md
    maintenance_state.json
```

---

## 8. Memory Model

The memory system should distinguish between different kinds of memory instead of treating everything as one blob.

## 8.1 Global Memory

Shared across all sessions.

Files may include:

* `user_profile.md` — durable user facts
* `preferences.md` — behavior and coding preferences
* `global_facts.md` — important facts relevant across topics
* `ongoing_projects.md` — active longer-running work
* `decisions.md` — decisions already made
* `learned_patterns.md` — recurring behaviors or habits
* `skill_candidates.md` — repeated workflows that might become skills
* `inbox.md` — raw captured facts not yet classified

## 8.2 Session/Topic Summaries

Each session gets a rolling summary file.

Examples:

* `memory/summaries/private_main.md`
* `memory/summaries/group_<chat_id>_topic_<topic_id>.md`

Each summary should contain:

* current topic focus
* relevant context
* unresolved questions
* active linked tasks
* important recent outcomes
* short history of notable turns

These summaries must be compact and maintained over time.

## 8.3 Memory Promotion Rules

When new information arrives, the agent should decide whether it is:

* ephemeral only
* session-local
* globally durable
* task-related
* candidate for a reusable skill

The default rule is to avoid polluting durable memory with transient noise.

When uncertain, store in `inbox.md` rather than immediately promoting into stable memory.

---

## 9. Task-Centric Thinking Model

The agent must think in tasks.

Whenever the user asks for something, the system should attempt to represent the work as explicit tasks.

## 9.1 Task Expectations

For each user request, the agent should:

* identify the main goal
* break the goal into concrete tasks or subtasks
* mark what is done
* mark what remains
* preserve task state across turns
* reconnect future related turns to existing tasks when appropriate

## 9.2 Task Status Model

Suggested statuses:

* `new`
* `planned`
* `in_progress`
* `waiting`
* `blocked`
* `done`
* `cancelled`

## 9.3 Task Metadata

Each task should support fields like:

```json
{
  "id": "task_2026_000123",
  "title": "Draft Telegram Codex architecture spec",
  "status": "in_progress",
  "session_key": "private_main",
  "created_at": "2026-03-08T10:00:00Z",
  "updated_at": "2026-03-08T10:12:00Z",
  "parent_task_id": null,
  "tags": ["spec", "architecture"],
  "summary": "Create the architecture specification for the Telegram Codex persistent agent system.",
  "next_steps": [
    "Finalize memory model",
    "Define cron job behavior"
  ],
  "completed_steps": [
    "Defined session model"
  ]
}
```

## 9.4 Task Storage

Primary machine-readable store:

* `tasks/task_index.json`

Human-readable rollups:

* `tasks/open_tasks.md`
* `tasks/completed_tasks.md`
* `tasks/blocked_tasks.md`

Daily activity log:

* `tasks/task_history/YYYY-MM-DD.md`

## 9.5 Task Reconciliation

The agent must avoid duplicating tasks unnecessarily.

When handling a new message, it should check whether the message:

* advances an existing task
* creates a new task
* changes a blocked task
* completes a task
* spawns a subtask

---

## 10. Skill System

The system should rely on Codex skills for reusable operational behaviors.

## 10.1 Required Skills

### 10.1.1 Memory Manager Skill

Responsible for:

* classifying memory updates
* promoting durable facts
* updating summaries
* reducing duplication
* managing inbox-to-memory promotion

### 10.1.2 Task Manager Skill

Responsible for:

* decomposing user requests into tasks
* updating task state
* marking completed/pending work
* reconciling duplicate tasks
* linking tasks to sessions and memory

### 10.1.3 Cron Job Skill

Responsible for:

* handling scheduled maintenance prompts
* running heartbeat flow
* running daily update flow
* committing maintenance changes
* coordinating scheduler behavior

### 10.1.4 Sheriff Skill

This should exist as a placeholder and be clearly marked as future work.

Responsibilities for now:

* `TODO: define sheriff protocol and communication contract`
* `TODO: define what conditions should trigger sheriff interaction`
* `TODO: define whether sheriff is supervisory, approval-based, or collaborative`

---

## 11. AGENTS.md Responsibilities

`AGENTS.md` should define the operational rules Codex follows inside the repo.

It should instruct Codex to:

* use task-centric reasoning
* check and update task state on meaningful turns
* preserve shared memory across sessions
* update session summaries when needed
* promote only durable facts into long-term memory
* identify repeated workflows that should become skills
* use the cron-job skill for scheduled maintenance behavior
* leave Sheriff integration as TODO
* commit meaningful maintenance changes
* avoid noisy commits
* prefer compact summaries
* avoid duplicating information across files
* use inbox/staging files when uncertain

It should also explicitly define the two conversation modes:

* private chat => one main session
* group chat => one session per topic

---

## 12. Scheduled Maintenance Flows

The system needs two recurring cron-driven flows from the “geko”.

I assume “crone” here means **cron-like scheduled jobs**. I’d standardize the implementation name as **cron job** everywhere in code and docs.

## 12.1 Daily Update Job

Runs once per day.

Purpose:

* review all docs
* review all sessions
* improve and compress summaries
* reconcile stale task state
* promote important memory
* inspect repeated patterns that can be converted into skills
* improve the structure and quality of the overall system state

Expected behavior:

* inspect memory files
* inspect session metadata
* inspect summaries
* inspect task registry
* identify weak summaries and improve them
* identify repeated operational workflows
* append or update entries in `skill_candidates.md`
* update docs as needed
* optionally commit resulting changes

Important constraint:

* **heartbeat must be skipped while daily update is running**

Suggested prompt intent:

```text
Perform full daily maintenance across memory, tasks, sessions, and summaries.
Review repeated work patterns and record skill candidates.
Improve compactness and clarity of persistent state.
Commit meaningful maintenance changes when appropriate.
```

## 12.2 Heartbeat Job

Runs once per hour.

Purpose:

* proactively check whether the agent has unfinished work
* determine whether anything requires action
* act on pending items when possible
* commit pending changes

Expected behavior:

* inspect open and waiting tasks
* inspect blocked tasks for changed conditions
* inspect pending repo changes
* determine whether any action is required
* make lightweight maintenance updates if needed
* commit pending changes when appropriate

Suggested prompt intent:

```text
Review unfinished tasks, pending work, and outstanding maintenance.
Determine whether action is needed and perform it if appropriate.
Commit pending repo changes when the current state is coherent.
```

Important rule:

* if daily update is active, **skip heartbeat**

---

## 13. Scheduler Rules

The scheduler should coordinate recurring jobs safely.

## 13.1 Required Scheduling Rules

* run daily update once per day
* run heartbeat once per hour
* do not run heartbeat during daily update
* do not run concurrent maintenance jobs that modify the same state
* avoid overlapping maintenance operations with active user-turn processing where possible

## 13.2 Concurrency Policy

Use a simple maintenance lock.

Suggested behavior:

* acquire maintenance lock before running daily update or heartbeat
* if lock is held by daily update, heartbeat exits immediately
* if lock is held by another heartbeat, skip duplicate run
* release lock after maintenance completes

---

## 14. Session Metadata

Each session should have metadata stored in the repo.

Suggested fields:

```json
{
  "session_key": "group_123_topic_9",
  "session_type": "group_topic",
  "chat_id": 123,
  "topic_id": 9,
  "codex_session_id": "abc123",
  "summary_file": "memory/summaries/group_123_topic_9.md",
  "created_at": "2026-03-08T10:00:00Z",
  "last_active_at": "2026-03-08T12:00:00Z",
  "linked_task_ids": ["task_2026_000123"],
  "status": "active"
}
```

There should also be a special metadata file for `private_main`.

---

## 15. Incoming Message Processing Flow

For every Telegram message, the system should follow this flow:

### 15.1 Resolve Conversation Identity

Determine whether the message belongs to:

* private chat => `private_main`
* group topic => `group_<chat_id>_topic_<topic_id>`

### 15.2 Load Session Context

Load:

* session metadata
* session summary
* relevant open tasks
* selected shared memory files
* latest relevant recent conversation context

### 15.3 Resume Codex Session

Resume the corresponding Codex session if it exists; otherwise create it.

### 15.4 Task-Oriented Interpretation

Before producing the response, the agent should:

* identify user intent
* map it to existing tasks or create new ones
* update task state
* note what is done and what remains

### 15.5 Produce Response

Return a useful conversational response through Telegram.

### 15.6 Post-Response Maintenance

After the response, the agent may:

* update session summary
* update memory
* update task files
* stage relevant repo changes

Not every turn requires a commit, but meaningful state changes should be captured in the repo.

---

## 16. Summary Improvement Strategy

The system should aggressively maintain useful summaries.

A good summary should be:

* compact
* current
* readable
* action-oriented
* linked to task state
* free of stale trivia

Daily update is responsible for global summary quality, but individual sessions can also update summaries incrementally after important turns.

---

## 17. Skill Candidate Detection

The system should continuously look for repeated workflows that should become reusable skills.

Examples of candidate patterns:

* recurring maintenance procedure
* repeated file reconciliation flow
* common style of Telegram request handling
* repeated multi-step coding workflow
* repeated memory normalization workflow

These should be tracked in:

* `memory/skill_candidates.md`

The daily update job should review this file and improve it.

---

## 18. Git Behavior

The repo must be treated as the durable operational state of the agent.

## 18.1 Required Git Capabilities

Codex should be able to:

* inspect status
* inspect diff
* add changes
* commit changes
* revert/reset when explicitly needed or when directed by policy

## 18.2 Commit Policy

Commits should happen when:

* heartbeat finds coherent pending changes
* daily update performs meaningful maintenance
* other agent operations produce major durable state transitions

Commits should not happen for tiny meaningless churn unless policy says otherwise.

## 18.3 Revert Policy

Reverts should be possible because the repo is local and versioned.

The system should preserve enough discipline that bad memory edits can be undone.

---

## 19. Safety and Control Principles

The system should be autonomous but not chaotic.

Principles:

* avoid runaway self-modification
* keep changes inspectable
* keep summaries compact
* prefer explicit task tracking
* prefer file-based durable memory over transcript sprawl
* treat skills as stable reusable workflows
* keep Sheriff integration as TODO until designed properly

---

## 20. Open TODOs

### Sheriff Integration

We need skills for all the integrations with the sheriff

## 21. Final Architecture Summary

The target system is a Telegram-connected persistent Codex agent with:

* one **main session** for private chat
* one **session per topic** for group chat
* a **shared durable memory system** across all sessions
* a **task-centric reasoning model**
* repo-backed state for memory, tasks, and sessions
* Git-enabled commits and reverts
* a **cron job skill**
* a placeholder **Sheriff skill**
* a daily maintenance job
* an hourly heartbeat job
* heartbeat skipped during daily update
* periodic identification of workflows that should be converted into skills

The transcript is not the source of truth.
The repo is the source of truth.
Codex sessions provide conversational continuity, while the repo provides persistent cognition.