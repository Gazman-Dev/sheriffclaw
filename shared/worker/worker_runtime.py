from __future__ import annotations

import uuid
import json
import asyncio
from pathlib import Path

from shared.llm.providers import ChatGPTSubscriptionCodexProvider, OpenAICodexProvider, StubProvider, TestProvider
from shared.llm.registry import resolve_model
from shared.skills.loader import SkillLoader
from shared.proc_rpc import ProcClient


class WorkerRuntime:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.providers: dict[str, object] = {}
        self.workspace_root = Path.cwd()

        # Setup agent-owned persistent memory layer
        self.memory_dir = self.workspace_root / ".memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.memory_dir / "session.json"

        self.skill_loader = SkillLoader(
            user_root=self.workspace_root / "skills",
            system_root=self.workspace_root / "system_skills",
        )
        (self.workspace_root / "agent_workspace").mkdir(parents=True, exist_ok=True)
        self.skills = self.skill_loader.load()
        self._rpc_clients: dict[str, ProcClient] = {}

    def _load_session(self, handle: str) -> list[dict]:
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                if data.get("session_handle") == handle:
                    return data.get("conversation_buffer",[])
            except Exception:
                pass
        return []

    def _save_session(self, handle: str, buffer: list[dict]) -> None:
        self.session_file.write_text(
            json.dumps({"session_handle": handle, "conversation_buffer": buffer}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @staticmethod
    def _last_tool_result(history: list[dict]) -> str:
        for entry in reversed(history):
            if entry.get("role") == "tool":
                return str(entry.get("content", ""))
        return "none"

    async def _scenario_message(self, history: list[dict], text: str, model: str, emit_event) -> str:
        stripped = text.strip()
        lower = stripped.lower()

        if lower.startswith("scenario secret "):
            handle = stripped.split(maxsplit=2)[2]
            await emit_event(
                "tool.call",
                {"tool_name": "secure.secret.ensure", "payload": {"handle": handle}, "reason": "scenario-secret"},
            )
            return f"Scenario[{model}] requested secret handle: {handle}"

        if lower.startswith("scenario exec "):
            tool_name = stripped.split(maxsplit=2)[2]
            await emit_event(
                "tool.call",
                {
                    "tool_name": "tools.exec",
                    "payload": {"argv":[tool_name, "--version"], "taint": False},
                    "reason": "scenario-exec",
                },
            )
            return f"Scenario[{model}] requested tool execution: {tool_name}"

        if lower.startswith("scenario web "):
            host = stripped.split(maxsplit=2)[2]
            await emit_event(
                "tool.call",
                {"tool_name": "secure.web.request", "payload": {"host": host, "path": "/", "method": "GET"}, "reason": "scenario-web"},
            )
            return f"Scenario[{model}] requested web access: {host}"

        if lower == "scenario last tool":
            return f"Scenario[{model}] last tool result: {self._last_tool_result(history)}"

        return f"Scenario[{model}] echo: {text}"

    def _rpc_client(self, service: str) -> ProcClient:
        cli = self._rpc_clients.get(service)
        if cli is None:
            cli = ProcClient(service)
            self._rpc_clients[service] = cli
        return cli

    async def _sheriff_call(self, service: str, op: str, payload: dict):
        if not service.startswith("sheriff-"):
            raise ValueError("sheriff_call service must start with sheriff-")
        cli = self._rpc_client(service)
        _, res = await cli.request(op, payload)
        return res.get("result", {})

    def _provider(self, provider: str, api_key: str, base_url: str = "", codex_state_b64: str = ""):
        key = f"{provider}:{api_key}:{base_url}:{hash(codex_state_b64)}"
        if key not in self.providers:
            if provider == "test":
                self.providers[key] = TestProvider()
            elif provider in {"openai-codex"}:
                self.providers[key] = OpenAICodexProvider(api_key=api_key, base_url=base_url or "https://api.openai.com/v1", codex_state_b64=codex_state_b64)
            elif provider in {"openai-codex-chatgpt"}:
                self.providers[key] = ChatGPTSubscriptionCodexProvider(access_token=api_key, base_url=base_url or "https://chatgpt.com/backend-api/codex", codex_state_b64=codex_state_b64)
            else:
                self.providers[key] = StubProvider()
        return self.providers[key]

    async def session_open(self, session_id: str | None) -> str:
        handle = "primary_session"
        self.sessions[handle] = self._load_session(handle)
        return handle

    async def session_close(self, session_handle: str) -> None:
        self.sessions.pop(session_handle, None)

    async def user_message(
            self,
            session_handle: str,
            text: str,
            model_ref: str | None,
            emit_event,
            provider_name: str | None = None,
            api_key: str = "",
            base_url: str = "",
            codex_state_b64: str = "",
    ):
        history = self._load_session(session_handle)
        history.append({"role": "user", "content": text})
        model = resolve_model(model_ref)

        if model.startswith("scenario/"):
            answer = await self._scenario_message(history, text, model, emit_event)
        else:
            lower = text.lower()
            if "tool" in lower:
                await emit_event("tool.call", {"tool_name": "tools.exec", "payload": {"argv": ["echo", "tool-invoked"], "taint": False}, "reason": "trigger word"})
            selected_provider = provider_name or ("test" if model.startswith("test/") else "stub")
            provider = self._provider(selected_provider, api_key, base_url, codex_state_b64)
            answer = await provider.generate(history, model=model)
            state_b64 = getattr(provider, "last_codex_state_b64", "")
            if state_b64:
                await emit_event("provider.state", {"codex_state_b64": state_b64})

        await emit_event("assistant.delta", {"text": answer})
        await emit_event("assistant.final", {"text": answer})

        history.append({"role": "assistant", "content": answer})
        self._save_session(session_handle, history)
        self.sessions[session_handle] = history

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        history = self._load_session(session_handle)
        history.append({"role": "tool", "name": tool_name, "content": str(result)})
        self._save_session(session_handle, history)
        self.sessions[session_handle] = history

    async def list_skills(self) -> list[str]:
        self.skills = self.skill_loader.load()
        return sorted(self.skills.keys())

    @staticmethod
    def _sandboxed_path(base: Path, raw: str) -> Path:
        p = (base / raw).resolve()
        if not str(p).startswith(str(base.resolve())):
            raise ValueError("path outside sandbox")
        return p

    async def skill_run(self, name: str, payload: dict, emit_event) -> dict:
        self.skills = self.skill_loader.load()
        loaded = self.skills.get(name)
        if not loaded:
            raise ValueError(f"unknown skill: {name}")

        cmd = loaded.command
        argv = payload.get("argv",[])
        stdin_data = payload.get("stdin", "")

        if argv:
            cmd = f"{cmd} {' '.join(argv)}"

        cwd = str((self.workspace_root / "agent_workspace").resolve())

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE if stdin_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        stdout, stderr = await proc.communicate(input=stdin_data.encode("utf-8") if stdin_data else None)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "code": proc.returncode
        }