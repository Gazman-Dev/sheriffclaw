from __future__ import annotations

import json
from pathlib import Path

from shared.paths import agent_repo_root


REQUIRED_DIRS = (
    ".codex",
    "memory",
    "memory/summaries",
    "tasks",
    "tasks/task_history",
    "sessions",
    "skills",
    "system",
    "logs",
)

DEFAULT_TEXT_FILES = {
    "AGENTS.md": (
        "# SheriffClaw Agent Instructions\n\n"
        "The repo is the durable source of truth. Do not treat the transient chat transcript as the authoritative state.\n\n"
        "## Core Behavior\n"
        "- Read and update repo-backed tasks, session summaries, and memory when the work actually warrants it.\n"
        "- Do not assume the host has already decomposed tasks, reconciled summaries, or promoted memory.\n"
        "- Preserve raw user meaning. Treat incoming user messages as the user turn itself, not as host-written wrappers.\n"
        "- For private chat use `private_main`. For group topics use `group_<chat_id>_topic_<topic_id>`.\n"
        "- Prefer compact durable state over noisy duplicated notes.\n\n"
        "## Task Behavior\n"
        "- Think in tasks for meaningful user requests.\n"
        "- Inspect `tasks/task_index.json`, rendered task views, and relevant session files before deciding whether to create, update, block, complete, or cancel tasks.\n"
        "- Reuse existing tasks when the new turn clearly advances ongoing work.\n"
        "- Break larger work into explicit subtasks when that improves execution clarity.\n\n"
        "## Memory Behavior\n"
        "- Use `memory/inbox.md` for raw captured inputs and uncertain facts.\n"
        "- Promote only durable information into `user_profile.md`, `preferences.md`, `global_facts.md`, `ongoing_projects.md`, `decisions.md`, `learned_patterns.md`, or `skill_candidates.md`.\n"
        "- Rewrite session summaries to stay compact, current, and action-oriented.\n"
        "- Avoid polluting durable memory with transient or repetitive details.\n\n"
        "## Maintenance Behavior\n"
        "- During heartbeat and daily-update work, inspect repo-backed tasks, sessions, summaries, and memory before deciding what to change.\n"
        "- Use the maintenance skills in `skills/` when they match the current situation.\n"
        "- If no repo change is warranted, leave the durable state alone.\n\n"
        "## Skills\n"
        "- `skills/task-manager/SKILL.md`: task decomposition and task-state reconciliation.\n"
        "- `skills/memory-manager/SKILL.md`: memory promotion and summary maintenance.\n"
        "- `skills/cron-job/SKILL.md`: heartbeat and daily-update maintenance behavior.\n"
        "- `skills/sheriff/SKILL.md`: placeholder for future Sheriff integration.\n"
    ),
    "config.toml": "",
    ".codex/config.toml": "",
    "memory/user_profile.md": "# User Profile\n",
    "memory/preferences.md": "# Preferences\n",
    "memory/global_facts.md": "# Global Facts\n",
    "memory/ongoing_projects.md": "# Ongoing Projects\n",
    "memory/decisions.md": "# Decisions\n",
    "memory/inbox.md": "# Inbox\n",
    "memory/learned_patterns.md": "# Learned Patterns\n",
    "memory/skill_candidates.md": "# Skill Candidates\n",
    "tasks/open_tasks.md": "# Open Tasks\n",
    "tasks/completed_tasks.md": "# Completed Tasks\n",
    "tasks/blocked_tasks.md": "# Blocked Tasks\n",
    "system/policies.md": "# Policies\n",
    "README.md": "# Agent Repo\n",
    "skills/task-manager/SKILL.md": (
        "---\n"
        "name: task-manager\n"
        "description: Decide how repo-backed task state should change for current work, including task creation, reuse, reconciliation, and subtask planning.\n"
        "---\n\n"
        "# Task Manager\n\n"
        "Use this skill when a turn requires deciding how repo-backed task state should change.\n"
        "Inspect the current session summary, task index, rendered task views, and any relevant memory before editing task files.\n"
        "Prefer updating an existing task when the request clearly continues active work. Create subtasks when the work has distinct deliverables.\n"
    ),
    "skills/memory-manager/SKILL.md": (
        "---\n"
        "name: memory-manager\n"
        "description: Decide whether information belongs in durable memory, including memory promotion, pruning, and session summary maintenance.\n"
        "---\n\n"
        "# Memory Manager\n\n"
        "Use this skill when deciding whether information belongs in durable memory.\n"
        "Start from raw captures in `memory/inbox.md`, session summaries, and task state. Promote only durable information.\n"
        "Keep summaries compact and rewrite them instead of blindly appending noise.\n"
    ),
    "skills/cron-job/SKILL.md": (
        "---\n"
        "name: cron-job\n"
        "description: Run scheduler-driven maintenance such as heartbeat and daily update by inspecting repo-backed tasks, summaries, and memory before changing state.\n"
        "---\n\n"
        "# Cron Job\n\n"
        "Use this skill during scheduler-driven maintenance such as heartbeat or daily update.\n"
        "Inspect tasks, summaries, and memory first. Decide what maintenance work is actually needed, then perform only coherent repo changes.\n"
    ),
    "skills/sheriff/SKILL.md": (
        "---\n"
        "name: sheriff\n"
        "description: Placeholder skill for future Sheriff integration behavior and constraints inside the repo-backed agent workflow.\n"
        "---\n\n"
        "# Sheriff\n\n"
        "Placeholder for future Sheriff integration.\n"
        "Do not invent a Sheriff protocol yet. Record integration needs and constraints, but treat execution behavior as TODO until designed.\n"
    ),
    "skills/task-manager/manifest.json": (
        '{\n'
        '  "skill_id": "task-manager",\n'
        '  "description": "Task decomposition and task-state reconciliation guidance",\n'
        '  "command": "python -c \\"print(\'task-manager guidance only\')\\"",\n'
        '  "tags": ["tasks", "planning"]\n'
        '}\n'
    ),
    "skills/memory-manager/manifest.json": (
        '{\n'
        '  "skill_id": "memory-manager",\n'
        '  "description": "Memory promotion and summary maintenance guidance",\n'
        '  "command": "python -c \\"print(\'memory-manager guidance only\')\\"",\n'
        '  "tags": ["memory", "summaries"]\n'
        '}\n'
    ),
    "skills/cron-job/manifest.json": (
        '{\n'
        '  "skill_id": "cron-job",\n'
        '  "description": "Scheduler maintenance guidance",\n'
        '  "command": "python -c \\"print(\'cron-job guidance only\')\\"",\n'
        '  "tags": ["scheduler", "maintenance"]\n'
        '}\n'
    ),
    "skills/sheriff/manifest.json": (
        '{\n'
        '  "skill_id": "sheriff",\n'
        '  "description": "Placeholder Sheriff integration guidance",\n'
        '  "command": "python -c \\"print(\'sheriff guidance only\')\\"",\n'
        '  "tags": ["sheriff", "future"]\n'
        '}\n'
    ),
}

