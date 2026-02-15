from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from python_openclaw.common.models import Principal
from python_openclaw.gateway.approvals import ApprovalManager
from python_openclaw.gateway.ipc_server import IPCClient
from python_openclaw.gateway.secure_web import SecureWebRequester, body_summary
from python_openclaw.gateway.sessions import IdentityManager, session_key
from python_openclaw.gateway.transcript import TranscriptStore


class ChannelAdapter(Protocol):
    async def send_stream(self, session_key: str, event: dict) -> None: ...


@dataclass
class GatewayCore:
    identities: IdentityManager
    transcripts: TranscriptStore
    ipc_client: IPCClient
    secure_web: SecureWebRequester
    approvals: ApprovalManager
    audit_log: list[dict]

    def __init__(
        self,
        identities: IdentityManager,
        transcripts: TranscriptStore,
        ipc_client: IPCClient,
        secure_web: SecureWebRequester,
        approvals: ApprovalManager,
    ) -> None:
        self.identities = identities
        self.transcripts = transcripts
        self.ipc_client = ipc_client
        self.secure_web = secure_web
        self.approvals = approvals
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
                result = self._handle_tool_call(principal, event["payload"])
                self.transcripts.append(skey, {"type": "tool.result", **result})
                await adapter.send_stream(skey, {"stream": "tool.result", "payload": result})
            await adapter.send_stream(skey, event)

    def _handle_tool_call(self, principal: Principal, event_payload: dict) -> dict:
        tool_name = event_payload["tool_name"]
        payload = event_payload["payload"]
        reason = event_payload.get("reason")

        if tool_name == "secure.secret.ensure":
            handle = payload["handle"]
            ok = self.secure_web.secrets.ensure_handle(handle)
            return {"tool_name": tool_name, "ok": ok}

        if tool_name == "secure.web.request":
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
            response = self.secure_web.request(payload)
            self._append_audit(principal.principal_id, tool_name, payload, "executed", response)
            return {"tool_name": tool_name, "status": "executed", "response": response}

        return {"tool_name": tool_name, "error": "unsupported tool"}

    def execute_approved_web_request(self, principal_id: str, payload: dict, token: str) -> dict:
        if not self.approvals.verify_and_consume(token):
            raise PermissionError("invalid approval token")
        payload = dict(payload)
        payload["approval_token"] = token
        response = self.secure_web.request(payload)
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
