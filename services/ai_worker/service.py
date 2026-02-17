from __future__ import annotations

from shared.worker.worker_runtime import WorkerRuntime


class AIWorkerService:
    def __init__(self) -> None:
        self.runtime = WorkerRuntime()

    async def open_session(self, payload, emit_event, req_id):
        return {"session_handle": await self.runtime.session_open(payload.get("session_id"))}

    async def close_session(self, payload, emit_event, req_id):
        await self.runtime.session_close(payload["session_handle"])
        return {"status": "closed"}

    async def user_message(self, payload, emit_event, req_id):
        await self.runtime.user_message(payload["session_handle"], payload.get("text", ""), payload.get("model_ref"), emit_event)
        return {"status": "done"}

    async def tool_result(self, payload, emit_event, req_id):
        await self.runtime.tool_result(payload["session_handle"], payload.get("tool_name", "tool"), payload.get("result", {}))
        return {"status": "appended"}

    async def skills_list(self, payload, emit_event, req_id):
        return {"skills": await self.runtime.list_skills()}

    async def skill_run(self, payload, emit_event, req_id):
        result = await self.runtime.skill_run(payload["name"], payload.get("payload", {}), emit_event)
        return {"name": payload["name"], "result": result}

    async def skill_main(self, payload, emit_event, req_id):
        argv = payload.get("argv", [])
        if not argv:
            raise ValueError("skill name required")
        result = await self.runtime.skill_run(argv[0], {"argv": argv[1:], "stdin": payload.get("stdin", "")}, emit_event)
        return {"stdout": result.get("stdout", str(result)), "stderr": result.get("stderr", ""), "code": int(result.get("code", 0))}

    def ops(self):
        return {
            "agent.session.open": self.open_session,
            "agent.session.close": self.close_session,
            "agent.session.user_message": self.user_message,
            "agent.session.tool_result": self.tool_result,
            "skills.list": self.skills_list,
            "skill.run": self.skill_run,
            "skill.main": self.skill_main,
        }
