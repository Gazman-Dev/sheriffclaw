from __future__ import annotations

from collections.abc import AsyncIterator


async def run_agent(messages: list[dict]) -> AsyncIterator[dict]:
    text = messages[-1]["content"].lower()
    if "call github" in text:
        yield {
            "stream": "tool.call",
            "payload": {
                "tool_name": "secure.secret.ensure",
                "payload": {"handle": "github"},
                "reason": "Need github token before API call",
            },
        }
        yield {
            "stream": "tool.call",
            "payload": {
                "tool_name": "secure.web.request",
                "payload": {
                    "method": "GET",
                    "host": "api.github.com",
                    "path": "/user",
                    "headers": {"accept": "application/json"},
                    "auth_handle": "github",
                },
                "reason": "Fetch GitHub profile",
            },
        }
        yield {"stream": "assistant.final", "payload": {"content": "Requested secure GitHub call."}}
        return

    response = f"Echo: {messages[-1]['content']}"
    for token in response.split():
        yield {"stream": "assistant.delta", "payload": {"delta": token + " "}}
    yield {"stream": "assistant.final", "payload": {"content": response}}
