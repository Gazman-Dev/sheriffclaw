from __future__ import annotations

import asyncio
from collections import deque
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
    tool_output_store: dict[str, dict]

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
        self.tool_output_store = {}
        self._tool_output_order: deque[str] = deque(maxlen=100)

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
                approval_id = await self._request_approval(principal, payload, reason, adapter, source_session_key, exc)
                return {"tool_name": tool_name, "status": "approval_requested", "approval_id": approval_id}
            except SecretNotFoundError as exc:
                return {"tool_name": tool_name, "status": "error", "error": str(exc), "error_type": "SecretNotFoundError", "key": exc.handle}
            except SecureWebError as exc:
                return {"tool_name": tool_name, "status": "error", "error": str(exc)}

        if tool_name in {"tools.exec", "tools.run"}:
            try:
                result = self.tools.execute(payload, principal_id=principal.principal_id)
                captured = result.pop("__captured_output", None)
                if captured:
                    self._store_tool_output(
                        result["run_id"],
                        {
                            "tool": result.get("tool"),
                            "stdout": captured.get("stdout", ""),
                            "stderr": captured.get("stderr", ""),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "tainted": result.get("tainted", False),
                            "principal_id": principal.principal_id,
                        },
                    )
                return {"tool_name": tool_name, **result}
            except PermissionDeniedException as exc:
                return {
                    "tool_name": tool_name,
                    "status": "permission_denied",
                    "code": 403,
                    "error": str(exc),
                    "resource": {"type": exc.resource_type, "value": exc.resource_value},
                }

        if tool_name == "secure.disclose_output":
            run_id = payload.get("run_id")
            if not run_id:
                return {"tool_name": tool_name, "status": "error", "error": "run_id is required"}
            target = payload.get("target", "secure_channel")
            if target != "secure_channel":
                return {"tool_name": tool_name, "status": "error", "error": "only secure_channel target is supported"}
            stored = self.tool_output_store.get(run_id)
            if not stored:
                return {"tool_name": tool_name, "status": "error", "error": "run_id not found"}
            if stored.get("principal_id") != principal.principal_id:
                return {"tool_name": tool_name, "status": "error", "error": "run_id belongs to another principal"}

            gate_session = self.identities.gate_for(principal.principal_id, source_session_key)
            if not gate_session or not self.secure_gate_adapter:
                return {"tool_name": tool_name, "status": "error", "error": "secure channel unavailable"}

            metadata = {
                "session_key": gate_session,
                "principal": principal.principal_id,
                "action_type": "disclose_output",
                "tool": stored.get("tool"),
                "run_id": run_id,
                "bytes_stdout": len(stored.get("stdout", "").encode("utf-8")),
                "bytes_stderr": len(stored.get("stderr", "").encode("utf-8")),
                "tainted": stored.get("tainted", False),
                "warning": "May contain secrets",
                "reason": payload.get("reason"),
            }
            pending = self.approval_gate.request_action(
                principal.principal_id,
                "disclose_output",
                metadata,
                callback=lambda approved: self._dispatch_disclosure_decision(approved, metadata),
            )
            await self.secure_gate_adapter.send_approval_request(pending.approval_id, metadata)
            return {"tool_name": tool_name, "status": "approval_requested", "approval_id": pending.approval_id}

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
            await self._send_approval_request(prompt.approval_id, prompt, adapter, source_session_key)
            return {"tool_name": tool_name, "status": "approval_requested", "approval_id": prompt.approval_id}

        return {"tool_name": tool_name, "error": "unsupported tool"}

    async def _request_approval(
        self,
        principal: Principal,
        payload: dict,
        reason: str | None,
        adapter: ChannelAdapter | None,
        source_session_key: str,
        exc: PermissionDeniedException,
    ) -> str:
        prompt = self.approval_gate.request(
            PermissionDeniedException(
                principal_id=principal.principal_id,
                resource_type=exc.resource_type,
                resource_value=exc.resource_value,
                metadata={
                    "reason": reason,
                    "method": payload.get("method"),
                    "path": payload.get("path"),
                    "body": body_summary(payload.get("body")),
                    "uses_secret_headers": bool(payload.get("secret_headers") or payload.get("auth_handle")),
                },
            )
        )
        await self._send_approval_request(prompt.approval_id, prompt, adapter, source_session_key)
        return prompt.approval_id

    async def _send_approval_request(self, approval_id: str, prompt: object, adapter: ChannelAdapter | None, source_session_key: str) -> None:
        gate_session = self.identities.gate_for(getattr(prompt, "principal_id", ""), source_session_key)
        context = {
            "session_key": gate_session,
            "principal": getattr(prompt, "principal_id", ""),
            "resource_type": getattr(prompt, "resource_type", "action"),
            "resource_value": getattr(prompt, "resource_value", ""),
            "metadata": getattr(prompt, "metadata", {}),
        }
        if self.secure_gate_adapter is not None and gate_session:
            await self.secure_gate_adapter.send_approval_request(approval_id, context)
            if adapter is not None:
                await adapter.send_stream(source_session_key, {"stream": "tool.result", "payload": {"status": "approval_requested"}})
        elif adapter is not None:
            await adapter.send_approval_request(approval_id, context)


    def _dispatch_disclosure_decision(self, approved: bool, metadata: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handle_disclosure_decision(approved, metadata))
        except RuntimeError:
            asyncio.run(self._handle_disclosure_decision(approved, metadata))

    async def _handle_disclosure_decision(self, approved: bool, metadata: dict) -> None:
        if not self.secure_gate_adapter:
            return
        session_key = metadata.get("session_key")
        if not session_key:
            return
        if not approved:
            await self.secure_gate_adapter.send_gate_message(session_key, "Disclosure denied.")
            return
        run_id = metadata.get("run_id", "")
        output = self.tool_output_store.get(run_id)
        if not output:
            await self.secure_gate_adapter.send_gate_message(session_key, "Disclosure failed: run output no longer available.")
            return
        message = (
            f"Disclosed output for run {run_id} ({output.get('tool')})\n"
            f"stdout:\n{output.get('stdout', '')}\n\n"
            f"stderr:\n{output.get('stderr', '')}"
        )
        await self.secure_gate_adapter.send_gate_message(session_key, message)

    def _store_tool_output(self, run_id: str, entry: dict) -> None:
        if run_id not in self.tool_output_store and len(self._tool_output_order) == self._tool_output_order.maxlen:
            oldest = self._tool_output_order.popleft()
            self.tool_output_store.pop(oldest, None)
        if run_id not in self.tool_output_store:
            self._tool_output_order.append(run_id)
        self.tool_output_store[run_id] = entry

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
