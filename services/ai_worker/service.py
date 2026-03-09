from __future__ import annotations

from shared.codex_output import extract_text_content
from shared.codex_session_manager import CodexSessionManager
from shared.worker.worker_runtime import WorkerRuntime


class AIWorkerService:
    def __init__(self, *, runtime: WorkerRuntime | None = None, session_manager: CodexSessionManager | None = None) -> None:
        self.runtime = runtime or WorkerRuntime()
        self.session_manager = session_manager or CodexSessionManager()

    async def skills_list(self, payload, emit_event, req_id):
        return {"skills": await self.runtime.list_skills()}

    async def skill_run(self, payload, emit_event, req_id):
        result = await self.runtime.skill_run(payload["name"], payload.get("payload", {}), emit_event)
        return {"name": payload["name"], "result": result}

    async def skill_main(self, payload, emit_event, req_id):
        argv = payload.get("argv", [])
        if not argv:
            raise ValueError("skill name required")
        result = await self.runtime.skill_run(argv[0], {"argv": argv[1:], "stdin": payload.get("stdin", "")},
                                              emit_event)
        return {"stdout": result.get("stdout", str(result)), "stderr": result.get("stderr", ""),
                "code": int(result.get("code", 0))}

    async def codex_session_ensure(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        if not session_key:
            raise ValueError("session_key required")
        record = await self.session_manager.ensure_session(session_key, hydrate=bool(payload.get("hydrate", True)))
        return {"session": record}

    async def codex_session_send(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        prompt = str(payload.get("prompt") or "")
        if not session_key:
            raise ValueError("session_key required")
        if not prompt:
            raise ValueError("prompt required")
        model = str(payload.get("model_ref") or "").strip() or None
        result = await self.session_manager.send_message(session_key, prompt, model=model)
        tool_result = result.get("result") or {}
        if isinstance(tool_result, dict) and tool_result.get("isError"):
            return {
                "ok": False,
                "error": extract_text_content(tool_result) or "codex_tool_error",
                "session": result.get("session"),
                "thread_id": result.get("thread_id"),
                "result": tool_result,
            }
        content = extract_text_content(tool_result)
        if content:
            await emit_event("assistant.final", {"text": str(content)})
        return result

    async def codex_session_invalidate(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        if not session_key:
            raise ValueError("session_key required")
        record = await self.session_manager.invalidate_session(
            session_key,
            reason=str(payload.get("reason") or "manual"),
        )
        return {"session": record}

    async def codex_session_hydrate(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        if not session_key:
            raise ValueError("session_key required")
        record = await self.session_manager.hydrate_session(
            session_key,
            reason=str(payload.get("reason") or "hydrate"),
        )
        return {"session": record}

    async def codex_memory_refresh(self, payload, emit_event, req_id):
        return await self.session_manager.refresh_memory()

    async def codex_runtime_health(self, payload, emit_event, req_id):
        return await self.session_manager.runtime_health()

    async def codex_task_create(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not session_key:
            raise ValueError("session_key required")
        if not title:
            raise ValueError("title required")
        task = await self.session_manager.create_task(
            session_key=session_key,
            title=title,
            details=str(payload.get("details") or ""),
            owner=str(payload.get("owner") or "codex"),
            status=str(payload.get("status") or "open"),
            refs=list(payload.get("refs") or []),
        )
        return {"task": task}

    async def codex_task_list(self, payload, emit_event, req_id):
        return await self.session_manager.list_tasks(
            session_key=payload.get("session_key"),
            status=payload.get("status"),
        )

    async def codex_memory_inbox_append(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        text = str(payload.get("text") or "")
        if not session_key:
            raise ValueError("session_key required")
        if not text:
            raise ValueError("text required")
        entry = await self.session_manager.append_inbox(
            session_key=session_key,
            text=text,
            channel=str(payload.get("channel") or "cli"),
            principal_id=str(payload.get("principal_id") or "unknown"),
            metadata=payload.get("metadata"),
        )
        return {"entry": entry}

    async def codex_task_capture_from_message(self, payload, emit_event, req_id):
        session_key = str(payload.get("session_key") or "").strip()
        text = str(payload.get("text") or "")
        if not session_key:
            raise ValueError("session_key required")
        return await self.session_manager.capture_message_task(
            session_key=session_key,
            text=text,
            channel=str(payload.get("channel") or "cli"),
            principal_id=str(payload.get("principal_id") or "unknown"),
        )

    def ops(self):
        return {
            "skills.list": self.skills_list,
            "skill.run": self.skill_run,
            "skill.main": self.skill_main,
            "codex.session.ensure": self.codex_session_ensure,
            "codex.session.send": self.codex_session_send,
            "codex.session.invalidate": self.codex_session_invalidate,
            "codex.session.hydrate": self.codex_session_hydrate,
            "codex.memory.refresh": self.codex_memory_refresh,
            "codex.runtime.health": self.codex_runtime_health,
            "codex.task.create": self.codex_task_create,
            "codex.task.list": self.codex_task_list,
            "codex.task.capture_from_message": self.codex_task_capture_from_message,
            "codex.memory.inbox.append": self.codex_memory_inbox_append,
        }
