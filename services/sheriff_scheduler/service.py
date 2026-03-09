from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from typing import Any

from shared import agent_repo
from shared.oplog import get_op_logger
from shared.proc_rpc import ProcClient
from shared.task_store import TaskStore


class SheriffSchedulerService:
    def __init__(self) -> None:
        self.log = get_op_logger("scheduler")
        self.state_path = agent_repo.path_for("system", "maintenance_state.json")
        self.task_store = TaskStore()
        self.gateway = ProcClient("sheriff-gateway", spawn_fallback=False)
        self.ai = ProcClient("codex-mcp-host", spawn_fallback=False)
        self.poll_interval_sec = float(os.environ.get("SHERIFF_SCHEDULER_POLL_SEC", "30"))
        self.heartbeat_interval_sec = float(os.environ.get("SHERIFF_HEARTBEAT_INTERVAL_SEC", "3600"))
        self.daily_update_interval_sec = float(os.environ.get("SHERIFF_DAILY_UPDATE_INTERVAL_SEC", "86400"))

    def _load_state(self) -> dict[str, Any]:
        agent_repo.ensure_layout()
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    async def run_due(self, payload, emit_event, req_id):
        return await self._run_due_jobs(force=bool(payload.get("force", False)))

    async def status(self, payload, emit_event, req_id):
        return self._load_state()

    def ops(self):
        return {
            "scheduler.run_due": self.run_due,
            "scheduler.status": self.status,
        }

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_due_jobs(force=False)
            except Exception as exc:  # noqa: BLE001
                self.log.exception("scheduler loop failed: %s", exc)
            await asyncio.sleep(self.poll_interval_sec)

    async def _run_due_jobs(self, *, force: bool) -> dict[str, Any]:
        state = self._load_state()
        now = time.time()
        results: dict[str, Any] = {}

        daily = state["daily_update"]
        if force or self._job_due(daily, now, self.daily_update_interval_sec):
            results["daily_update"] = await self._run_job("daily_update", state)

        heartbeat = state["heartbeat"]
        if state["daily_update"]["status"] == "running":
            results["heartbeat"] = {"status": "skipped", "reason": "daily_update_running"}
        elif force or self._job_due(heartbeat, now, self.heartbeat_interval_sec):
            results["heartbeat"] = await self._run_job("heartbeat", state)

        if not results:
            results["status"] = "idle"
        return results

    def _job_due(self, job_state: dict[str, Any], now: float, interval_sec: float) -> bool:
        last = job_state.get("last_run_at")
        if last is None:
            return True
        return (float(now) - float(last)) >= interval_sec

    async def _run_job(self, job_name: str, state: dict[str, Any]) -> dict[str, Any]:
        state[job_name]["status"] = "running"
        state[job_name]["last_started_at"] = time.time()
        self._save_state(state)

        try:
            _, queue = await self.gateway.request("gateway.queue.status", {})
            queue_state = queue.get("result", {})
            if int(queue_state.get("processing", 0)) > 0:
                state[job_name]["status"] = "idle"
                state[job_name]["last_skipped_at"] = time.time()
                state[job_name]["last_skip_reason"] = "gateway_busy"
                self._save_state(state)
                return {"status": "skipped", "reason": "gateway_busy"}

            prompt = self._build_job_prompt(job_name)
            await self.ai.request("codex.session.ensure", {"session_key": "system_maintenance", "hydrate": True})
            stream, final = await self.ai.request(
                "codex.session.send",
                {"session_key": "system_maintenance", "prompt": prompt},
                stream_events=True,
            )
            reply = ""
            async for frame in stream:
                if frame.get("event") == "assistant.final":
                    reply = str((frame.get("payload") or {}).get("text") or "")
                elif frame.get("event") == "assistant.delta":
                    reply += str((frame.get("payload") or {}).get("text") or "")
            final_res = await final if inspect.isawaitable(final) else final
            state[job_name]["status"] = "idle"
            state[job_name]["last_run_at"] = time.time()
            state[job_name]["last_result"] = (reply or "").strip()
            self._save_state(state)
            return {"status": "ran", "reply": reply.strip(), "final": final_res.get("result", {}) if isinstance(final_res, dict) else {}}
        except Exception as exc:  # noqa: BLE001
            state[job_name]["status"] = "error"
            state[job_name]["last_error_at"] = time.time()
            state[job_name]["last_error"] = str(exc)
            self._save_state(state)
            raise

    def _build_job_prompt(self, job_name: str) -> str:
        task_lines = self.task_store.summary_lines(limit=12)
        tasks_block = "\n".join(task_lines) if task_lines else "- no tracked tasks"
        session_index = json.loads(agent_repo.path_for("sessions", "sessions.json").read_text(encoding="utf-8"))
        session_keys = sorted((session_index.get("sessions") or {}).keys())
        session_block = "\n".join(f"- {session_key}" for session_key in session_keys) if session_keys else "- no tracked sessions"
        job_intro = (
            "Run the periodic heartbeat maintenance skill and decide whether any lightweight repo maintenance is needed."
            if job_name == "heartbeat"
            else "Run the daily-update maintenance skill and decide what broader repo maintenance is needed."
        )
        return (
            f"{job_intro}\n\n"
            "Inspect repo-backed memory, summaries, sessions, and tasks before deciding what maintenance to perform.\n"
            "If updates are needed, make those repo changes yourself in this Codex turn.\n\n"
            "## Active Sessions\n"
            f"{session_block}\n\n"
            "## Current Tasks\n"
            f"{tasks_block}\n\n"
            "## Key Memory Files\n"
            "- memory/inbox.md\n"
            "- memory/decisions.md\n"
            "- memory/user_profile.md\n"
            "- memory/preferences.md\n"
            "- memory/global_facts.md\n"
            "- memory/ongoing_projects.md\n"
            "- memory/learned_patterns.md\n"
            "- memory/skill_candidates.md\n"
        )