DEFAULT_JSON_FILES = {
    "sessions/sessions.json": {"version": 1, "restart_generation": 0, "sessions": {}},
    "tasks/task_index.json": {"version": 1, "tasks": {}},
    "system/config.json": {"version": 1},
    "system/maintenance_state.json": {
        "version": 1,
        "heartbeat": {"last_run_at": None, "status": "idle"},
        "daily_update": {"last_run_at": None, "status": "idle"},
    },
}


def root() -> Path:
    return agent_repo_root()


def path_for(*parts: str) -> Path:
    return root().joinpath(*parts)


def ensure_layout() -> Path:
    repo_root = root()
    for rel in REQUIRED_DIRS:
        path_for(*Path(rel).parts).mkdir(parents=True, exist_ok=True)
    for rel, content in DEFAULT_TEXT_FILES.items():
        _write_text_if_missing(path_for(*Path(rel).parts), content)
    for rel, payload in DEFAULT_JSON_FILES.items():
        _write_json_if_missing(path_for(*Path(rel).parts), payload)
    return repo_root


def session_file(session_key: str) -> Path:
    return path_for("sessions", f"{session_key}.json")


def summary_file(session_key: str) -> Path:
    return path_for("memory", "summaries", f"{session_key}.md")


def ensure_session_artifacts(session_key: str) -> dict[str, Path]:
    ensure_layout()
    session_path = session_file(session_key)
    summary_path = summary_file(session_key)
    _write_json_if_missing(
        session_path,
        {
            "session_key": session_key,
            "thread_id": None,
            "status": "new",
            "task_refs": [],
            "restart_generation": 0,
        },
    )
    _write_text_if_missing(summary_path, f"# Session Summary: {session_key}\n")
    return {"session": session_path, "summary": summary_path}


def _write_text_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json_if_missing(path: Path, payload: dict) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
