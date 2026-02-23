from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from typing import Any


class StubProvider:
    async def generate(self, messages: list[dict], model: str = "stub") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"Assistant: {last}" if last else "Assistant: ready"


class TestProvider:
    async def generate(self, messages: list[dict], model: str = "test") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"TestBot[{model}]: {last}" if last else f"TestBot[{model}]: ready"


class _CodexCliBase:
    _codex_checked = False

    @classmethod
    def _ensure_codex_installed(cls) -> None:
        if shutil.which("codex"):
            cls._codex_checked = True
            return
        if cls._codex_checked:
            return
        cls._codex_checked = True
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("codex CLI missing and npm not found; install @openai/codex manually")
        proc = subprocess.run([npm, "i", "-g", "@openai/codex"], capture_output=True, text=True, check=False)  # noqa: S603
        if proc.returncode != 0 or not shutil.which("codex"):
            msg = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"failed to lazy-install codex CLI: {msg}")

    @staticmethod
    def _render_prompt(messages: list[dict[str, Any]]) -> str:
        lines: list[str] = ["Conversation history:"]
        for msg in messages[-20:]:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            lines.append(f"[{role}] {content}")
        lines.append("\nReply as the assistant to the last user message.")
        return "\n".join(lines)

    @classmethod
    def _run_codex_exec(cls, prompt: str, model: str, env_extra: dict[str, str] | None = None) -> str:
        cls._ensure_codex_installed()
        env = os.environ.copy()
        if env_extra:
            env.update({k: v for k, v in env_extra.items() if v is not None})

        cmd = ["codex", "exec", "--model", model, prompt]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)  # noqa: S603
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"codex exec failed ({proc.returncode}): {err}")
        out = (proc.stdout or "").strip()
        if out:
            return out
        raise RuntimeError("codex exec returned empty stdout")


class OpenAICodexProvider(_CodexCliBase):
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _generate_sync(self, messages: list[dict], model: str) -> str:
        if not self.api_key:
            raise ValueError("missing OpenAI API key")
        prompt = self._render_prompt(messages)
        return self._run_codex_exec(prompt, model, {"OPENAI_API_KEY": self.api_key})

    async def generate(self, messages: list[dict], model: str = "gpt-5.3-codex") -> str:
        return await asyncio.to_thread(self._generate_sync, messages, model)


class ChatGPTSubscriptionCodexProvider(_CodexCliBase):
    def __init__(self, access_token: str, base_url: str = "https://chatgpt.com/backend-api/codex"):
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")

    def _generate_sync(self, messages: list[dict], model: str) -> str:
        # Subscription auth is handled by `codex login` token store.
        # Keep access_token argument for backward compatibility with stored settings.
        prompt = self._render_prompt(messages)
        return self._run_codex_exec(prompt, model)

    async def generate(self, messages: list[dict], model: str = "gpt-5.3-codex") -> str:
        return await asyncio.to_thread(self._generate_sync, messages, model)
