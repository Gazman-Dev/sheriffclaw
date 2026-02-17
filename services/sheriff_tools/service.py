from __future__ import annotations

import uuid

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from shared.tools_exec import ToolExecutor


class SheriffToolsService:
    def __init__(self) -> None:
        self.execer = ToolExecutor(gw_root() / "state" / "tool_output")
        self.policy = ProcClient("sheriff-policy")

    async def exec_tool(self, payload, emit_event, req_id):
        principal = payload["principal_id"]
        argv = payload["argv"]
        _, dec = await self.policy.request("policy.get_decision", {"principal_id": principal, "resource_type": "tool", "resource_value": argv[0]})
        decision = dec["result"].get("decision")
        if decision != "ALLOW":
            return {"status": "needs_tool_approval", "tool": argv[0]}
        result = self.execer.exec(argv, payload.get("stdin", ""))
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
        _, dec = await self.policy.request("policy.get_decision", {"principal_id": principal, "resource_type": "disclose_output", "resource_value": run_id})

        if dec["result"].get("decision") != "ALLOW":
            return {"status": "needs_disclose_approval", "run_id": run_id}

        return await self.get_output(payload, emit_event, req_id)

    def ops(self):
        return {"tools.exec": self.exec_tool, "tools.get_output": self.get_output, "tools.disclose_output": self.disclose_output}