from __future__ import annotations

import os
import uuid

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.tools_exec import ToolExecutor


class SheriffToolsService:
    def __init__(self) -> None:
        self.execer = ToolExecutor(gw_root() / "state" / "tool_output")
        self.policy = ProcClient("sheriff-policy", spawn_fallback=False)
        self.requests = ProcClient("sheriff-requests", spawn_fallback=False)
        self.secrets = ProcClient("sheriff-secrets", spawn_fallback=False)

    async def _ensure_tool_allowed(self, principal: str, argv: list[str]) -> dict | None:
        _, dec = await self.policy.request(
            "policy.get_decision",
            {"principal_id": principal, "resource_type": "tool", "resource_value": argv[0]},
        )
        decision = dec["result"].get("decision")
        if decision == "ALLOW":
            return None
        await self.requests.request(
            "requests.create_or_update",
            {
                "type": "tool",
                "key": argv[0],
                "one_liner": f"Allow command execution for {' '.join(argv[:6])}",
                "context": {"title": argv[0], "argv": argv},
            },
        )
        return {"status": "needs_tool_approval", "tool": argv[0]}

    async def _resolve_secret_env(self, argv: list[str], handles: list[str]) -> dict:
        if not handles:
            return {"status": "ok", "env": {}}

        _, unlocked = await self.secrets.request("secrets.is_unlocked", {})
        if not unlocked.get("result", {}).get("unlocked"):
            return {"status": "master_password_required"}

        resolved_env: dict[str, str] = {}
        missing: list[str] = []
        for handle in handles:
            _, res = await self.secrets.request("secrets.get_secret", {"handle": handle})
            value = res.get("result", {}).get("value")
            if value is None:
                missing.append(handle)
                await self.requests.request(
                    "requests.create_or_update",
                    {
                        "type": "secret",
                        "key": handle,
                        "one_liner": f"Need {handle} to run {' '.join(argv[:6])}",
                        "context": {"title": handle, "tool": argv[0], "argv": argv},
                    },
                )
                continue
            resolved_env[handle] = value

        if missing:
            return {"status": "needs_secret", "missing_handles": missing}
        return {"status": "ok", "env": resolved_env}

    async def exec_tool(self, payload, emit_event, req_id):
        principal = payload["principal_id"]
        argv = payload["argv"]
        env_handles = [str(item) for item in payload.get("env_handles", []) if str(item).strip()]

        approval_result = await self._ensure_tool_allowed(principal, argv)
        if approval_result is not None:
            return approval_result

        secret_result = await self._resolve_secret_env(argv, env_handles)
        if secret_result["status"] != "ok":
            return secret_result

        child_env = os.environ.copy()
        child_env.update(secret_result["env"])
        result = self.execer.exec(argv, payload.get("stdin", ""), env=child_env)
        if payload.get("taint"):
            run_id = payload.get("run_id") or str(uuid.uuid4())
            self.execer.save_output(run_id, result)
            return {"status": "executed", "run_id": run_id, "disclosure_available": True}
        return {"status": "executed", **result}

    async def get_output(self, payload, emit_event, req_id):
        out = self.execer.load_output(payload["run_id"])
        return {"status": "not_found"} if out is None else {"status": "ok", **out}

    async def disclose_output(self, payload, emit_event, req_id):
        principal = payload["principal_id"]
        run_id = payload["run_id"]
        _, dec = await self.policy.request("policy.get_decision",
                                           {"principal_id": principal, "resource_type": "disclose_output",
                                            "resource_value": run_id})

        if dec["result"].get("decision") != "ALLOW":
            return {"status": "needs_disclose_approval", "run_id": run_id}

        return await self.get_output(payload, emit_event, req_id)

    def ops(self):
        return {"tools.exec": self.exec_tool, "tools.get_output": self.get_output,
                "tools.disclose_output": self.disclose_output}
