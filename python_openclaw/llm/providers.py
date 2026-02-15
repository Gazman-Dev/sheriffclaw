from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


class LLMProviderError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class NormalizedChunk:
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    done: bool = False


class ModelProvider(ABC):
    def __init__(self, api_key: str, *, model_map: dict[str, str], base_url: str, timeout_seconds: float = 20.0):
        self.api_key = api_key
        self.model_map = model_map
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def chat_completion(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[NormalizedChunk]:
        raise NotImplementedError

    @abstractmethod
    def convert_messages(self, messages: list[dict]) -> dict:
        raise NotImplementedError

    @abstractmethod
    def convert_tools(self, tools: list[dict] | None) -> dict:
        raise NotImplementedError

    @abstractmethod
    def parse_tool_calls(self, payload: dict) -> list[ToolCall]:
        raise NotImplementedError

    @abstractmethod
    def models_list(self) -> list[str]:
        raise NotImplementedError

    async def _request_json(self, url: str, payload: dict, headers: dict[str, str], retries: int = 3) -> dict:
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, method="POST", data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < retries:
                    await asyncio.sleep(0.25 * attempt)
                    continue
                raise LLMProviderError(f"provider request failed: {exc.code}") from exc

    def _resolve_model(self, model: str) -> str:
        return self.model_map.get(model, model)


class OpenAIProvider(ModelProvider):
    def __init__(self, api_key: str, *, base_url: str = "https://api.openai.com/v1"):
        super().__init__(
            api_key,
            model_map={"openai/best": "gpt-4o", "openai/flash": "gpt-4o-mini"},
            base_url=base_url,
        )

    def models_list(self) -> list[str]:
        return sorted(set(self.model_map.values()))

    async def chat_completion(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[NormalizedChunk]:
        payload = {"model": self._resolve_model(model), **self.convert_messages(messages), **self.convert_tools(tools)}
        response = await self._request_json(
            f"{self.base_url}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        calls = self.parse_tool_calls(message)
        yield NormalizedChunk(content=content, tool_calls=calls or None, done=True)

    def convert_messages(self, messages: list[dict]) -> dict:
        return {"messages": _normalize_openai_messages(messages)}

    def convert_tools(self, tools: list[dict] | None) -> dict:
        return {"tools": tools} if tools else {}

    def parse_tool_calls(self, payload: dict) -> list[ToolCall]:
        calls = []
        for tc in payload.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            if not isinstance(raw_args, str):
                raise LLMProviderError("OpenAI tool arguments must be JSON string")
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise LLMProviderError("OpenAI tool arguments are invalid JSON") from exc
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return calls


class AnthropicProvider(ModelProvider):
    def __init__(self, api_key: str):
        super().__init__(
            api_key,
            model_map={"anthropic/claude-best": "claude-3-5-sonnet", "anthropic/flash": "claude-3-haiku"},
            base_url="https://api.anthropic.com/v1",
        )

    def models_list(self) -> list[str]:
        return sorted(set(self.model_map.values()))

    async def chat_completion(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[NormalizedChunk]:
        payload = {"model": self._resolve_model(model), "max_tokens": 2048, **self.convert_messages(messages), **self.convert_tools(tools)}
        response = await self._request_json(
            f"{self.base_url}/messages",
            payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        content_items = response.get("content") or []
        text_bits: list[str] = []
        calls = self.parse_tool_calls({"content": content_items})
        for item in content_items:
            if item.get("type") == "text":
                text_bits.append(item.get("text", ""))
        yield NormalizedChunk(content="".join(text_bits), tool_calls=calls or None, done=True)

    def convert_messages(self, messages: list[dict]) -> dict:
        system, anthropic_messages = _normalize_anthropic_messages(messages)
        payload = {"messages": anthropic_messages}
        if system:
            payload["system"] = system
        return payload

    def convert_tools(self, tools: list[dict] | None) -> dict:
        return {"tools": [t.get("function", t) for t in tools]} if tools else {}

    def parse_tool_calls(self, payload: dict) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for item in payload.get("content") or []:
            if item.get("type") == "tool_use":
                calls.append(ToolCall(id=item.get("id", ""), name=item.get("name", ""), arguments=item.get("input") or {}))
        return calls


class GoogleProvider(ModelProvider):
    def __init__(self, api_key: str):
        super().__init__(
            api_key,
            model_map={"google/best": "gemini-1.5-pro", "google/flash": "gemini-1.5-flash"},
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )

    def models_list(self) -> list[str]:
        return sorted(set(self.model_map.values()))

    async def chat_completion(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[NormalizedChunk]:
        payload = {**self.convert_messages(messages), **self.convert_tools(tools)}
        response = await self._request_json(
            f"{self.base_url}/models/{self._resolve_model(model)}:generateContent?key={self.api_key}",
            payload,
            headers={"Content-Type": "application/json"},
        )
        candidates = response.get("candidates") or []
        parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts") or [])
        content_bits: list[str] = []
        calls = self.parse_tool_calls({"parts": parts})
        for part in parts:
            if "text" in part:
                content_bits.append(part["text"])
        yield NormalizedChunk(content="".join(content_bits), tool_calls=calls or None, done=True)

    def convert_messages(self, messages: list[dict]) -> dict:
        return {"contents": _normalize_gemini_contents(messages)}

    def convert_tools(self, tools: list[dict] | None) -> dict:
        if not tools:
            return {}
        declarations = [t["function"] for t in tools if "function" in t]
        return {"tools": [{"functionDeclarations": declarations}]}

    def parse_tool_calls(self, payload: dict) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for part in payload.get("parts") or []:
            if "functionCall" in part:
                fn = part["functionCall"]
                calls.append(ToolCall(id=fn.get("name", ""), name=fn.get("name", ""), arguments=fn.get("args") or {}))
        return calls


class MoonshotProvider(OpenAIProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key, base_url="https://api.moonshot.cn/v1")
        self.model_map.update({"moonshot/kimi-best": "moonshot-v1-128k", "moonshot/flash": "moonshot-v1-8k"})


def _normalize_openai_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": m.get("content", "")} for m in messages]


def _normalize_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_bits: list[str] = []
    normalized: list[dict] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            system_bits.append(message.get("content", ""))
            continue
        normalized.append({"role": "assistant" if role == "assistant" else "user", "content": message.get("content", "")})
    return "\n\n".join(system_bits), normalized


def _normalize_gemini_contents(messages: list[dict]) -> list[dict]:
    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        if message["role"] == "system":
            role = "user"
        contents.append({"role": role, "parts": [{"text": message.get("content", "")}]} )
    return contents


def provider_from_ref(model_ref: str, *, api_keys: dict[str, str] | None = None) -> ModelProvider:
    api_keys = api_keys or {
        "openai": os.getenv("OPENAI_API_KEY", ""),
        "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
        "google": os.getenv("GOOGLE_API_KEY", ""),
        "moonshot": os.getenv("MOONSHOT_API_KEY", ""),
    }
    provider_name = model_ref.split("/", 1)[0]
    if provider_name == "openai":
        return OpenAIProvider(api_keys["openai"])
    if provider_name == "anthropic":
        return AnthropicProvider(api_keys["anthropic"])
    if provider_name == "google":
        return GoogleProvider(api_keys["google"])
    if provider_name == "moonshot":
        return MoonshotProvider(api_keys["moonshot"])
    raise ValueError(f"unsupported provider: {provider_name}")
