from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from python_openclaw.llm.providers import ModelProvider
from python_openclaw.memory.sessions import SessionManager
from python_openclaw.memory.workspace import WorkspaceLoader
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException
from python_openclaw.worker.agent_stub import run_agent


class Worker:
    def __init__(
        self,
        *,
        provider: ModelProvider | None = None,
        session_manager: SessionManager | None = None,
        workspace_loader: WorkspaceLoader | None = None,
        tool_executor: Callable[[dict], dict | Awaitable[dict]] | None = None,
        approval_gate: ApprovalGate | None = None,
        summarizer: Callable[[list[dict]], str | Awaitable[str]] | None = None,
        available_tools: list[dict] | None = None,
    ):
        self.provider = provider
        self.session_manager = session_manager
        self.workspace_loader = workspace_loader or WorkspaceLoader(Path.cwd())
        self.tool_executor = tool_executor
        self.approval_gate = approval_gate
        self.summarizer = summarizer or (lambda events: f"Compacted {len(events)} events")
        self.available_tools = available_tools or []

    async def run(self, session_id: str, messages: list[dict]) -> AsyncIterator[dict]:
        if not self.provider or not self.session_manager or not self.tool_executor:
            async for event in run_agent(messages):
                yield event
            return

        for msg in messages:
            self.session_manager.append(session_id, msg)

        await self.session_manager.maybe_compact(session_id, self.summarizer)
        history = self.session_manager.read(session_id)
        workspace = self.workspace_loader.load().system_prompt()
        llm_messages = list(history)
        if workspace:
            llm_messages = [{"role": "system", "content": workspace}, *llm_messages]

        while True:
            assistant_text = ""
            tool_calls: list[dict] = []
            async for chunk in self.provider.chat_completion("best", llm_messages, tools=self.available_tools):
                if chunk.content:
                    assistant_text += chunk.content
                    yield {"stream": "assistant.delta", "payload": {"delta": chunk.content}}
                if chunk.tool_calls:
                    for call in chunk.tool_calls:
                        tool_calls.append({"id": call.id, "name": call.name, "arguments": call.arguments})
                if chunk.done:
                    break

            if assistant_text:
                final_payload = {"content": assistant_text}
                self.session_manager.append(session_id, {"role": "assistant", "content": assistant_text})
                llm_messages.append({"role": "assistant", "content": assistant_text})
                yield {"stream": "assistant.final", "payload": final_payload}

            if not tool_calls:
                return

            for call in tool_calls:
                event_payload = {"tool_name": call["name"], "payload": call["arguments"]}
                yield {"stream": "tool.call", "payload": event_payload}
                try:
                    tool_result = self.tool_executor(event_payload)
                    if inspect.isawaitable(tool_result):
                        tool_result = await tool_result
                except PermissionDeniedException as exc:
                    if not self.approval_gate:
                        tool_result = {"status": "error", "error": str(exc)}
                    else:
                        prompt = self.approval_gate.request(exc)
                        tool_result = {
                            "status": "waiting_for_approval",
                            "approval_id": prompt.approval_id,
                            "resource_type": prompt.resource_type,
                            "resource_value": prompt.resource_value,
                        }
                        yield {"stream": "tool.result", "payload": tool_result}
                        return
                except Exception as exc:  # noqa: BLE001
                    tool_result = {"status": "error", "error": str(exc)}

                yield {"stream": "tool.result", "payload": tool_result}
                tool_msg = {"role": "tool", "name": call["name"], "content": str(tool_result)}
                self.session_manager.append(session_id, tool_msg)
                llm_messages.append(tool_msg)
