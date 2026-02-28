from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from shared.llm.providers import ChatGPTSubscriptionCodexProvider, OpenAICodexProvider, StubProvider, TestProvider
from shared.llm.registry import resolve_model
from shared.memory.embedding import LocalSemanticEmbeddingProvider
from shared.memory.phase4_runtime import run_turn, RuntimeStores, Phase4RuntimeConfig, ModelAdapter
from shared.memory.semantic_index import HnswlibSemanticIndex
# Memory Imports
from shared.memory.store import TopicStore
from shared.paths import base_root
from shared.proc_rpc import ProcClient
from shared.skills.loader import SkillLoader


class WorkerModelAdapter(ModelAdapter):
    def __init__(self, provider, model_name: str):
        self.provider = provider
        self.model_name = model_name

    def create_response(self, request: dict) -> dict:
        # Convert internal Phase4 request to Provider-compatible message list
        messages = []
        for msg in request.get("input", []):
            role = msg["role"]
            content = ""
            if isinstance(msg["content"], list):
                content = msg["content"][0].get("text", "")
            else:
                content = str(msg["content"])
            messages.append({"role": role, "content": content})

        # We run the async provider in a thread to keep the sync Adapter interface
        # but in a real production environment we would make run_turn async.
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in a loop, we use a future
            resp_text = asyncio.run_coroutine_threadsafe(
                self.provider.generate(messages, model=self.model_name), loop
            ).result()
        else:
            resp_text = asyncio.run(self.provider.generate(messages, model=self.model_name))

        # Check for tool-call patterns in text if the provider doesn't support native tool calls
        # For Phase 4 demo, we assume the AI outputs JSON or specific markers.
        if "TOOL_CALL:" in resp_text:
            try:
                raw_json = resp_text.split("TOOL_CALL:")[1].strip()
                call_data = json.loads(raw_json)
                return {
                    "type": "tool_calls",
                    "tool_calls": [{
                        "id": str(uuid.uuid4()),
                        "name": call_data.get("name"),
                        "arguments": call_data.get("arguments", {})
                    }]
                }
            except:
                pass

        return {"type": "message", "content": resp_text}


class WorkerRuntime:
    def __init__(self):
        self.sessions: dict[str, list[dict]] = {}
        self.providers: dict[str, object] = {}

        # Use explicit absolute paths for reliability
        self.repo_root = Path(__file__).resolve().parents[2]
        self.agent_workspace = base_root() / "agent_workspace"
        self.agent_workspace.mkdir(parents=True, exist_ok=True)

        # Setup agent-owned persistent memory layer
        self.memory_dir = self.agent_workspace / ".memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.memory_dir / "session.json"

        # Initialize semantic indexes
        self.embedder = LocalSemanticEmbeddingProvider()
        self.topics_index = HnswlibSemanticIndex(self.memory_dir / "semantic", name="topics", dim=self.embedder.dim)
        self.conv_index = HnswlibSemanticIndex(self.memory_dir / "semantic", name="conversations",
                                               dim=self.embedder.dim)
        self.topic_store = TopicStore(self.memory_dir / "topics.json")

        self.topics_index.load()
        self.conv_index.load()

        self.skill_loader = SkillLoader(
            user_root=self.repo_root / "skills",
            system_root=self.repo_root / "system_skills",
        )
        self.skills = self.skill_loader.load()
        self._rpc_clients: dict[str, ProcClient] = {}

    def _get_rpc(self, service: str) -> ProcClient:
        if service not in self._rpc_clients:
            self._rpc_clients[service] = ProcClient(service)
        return self._rpc_clients[service]

    def _load_session(self, handle: str) -> list[dict]:
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                if data.get("session_handle") == handle:
                    return data.get("conversation_buffer", [])
            except Exception:
                pass
        return []

    def _save_session(self, handle: str, buffer: list[dict]) -> None:
        self.session_file.write_text(
            json.dumps({"session_handle": handle, "conversation_buffer": buffer}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

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

        model = resolve_model(model_ref)
        selected_provider = provider_name or ("test" if model.startswith("test/") else "stub")
        provider = self._provider(selected_provider, api_key, base_url, codex_state_b64)

        # Setup Phase 4 Runtime Stores
        stores = RuntimeStores(
            topic_store=self.topic_store,
            embedding_provider=self.embedder,
            semantic_index=self.topics_index,
            wake_packet=None,  # Loaded if sleep/wake triggered
            skills_root=self.repo_root / "skills",
            skill_runner=self.skill_run,
            repo_tools={
                "requests.create_or_update": lambda args: self._sheriff_call_sync("sheriff-requests",
                                                                                  "requests.create_or_update", args)
            }
        )

        adapter = WorkerModelAdapter(provider, model)
        config = Phase4RuntimeConfig(model=model)

        # Execute turn through the tool-calling loop
        result = await asyncio.to_thread(
            run_turn,
            history, text, "now", stores, config, adapter
        )

        answer = result["assistant_msg"]
        await emit_event("assistant.delta", {"text": answer})
        await emit_event("assistant.final", {"text": answer})

        self._save_session(session_handle, result["updated_buffer"])
        self.sessions[session_handle] = result["updated_buffer"]

    def _sheriff_call_sync(self, svc: str, op: str, payload: dict) -> dict:
        """Synchronous wrapper for internal RPC calls made during the tool loop."""
        client = self._get_rpc(svc)
        loop = asyncio.get_event_loop()
        _, res = asyncio.run_coroutine_threadsafe(client.request(op, payload), loop).result()
        return res.get("result", {})

    async def tool_result(self, session_handle: str, tool_name: str, result: dict) -> None:
        history = self._load_session(session_handle)
        history.append({"role": "tool", "name": tool_name, "content": str(result)})
        self._save_session(session_handle, history)
        self.sessions[session_handle] = history

    async def skill_run(self, name: str, payload: dict, emit_event=None) -> dict:
        self.skills = self.skill_loader.load()
        loaded = self.skills.get(name)
        if not loaded:
            return {"error": f"unknown skill: {name}"}

        cmd = loaded.command
        argv = payload.get("argv", [])
        stdin_data = payload.get("stdin", "")
        if argv:
            cmd = f"{cmd} {' '.join(argv)}"

        cwd = str(self.agent_workspace.resolve())
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

    def _provider(self, provider: str, api_key: str, base_url: str = "", codex_state_b64: str = ""):
        if os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}:
            return TestProvider()
        key = f"{provider}:{api_key}:{base_url}:{hash(codex_state_b64)}"
        if key not in self.providers:
            if provider == "test":
                self.providers[key] = TestProvider()
            elif provider in {"openai-codex"}:
                self.providers[key] = OpenAICodexProvider(api_key=api_key,
                                                          base_url=base_url or "https://api.openai.com/v1",
                                                          codex_state_b64=codex_state_b64)
            elif provider in {"openai-codex-chatgpt"}:
                self.providers[key] = ChatGPTSubscriptionCodexProvider(access_token=api_key,
                                                                       base_url=base_url or "https://chatgpt.com/backend-api/codex",
                                                                       codex_state_b64=codex_state_b64)
            else:
                self.providers[key] = StubProvider()
        return self.providers[key]

    async def session_open(self, session_id: str | None) -> str:
        handle = "primary_session"
        self.sessions[handle] = self._load_session(handle)
        return handle

    async def session_close(self, session_handle: str) -> None:
        self.sessions.pop(session_handle, None)
