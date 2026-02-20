from __future__ import annotations


class StubProvider:
    async def generate(self, messages: list[dict], model: str = "stub") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"Assistant: {last}" if last else "Assistant: ready"


class TestProvider:
    async def generate(self, messages: list[dict], model: str = "test") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"TestBot[{model}]: {last}" if last else f"TestBot[{model}]: ready"
