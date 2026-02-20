from __future__ import annotations

import asyncio
from typing import Any

import requests


class StubProvider:
    async def generate(self, messages: list[dict], model: str = "stub") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"Assistant: {last}" if last else "Assistant: ready"


class TestProvider:
    async def generate(self, messages: list[dict], model: str = "test") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"TestBot[{model}]: {last}" if last else f"TestBot[{model}]: ready"


class OpenAICodexProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _to_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))
            items.append({"role": role, "content": [{"type": "input_text", "text": content}]})
        return items

    def _generate_sync(self, messages: list[dict], model: str) -> str:
        if not self.api_key:
            raise ValueError("missing OpenAI API key")

        url = f"{self.base_url}/responses"
        payload = {
            "model": model,
            "input": self._to_input(messages),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") in {"output_text", "text"} and c.get("text"):
                        return str(c["text"]).strip()

        return "(empty response)"

    async def generate(self, messages: list[dict], model: str = "gpt-5.3-codex") -> str:
        return await asyncio.to_thread(self._generate_sync, messages, model)
