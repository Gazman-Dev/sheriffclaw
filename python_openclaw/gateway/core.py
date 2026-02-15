from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from python_openclaw.common.models import Principal
from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.secure_web import SecureWebRequester, body_summary
from python_openclaw.gateway.sessions import IdentityManager, session_key
from python_openclaw.gateway.transcript import TranscriptStore
from python_openclaw.security.gate import ApprovalGate
from python_openclaw.security.permissions import PermissionDeniedException


class ChannelAdapter(Protocol):
    async def send_stream(self, session_key: str, event: dict) -> None: ...

    async def send_approval_request(self, approval_id: str, context: dict) -> None: ...


@dataclass
class GatewayCore:
    identities: IdentityManager
    transcripts: TranscriptStore
    ipc_client: IPCClient
    secure_web: SecureWebRequester
    approvals: ApprovalManager
    audit_log: list[dict]
    approval_gate: ApprovalGate | None

    def __init__(
        self,
        identities: IdentityManager,
        transcripts: TranscriptStore,
        ipc_client: IPCClient,
        secure_web: SecureWebRequester,
        approvals: ApprovalManager,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.identities = identities
        self.transcripts = transcripts
        self.ipc_client = ipc_client
        self.secure_web = secure_web
        self.approvals = approvals
        self.approval_gate = approval_gate
        self.audit_log = []

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

    async def _handle_tool_call_async(self, principal: Principal, event_payload: dict, adapter: ChannelAdapter | None, source_session_key: str) -> dict:
        tool_name = event_payload["tool_name"]
        payload = event_payload["payload"]
        reason = event_payload.get("reason")

        if tool_name == "secure.secret.ensure":
            handle = payload["handle"]
            ok = self.secure_web.secrets.ensure_handle(handle)
            return {"tool_name": tool_name, "ok": ok}

        if tool_name == "secure.web.request":
            try:
                if payload.get("auth_handle"):
                    req = self.approvals.request(principal.principal_id, tool_name, payload, reason)
                    return {
                        "tool_name": tool_name,
                        "status": "approval_required",
                        "approval_id": req.approval_id,
                        "summary": {
                            "principal": principal.principal_id,
                            "method": payload["method"],
                            "host": payload["host"],
                            "path": payload["path"],
                            "auth_handle": payload.get("auth_handle"),
                            "body": body_summary(payload.get("body")),
                            "reason": reason,
                        },
                    }

                response = self.secure_web.request(payload, principal_id=principal.principal_id)
                self._append_audit(principal.principal_id, tool_name, payload, "executed", response)
                return {"tool_name": tool_name, "status": "executed", "response": response}
            except PermissionDeniedException as exc:
                if not self.approval_gate:
                    raise
                prompt = self.approval_gate.request(exc)
                gate_session = self.identities.gate_for(principal.principal_id, source_session_key)
                if adapter is not None:
                    await adapter.send_approval_request(
                        prompt.approval_id,
                        {
                            "session_key": gate_session,
                            "principal": principal.principal_id,
                            "resource_type": prompt.resource_type,
                            "resource_value": prompt.resource_value,
                            "metadata": prompt.metadata,
                        },
                    )
                return {"tool_name": tool_name, "status": "permission_required", "approval_id": prompt.approval_id}

        return {"tool_name": tool_name, "error": "unsupported tool"}

    def execute_approved_web_request(self, principal_id: str, payload: dict, token: str) -> dict:
        if not self.approvals.verify_and_consume(token):
            raise PermissionError("invalid approval token")
        payload = dict(payload)
        payload["approval_token"] = token
        response = self.secure_web.request(payload, principal_id=principal_id)
        self._append_audit(principal_id, "secure.web.request", payload, "approved_executed", response)
        return response

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
