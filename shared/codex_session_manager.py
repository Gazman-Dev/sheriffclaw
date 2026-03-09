from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from shared import agent_repo
from shared.codex_mcp.runtime import CodexMCPRuntime
from shared.memory_store import MemoryStore
from shared.paths import agent_repo_root
from shared.session_registry import SessionRegistry
from shared.task_store import TaskStore


class CodexSessionManager:
    def __init__(
        self,
        *,
        runtime: CodexMCPRuntime | None = None,
        registry: SessionRegistry | None = None,
    ) -> None:
        self.registry = registry or SessionRegistry()
        self.runtime = runtime or CodexMCPRuntime(Path(__file__).resolve().parents[1], cwd=agent_repo_root())
        self.memory = MemoryStore()
        self.tasks = TaskStore()
        self.registry.mark_restart_generation()

    async def ensure_session(self, session_key: str, *, hydrate: bool = True) -> dict[str, Any]:
        record = self.registry.ensure_session(session_key)
        await self.runtime.ensure_started()
        if hydrate and not record.get("thread_id"):
            record = await self.hydrate_session(session_key)
        else:
            record = self.registry.mark_used(session_key)
        return record

    async def hydrate_session(self, session_key: str, *, reason: str = "hydrate") -> dict[str, Any]:
        record = self.registry.ensure_session(session_key)
        prompt = self._build_hydration_prompt(session_key, reason=reason)
        result = await self.runtime.start_conversation(
            prompt,
            cwd=str(agent_repo_root()),
            sandbox="workspace-write",
            include_plan_tool=True,
        )
        thread_id = _extract_thread_id(result)
        if thread_id:
            record = self.registry.bind_thread(session_key, thread_id)
        return record

    async def send_message(self, session_key: str, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        record = self.registry.ensure_session(session_key)
        await self.runtime.ensure_started()
        thread_id = str(record.get("thread_id") or "")
        if thread_id:
            result = await self.runtime.continue_conversation(prompt, thread_id)
        else:
            kwargs: dict[str, Any] = {"cwd": str(agent_repo_root()), "sandbox": "workspace-write"}
            if model:
                kwargs["model"] = model
            result = await self.runtime.start_conversation(prompt, **kwargs)
            new_thread_id = _extract_thread_id(result)
            if new_thread_id:
                record = self.registry.bind_thread(session_key, new_thread_id)
                thread_id = new_thread_id
        self.registry.mark_used(session_key)
        return {"session": self.registry.ensure_session(session_key), "result": result, "thread_id": thread_id}

    async def invalidate_session(self, session_key: str, *, reason: str = "manual") -> dict[str, Any]:
        return self.registry.invalidate_session(session_key, reason=reason)

    async def refresh_memory(self) -> dict[str, Any]:
        root = agent_repo.ensure_layout()
        snapshot = self.memory.global_memory_snapshot()
        return {
            "root": str(root),
            "memory_files": [
                str(agent_repo.path_for("memory", "user_profile.md")),
                str(agent_repo.path_for("memory", "preferences.md")),
                str(agent_repo.path_for("memory", "global_facts.md")),
                str(agent_repo.path_for("memory", "ongoing_projects.md")),
                str(agent_repo.path_for("memory", "decisions.md")),
            ],
            "snapshot_keys": sorted(snapshot.keys()),
        }

    async def runtime_health(self) -> dict[str, Any]:
        return await self.runtime.health()

    async def create_task(
        self,
        *,
        session_key: str,
        title: str,
        details: str = "",
        owner: str = "codex",
        status: str = "open",
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        task = self.tasks.create_task(
            title=title,
            session_key=session_key,
            details=details,
            owner=owner,
            status=status,
            refs=refs,
        )
        self.registry.add_task_ref(session_key, task["id"])
        return task

    async def list_tasks(self, *, session_key: str | None = None, status: str | None = None) -> dict[str, Any]:
        return {"tasks": self.tasks.list_tasks(session_key=session_key, status=status)}

    async def capture_message_task(
        self,
        *,
        session_key: str,
        text: str,
        channel: str,
        principal_id: str,
    ) -> dict[str, Any]:
        body = " ".join(text.strip().split())
        if not body or body.startswith("/"):
            return {"action": "skipped", "reason": "non_task_message"}
        ref = f"message:{channel}:{principal_id}:{int(time.time())}"
        open_tasks = sorted(
            self.tasks.open_tasks_for_session(session_key),
            key=lambda item: item.get("updated_at", 0),
            reverse=True,
        )
        if open_tasks:
            latest = open_tasks[0]
            if (time.time() - float(latest.get("updated_at", 0))) <= 900:
                updated = self.tasks.append_note(latest["id"], f"{channel}:{principal_id}: {body}", ref=ref)
                return {"action": "updated", "task": updated}
        title = self._task_title_from_text(body)
        task = await self.create_task(
            session_key=session_key,
            title=title,
            details=f"Initial request:\n{body}",
            refs=[ref],
        )
        return {"action": "created", "task": task}

    async def append_inbox(
        self,
        *,
        session_key: str,
        text: str,
        channel: str,
        principal_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = self.memory.append_inbox(
            session_key=session_key,
            text=text,
            channel=channel,
            principal_id=principal_id,
            metadata=metadata,
        )
        return entry

    async def append_decision(
        self,
        *,
        session_key: str | None,
        text: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.memory.append_decision(session_key=session_key, text=text, source=source, metadata=metadata)

    def _build_hydration_prompt(self, session_key: str, *, reason: str) -> str:
        agent_repo.ensure_session_artifacts(session_key)
        summary = agent_repo.summary_file(session_key).read_text(encoding="utf-8").strip()
        session_type = "private" if session_key == "private_main" else "group_topic"
        global_memory_parts = []
        for rel in (
            ("memory", "user_profile.md"),
            ("memory", "preferences.md"),
            ("memory", "global_facts.md"),
            ("memory", "ongoing_projects.md"),
            ("memory", "decisions.md"),
            ("tasks", "open_tasks.md"),
        ):
            path = agent_repo.path_for(*rel)
            global_memory_parts.append(f"## {path.name}\n{path.read_text(encoding='utf-8').strip()}")
        task_lines = self.tasks.summary_lines(session_key=session_key, limit=8)
        if task_lines:
            global_memory_parts.append("## Session Tasks\n" + "\n".join(task_lines))
        return (
            "Reconstruct this session from the repository state and continue coherently.\n\n"
            f"## Session Context\n- session_key: {session_key}\n- session_type: {session_type}\n- reason: {reason}\n\n"
            f"## Session Summary\n{summary}\n\n"
            + "\n\n".join(global_memory_parts)
        )

    def _task_title_from_text(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= 72:
            return compact
        return compact[:69].rstrip() + "..."


def _extract_thread_id(result: dict[str, Any]) -> str:
    structured = result.get("structuredContent", {}) if isinstance(result, dict) else {}
    thread_id = structured.get("threadId", "") if isinstance(structured, dict) else ""
    return str(thread_id or "")
