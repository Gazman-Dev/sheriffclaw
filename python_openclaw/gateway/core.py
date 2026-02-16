from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from python_openclaw.common.models import Principal
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.secure_web import SecureWebError, SecureWebRequester, body_summary
from python_openclaw.gateway.secrets.store import SecretNotFoundError
from python_openclaw.gateway.services import RequestService, ToolsService
from python_openclaw.gateway.sessions import IdentityManager, session_key
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException


class ChannelAdapter(Protocol):
    async def send_stream(self, session_key: str, event: dict) -> None: ...

    async def send_approval_request(self, approval_id: str, context: dict) -> None: ...


class SecureGateAdapter(Protocol):
    async def send_approval_request(self, approval_id: str, context: dict) -> None: ...

    async def send_secret_request(self, session_key: str, principal_id: str, handle: str) -> None: ...

    async def send_gate_message(self, session_key: str, text: str) -> None: ...


@dataclass
class GatewayCore:
    identities: IdentityManager
    transcripts: TranscriptStore
    ipc_client: IPCClient
    secure_web: SecureWebRequester
    tools: ToolsService
    requests: RequestService
    approval_gate: ApprovalGate
    audit_log: list[dict]
    secure_gate_adapter: SecureGateAdapter | None
    pending_secret_inputs: dict[str, list[str]]

    def __init__(
        self,
        identities: IdentityManager,
        transcripts: TranscriptStore,
        ipc_client: IPCClient,
        secure_web: SecureWebRequester,
        approval_gate: ApprovalGate,
        tools: ToolsService,
        requests: RequestService,
    ) -> None:
        self.identities = identities
        self.transcripts = transcripts
        self.ipc_client = ipc_client
        self.secure_web = secure_web
        self.approval_gate = approval_gate
        self.tools = tools
        self.requests = requests
        self.audit_log = []
        self.secure_gate_adapter = None
        self.pending_secret_inputs = {}

    def set_secure_gate_adapter(self, adapter: SecureGateAdapter) -> None:
        self.secure_gate_adapter = adapter

    def pending_secret_handle_for(self, principal_id: str) -> str | None:
        queue = self.pending_secret_inputs.get(principal_id, [])
        return queue[0] if queue else None

    async def handle_secret_reply(self, principal: Principal, value: str) -> str | None:
        queue = self.pending_secret_inputs.get(principal.principal_id, [])
        if not queue:
            return None
        handle = queue.pop(0)
        if not queue:
            self.pending_secret_inputs.pop(principal.principal_id, None)
        self.requests.store_secret(handle, value)
        return handle

    async def handle_user_message(
        self,
        *,
        channel: str,
        context: dict,
        principal: Principal,
        text: str,
        adapter: ChannelAdapter,
    ) -> None:
        skey = session_key(channel, context)
        self.transcripts.append(skey, {"type": "user", "content": text})
        messages = [{"role": "user", "content": text}]

        async for event in self.ipc_client.run_agent(skey, messages):
            stream = event["stream"]
            self.transcripts.append(skey, {"type": stream, **event["payload"]})
            if stream == "tool.call":
                result = await self._handle_tool_call_async(principal, event["payload"], adapter, skey)
                self.transcripts.append(skey, {"type": "tool.result", **result})
                await adapter.send_stream(skey, {"stream": "tool.result", "payload": result})
            await adapter.send_stream(skey, event)

    def _handle_tool_call(self, principal: Principal, event_payload: dict) -> dict:
        return asyncio.run(self._handle_tool_call_async(principal, event_payload, None, ""))

    async def _handle_tool_call_async(
        self,
        principal: Principal,
        event_payload: dict,
        adapter: ChannelAdapter | None,
        source_session_key: str,
    ) -> dict:
        tool_name = event_payload["tool_name"]
        payload = event_payload.get("payload", {})
        reason = event_payload.get("reason")

        if tool_name == "secure.secret.ensure":
            handle = payload["handle"]
            ok = self.secure_web.secrets.ensure_handle(handle)
            if ok:
                return {"tool_name": tool_name, "ok": ok, "status": "available", "key": handle}
            gate_session = self.identities.gate_for(principal.principal_id)
            if gate_session and self.secure_gate_adapter:
                queue = self.pending_secret_inputs.setdefault(principal.principal_id, [])
                if handle not in queue:
                    queue.append(handle)
                await self.secure_gate_adapter.send_secret_request(gate_session, principal.principal_id, handle)
            return {"tool_name": tool_name, "ok": False, "status": "secret_requested", "key": handle}

        if tool_name in {"secure.web.request", "web.request"}:
            try:
                response = self.secure_web.request(payload, principal_id=principal.principal_id)
                self._append_audit(principal.principal_id, tool_name, payload, "executed", response)
                return {"tool_name": tool_name, "status": "executed", "response": response}
            except PermissionDeniedException as exc:
                return {
                    "tool_name": tool_name,
                    "status": "permission_denied",
                    "code": 403,
                    "error": str(exc),
                    "resource": {"type": exc.resource_type, "value": exc.resource_value},
                }
            except SecretNotFoundError as exc:
                return {"tool_name": tool_name, "status": "error", "error": str(exc), "error_type": "SecretNotFoundError", "key": exc.handle}
            except SecureWebError as exc:
                return {"tool_name": tool_name, "status": "error", "error": str(exc)}

        if tool_name in {"tools.exec", "tools.run"}:
            try:
                result = self.tools.execute(payload, principal_id=principal.principal_id)
                return {"tool_name": tool_name, **result}
            except PermissionDeniedException as exc:
                return {
                    "tool_name": tool_name,
                    "status": "permission_denied",
                    "code": 403,
                    "error": str(exc),
                    "resource": {"type": exc.resource_type, "value": exc.resource_value},
                }
            except SecretNotFoundError as exc:
                return {"tool_name": tool_name, "status": "error", "error": str(exc), "error_type": "SecretNotFoundError", "key": exc.handle}

        if tool_name == "request":
            prompt = self.approval_gate.request(
                PermissionDeniedException(
                    principal_id=principal.principal_id,
                    resource_type=payload.get("resource_type", payload.get("type", "domain")),
                    resource_value=payload.get("resource_value", payload.get("target", payload.get("host", "unknown"))),
                    metadata={
                        "reason": reason,
                        "method": payload.get("method"),
                        "path": payload.get("path"),
                        "body": body_summary(payload.get("body")),
                    },
                )
            )
            gate_session = self.identities.gate_for(principal.principal_id, source_session_key)
            if self.secure_gate_adapter is not None and gate_session:
                await self.secure_gate_adapter.send_approval_request(
                    prompt.approval_id,
                    {
                        "session_key": gate_session,
                        "principal": prompt.principal_id,
                        "resource_type": prompt.resource_type,
                        "resource_value": prompt.resource_value,
                        "metadata": prompt.metadata,
                    },
                )
            elif adapter is not None:
                await adapter.send_approval_request(
                    prompt.approval_id,
                    {
                        "session_key": source_session_key,
                        "principal": prompt.principal_id,
                        "resource_type": prompt.resource_type,
                        "resource_value": prompt.resource_value,
                        "metadata": prompt.metadata,
                    },
                )
            return {"tool_name": tool_name, "status": "approval_requested", "approval_id": prompt.approval_id}

        return {"tool_name": tool_name, "error": "unsupported tool"}

    def _append_audit(self, principal_id: str, tool_name: str, payload: dict, decision: str, response: dict) -> None:
        self.audit_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "principal_id": principal_id,
                "tool_name": tool_name,
                "summary": {
                    "method": payload.get("method"),
                    "host": payload.get("host"),
                    "path": payload.get("path"),
                    "auth_handle": payload.get("auth_handle"),
                },
                "approval_decision": decision,
                "status": response.get("status"),
                "bytes": response.get("bytes"),
            }
        )
